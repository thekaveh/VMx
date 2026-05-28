using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance stubs: COL-016..COL-021 — PagedComposition&lt;TVM&gt;.
/// See spec/21-collections.md §5 and ADR-0023.
/// Implemented in Substage 1C.
/// </summary>
public class COL_016_to_021_PagedCompositionTests
{
    // ── COL-016 ──────────────────────────────────────────────────────────────

    /// <summary>COL-016: PagedComposition clamps CurrentPageIndex when source shrinks.</summary>
    [Fact, Trait("Conformance", "COL-016")]
    public void COL_016_ClampsCurrentPageIndex_WhenSourceShrinks()
    {
        throw new NotImplementedException("COL-016 stub — implement in Substage 1C");
    }

    // ── COL-017 ──────────────────────────────────────────────────────────────

    /// <summary>COL-017: PagedComposition PageCount derivation under add and remove.</summary>
    [Fact, Trait("Conformance", "COL-017")]
    public void COL_017_PageCount_DerivationUnderAddAndRemove()
    {
        throw new NotImplementedException("COL-017 stub — implement in Substage 1C");
    }

    // ── COL-018 ──────────────────────────────────────────────────────────────

    /// <summary>COL-018: PagedComposition navigation no-ops at bounds.</summary>
    [Fact, Trait("Conformance", "COL-018")]
    public void COL_018_Navigation_NoOpsAtBounds()
    {
        throw new NotImplementedException("COL-018 stub — implement in Substage 1C");
    }

    // ── COL-019 ──────────────────────────────────────────────────────────────

    /// <summary>COL-019: PagedComposition PageSize==0 passes through all items.</summary>
    [Fact, Trait("Conformance", "COL-019")]
    public void COL_019_PageSizeZero_PassesThroughAllItems()
    {
        throw new NotImplementedException("COL-019 stub — implement in Substage 1C");
    }

    // ── COL-020 ──────────────────────────────────────────────────────────────

    /// <summary>COL-020: PagedComposition empty-source behavior.</summary>
    [Fact, Trait("Conformance", "COL-020")]
    public void COL_020_EmptySource_Behavior()
    {
        throw new NotImplementedException("COL-020 stub — implement in Substage 1C");
    }

    // ── COL-021 ──────────────────────────────────────────────────────────────

    /// <summary>COL-021: PagedComposition composition with SearchableState.</summary>
    [Fact, Trait("Conformance", "COL-021")]
    public void COL_021_CompositionWith_SearchableState()
    {
        throw new NotImplementedException("COL-021 stub — implement in Substage 1C");
    }
}
