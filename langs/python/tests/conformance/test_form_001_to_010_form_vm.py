"""FORM-001..FORM-010 — VMx FormVM conformance tests.

Per spec/20-form-vm.md and ADR-0030.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from vmx.commands.confirmation_decorator_command import ConfirmationDecoratorCommand
from vmx.dialogs import NullDialogService
from vmx.forms import FormVM
from vmx.messages import FormRevertedMessage, PropertyChangedMessage
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Shared model
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Model:
    name: str
    value: int


def _make_form_vm(initial: _Model) -> FormVM[_Model]:
    async def _noop_persister(m: _Model) -> None:
        pass

    return FormVM(initial, _noop_persister)


# ---------------------------------------------------------------------------
# FORM-001 — Snapshot captured at construct
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-001")
def test_form_001_snapshot_captured_at_construct() -> None:
    """Snapshot captured at construct; model == snapshot; is_dirty == False."""
    initial = _Model("Alice", 1)
    sut = _make_form_vm(initial)

    assert sut.model == initial
    assert sut.snapshot == initial
    assert sut.is_dirty is False


# ---------------------------------------------------------------------------
# FORM-002 — Model mutation reflected in IsDirty
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-002")
def test_form_002_model_mutation_reflected_in_is_dirty() -> None:
    """Model mutation reflected in is_dirty; snapshot unchanged."""
    initial = _Model("Alice", 1)
    sut = _make_form_vm(initial)

    sut.set_model(_Model("Bob", 2))

    assert sut.is_dirty is True
    assert sut.snapshot == initial, "snapshot unchanged after set_model"
    assert sut.model == _Model("Bob", 2)


# ---------------------------------------------------------------------------
# FORM-003 — IsDirty derivation via structural inequality
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-003")
def test_form_003_is_dirty_structural_inequality() -> None:
    """IsDirty uses structural inequality via __eq__."""
    initial = _Model("Alice", 1)
    sut = _make_form_vm(initial)

    # Value-equal model (different instance due to frozen dataclass) → not dirty.
    sut.set_model(_Model("Alice", 1))
    assert sut.is_dirty is False, "equal value → not dirty"

    # Structurally different → dirty.
    sut.set_model(_Model("Alice", 99))
    assert sut.is_dirty is True, "different value → dirty"


# ---------------------------------------------------------------------------
# FORM-004 — DenyCommand reverts Model to Snapshot
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-004")
def test_form_004_deny_command_reverts_to_snapshot() -> None:
    """DenyCommand reverts model to snapshot; is_dirty == False after revert."""
    initial = _Model("Alice", 1)
    sut = _make_form_vm(initial)

    sut.set_model(_Model("Bob", 2))
    assert sut.is_dirty is True

    sut.deny_command.execute()

    assert sut.model == initial, "model reverted to snapshot value"
    assert sut.is_dirty is False, "no longer dirty after revert"


# ---------------------------------------------------------------------------
# FORM-005 — ApproveCommand invokes persister; Snapshot advances on success
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-005")
async def test_form_005_approve_command_persists_and_advances_snapshot() -> None:
    """ApproveCommand invokes persister; snapshot advances on success."""
    initial = _Model("Alice", 1)
    persisted: list[_Model] = []

    async def persister(m: _Model) -> None:
        persisted.append(m)

    sut: FormVM[_Model] = FormVM(initial, persister)
    updated = _Model("Bob", 2)
    sut.set_model(updated)

    await sut.approve_async()

    assert len(persisted) == 1, "persister called once"
    assert persisted[0] == updated, "persister called with model"
    assert sut.snapshot == updated, "snapshot advanced to model after success"
    assert sut.is_dirty is False, "no longer dirty after approve"


# ---------------------------------------------------------------------------
# FORM-006 — OnApproved fires only after successful persist
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-006")
async def test_form_006_on_approved_fires_only_after_success() -> None:
    """on_approved fires only after successful persist; not before."""
    initial = _Model("Alice", 1)
    approved: list[_Model] = []

    async def persister(m: _Model) -> None:
        pass

    sut: FormVM[_Model] = FormVM(initial, persister)
    sub = sut.on_approved.subscribe(approved.append)

    assert len(approved) == 0, "on_approved not yet fired"

    sut.set_model(_Model("Bob", 2))
    await sut.approve_async()

    assert len(approved) == 1
    assert approved[0] == _Model("Bob", 2)

    sub.dispose()


# ---------------------------------------------------------------------------
# FORM-007 — Persist failure leaves state unchanged
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-007")
async def test_form_007_persist_failure_leaves_state_unchanged() -> None:
    """Persist failure leaves Snapshot and Model unchanged; exception propagates."""
    initial = _Model("Alice", 1)
    updated = _Model("Bob", 2)
    approved: list[_Model] = []

    async def failing_persister(m: _Model) -> None:
        raise RuntimeError("DB error")

    sut: FormVM[_Model] = FormVM(initial, failing_persister)
    sub = sut.on_approved.subscribe(approved.append)

    sut.set_model(updated)

    with pytest.raises(RuntimeError, match="DB error"):
        await sut.approve_async()

    assert sut.model == updated, "model unchanged after failed persist"
    assert sut.snapshot == initial, "snapshot unchanged after failed persist"
    assert sut.is_dirty is True, "still dirty after failed persist"
    assert len(approved) == 0, "on_approved not fired on failure"

    sub.dispose()


# ---------------------------------------------------------------------------
# FORM-008 — Hub messages on revert
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-008")
def test_form_008_hub_messages_on_revert() -> None:
    """DenyCommand publishes FormRevertedMessage and PropertyChangedMessage('model') on hub."""
    hub: MessageHub[Any] = MessageHub()
    messages: list[Any] = []
    sub = hub.messages.subscribe(messages.append)

    initial = _Model("Alice", 1)

    async def persister(m: _Model) -> None:
        pass

    sut: FormVM[_Model] = FormVM(initial, persister, hub=hub)

    sut.set_model(_Model("Bob", 2))
    messages.clear()
    sut.deny_command.execute()

    sub.dispose()

    assert len(messages) == 2, "two hub messages published on revert"
    # FORM-008 order: the model PropertyChangedMessage is published AFTER the
    # FormRevertedMessage.
    assert isinstance(messages[0], FormRevertedMessage), "revert precedes the model change"
    assert isinstance(messages[1], PropertyChangedMessage), "model change follows the revert"

    revert_msgs = [m for m in messages if isinstance(m, FormRevertedMessage)]
    assert len(revert_msgs) == 1, "FormRevertedMessage published"
    assert revert_msgs[0].sender is sut, "sender is the FormVM instance"
    assert revert_msgs[0].sender_name == "FormVM", "sender_name is the type name"

    prop_msgs = [m for m in messages if isinstance(m, PropertyChangedMessage)]
    assert len(prop_msgs) == 1, "PropertyChangedMessage published"
    assert prop_msgs[0].property_name == "model"


# ---------------------------------------------------------------------------
# FORM-009 — Strict mode: ApproveCommand.CanExecute gates on IsDirty
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-009")
def test_form_009_strict_mode_approve_can_execute_gates_on_is_dirty() -> None:
    """Strict mode: approve_command.can_execute() is False when not dirty."""

    async def persister(m: _Model) -> None:
        pass

    initial = _Model("Alice", 1)
    sut: FormVM[_Model] = FormVM(initial, persister, strict=True)

    # Initially not dirty → cannot approve.
    assert sut.is_dirty is False
    assert sut.approve_command.can_execute() is False, "strict: not dirty → cannot approve"

    # Dirty → can approve.
    sut.set_model(_Model("Bob", 2))
    assert sut.approve_command.can_execute() is True, "strict: dirty → can approve"

    # Non-strict (default): always True regardless of is_dirty.
    non_strict: FormVM[_Model] = FormVM(initial, persister, strict=False)
    assert non_strict.approve_command.can_execute() is True, (
        "non-strict: can approve even when not dirty"
    )


# ---------------------------------------------------------------------------
# FORM-010 — Integration with DialogService.confirm
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-010")
async def test_form_010_dialog_service_confirm_integration() -> None:
    """Integration with ``DialogService.confirm``.

    Confirm guard prevents revert on False return.
    """
    initial = _Model("Alice", 1)
    sut = _make_form_vm(initial)

    sut.set_model(_Model("Bob", 2))
    assert sut.is_dirty is True

    # Wrap DenyCommand with NullDialogService.Confirm (returns False → guard blocks revert).
    null_ds = NullDialogService()
    guarded_deny = ConfirmationDecoratorCommand(
        inner=sut.deny_command,
        confirm=lambda: null_ds.confirm("Discard changes?"),
    )

    await guarded_deny.execute_async()

    # Model should NOT have been reverted (confirm returned False).
    assert sut.is_dirty is True, "deny blocked by confirm returning False"
    assert sut.model == _Model("Bob", 2), "model unchanged when confirm returns False"

    # Now confirm returns True → revert proceeds.
    async def _always_true() -> bool:
        return True

    confirming_deny = ConfirmationDecoratorCommand(
        inner=sut.deny_command,
        confirm=_always_true,
    )
    await confirming_deny.execute_async()

    assert sut.is_dirty is False, "model reverted when confirm returns True"
    assert sut.model == initial, "model restored to snapshot"


@pytest.mark.conformance("FORM-014")
async def test_FORM_014_disposed_form_is_inert() -> None:
    """FORM-014: A disposed form is inert — approve never invokes the
    persister; deny does not revert the model (spec/20 §9)."""
    persisted: list[_Model] = []

    async def persister(m: _Model) -> None:
        persisted.append(m)

    sut: FormVM[_Model] = FormVM(_Model("Alice", 1), persister)
    sut.set_model(_Model("Bob", 2))
    assert sut.is_dirty is True

    sut.dispose()

    await sut.approve_async()
    sut.deny_command.execute()

    assert persisted == [], "persister must not run on a disposed form"
    assert sut.model == _Model("Bob", 2), "deny must not revert a disposed form"


# ---------------------------------------------------------------------------
# FORM-015 — ApproveCommand surfaces persister failure on approve_errors
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-015")
async def test_form_015_approve_command_surfaces_persister_error() -> None:
    """FORM-015: a persister failure on the fire-and-forget command path is
    surfaced on ``approve_errors`` (not swallowed); no state is mutated and
    ``on_approved`` does not fire (spec/20 §2/§7, ADR-0048)."""
    boom = RuntimeError("persist failed")
    initial = _Model("Alice", 1)

    async def failing_persister(m: _Model) -> None:
        raise boom

    sut: FormVM[_Model] = FormVM(initial, failing_persister)
    errors: list[BaseException] = []
    approved: list[_Model] = []
    err_sub = sut.approve_errors.subscribe(errors.append)
    appr_sub = sut.on_approved.subscribe(approved.append)

    sut.set_model(_Model("Bob", 2))

    sut.approve_command.execute()  # fire-and-forget command path
    # Let the scheduled task + its done-callback run.
    for _ in range(5):
        await asyncio.sleep(0)
        if errors:
            break

    assert errors == [boom], "persister error surfaced on approve_errors, not swallowed"
    assert sut.is_dirty is True, "a failed persist must not advance the snapshot"
    assert sut.snapshot == initial, "snapshot unchanged after a failed persist"
    assert approved == [], "on_approved must not fire on a failed persist"

    err_sub.dispose()
    appr_sub.dispose()


# ---------------------------------------------------------------------------
# Exceptional teardown (#336): every owned step runs once and the first error
# wins. Flavor-local repair of spec/20 §10; no new conformance ID.
# ---------------------------------------------------------------------------

_TEARDOWN_STEPS: tuple[tuple[str, str], ...] = (
    ("_on_approved", "on_completed"),
    ("_on_approved", "dispose"),
    ("_approve_errors", "on_completed"),
    ("_approve_errors", "dispose"),
    ("_errors_changed", "on_completed"),
    ("_errors_changed", "dispose"),
    ("_can_execute_trigger", "on_completed"),
    ("_can_execute_trigger", "dispose"),
    ("_deny_command", "dispose"),
    ("_approve_command", "dispose"),
)
_TEARDOWN_LABELS = [f"{owner}.{method}" for owner, method in _TEARDOWN_STEPS]
_OWNED_SUBJECTS = ("_on_approved", "_approve_errors", "_errors_changed", "_can_execute_trigger")


def _recording_step(
    ran: list[str],
    label: str,
    original: Callable[[], None],
    failure: BaseException | None,
) -> Callable[[], None]:
    def step() -> None:
        ran.append(label)
        original()
        if failure is not None:
            raise failure

    return step


def _spy_teardown(
    sut: FormVM[_Model], failures: Mapping[int, BaseException] | None = None
) -> list[str]:
    """Record every owned teardown step; a step listed in ``failures`` runs and then raises."""
    ran: list[str] = []
    for index, (owner_name, method_name) in enumerate(_TEARDOWN_STEPS):
        owner = getattr(sut, owner_name)
        failure = (failures or {}).get(index)
        step = _recording_step(ran, _TEARDOWN_LABELS[index], getattr(owner, method_name), failure)
        setattr(owner, method_name, step)
    return ran


def _required_name_form() -> FormVM[_Model]:
    async def persister(m: _Model) -> None:
        pass

    return FormVM(
        _Model("Alice", 1),
        persister,
        validators={"name": lambda m: "required" if not m.name else None},
    )


@pytest.mark.parametrize("failing_index", range(len(_TEARDOWN_STEPS)), ids=_TEARDOWN_LABELS)
def test_form_teardown_failure_at_any_step_still_runs_every_step(failing_index: int) -> None:
    sut = _make_form_vm(_Model("Alice", 1))
    boom = RuntimeError(f"teardown step {failing_index} failed")
    ran = _spy_teardown(sut, {failing_index: boom})

    with pytest.raises(RuntimeError) as raised:
        sut.dispose()

    assert raised.value is boom
    assert ran == _TEARDOWN_LABELS
    assert all(getattr(sut, name).is_disposed for name in _OWNED_SUBJECTS)
    sut.dispose()  # idempotent after a partial failure: nothing re-runs or raises
    assert ran == _TEARDOWN_LABELS


def test_form_raising_completion_observer_does_not_leak_later_steps() -> None:
    sut = _make_form_vm(_Model("Alice", 1))
    boom = RuntimeError("observer boom")
    later_completed: list[str] = []

    def raise_boom() -> None:
        raise boom

    sut.on_approved.subscribe(on_completed=raise_boom)
    sut.errors_changed.subscribe(on_completed=lambda: later_completed.append("errors_changed"))

    with pytest.raises(RuntimeError) as raised:
        sut.dispose()

    assert raised.value is boom
    assert later_completed == ["errors_changed"]
    assert all(getattr(sut, name).is_disposed for name in _OWNED_SUBJECTS)
    assert not sut.approve_command.can_execute()
    assert not sut.deny_command.can_execute()


def test_form_teardown_reraises_first_failure_not_a_later_one() -> None:
    sut = _make_form_vm(_Model("Alice", 1))
    first = RuntimeError("first failure")
    second = RuntimeError("second failure")
    ran = _spy_teardown(sut, {0: first, 5: second})

    with pytest.raises(RuntimeError) as raised:
        sut.dispose()

    assert raised.value is first
    assert ran == _TEARDOWN_LABELS


def test_form_dispose_from_completion_handler_runs_teardown_once() -> None:
    sut = _make_form_vm(_Model("Alice", 1))
    ran = _spy_teardown(sut)
    reentered: list[str] = []

    def dispose_again() -> None:
        reentered.append("on_completed")
        sut.dispose()

    sut.on_approved.subscribe(on_completed=dispose_again)
    sut.dispose()

    assert reentered == ["on_completed"]
    assert ran == _TEARDOWN_LABELS


def test_form_dispose_from_mutation_observer_defers_teardown_to_mutation_end() -> None:
    sut = _required_name_form()
    ran = _spy_teardown(sut)
    ran_during_observer: list[list[str]] = []

    def dispose_mid_mutation(_errors: dict[str, str]) -> None:
        sut.dispose()
        ran_during_observer.append(list(ran))

    sut.errors_changed.subscribe(dispose_mid_mutation)
    sut.set_model(_Model("", 1))

    assert ran_during_observer == [[]], "teardown must wait for the mutation to finish"
    assert ran == _TEARDOWN_LABELS
    assert sut.model == _Model("", 1)


def test_form_deferred_teardown_failure_does_not_replace_in_flight_error() -> None:
    sut = _required_name_form()
    observer_error = KeyError("observer failed after disposing")
    ran = _spy_teardown(sut, {2: RuntimeError("teardown failure")})

    def dispose_then_fail(_errors: dict[str, str]) -> None:
        sut.dispose()
        raise observer_error

    sut.errors_changed.subscribe(dispose_then_fail)

    with pytest.raises(KeyError) as raised:
        sut.set_model(_Model("", 1))

    assert raised.value is observer_error
    assert ran == _TEARDOWN_LABELS


def test_form_deferred_teardown_failure_on_deny_does_not_replace_in_flight_error() -> None:
    sut = _required_name_form()
    sut.set_model(_Model("", 1))
    observer_error = KeyError("deny observer failed after disposing")
    ran = _spy_teardown(sut, {0: RuntimeError("teardown failure")})

    def dispose_then_fail(_errors: dict[str, str]) -> None:
        sut.dispose()
        raise observer_error

    sut.errors_changed.subscribe(dispose_then_fail)

    with pytest.raises(KeyError) as raised:
        sut.deny_command.execute()

    assert raised.value is observer_error
    assert ran == _TEARDOWN_LABELS


def test_form_deferred_teardown_failure_surfaces_when_mutation_succeeded() -> None:
    sut = _required_name_form()
    teardown_error = RuntimeError("teardown failure")
    ran = _spy_teardown(sut, {4: teardown_error})
    sut.errors_changed.subscribe(lambda _errors: sut.dispose())

    with pytest.raises(RuntimeError) as raised:
        sut.set_model(_Model("", 1))

    assert raised.value is teardown_error
    assert ran == _TEARDOWN_LABELS


async def test_form_dispose_from_approval_observer_runs_teardown_once() -> None:
    sut = _make_form_vm(_Model("Alice", 1))
    ran = _spy_teardown(sut)
    approved: list[_Model] = []

    def dispose_on_approved(model: _Model) -> None:
        approved.append(model)
        sut.dispose()

    sut.on_approved.subscribe(dispose_on_approved)
    sut.set_model(_Model("Bob", 2))
    await sut.approve_async()

    assert approved == [_Model("Bob", 2)]
    assert ran == _TEARDOWN_LABELS
    sut.set_model(_Model("Carol", 3))  # inert after disposal
    assert sut.model == _Model("Bob", 2)


async def test_form_late_persister_error_after_dispose_is_inert() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def persister(m: _Model) -> None:
        entered.set()
        await release.wait()
        raise RuntimeError("late persister failure")

    sut: FormVM[_Model] = FormVM(_Model("Alice", 1), persister)
    surfaced: list[BaseException] = []
    sut.approve_errors.subscribe(surfaced.append)
    loop = asyncio.get_running_loop()
    callback_errors: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda _loop, context: callback_errors.append(context))
    try:
        sut.approve_command.execute()
        await entered.wait()
        sut.dispose()
        release.set()
        approvals = asyncio.all_tasks() - {asyncio.current_task()}
        assert len(approvals) == 1
        # The done-callback routing persister failures was registered first, so
        # it has run by the time this await resumes.
        await asyncio.gather(*approvals, return_exceptions=True)
    finally:
        loop.set_exception_handler(None)

    assert surfaced == []
    assert callback_errors == []


async def test_form_post_dispose_calls_are_inert() -> None:
    persisted: list[_Model] = []
    approved: list[_Model] = []
    changed: list[dict[str, str]] = []

    async def persister(m: _Model) -> None:
        persisted.append(m)

    sut: FormVM[_Model] = FormVM(_Model("Alice", 1), persister)
    sut.on_approved.subscribe(approved.append)
    sut.errors_changed.subscribe(changed.append)
    sut.dispose()

    sut.set_model(_Model("Bob", 2))
    sut.approve_command.execute()
    sut.deny_command.execute()
    await sut.approve_async()

    assert persisted == []
    assert approved == []
    assert changed == []
    assert sut.model == _Model("Alice", 1)


def test_form_disposal_leaves_caller_owned_hub_usable() -> None:
    hub = MessageHub()
    received: list[Any] = []
    hub.messages.subscribe(received.append)

    async def persister(m: _Model) -> None:
        pass

    sut: FormVM[_Model] = FormVM(_Model("Alice", 1), persister, hub=hub)
    sut.dispose()

    hub.send("after-form-dispose")
    assert received[-1] == "after-form-dispose"
