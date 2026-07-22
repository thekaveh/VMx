#pragma warning disable CA1715 // Spec uses 'VM' type parameter names per ADR-0006
using FluentAssertions;
using VMx.Aggregates;
using VMx.Components;
using VMx.Composites;
using VMx.Forwarding;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for AggregateVM covering AGG-001..006.
/// See spec/08-aggregate-vm.md and spec/12-conformance.md.
/// </summary>
public class AggregateVMConformanceTests
{
    private sealed class NoOpForwardingVM<M> : ForwardingComponentVM<M>
    {
        public NoOpForwardingVM(IComponentVM<M> wrapped) : base(wrapped) { }
    }

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

        // Scope to PropertyChangedMessages sent BY the aggregate itself for the
        // three component slots (parity with Python/TS, which filter on sender
        // and assert exactly three slot changes).
        var slotChanges = new List<string>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm &&
                ReferenceEquals(pcm.SenderObject, agg) &&
                pcm.PropertyName is "Component1" or "Component2" or "Component3")
            {
                slotChanges.Add(pcm.PropertyName);
            }
        });

        agg.Construct();

        slotChanges.Should().Contain("Component1",
            "PropertyChangedMessage(Component1) must be emitted on construct");
        slotChanges.Should().Contain("Component2",
            "PropertyChangedMessage(Component2) must be emitted on construct");
        slotChanges.Should().Contain("Component3",
            "PropertyChangedMessage(Component3) must be emitted on construct");
        slotChanges.Should().HaveCount(3,
            "exactly three slot PropertyChangedMessages are observed on construct");
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

    // ── AGG-006 — Arity-6 all six components reach Constructed; destruct waits ──

    /// <summary>
    /// AGG-006: Given AggregateVM6&lt;VM1..VM6&gt; in Destructed,
    /// when construct() is called:
    /// - every ComponentI.Status (I ∈ {1..6}) equals Constructed
    /// - agg.Status == Constructed
    /// when destruct() is then called:
    /// - every ComponentI.Status equals Destructed
    /// - agg.Status == Destructed
    /// Added in spec 2.2.0 per ADR-0034.
    /// </summary>
    [Fact, Trait("Conformance", "AGG-006")]
    public void AGG_006_Arity6_Construct_All_Then_Destruct_All()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM6<
            ComponentVM<string>, ComponentVM<string>, ComponentVM<string>,
            ComponentVM<string>, ComponentVM<string>, ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
            .Component2(() => MakeLeaf(hub, dispatcher, "c2"))
            .Component3(() => MakeLeaf(hub, dispatcher, "c3"))
            .Component4(() => MakeLeaf(hub, dispatcher, "c4"))
            .Component5(() => MakeLeaf(hub, dispatcher, "c5"))
            .Component6(() => MakeLeaf(hub, dispatcher, "c6"))
            .Build();

        agg.Construct();

        agg.Component1!.Status.Should().Be(ConstructionStatus.Constructed,
            "Component1 must be Constructed");
        agg.Component2!.Status.Should().Be(ConstructionStatus.Constructed,
            "Component2 must be Constructed");
        agg.Component3!.Status.Should().Be(ConstructionStatus.Constructed,
            "Component3 must be Constructed");
        agg.Component4!.Status.Should().Be(ConstructionStatus.Constructed,
            "Component4 must be Constructed");
        agg.Component5!.Status.Should().Be(ConstructionStatus.Constructed,
            "Component5 must be Constructed");
        agg.Component6!.Status.Should().Be(ConstructionStatus.Constructed,
            "Component6 must be Constructed");
        agg.Status.Should().Be(ConstructionStatus.Constructed,
            "aggregate itself must be Constructed");

        agg.Destruct();

        agg.Component1!.Status.Should().Be(ConstructionStatus.Destructed,
            "Component1 must be Destructed after agg.Destruct()");
        agg.Component2!.Status.Should().Be(ConstructionStatus.Destructed,
            "Component2 must be Destructed after agg.Destruct()");
        agg.Component3!.Status.Should().Be(ConstructionStatus.Destructed,
            "Component3 must be Destructed after agg.Destruct()");
        agg.Component4!.Status.Should().Be(ConstructionStatus.Destructed,
            "Component4 must be Destructed after agg.Destruct()");
        agg.Component5!.Status.Should().Be(ConstructionStatus.Destructed,
            "Component5 must be Destructed after agg.Destruct()");
        agg.Component6!.Status.Should().Be(ConstructionStatus.Destructed,
            "Component6 must be Destructed after agg.Destruct()");
        agg.Status.Should().Be(ConstructionStatus.Destructed,
            "aggregate itself must be Destructed");
    }

    // ── LIFE-013 (AggregateVM) — children Disposed before aggregate ──────────

    /// <summary>
    /// LIFE-013 for AggregateVMN: dispose disposes every component slot BEFORE
    /// the aggregate itself. Subscribers observe child Disposed transitions
    /// strictly before the aggregate's own Disposed transition. Sibling of the
    /// CompositeVM LIFE-013 cascade test and the Python parametric
    /// test_LIFE_013_aggregate_dispose_children_before_parent.
    /// </summary>
    [Theory, Trait("Conformance", "LIFE-013")]
    [InlineData(1)]
    [InlineData(2)]
    [InlineData(3)]
    [InlineData(4)]
    [InlineData(5)]
    [InlineData(6)]
    public void LIFE_013_AggregateVMN_Children_Disposed_Before_Parent(int arity)
    {
        var (hub, dispatcher) = MakeServices();
        var disposalOrder = new List<string>();
        using var sub = hub.Messages.Subscribe(m =>
        {
            if (m is ConstructionStatusChangedMessage csm
                && csm.Status == ConstructionStatus.Disposed)
            {
                disposalOrder.Add(csm.SenderName);
            }
        });

        IComponentVM agg = arity switch
        {
            1 => AggregateVM1<ComponentVM<string>>.Builder()
                .Name("agg1").Services(hub, dispatcher)
                .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
                .Build(),
            2 => AggregateVM2<ComponentVM<string>, ComponentVM<string>>.Builder()
                .Name("agg2").Services(hub, dispatcher)
                .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
                .Component2(() => MakeLeaf(hub, dispatcher, "c2"))
                .Build(),
            3 => AggregateVM3<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>>.Builder()
                .Name("agg3").Services(hub, dispatcher)
                .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
                .Component2(() => MakeLeaf(hub, dispatcher, "c2"))
                .Component3(() => MakeLeaf(hub, dispatcher, "c3"))
                .Build(),
            4 => AggregateVM4<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>, ComponentVM<string>>.Builder()
                .Name("agg4").Services(hub, dispatcher)
                .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
                .Component2(() => MakeLeaf(hub, dispatcher, "c2"))
                .Component3(() => MakeLeaf(hub, dispatcher, "c3"))
                .Component4(() => MakeLeaf(hub, dispatcher, "c4"))
                .Build(),
            5 => AggregateVM5<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>, ComponentVM<string>, ComponentVM<string>>.Builder()
                .Name("agg5").Services(hub, dispatcher)
                .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
                .Component2(() => MakeLeaf(hub, dispatcher, "c2"))
                .Component3(() => MakeLeaf(hub, dispatcher, "c3"))
                .Component4(() => MakeLeaf(hub, dispatcher, "c4"))
                .Component5(() => MakeLeaf(hub, dispatcher, "c5"))
                .Build(),
            6 => AggregateVM6<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>, ComponentVM<string>, ComponentVM<string>, ComponentVM<string>>.Builder()
                .Name($"agg{arity}").Services(hub, dispatcher)
                .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
                .Component2(() => MakeLeaf(hub, dispatcher, "c2"))
                .Component3(() => MakeLeaf(hub, dispatcher, "c3"))
                .Component4(() => MakeLeaf(hub, dispatcher, "c4"))
                .Component5(() => MakeLeaf(hub, dispatcher, "c5"))
                .Component6(() => MakeLeaf(hub, dispatcher, "c6"))
                .Build(),
            _ => throw new ArgumentOutOfRangeException(nameof(arity)),
        };
        agg.Construct();
        var aggName = $"agg{arity}";

        agg.Dispose();

        for (int n = 1; n <= arity; n++)
        {
            var childName = $"c{n}";
            disposalOrder.Should().Contain(childName,
                $"slot {childName} must reach Disposed");
            disposalOrder.IndexOf(childName).Should().BeLessThan(disposalOrder.IndexOf(aggName),
                $"{childName} must be Disposed before {aggName} (LIFE-013)");
        }
    }

    [Fact]
    public void Aggregate_Rejects_Forwarding_Aliases_Of_One_Canonical_Component()
    {
        var (hub, dispatcher) = MakeServices();
        var inner = MakeLeaf(hub, dispatcher);
        var duplicate = AggregateVM2<NoOpForwardingVM<string>, NoOpForwardingVM<string>>.Builder()
            .Name("duplicate").Services(hub, dispatcher)
            .Component1(() => new NoOpForwardingVM<string>(inner))
            .Component2(() => new NoOpForwardingVM<string>(inner)).Build();

        duplicate.Invoking(candidate => candidate.Construct())
            .Should().Throw<InvalidOperationException>()
            .WithMessage("*same canonical component identity*");
        duplicate.Component1.Should().BeNull();
        duplicate.Component2.Should().BeNull();

        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite").Services(hub, dispatcher)
            .Children(() => [inner]).Build();
        composite.Construct();
        var ownedAlias = AggregateVM1<NoOpForwardingVM<string>>.Builder()
            .Name("owned-alias").Services(hub, dispatcher)
            .Component1(() => new NoOpForwardingVM<string>(inner)).Build();

        ownedAlias.Invoking(candidate => candidate.Construct())
            .Should().Throw<InvalidOperationException>()
            .WithMessage("*already has a parent*");
        composite.Snapshot().Should().ContainSingle().Which.Should().BeSameAs(inner);
        ownedAlias.Component1.Should().BeNull();
    }

    [Fact]
    public void Aggregate_Rejects_Already_Owned_Factory_Result_Without_Mutation()
    {
        var (hub, dispatcher) = MakeServices();
        var child = MakeLeaf(hub, dispatcher);
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite").Services(hub, dispatcher)
            .Children(() => [child]).Build();
        composite.Construct();
        var aggregate = AggregateVM1<ComponentVM<string>>.Builder()
            .Name("aggregate").Services(hub, dispatcher)
            .Component1(() => child).Build();

        var act = aggregate.Invoking(candidate => candidate.Construct());

        act.Should().Throw<InvalidOperationException>().WithMessage("*already has a parent*");
        composite.Snapshot().Should().ContainSingle().Which.Should().BeSameAs(child);
        aggregate.Component1.Should().BeNull();
    }

    [Fact]
    public void Fixed_Aggregate_Slot_Cannot_Transfer_To_Mutable_Parent()
    {
        var (hub, dispatcher) = MakeServices();
        var child = MakeLeaf(hub, dispatcher);
        var aggregate = AggregateVM1<ComponentVM<string>>.Builder()
            .Name("aggregate").Services(hub, dispatcher)
            .Component1(() => child).Build();
        aggregate.Construct();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite").Services(hub, dispatcher)
            .Children(() => []).Build();
        composite.Construct();

        var act = composite.Invoking(candidate => candidate.Add(child));

        act.Should().Throw<InvalidOperationException>().WithMessage("*fixed aggregate slot*");
        aggregate.Component1.Should().BeSameAs(child);
        composite.Count.Should().Be(0);
    }
}
#pragma warning restore CA1715
