"""Unit tests for FormVM — edge cases and implementation details.

Conformance-level tests live in tests/conformance/test_form_001_to_010_form_vm.py.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from vmx.forms import FormVM
from vmx.messages import FormRevertedMessage, PropertyChangedMessage
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Shared model
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Model:
    name: str
    value: int


async def _noop(m: Model) -> None:
    pass


def _make(initial: Model | None = None) -> FormVM[Model]:
    return FormVM(initial or Model("A", 1), _noop)


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


def test_constructor_rejects_none_initial() -> None:
    with pytest.raises(ValueError, match="initial must not be None"):
        FormVM(None, _noop)  # type: ignore[arg-type]


def test_constructor_rejects_none_persister() -> None:
    with pytest.raises(ValueError, match="persister must not be None"):
        FormVM(Model("A", 1), None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_snapshot_is_value_equal_to_initial() -> None:
    initial = Model("Alice", 1)
    sut = _make(initial)
    assert sut.snapshot == initial


def test_custom_snapshotter_applied_at_construction() -> None:
    calls: list[Model] = []

    def snapshotter(m: Model) -> Model:
        calls.append(m)
        return dataclasses.replace(m, name=m.name + "-snap")

    initial = Model("Alice", 1)
    sut: FormVM[Model] = FormVM(initial, _noop, snapshotter=snapshotter)

    assert len(calls) == 1, "snapshotter called once during construction"
    assert sut.snapshot.name == "Alice-snap"


def test_custom_snapshotter_applied_on_deny() -> None:
    snap_calls: list[Model] = []

    def snapshotter(m: Model) -> Model:
        snap_calls.append(m)
        return dataclasses.replace(m, name=m.name)

    sut: FormVM[Model] = FormVM(Model("A", 1), _noop, snapshotter=snapshotter)
    snap_calls.clear()  # reset after construction

    sut.set_model(Model("B", 2))
    sut.deny_command.execute()

    assert len(snap_calls) == 1, "snapshotter called on deny"


# ---------------------------------------------------------------------------
# SetModel
# ---------------------------------------------------------------------------


def test_set_model_rejects_none() -> None:
    sut = _make()
    with pytest.raises(ValueError, match="model must not be None"):
        sut.set_model(None)  # type: ignore[arg-type]


def test_set_model_multiple_times_tracks_latest() -> None:
    sut = _make()
    sut.set_model(Model("B", 2))
    sut.set_model(Model("C", 3))
    assert sut.model == Model("C", 3)
    assert sut.is_dirty is True


# ---------------------------------------------------------------------------
# DenyCommand
# ---------------------------------------------------------------------------


def test_deny_command_can_execute_is_always_true() -> None:
    sut = _make()
    assert sut.deny_command.can_execute() is True


def test_deny_command_publishes_hub_messages_even_when_not_dirty() -> None:
    hub: MessageHub[Any] = MessageHub()
    messages: list[Any] = []
    sub = hub.messages.subscribe(messages.append)

    sut: FormVM[Model] = FormVM(Model("A", 1), _noop, hub=hub)
    # Not dirty; deny still sends hub messages.
    sut.deny_command.execute()

    sub.dispose()
    assert len(messages) == 2, "hub messages sent even when model == snapshot"


# ---------------------------------------------------------------------------
# ApproveAsync — multiple rounds
# ---------------------------------------------------------------------------


async def test_approve_advances_snapshot_across_multiple_rounds() -> None:
    sut = _make()

    sut.set_model(Model("B", 2))
    await sut.approve_async()
    assert sut.snapshot == Model("B", 2)

    sut.set_model(Model("C", 3))
    await sut.approve_async()
    assert sut.snapshot == Model("C", 3)
    assert sut.is_dirty is False


async def test_approve_when_not_dirty_fires_on_approved() -> None:
    """Non-strict mode allows re-approval without mutation."""
    approved: list[Model] = []
    sut = _make()
    sub = sut.on_approved.subscribe(approved.append)

    await sut.approve_async()  # Not dirty — but still allowed in non-strict mode.

    assert len(approved) == 1, "on_approved fires even when not dirty in non-strict mode"
    sub.dispose()


async def test_approve_persister_receives_current_model() -> None:
    received: list[Model] = []

    async def persister(m: Model) -> None:
        received.append(m)

    sut: FormVM[Model] = FormVM(Model("A", 1), persister)
    updated = Model("B", 2)
    sut.set_model(updated)
    await sut.approve_async()

    assert received == [updated]


# ---------------------------------------------------------------------------
# Strict mode: CanExecuteChanged transitions
# ---------------------------------------------------------------------------


def test_strict_mode_can_execute_changed_fires_on_set_model() -> None:
    async def persister(m: Model) -> None:
        pass

    sut: FormVM[Model] = FormVM(Model("A", 1), persister, strict=True)
    fired: list[None] = []
    sut.approve_command.can_execute_changed.subscribe(fired.append)

    sut.set_model(Model("B", 2))  # becomes dirty → CanExecuteChanged
    assert len(fired) >= 1, "CanExecuteChanged fired when is_dirty transitions True"


def test_strict_mode_can_execute_changed_fires_on_deny() -> None:
    async def persister(m: Model) -> None:
        pass

    sut: FormVM[Model] = FormVM(Model("A", 1), persister, strict=True)
    sut.set_model(Model("B", 2))  # make dirty

    fired: list[None] = []
    sut.approve_command.can_execute_changed.subscribe(fired.append)

    sut.deny_command.execute()  # becomes pristine → CanExecuteChanged
    assert len(fired) >= 1, "CanExecuteChanged fired when is_dirty transitions False on deny"


# ---------------------------------------------------------------------------
# Hub message sender identity
# ---------------------------------------------------------------------------


def test_hub_messages_sender_is_form_vm_instance() -> None:
    hub: MessageHub[Any] = MessageHub()
    messages: list[Any] = []
    sub = hub.messages.subscribe(messages.append)

    sut: FormVM[Model] = FormVM(Model("A", 1), _noop, hub=hub)
    sut.set_model(Model("B", 2))
    sut.deny_command.execute()

    sub.dispose()

    revert = next(m for m in messages if isinstance(m, FormRevertedMessage))
    assert revert.sender is sut

    prop_change = next(m for m in messages if isinstance(m, PropertyChangedMessage))
    assert prop_change.sender is sut
    assert prop_change.property_name == "model"


# ---------------------------------------------------------------------------
# on_approved observable completes on dispose
# ---------------------------------------------------------------------------


def test_on_approved_completes_on_dispose() -> None:
    completed: list[bool] = []
    sut = _make()
    sut.on_approved.subscribe(on_completed=lambda: completed.append(True))

    sut.dispose()
    assert len(completed) == 1, "on_approved observable completes on dispose"


def test_dispose_is_idempotent() -> None:
    """Second dispose must be a no-op, not a reactivex DisposedException."""
    sut = _make()
    sut.dispose()
    sut.dispose()


def test_builder_snapshotter_is_used() -> None:
    """The builder's snapshotter setter reaches the FormVM (was ctor-only tested)."""
    snaps: list[Model] = []

    def snap(m: Model) -> Model:
        snaps.append(m)
        return Model(m.name, m.value)

    sut = FormVM.builder().initial(Model("A", 1)).persister(_noop).snapshotter(snap).build()

    assert snaps, "snapshotter runs for the initial snapshot"
    assert sut.snapshot is not sut.model
