using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance stubs: DIA-001..DIA-008 — IDialogService (host modal interactions).
/// See spec/19-dialogs.md and ADR-0029. Substage 3A (spec foundation).
/// </summary>
public class DIA_001_to_008_DialogService_Tests
{
    // ── DIA-001 ──────────────────────────────────────────────────────────────

    /// <summary>DIA-001: PickFileToOpen contract — optional filter/title; returns path or null.</summary>
    [Fact(Skip = "DIA-001 not yet implemented")]
    [Trait("Conformance", "DIA-001")]
    public void DIA_001_PickFileToOpen_Contract()
    {
        throw new System.NotImplementedException("DIA-001");
    }

    // ── DIA-002 ──────────────────────────────────────────────────────────────

    /// <summary>DIA-002: PickFileToSave contract — optional filter/title/suggestedName; returns path or null.</summary>
    [Fact(Skip = "DIA-002 not yet implemented")]
    [Trait("Conformance", "DIA-002")]
    public void DIA_002_PickFileToSave_Contract()
    {
        throw new System.NotImplementedException("DIA-002");
    }

    // ── DIA-003 ──────────────────────────────────────────────────────────────

    /// <summary>DIA-003: Confirm contract — message + optional title; returns bool.</summary>
    [Fact(Skip = "DIA-003 not yet implemented")]
    [Trait("Conformance", "DIA-003")]
    public void DIA_003_Confirm_Contract()
    {
        throw new System.NotImplementedException("DIA-003");
    }

    // ── DIA-004 ──────────────────────────────────────────────────────────────

    /// <summary>DIA-004: Notify contract — message/title/severity; completes without error.</summary>
    [Fact(Skip = "DIA-004 not yet implemented")]
    [Trait("Conformance", "DIA-004")]
    public void DIA_004_Notify_Contract()
    {
        throw new System.NotImplementedException("DIA-004");
    }

    // ── DIA-005 ──────────────────────────────────────────────────────────────

    /// <summary>DIA-005: NullDialogService — PickFile* returns null; Confirm returns false; Notify no-op.</summary>
    [Fact(Skip = "DIA-005 not yet implemented")]
    [Trait("Conformance", "DIA-005")]
    public void DIA_005_NullDialogService_Null_Object_Behavior()
    {
        throw new System.NotImplementedException("DIA-005");
    }

    // ── DIA-006 ──────────────────────────────────────────────────────────────

    /// <summary>DIA-006: Reentrancy is implementation-defined; both queueing and rejecting impls conform.</summary>
    [Fact(Skip = "DIA-006 not yet implemented")]
    [Trait("Conformance", "DIA-006")]
    public void DIA_006_Reentrancy_Implementation_Defined()
    {
        throw new System.NotImplementedException("DIA-006");
    }

    // ── DIA-007 ──────────────────────────────────────────────────────────────

    /// <summary>DIA-007: Cancellation completes with safe default (null/false), does not throw.</summary>
    [Fact(Skip = "DIA-007 not yet implemented")]
    [Trait("Conformance", "DIA-007")]
    public void DIA_007_Cancellation_Completes_With_Safe_Default()
    {
        throw new System.NotImplementedException("DIA-007");
    }

    // ── DIA-008 ──────────────────────────────────────────────────────────────

    /// <summary>DIA-008: ConfirmationDecoratorCommand with dialogService.Confirm constructs valid command graph.</summary>
    [Fact(Skip = "DIA-008 not yet implemented")]
    [Trait("Conformance", "DIA-008")]
    public void DIA_008_ConfirmationDecoratorCommand_Integration()
    {
        throw new System.NotImplementedException("DIA-008");
    }
}
