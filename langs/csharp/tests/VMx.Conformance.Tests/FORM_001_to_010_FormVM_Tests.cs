using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance stubs: FORM-001..FORM-010 — FormVM&lt;TM&gt; (snapshot/revert edit lifecycle).
/// See spec/20-form-vm.md and ADR-0030. Substage 3A (spec foundation).
/// </summary>
public class FORM_001_to_010_FormVM_Tests
{
    // ── FORM-001 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-001: Snapshot captured at construct; Model == Snapshot; IsDirty == false.</summary>
    [Fact(Skip = "FORM-001 not yet implemented")]
    [Trait("Conformance", "FORM-001")]
    public void FORM_001_Snapshot_Captured_At_Construct()
    {
        throw new System.NotImplementedException("FORM-001");
    }

    // ── FORM-002 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-002: Model mutation reflected in IsDirty; Snapshot unchanged.</summary>
    [Fact(Skip = "FORM-002 not yet implemented")]
    [Trait("Conformance", "FORM-002")]
    public void FORM_002_Model_Mutation_Reflected_In_IsDirty()
    {
        throw new System.NotImplementedException("FORM-002");
    }

    // ── FORM-003 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-003: IsDirty derivation via structural inequality.</summary>
    [Fact(Skip = "FORM-003 not yet implemented")]
    [Trait("Conformance", "FORM-003")]
    public void FORM_003_IsDirty_Structural_Inequality()
    {
        throw new System.NotImplementedException("FORM-003");
    }

    // ── FORM-004 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-004: DenyCommand reverts Model to Snapshot; IsDirty == false after revert.</summary>
    [Fact(Skip = "FORM-004 not yet implemented")]
    [Trait("Conformance", "FORM-004")]
    public void FORM_004_DenyCommand_Reverts_To_Snapshot()
    {
        throw new System.NotImplementedException("FORM-004");
    }

    // ── FORM-005 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-005: ApproveCommand invokes persister; Snapshot advances on success.</summary>
    [Fact(Skip = "FORM-005 not yet implemented")]
    [Trait("Conformance", "FORM-005")]
    public void FORM_005_ApproveCommand_Persists_And_Advances_Snapshot()
    {
        throw new System.NotImplementedException("FORM-005");
    }

    // ── FORM-006 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-006: OnApproved fires only after successful persist.</summary>
    [Fact(Skip = "FORM-006 not yet implemented")]
    [Trait("Conformance", "FORM-006")]
    public void FORM_006_OnApproved_Fires_Only_After_Success()
    {
        throw new System.NotImplementedException("FORM-006");
    }

    // ── FORM-007 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-007: Persist failure leaves state unchanged; exception propagates.</summary>
    [Fact(Skip = "FORM-007 not yet implemented")]
    [Trait("Conformance", "FORM-007")]
    public void FORM_007_Persist_Failure_Leaves_State_Unchanged()
    {
        throw new System.NotImplementedException("FORM-007");
    }

    // ── FORM-008 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-008: Hub messages on revert — FormRevertedMessage + PropertyChangedMessage("Model").</summary>
    [Fact(Skip = "FORM-008 not yet implemented")]
    [Trait("Conformance", "FORM-008")]
    public void FORM_008_Hub_Messages_On_Revert()
    {
        throw new System.NotImplementedException("FORM-008");
    }

    // ── FORM-009 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-009: Strict mode — ApproveCommand.CanExecute gates on IsDirty.</summary>
    [Fact(Skip = "FORM-009 not yet implemented")]
    [Trait("Conformance", "FORM-009")]
    public void FORM_009_Strict_Mode_ApproveCanExecute_Gates_On_IsDirty()
    {
        throw new System.NotImplementedException("FORM-009");
    }

    // ── FORM-010 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-010: Integration with IDialogService.Confirm — confirm guard prevents revert on false.</summary>
    [Fact(Skip = "FORM-010 not yet implemented")]
    [Trait("Conformance", "FORM-010")]
    public void FORM_010_IDialogService_Confirm_Integration()
    {
        throw new System.NotImplementedException("FORM-010");
    }
}
