using FluentAssertions;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// LIFE-001 through LIFE-013 — see spec/12-conformance.md.
///
/// LIFE-005, LIFE-006, and LIFE-011 drive real VM instances (a maintenance
/// audit found the earlier validator-only versions could not fail if
/// Construct() stopped routing through Require). The remaining LIFE-* tests
/// that need richer harnesses live in ComponentVMConformanceTests /
/// CompositeVMConformanceTests and are delegated below.
/// </summary>
public class LifecycleConformanceTests
{
    private static ComponentVM<string> BuildVm(
        Action? onConstruct = null, Action? onDestruct = null)
    {
        var builder = ComponentVM<string>.Builder()
            .Name("life-vm")
            .Services(new TestHub(), new TestDispatcher())
            .Model("m");
        if (onConstruct is not null) builder = builder.OnConstruct(onConstruct);
        if (onDestruct is not null) builder = builder.OnDestruct(onDestruct);
        return builder.Build();
    }

    // LIFE-005 — construct from Disposed raises (message must mention state + op).
    [Fact, Trait("Conformance", "LIFE-005")]
    public void LIFE_005_Construct_From_Disposed_Raises_With_Message()
    {
        var vm = BuildVm();
        vm.Dispose();
        var ex = Assert.Throws<StatusTransitionException>(() => vm.Construct());
        ex.Message.Should().Contain("Disposed").And.Contain("construct");
    }

    // LIFE-006 — destruct from Disposed raises (parity with LIFE-005).
    [Fact, Trait("Conformance", "LIFE-006")]
    public void LIFE_006_Destruct_From_Disposed_Raises_With_Message()
    {
        var vm = BuildVm();
        vm.Dispose();
        var ex = Assert.Throws<StatusTransitionException>(() => vm.Destruct());
        ex.Message.Should().Contain("Disposed").And.Contain("destruct");
    }

    // LIFE-011 — every fixture row driven against a real VM: legal rows reach
    // to_final; illegal rows raise. Mid-transition rows reach Constructing /
    // Destructing via the builder's lifecycle hooks (the catalog's
    // "controllable hook" allowance).
    [Fact, Trait("Conformance", "LIFE-011")]
    public void LIFE_011_Vm_Transitions_Match_Fixture_Table()
    {
        foreach (var row in EnumerateFixtureRows())
        {
            var from = Enum.Parse<ConstructionStatus>(row.From, ignoreCase: false);

            // Validator-level agreement (fast feedback on table drift).
            LifecycleTransitionValidator.IsLegal(from, row.Via).Should().Be(row.Legal,
                $"row {row.From}/{row.Via} should have legal={row.Legal}");

            var (error, final) = DriveTransition(from, row.Via);
            if (row.Legal)
            {
                error.Should().BeNull($"row {row.From}/{row.Via} is legal");
                var expectedFinal = Enum.Parse<ConstructionStatus>(row.ToFinal!, ignoreCase: false);
                final.Should().Be(expectedFinal, $"row {row.From}/{row.Via}");
            }
            else
            {
                error.Should().BeOfType<StatusTransitionException>(
                    $"row {row.From}/{row.Via} is illegal");
            }
        }
    }

    private static (Exception? error, ConstructionStatus final) DriveTransition(
        ConstructionStatus from, string op)
    {
        Exception? captured = null;
        ComponentVM<string>? vm = null;

        void Invoke()
        {
            try
            {
                switch (op)
                {
                    case "construct": vm!.Construct(); break;
                    case "destruct": vm!.Destruct(); break;
                    case "reconstruct": vm!.Reconstruct(); break;
                    case "dispose": vm!.Dispose(); break;
                    default: throw new InvalidOperationException($"unknown op '{op}'");
                }
            }
            catch (StatusTransitionException ex)
            {
                captured = ex;
            }
        }

        switch (from)
        {
            case ConstructionStatus.Constructing:
                vm = BuildVm(onConstruct: Invoke);
                vm.Construct();
                break;
            case ConstructionStatus.Destructing:
                vm = BuildVm(onDestruct: Invoke);
                vm.Construct();
                vm.Destruct();
                break;
            default:
                vm = BuildVm();
                if (from == ConstructionStatus.Constructed) vm.Construct();
                else if (from == ConstructionStatus.Disposed) vm.Dispose();
                // Destructed is the freshly-built state.
                Invoke();
                break;
        }

        return (captured, vm.Status);
    }

    private static List<FixtureRow> EnumerateFixtureRows()
    {
        var table = Fixtures.FixtureLoader.Load<FixtureRoot>("lifecycle-transitions.json");
        return table.Transitions;
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
        public string? ToFinal { get; init; }
    }
}
