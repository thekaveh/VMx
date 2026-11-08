using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: FORM-039..FORM-040 — <c>FormVM</c> queues updates made
/// during approval publication and replays them after <c>OnApproved</c>. See
/// spec/20-form-vm.md §5.1/§5.3/§5.4 and ADR-0174.
/// </summary>
/// <remarks>
/// PLACEHOLDER: the spec change for ADR-0174 adds these IDs before the C#
/// implementation lands. The implementation PR replaces each skipped test with
/// the behavioral test. The conformance execution check counts a skipped ID as
/// not passing, so CI stays red until then.
/// </remarks>
public sealed class FORM_039_to_040_ApprovalUpdateQueue_Tests
{
    private const string Placeholder = "ADR-0174 placeholder: replaced by the C# FormVM implementation";

    [Fact(Skip = Placeholder)]
    [Trait("Conformance", "FORM-039")]
    public void UpdatesDuringPublicationReplayAfterOnApproved()
    {
    }

    [Fact(Skip = Placeholder)]
    [Trait("Conformance", "FORM-040")]
    public void QueuedUpdatePreparesAtCallTimeAndReplaysInIsolation()
    {
    }
}
