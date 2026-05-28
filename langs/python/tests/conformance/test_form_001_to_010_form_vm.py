"""FORM-001..FORM-010 stubs — VMx absorption audit Stage 3 (FormVM).

Per spec/20-form-vm.md and ADR-0030. Substage 3A (spec foundation).
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# FORM-001 — Snapshot captured at construct
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-001")
@pytest.mark.skip(reason="FORM-001 not yet implemented")
def test_form_001_snapshot_captured_at_construct() -> None:
    raise NotImplementedError("FORM-001")


# ---------------------------------------------------------------------------
# FORM-002 — Model mutation reflected in IsDirty
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-002")
@pytest.mark.skip(reason="FORM-002 not yet implemented")
def test_form_002_model_mutation_reflected_in_is_dirty() -> None:
    raise NotImplementedError("FORM-002")


# ---------------------------------------------------------------------------
# FORM-003 — IsDirty derivation via structural inequality
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-003")
@pytest.mark.skip(reason="FORM-003 not yet implemented")
def test_form_003_is_dirty_structural_inequality() -> None:
    raise NotImplementedError("FORM-003")


# ---------------------------------------------------------------------------
# FORM-004 — DenyCommand reverts Model to Snapshot
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-004")
@pytest.mark.skip(reason="FORM-004 not yet implemented")
def test_form_004_deny_command_reverts_to_snapshot() -> None:
    raise NotImplementedError("FORM-004")


# ---------------------------------------------------------------------------
# FORM-005 — ApproveCommand invokes persister; Snapshot advances on success
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-005")
@pytest.mark.skip(reason="FORM-005 not yet implemented")
def test_form_005_approve_command_persists_and_advances_snapshot() -> None:
    raise NotImplementedError("FORM-005")


# ---------------------------------------------------------------------------
# FORM-006 — OnApproved fires only after successful persist
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-006")
@pytest.mark.skip(reason="FORM-006 not yet implemented")
def test_form_006_on_approved_fires_only_after_success() -> None:
    raise NotImplementedError("FORM-006")


# ---------------------------------------------------------------------------
# FORM-007 — Persist failure leaves state unchanged
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-007")
@pytest.mark.skip(reason="FORM-007 not yet implemented")
def test_form_007_persist_failure_leaves_state_unchanged() -> None:
    raise NotImplementedError("FORM-007")


# ---------------------------------------------------------------------------
# FORM-008 — Hub messages on revert
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-008")
@pytest.mark.skip(reason="FORM-008 not yet implemented")
def test_form_008_hub_messages_on_revert() -> None:
    raise NotImplementedError("FORM-008")


# ---------------------------------------------------------------------------
# FORM-009 — Strict mode: ApproveCommand.CanExecute gates on IsDirty
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-009")
@pytest.mark.skip(reason="FORM-009 not yet implemented")
def test_form_009_strict_mode_approve_can_execute_gates_on_is_dirty() -> None:
    raise NotImplementedError("FORM-009")


# ---------------------------------------------------------------------------
# FORM-010 — Integration with IDialogService.Confirm
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-010")
@pytest.mark.skip(reason="FORM-010 not yet implemented")
def test_form_010_dialog_service_confirm_integration() -> None:
    raise NotImplementedError("FORM-010")
