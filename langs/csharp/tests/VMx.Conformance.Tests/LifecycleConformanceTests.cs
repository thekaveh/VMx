using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// LIFE-001 through LIFE-013 — see spec/12-conformance.md.
///
/// Every LIFE-* id is exercised here by a self-contained test that drives a
/// real VM instance and asserts that id's own normative behavior (the
/// transition reached, the ConstructionStatusChangedMessage sequence emitted,
/// the gating exception, the idempotency, or the depth-first dispose cascade).
/// No test delegates to a different conformance id.
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

    private static (ComponentVM<string> vm, TestHub hub) BuildVmWithHub(string name = "life-vm")
    {
        var hub = new TestHub();
        var vm = ComponentVM<string>.Builder()
            .Name(name)
            .Services(hub, new TestDispatcher())
            .Model("m")
            .Build();
        return (vm, hub);
    }

    private static List<ConstructionStatusChangedMessage> RecordStatusMessages(TestHub hub)
    {
        var messages = new List<ConstructionStatusChangedMessage>();
        hub.Messages.Subscribe(m =>
        {
            if (m is ConstructionStatusChangedMessage csm) messages.Add(csm);
        });
        return messages;
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

    // LIFE-001..004, LIFE-007..010, LIFE-012, LIFE-013 — each below drives a
    // real VM instance and asserts that id's own normative behavior directly.

    // LIFE-001 — construct from Destructed observes exactly Constructing then
    // Constructed, and IsConstructed is true afterwards.
    [Fact, Trait("Conformance", "LIFE-001")]
    public void LIFE_001_Construct_Transitions_Through_Constructing_To_Constructed()
    {
        var (vm, hub) = BuildVmWithHub();
        vm.Status.Should().Be(ConstructionStatus.Destructed, "a freshly built VM starts Destructed");
        var messages = RecordStatusMessages(hub);

        vm.Construct();

        messages.Should().HaveCount(2);
        messages[0].Status.Should().Be(ConstructionStatus.Constructing);
        messages[1].Status.Should().Be(ConstructionStatus.Constructed);
        vm.IsConstructed.Should().BeTrue();
        vm.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // LIFE-002 — destruct from Constructed observes exactly Destructing then
    // Destructed, and IsConstructed is false afterwards.
    [Fact, Trait("Conformance", "LIFE-002")]
    public void LIFE_002_Destruct_Transitions_Through_Destructing_To_Destructed()
    {
        var (vm, hub) = BuildVmWithHub();
        vm.Construct();
        var messages = RecordStatusMessages(hub);

        vm.Destruct();

        messages.Should().HaveCount(2);
        messages[0].Status.Should().Be(ConstructionStatus.Destructing);
        messages[1].Status.Should().Be(ConstructionStatus.Destructed);
        vm.IsConstructed.Should().BeFalse();
        vm.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // LIFE-003 — reconstruct from Constructed observes exactly Destructing,
    // Destructed, Constructing, Constructed, in that order.
    [Fact, Trait("Conformance", "LIFE-003")]
    public void LIFE_003_Reconstruct_Emits_Full_Sequence()
    {
        var (vm, hub) = BuildVmWithHub();
        vm.Construct();
        var messages = RecordStatusMessages(hub);

        vm.Reconstruct();

        messages.Select(m => m.Status).Should().Equal(
            ConstructionStatus.Destructing,
            ConstructionStatus.Destructed,
            ConstructionStatus.Constructing,
            ConstructionStatus.Constructed);
        vm.IsConstructed.Should().BeTrue();
    }

    // LIFE-004 — dispose reaches Disposed from any state ∈ {Destructed,
    // Constructing, Constructed, Destructing} and emits a Disposed message.
    [Fact, Trait("Conformance", "LIFE-004")]
    public void LIFE_004_Dispose_Transitions_From_Any_State()
    {
        // From Destructed (freshly built).
        {
            var (vm, hub) = BuildVmWithHub();
            vm.Status.Should().Be(ConstructionStatus.Destructed);
            var messages = RecordStatusMessages(hub);

            vm.Dispose();

            vm.Status.Should().Be(ConstructionStatus.Disposed);
            messages.Should().Contain(m => m.Status == ConstructionStatus.Disposed);
        }

        // From Constructed.
        {
            var (vm, hub) = BuildVmWithHub();
            vm.Construct();
            var messages = RecordStatusMessages(hub);

            vm.Dispose();

            vm.Status.Should().Be(ConstructionStatus.Disposed);
            messages.Should().Contain(m => m.Status == ConstructionStatus.Disposed);
        }

        // From Constructing — dispose mid-construct via the OnConstruct hook,
        // where Status is observably Constructing.
        {
            var hub = new TestHub();
            ComponentVM<string>? vm = null;
            vm = ComponentVM<string>.Builder()
                .Name("life-vm").Services(hub, new TestDispatcher()).Model("m")
                .OnConstruct(() =>
                {
                    vm!.Status.Should().Be(ConstructionStatus.Constructing);
                    vm.Dispose();
                })
                .Build();

            vm.Construct();

            vm.Status.Should().Be(ConstructionStatus.Disposed);
        }

        // From Destructing — dispose mid-destruct via the OnDestruct hook,
        // where Status is observably Destructing.
        {
            var hub = new TestHub();
            ComponentVM<string>? vm = null;
            vm = ComponentVM<string>.Builder()
                .Name("life-vm").Services(hub, new TestDispatcher()).Model("m")
                .OnDestruct(() =>
                {
                    vm!.Status.Should().Be(ConstructionStatus.Destructing);
                    vm.Dispose();
                })
                .Build();
            vm.Construct();

            vm.Destruct();

            vm.Status.Should().Be(ConstructionStatus.Disposed);
        }
    }

    // LIFE-007 — IsConstructed equals (Status == Constructed) in every state.
    [Fact, Trait("Conformance", "LIFE-007")]
    public void LIFE_007_IsConstructed_Equals_Status_Constructed()
    {
        var (vm, _) = BuildVmWithHub();
        vm.IsConstructed.Should().Be(vm.Status == ConstructionStatus.Constructed);
        vm.IsConstructed.Should().BeFalse("freshly built is Destructed");

        vm.Construct();
        vm.IsConstructed.Should().Be(vm.Status == ConstructionStatus.Constructed);
        vm.IsConstructed.Should().BeTrue();

        vm.Destruct();
        vm.IsConstructed.Should().Be(vm.Status == ConstructionStatus.Constructed);
        vm.IsConstructed.Should().BeFalse();

        vm.Dispose();
        vm.IsConstructed.Should().Be(vm.Status == ConstructionStatus.Constructed);
        vm.IsConstructed.Should().BeFalse();
    }

    // LIFE-008 — re-invoking construct() while a construct() is in progress
    // (Status == Constructing) raises StatusTransitionException.
    [Fact, Trait("Conformance", "LIFE-008")]
    public void LIFE_008_Concurrent_Operation_While_Transitioning_Raises()
    {
        StatusTransitionException? caught = null;
        ComponentVM<string>? vm = null;
        vm = ComponentVM<string>.Builder()
            .Name("life-vm").Services(new TestHub(), new TestDispatcher()).Model("m")
            .OnConstruct(() =>
            {
                vm!.Status.Should().Be(ConstructionStatus.Constructing);
                try { vm.Construct(); }
                catch (StatusTransitionException ex) { caught = ex; }
            })
            .Build();

        vm.Construct();

        caught.Should().NotBeNull(
            "a second Construct while already Constructing must raise StatusTransitionException");
    }

    // LIFE-009 — construct from Constructed is a no-op: no new messages and
    // Status stays Constructed.
    [Fact, Trait("Conformance", "LIFE-009")]
    public void LIFE_009_Construct_From_Constructed_Is_Idempotent()
    {
        var (vm, hub) = BuildVmWithHub();
        vm.Construct();
        var messages = RecordStatusMessages(hub);

        vm.Construct(); // already Constructed

        messages.Should().BeEmpty();
        vm.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // LIFE-010 — destruct from Destructed is a no-op: no new messages and
    // Status stays Destructed.
    [Fact, Trait("Conformance", "LIFE-010")]
    public void LIFE_010_Destruct_From_Destructed_Is_Idempotent()
    {
        var (vm, hub) = BuildVmWithHub();
        vm.Status.Should().Be(ConstructionStatus.Destructed);
        var messages = RecordStatusMessages(hub);

        vm.Destruct(); // already Destructed

        messages.Should().BeEmpty();
        vm.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // LIFE-012 — dispose from Disposed is a no-op: no new messages and Status
    // stays Disposed.
    [Fact, Trait("Conformance", "LIFE-012")]
    public void LIFE_012_Dispose_From_Disposed_Emits_No_Message()
    {
        var (vm, hub) = BuildVmWithHub();
        vm.Dispose();
        vm.Status.Should().Be(ConstructionStatus.Disposed);
        var messages = RecordStatusMessages(hub);

        vm.Dispose(); // already Disposed

        messages.Should().BeEmpty();
        vm.Status.Should().Be(ConstructionStatus.Disposed);
    }

    // LIFE-013 — dispose on a parent disposes every child and grand-child, and
    // the disposal order is depth-first (descendants before their parent).
    [Fact, Trait("Conformance", "LIFE-013")]
    public void LIFE_013_Dispose_Cascade_Depth_First()
    {
        // root
        //   ├── child1 ── { gc1a, gc1b }
        //   └── child2 ── { gc2a }
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();

        ComponentVM<string> MakeLeaf(string name)
            => ComponentVM<string>.Builder()
                .Name(name).Services(hub, dispatcher).Model("m").Build();

        var gc1a = MakeLeaf("gc1a");
        var gc1b = MakeLeaf("gc1b");
        var gc2a = MakeLeaf("gc2a");

        var root = CompositeVM<IComponentVM>.Builder()
            .Name("root").Services(hub, dispatcher)
            .Children(() => Array.Empty<IComponentVM>())
            .Build();

        var child1 = CompositeVM<ComponentVM<string>>.Builder()
            .Name("child1").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        child1.Add(gc1a);
        child1.Add(gc1b);

        var child2 = CompositeVM<ComponentVM<string>>.Builder()
            .Name("child2").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        child2.Add(gc2a);

        root.Add(child1);
        root.Add(child2);

        gc1a.Construct();
        gc1b.Construct();
        gc2a.Construct();
        child1.Construct();
        child2.Construct();
        root.Construct();

        var disposalOrder = new List<string>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IConstructionStatusChangedMessage csm &&
                csm.Status == ConstructionStatus.Disposed)
                disposalOrder.Add(csm.SenderName);
        });

        root.Dispose();

        // Every node reached Disposed.
        gc1a.Status.Should().Be(ConstructionStatus.Disposed);
        gc1b.Status.Should().Be(ConstructionStatus.Disposed);
        gc2a.Status.Should().Be(ConstructionStatus.Disposed);
        child1.Status.Should().Be(ConstructionStatus.Disposed);
        child2.Status.Should().Be(ConstructionStatus.Disposed);
        root.Status.Should().Be(ConstructionStatus.Disposed);

        // Depth-first: each descendant disposed before its parent.
        disposalOrder.IndexOf("gc1a").Should().BeLessThan(disposalOrder.IndexOf("child1"));
        disposalOrder.IndexOf("gc1b").Should().BeLessThan(disposalOrder.IndexOf("child1"));
        disposalOrder.IndexOf("gc2a").Should().BeLessThan(disposalOrder.IndexOf("child2"));
        disposalOrder.IndexOf("child1").Should().BeLessThan(disposalOrder.IndexOf("root"));
        disposalOrder.IndexOf("child2").Should().BeLessThan(disposalOrder.IndexOf("root"));
    }

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
