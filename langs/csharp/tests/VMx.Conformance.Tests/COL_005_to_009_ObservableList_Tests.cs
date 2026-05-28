using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance stubs: COL-005..COL-009 — ObservableList&lt;T&gt; granular events.
/// See spec/21-collections.md §3 and ADR-0026.
/// Implemented in Substage 1C.
/// </summary>
public class COL_005_to_009_ObservableListTests
{
    // ── COL-005 ──────────────────────────────────────────────────────────────

    /// <summary>COL-005: ObservableList ItemAdded payload shape.</summary>
    [Fact, Trait("Conformance", "COL-005")]
    public void COL_005_ItemAdded_PayloadShape()
    {
        throw new NotImplementedException("COL-005 stub — implement in Substage 1C");
    }

    // ── COL-006 ──────────────────────────────────────────────────────────────

    /// <summary>COL-006: ObservableList ItemRemoved payload shape.</summary>
    [Fact, Trait("Conformance", "COL-006")]
    public void COL_006_ItemRemoved_PayloadShape()
    {
        throw new NotImplementedException("COL-006 stub — implement in Substage 1C");
    }

    // ── COL-007 ──────────────────────────────────────────────────────────────

    /// <summary>COL-007: ObservableList ItemReplaced payload shape.</summary>
    [Fact, Trait("Conformance", "COL-007")]
    public void COL_007_ItemReplaced_PayloadShape()
    {
        throw new NotImplementedException("COL-007 stub — implement in Substage 1C");
    }

    // ── COL-008 ──────────────────────────────────────────────────────────────

    /// <summary>COL-008: ObservableList Count/PropertyChanged ordering after add.</summary>
    [Fact, Trait("Conformance", "COL-008")]
    public void COL_008_CountPropertyChangedOrdering_AfterAdd()
    {
        throw new NotImplementedException("COL-008 stub — implement in Substage 1C");
    }

    // ── COL-009 ──────────────────────────────────────────────────────────────

    /// <summary>COL-009: ObservableList batch suppression — only Reset fires inside BatchUpdate.</summary>
    [Fact, Trait("Conformance", "COL-009")]
    public void COL_009_BatchSuppression_OnlyResetFires()
    {
        throw new NotImplementedException("COL-009 stub — implement in Substage 1C");
    }
}
