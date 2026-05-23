#pragma warning disable CA1715 // Spec uses 'VM' type parameter names per ADR-0006
using FluentAssertions;
using VMx.Aggregates;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for AggregateVM covering AGG-001..005.
/// See spec/08-aggregate-vm.md and spec/12-conformance.md.
/// </summary>
public class AggregateVMConformanceTests
{
    // ── Factory helpers ──────────────────────────────────────────────────────

    private static (TestHub hub, TestDispatcher dispatcher) MakeServices()
        => (new TestHub(), new TestDispatcher());

    private static ComponentVM<string> MakeLeaf(TestHub hub, TestDispatcher dispatcher, string name = "leaf")
        => ComponentVM<string>.Builder()
            .Name(name).Services(hub, dispatcher).Model("m").Build();

    // ── AGG-001 — Arity-1 ComponentN factory invoked on construct ─────────────

    /// <summary>
    /// AGG-001: Given AggregateVM1&lt;VM1&gt; built with .Component1(() =&gt; makeVm1()),
    /// when construct() is called:
    /// - agg.Component1 is populated with the result of makeVm1()
    /// - agg.Component1.Status == Constructed
    /// </summary>
    [Fact, Trait("Conformance", "AGG-001")]
    public void AGG_001_Arity1_Component1_Factory_Invoked_On_Construct()
    {
        var (hub, dispatcher) = MakeServices();
        ComponentVM<string>? factoryResult = null;
        var factoryInvoked = false;

        var agg = AggregateVM1<ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() =>
            {
                factoryInvoked = true;
                factoryResult = MakeLeaf(hub, dispatcher, "c1");
                return factoryResult;
            })
            .Build();

        // Factory not yet invoked before construct.
        factoryInvoked.Should().BeFalse();
        agg.Component1.Should().BeNull();

        agg.Construct();

        factoryInvoked.Should().BeTrue("factory must be invoked during construct()");
        agg.Component1.Should().BeSameAs(factoryResult,
            "Component1 must be the value returned by the factory");
        agg.Component1!.Status.Should().Be(ConstructionStatus.Constructed,
            "Component1 must be Constructed after agg.Construct()");
    }

    // ── AGG-002 — Arity-2 both components reach Constructed ───────────────────

    /// <summary>
    /// AGG-002: Given AggregateVM2&lt;VM1, VM2&gt; in Destructed,
    /// when construct() is called:
    /// - both agg.Component1.Status and agg.Component2.Status equal Constructed
    /// - the aggregate's Status == Constructed
    /// </summary>
    [Fact, Trait("Conformance", "AGG-002")]
    public void AGG_002_Arity2_Both_Components_Reach_Constructed()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM2<ComponentVM<string>, ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
            .Component2(() => MakeLeaf(hub, dispatcher, "c2"))
            .Build();

        agg.Construct();

        agg.Component1.Should().NotBeNull();
        agg.Component2.Should().NotBeNull();
        agg.Component1!.Status.Should().Be(ConstructionStatus.Constructed,
            "Component1 must be Constructed");
        agg.Component2!.Status.Should().Be(ConstructionStatus.Constructed,
            "Component2 must be Constructed");
        agg.Status.Should().Be(ConstructionStatus.Constructed,
            "aggregate itself must be Constructed");
    }

    // ── AGG-003 — Arity-5 all five components reach Constructed before parent ──

    /// <summary>
    /// AGG-003: Given AggregateVM5&lt;VM1..VM5&gt; in Destructed and a subscriber
    /// filtered on ConstructionStatusChangedMessage where Sender == agg,
    /// when construct() is called:
    /// the message with Status = Constructed and Sender == agg is observed
    /// ONLY AFTER every ComponentI.Status has reached Constructed.
    /// </summary>
    [Fact, Trait("Conformance", "AGG-003")]
    public void AGG_003_Arity5_All_Components_Constructed_Before_Parent()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM5<
            ComponentVM<string>, ComponentVM<string>, ComponentVM<string>,
            ComponentVM<string>, ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
            .Component2(() => MakeLeaf(hub, dispatcher, "c2"))
            .Component3(() => MakeLeaf(hub, dispatcher, "c3"))
            .Component4(() => MakeLeaf(hub, dispatcher, "c4"))
            .Component5(() => MakeLeaf(hub, dispatcher, "c5"))
            .Build();

        // Track child statuses at the moment the aggregate emits its Constructed message.
        int[]? childStatusesAtAggConstructed = null;

        hub.Messages.Subscribe(m =>
        {
            if (m is IConstructionStatusChangedMessage csm &&
                ReferenceEquals(csm.SenderObject, agg) &&
                csm.Status == ConstructionStatus.Constructed)
            {
                // Snapshot all child statuses at the instant the aggregate's Constructed fires.
                childStatusesAtAggConstructed = new[]
                {
                    (int)agg.Component1!.Status,
                    (int)agg.Component2!.Status,
                    (int)agg.Component3!.Status,
                    (int)agg.Component4!.Status,
                    (int)agg.Component5!.Status,
                };
            }
        });

        agg.Construct();

        childStatusesAtAggConstructed.Should().NotBeNull(
            "agg must have emitted a Constructed message");
        foreach (var status in childStatusesAtAggConstructed!)
        {
            status.Should().Be((int)ConstructionStatus.Constructed,
                "every child must be Constructed before the aggregate emits Constructed");
        }
    }

    // ── AGG-004 — ComponentN property change fires on construct ───────────────

    /// <summary>
    /// AGG-004: Given AggregateVM3&lt;VM1, VM2, VM3&gt; in Destructed and a subscriber
    /// filtered on PropertyChangedMessage,
    /// when construct() is called:
    /// three PropertyChangedMessage events with PropertyName in
    /// {"Component1", "Component2", "Component3"} are observed.
    /// </summary>
    [Fact, Trait("Conformance", "AGG-004")]
    public void AGG_004_ComponentN_PropertyChanged_Fires_On_Construct()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM3<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
            .Component2(() => MakeLeaf(hub, dispatcher, "c2"))
            .Component3(() => MakeLeaf(hub, dispatcher, "c3"))
            .Build();

        var observedPropNames = new List<string>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<AggregateVM3<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>>> pcm)
                observedPropNames.Add(pcm.PropertyName);
        });

        agg.Construct();

        observedPropNames.Should().Contain("Component1",
            "PropertyChangedMessage(Component1) must be emitted on construct");
        observedPropNames.Should().Contain("Component2",
            "PropertyChangedMessage(Component2) must be emitted on construct");
        observedPropNames.Should().Contain("Component3",
            "PropertyChangedMessage(Component3) must be emitted on construct");
    }

    // ── AGG-005 — Destruction waits for all children Destructed ───────────────

    /// <summary>
    /// AGG-005: Given AggregateVM2&lt;VM1, VM2&gt; in Constructed,
    /// when destruct() is called:
    /// - agg.Component1.Status == Destructed
    /// - agg.Component2.Status == Destructed
    /// - agg.Status == Destructed
    /// </summary>
    [Fact, Trait("Conformance", "AGG-005")]
    public void AGG_005_Destruct_Waits_For_All_Children_Destructed()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM2<ComponentVM<string>, ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
            .Component2(() => MakeLeaf(hub, dispatcher, "c2"))
            .Build();

        agg.Construct();

        agg.Component1.Should().NotBeNull();
        agg.Component2.Should().NotBeNull();

        agg.Destruct();

        agg.Component1!.Status.Should().Be(ConstructionStatus.Destructed,
            "Component1 must be Destructed after agg.Destruct()");
        agg.Component2!.Status.Should().Be(ConstructionStatus.Destructed,
            "Component2 must be Destructed after agg.Destruct()");
        agg.Status.Should().Be(ConstructionStatus.Destructed,
            "aggregate itself must be Destructed");
    }
}
#pragma warning restore CA1715
