"""FORM-001..FORM-010 — VMx FormVM conformance tests.

Per spec/20-form-vm.md and ADR-0030.
"""

from __future__ import annotations

import dataclasses
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
    sut.deny_command.execute()

    sub.dispose()

    assert len(messages) == 2, "two hub messages published on revert"

    revert_msgs = [m for m in messages if isinstance(m, FormRevertedMessage)]
    assert len(revert_msgs) == 1, "FormRevertedMessage published"
    assert revert_msgs[0].sender is sut, "sender is the FormVM instance"

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
