using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance stubs: COL-001..COL-004 — ServicedObservableCollection&lt;T&gt;.
/// See spec/21-collections.md §2 and ADR-0024.
/// Implemented in Substage 1C.
/// </summary>
public class COL_001_to_004_ServicedObservableCollectionTests
{
    // ── COL-001 ──────────────────────────────────────────────────────────────

    /// <summary>COL-001: ServicedObservableCollection publishes to hub after local event on add.</summary>
    [Fact, Trait("Conformance", "COL-001")]
    public void COL_001_PublishesToHubAfterLocalEventOnAdd()
    {
        throw new NotImplementedException("COL-001 stub — implement in Substage 1C");
    }

    // ── COL-002 ──────────────────────────────────────────────────────────────

    /// <summary>COL-002: ServicedObservableCollection publishes on remove and replace.</summary>
    [Fact, Trait("Conformance", "COL-002")]
    public void COL_002_PublishesOnRemoveAndReplace()
    {
        throw new NotImplementedException("COL-002 stub — implement in Substage 1C");
    }

    // ── COL-003 ──────────────────────────────────────────────────────────────

    /// <summary>COL-003: Null-hub fallback — no hub means no publication, no error.</summary>
    [Fact, Trait("Conformance", "COL-003")]
    public void COL_003_NullHubFallback_NoPublicationNoError()
    {
        throw new NotImplementedException("COL-003 stub — implement in Substage 1C");
    }

    // ── COL-004 ──────────────────────────────────────────────────────────────

    /// <summary>COL-004: ServicedObservableCollection fires on caller thread, no marshal.</summary>
    [Fact, Trait("Conformance", "COL-004")]
    public void COL_004_FiresOnCallerThread_NoMarshal()
    {
        throw new NotImplementedException("COL-004 stub — implement in Substage 1C");
    }
}
