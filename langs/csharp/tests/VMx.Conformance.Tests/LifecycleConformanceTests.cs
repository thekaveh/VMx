using FluentAssertions;
using VMx.Lifecycle;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// LIFE-001 through LIFE-013 — see spec/12-conformance.md.
///
/// The component-VM lifecycle tests that exercise actual VM instances live in
/// ComponentVMConformanceTests; the LIFE-* tests here exercise the static
/// transition contract directly (state machine, exception type/message, fixture
/// table). Where a LIFE-* test depends on an actual VM instance (e.g., emit-zero-
/// messages from Disposed), the test re-runs against a freshly-built ComponentVM
/// to verify the integration.
/// </summary>
public class LifecycleConformanceTests
{
    // LIFE-005 — construct from Disposed raises (message must mention state + op).
    [Fact, Trait("Conformance", "LIFE-005")]
    public void LIFE_005_Construct_From_Disposed_Raises_With_Message()
    {
        var ex = Assert.Throws<StatusTransitionException>(
            () => LifecycleTransitionValidator.Require(ConstructionStatus.Disposed, "construct"));
        ex.Message.Should().Contain("Disposed").And.Contain("construct");
    }

    // LIFE-006 — destruct from Disposed raises (parity with LIFE-005).
    [Fact, Trait("Conformance", "LIFE-006")]
    public void LIFE_006_Destruct_From_Disposed_Raises_With_Message()
    {
        var ex = Assert.Throws<StatusTransitionException>(
            () => LifecycleTransitionValidator.Require(ConstructionStatus.Disposed, "destruct"));
        ex.Message.Should().Contain("Disposed").And.Contain("destruct");
    }

    // LIFE-011 — every row in the fixture exercised against the static validator.
    [Fact, Trait("Conformance", "LIFE-011")]
    public void LIFE_011_Validator_Matches_Fixture_Table()
    {
        // For each row in the fixture, verify the validator's IsLegal matches.
        // The validator already loads the same fixture as its source-of-truth,
        // so this test guards against future divergence (e.g., someone hand-codes
        // a transition that disagrees with the fixture).
        foreach (var (from, op, expectedLegal) in EnumerateFixtureRows())
        {
            LifecycleTransitionValidator.IsLegal(from, op).Should().Be(expectedLegal,
                $"row {from}/{op} should have legal={expectedLegal}");
        }
    }

    private static IEnumerable<(ConstructionStatus from, string op, bool legal)> EnumerateFixtureRows()
    {
        var table = Fixtures.FixtureLoader.Load<FixtureRoot>("lifecycle-transitions.json");
        foreach (var row in table.Transitions)
        {
            var from = Enum.Parse<ConstructionStatus>(row.From, ignoreCase: false);
            yield return (from, row.Via, row.Legal);
        }
    }

    // LIFE-001..004, LIFE-007..010, LIFE-012, LIFE-013 — these all require an
    // actual VM instance. Their assertions live in ComponentVMConformanceTests
    // and (for LIFE-013 disposal cascade) CompositeVMConformanceTests. We
    // declare placeholder [Fact, Trait] entries here that delegate, so the
    // catalog coverage tool sees each ID present in the C# conformance project.

    [Fact, Trait("Conformance", "LIFE-001")]
    public void LIFE_001_Construct_Transitions_Through_Constructing_To_Constructed()
        => new ComponentVMConformanceTests().CVM_001_Construct_Emits_Status_Messages();

    [Fact, Trait("Conformance", "LIFE-002")]
    public void LIFE_002_Destruct_Transitions_Through_Destructing_To_Destructed()
        => new ComponentVMConformanceTests().LIFE_002_Destruct_Transitions();

    [Fact, Trait("Conformance", "LIFE-003")]
    public void LIFE_003_Reconstruct_Emits_Full_Sequence()
        => new ComponentVMConformanceTests().LIFE_003_Reconstruct();

    [Fact, Trait("Conformance", "LIFE-004")]
    public void LIFE_004_Dispose_Transitions_From_Any_State()
        => new ComponentVMConformanceTests().LIFE_004_Dispose_From_Any_State();

    [Fact, Trait("Conformance", "LIFE-007")]
    public void LIFE_007_IsConstructed_Equals_Status_Constructed()
        => new ComponentVMConformanceTests().LIFE_007_IsConstructed_Invariant();

    [Fact, Trait("Conformance", "LIFE-008")]
    public void LIFE_008_Concurrent_Operation_While_Transitioning_Raises()
        => new ComponentVMConformanceTests().LIFE_008_Concurrent_Operation_Raises();

    [Fact, Trait("Conformance", "LIFE-009")]
    public void LIFE_009_Construct_From_Constructed_Is_Idempotent()
        => new ComponentVMConformanceTests().LIFE_009_Idempotent_Construct();

    [Fact, Trait("Conformance", "LIFE-010")]
    public void LIFE_010_Destruct_From_Destructed_Is_Idempotent()
        => new ComponentVMConformanceTests().LIFE_010_Idempotent_Destruct();

    [Fact, Trait("Conformance", "LIFE-012")]
    public void LIFE_012_Dispose_From_Disposed_Emits_No_Message()
        => new ComponentVMConformanceTests().LIFE_012_Dispose_From_Disposed_Silent();

    [Fact, Trait("Conformance", "LIFE-013")]
    public void LIFE_013_Dispose_Cascade_Depth_First()
        => new CompositeVMConformanceTests().LIFE_013_Dispose_Cascade();

    private sealed class FixtureRoot
    {
        public List<FixtureRow> Transitions { get; init; } = new();
    }

    private sealed class FixtureRow
    {
        public string From { get; init; } = "";
        public string Via { get; init; } = "";
        public bool Legal { get; init; }
    }
}
