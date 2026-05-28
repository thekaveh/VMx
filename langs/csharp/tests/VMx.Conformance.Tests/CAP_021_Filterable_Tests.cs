using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance stub: CAP-021 — IFilterable&lt;TItem&gt; capability contract surface and opt-in behavior.
/// See spec/12-conformance.md §CAP-021 and spec/14-capabilities.md.
/// IFilterable&lt;TItem&gt; does not exist yet; this stub will be filled in during Task 1A.5–1A.7.
/// </summary>
public class CAP_021_Filterable_Tests
{
    // ── CAP-021 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-021: IFilterable&lt;TItem&gt; contract — stub, not yet implemented.</summary>
    [Fact, Trait("Conformance", "CAP-021")]
    public void CAP_021_IFilterable_Contract_Stub()
    {
        // IFilterable<TItem> is not implemented yet (Task 1A.5–1A.7).
        // This stub satisfies the conformance coverage requirement; replace with
        // a real test once IFilterable<TItem> lands in VMx.Capabilities.
        throw new NotImplementedException("CAP-021: IFilterable<TItem> not yet implemented — see Task 1A.5");
    }
}
