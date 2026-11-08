#pragma warning disable CA1715 // Spec uses 'VM' type parameter names per ADR-0006
using FluentAssertions;
using VMx.Aggregates;
using VMx.Components;
using VMx.Composites;
using VMx.Forwarding;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
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

    [Fact, Trait("Conformance", "AGG-007")]
    public void Aggregate_Reconstruct_Rejects_Its_Current_Slot_Without_Disposing_It()
    {
        var (hub, dispatcher) = MakeServices();
        var child = MakeLeaf(hub, dispatcher);
        var aggregate = AggregateVM1<ComponentVM<string>>.Builder()
            .Name("aggregate").Services(hub, dispatcher)
            .Component1(() => child).Build();
        aggregate.Construct();

        var act = aggregate.Invoking(candidate => candidate.Reconstruct());

        act.Should().Throw<InvalidOperationException>().WithMessage("*already has a parent*");
        aggregate.Component1.Should().BeSameAs(child);
        child.Status.Should().Be(ConstructionStatus.Destructed);
        child.GetParent().Should().NotBeNull();
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

    // ── LIFE-015 (AggregateVMN) — slot cascade waits for the admitted hook ──

    /// <summary>Builds an aggregate of the given arity whose slot N comes from <paramref name="slot"/>(N).</summary>
    private static IComponentVM BuildAggregate(
        int arity, string name, TestHub hub, Func<int, IComponentVM> slot)
        => arity switch
        {
            1 => AggregateVM1<IComponentVM>.Builder()
                .Name(name).Services(hub, NullDispatcher.Instance)
                .Component1(() => slot(1))
                .Build(),
            2 => AggregateVM2<IComponentVM, IComponentVM>.Builder()
                .Name(name).Services(hub, NullDispatcher.Instance)
                .Component1(() => slot(1)).Component2(() => slot(2))
                .Build(),
            3 => AggregateVM3<IComponentVM, IComponentVM, IComponentVM>.Builder()
                .Name(name).Services(hub, NullDispatcher.Instance)
                .Component1(() => slot(1)).Component2(() => slot(2)).Component3(() => slot(3))
                .Build(),
            4 => AggregateVM4<IComponentVM, IComponentVM, IComponentVM, IComponentVM>.Builder()
                .Name(name).Services(hub, NullDispatcher.Instance)
                .Component1(() => slot(1)).Component2(() => slot(2)).Component3(() => slot(3))
                .Component4(() => slot(4))
                .Build(),
            5 => AggregateVM5<IComponentVM, IComponentVM, IComponentVM, IComponentVM, IComponentVM>.Builder()
                .Name(name).Services(hub, NullDispatcher.Instance)
                .Component1(() => slot(1)).Component2(() => slot(2)).Component3(() => slot(3))
                .Component4(() => slot(4)).Component5(() => slot(5))
                .Build(),
            6 => AggregateVM6<IComponentVM, IComponentVM, IComponentVM, IComponentVM, IComponentVM, IComponentVM>.Builder()
                .Name(name).Services(hub, NullDispatcher.Instance)
                .Component1(() => slot(1)).Component2(() => slot(2)).Component3(() => slot(3))
                .Component4(() => slot(4)).Component5(() => slot(5)).Component6(() => slot(6))
                .Build(),
            _ => throw new ArgumentOutOfRangeException(nameof(arity)),
        };

    private static ComponentVM<string> BlockingSlot(
        TestHub hub, string name, bool blockConstruct,
        ManualResetEventSlim entered, ManualResetEventSlim release)
    {
        void Block()
        {
            entered.Set();
            release.Wait(Liveness.HangGuard).Should().BeTrue();
        }

        var builder = ComponentVM<string>.Builder()
            .Name(name).Services(hub, NullDispatcher.Instance).Model("m");
        builder = blockConstruct ? builder.OnConstruct(Block) : builder.OnDestruct(Block);
        return builder.Build();
    }

    private static ComponentVM<string> PlainSlot(TestHub hub, string name)
        => ComponentVM<string>.Builder().Name(name).Services(hub, NullDispatcher.Instance).Model("m").Build();

    private static System.Collections.Concurrent.ConcurrentQueue<string> RecordStatuses(TestHub hub)
    {
        var recorded = new System.Collections.Concurrent.ConcurrentQueue<string>();
        hub.Messages.Subscribe(message =>
        {
            if (message is ConstructionStatusChangedMessage changed)
                recorded.Enqueue($"{changed.SenderName}:{changed.Status}");
        });
        return recorded;
    }

    private static Task<Exception?> OnOwnThread(Action action)
        => Task.Factory.StartNew<Exception?>(
            () => Record.Exception(action),
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);

    /// <summary>
    /// LIFE-015 (#1166, case A): a foreign Dispose() of an aggregate whose
    /// destruct hook waits on slot 1 publishes Disposed and disposes no slot
    /// while the hook runs. After the hook returns, slot 1 publishes
    /// Destructed and one Disposed, the aggregate publishes no Constructed,
    /// and neither call throws.
    /// </summary>
    [Theory, Trait("Conformance", "LIFE-015")]
    [InlineData(1)]
    [InlineData(2)]
    [InlineData(3)]
    [InlineData(4)]
    [InlineData(5)]
    [InlineData(6)]
    public async Task LIFE_015_Foreign_Dispose_During_Aggregate_Destruct_Hook_Waits(int arity)
    {
        using var hub = new TestHub();
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        var agg = BuildAggregate(arity, "agg", hub, n => n == 1
            ? BlockingSlot(hub, "c1", blockConstruct: false, entered, release)
            : PlainSlot(hub, $"c{n}"));
        agg.Construct();
        var c1 = ((IAggregateSlots)agg).EnumerateSlots().First();
        var recorded = RecordStatuses(hub);

        var destruct = OnOwnThread(agg.Destruct);
        entered.Wait(Liveness.HangGuard).Should().BeTrue();
        var dispose = OnOwnThread(agg.Dispose);
        var disposedDuringHook = SpinWait.SpinUntil(
            () => agg.Status == ConstructionStatus.Disposed, TimeSpan.FromSeconds(5));
        // Give the disposal time to reach the slots if it would.
        await Task.Delay(100);
        var slotDuringHook = c1.Status;
        release.Set();
        disposedDuringHook.Should().BeTrue("the foreign disposal publishes Disposed while the hook runs");
        slotDuringHook.Should().Be(ConstructionStatus.Destructing, "no slot is disposed while the hook runs");
        await Task.WhenAll(destruct, dispose).WaitAsync(Liveness.HangGuard);

        (await destruct).Should().BeNull();
        (await dispose).Should().BeNull();
        recorded.Where(entry => entry.StartsWith("c1:", StringComparison.Ordinal))
            .Should().Equal("c1:Destructing", "c1:Destructed", "c1:Disposed");
        recorded.Where(entry => entry.StartsWith("agg:", StringComparison.Ordinal))
            .Should().Equal("agg:Destructing", "agg:Disposed");
        ((IAggregateSlots)agg).EnumerateSlots()
            .All(slot => slot.Status == ConstructionStatus.Disposed).Should().BeTrue();
    }

    /// <summary>
    /// LIFE-015 (#1166, case B): a foreign Dispose() of an aggregate whose
    /// construct hook waits on slot 1 publishes Disposed while the hook runs.
    /// After the hook returns, the slot the factory created is disposed once
    /// and the aggregate publishes no Constructed.
    /// </summary>
    [Theory, Trait("Conformance", "LIFE-015")]
    [InlineData(1)]
    [InlineData(2)]
    [InlineData(3)]
    [InlineData(4)]
    [InlineData(5)]
    [InlineData(6)]
    public async Task LIFE_015_Foreign_Dispose_During_Aggregate_Construct_Hook_Waits(int arity)
    {
        using var hub = new TestHub();
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        var agg = BuildAggregate(arity, "agg", hub, n => n == 1
            ? BlockingSlot(hub, "c1", blockConstruct: true, entered, release)
            : PlainSlot(hub, $"c{n}"));
        var recorded = RecordStatuses(hub);

        var construct = OnOwnThread(agg.Construct);
        entered.Wait(Liveness.HangGuard).Should().BeTrue();
        var dispose = OnOwnThread(agg.Dispose);
        var disposedDuringHook = SpinWait.SpinUntil(
            () => agg.Status == ConstructionStatus.Disposed, TimeSpan.FromSeconds(5));
        release.Set();
        disposedDuringHook.Should().BeTrue(
            "the foreign disposal publishes Disposed without waiting on the aggregate's slot lock");
        await Task.WhenAll(construct, dispose).WaitAsync(Liveness.HangGuard);

        (await construct).Should().BeNull();
        (await dispose).Should().BeNull();
        recorded.Count(entry => entry == "c1:Disposed").Should().Be(1);
        recorded.Should().NotContain("agg:Constructed");
        ((IAggregateSlots)agg).EnumerateSlots()
            .All(slot => slot.Status == ConstructionStatus.Disposed).Should().BeTrue();
    }

    /// <summary>
    /// LIFE-015 (#1166, case C): Construct() and a foreign Dispose() started
    /// together never hang, and the aggregate always ends Disposed.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-015")]
    public async Task LIFE_015_Aggregate_Construct_Dispose_Race_Never_Hangs()
    {
        var random = new Random(1166);
        for (var iteration = 0; iteration < 200; iteration++)
        {
            using var hub = new TestHub();
            var agg = BuildAggregate(1, "agg", hub, n => PlainSlot(hub, $"c{n}"));
            var spins = random.Next(0, 400);
            using var start = new ManualResetEventSlim();
            var construct = OnOwnThread(() =>
            {
                start.Wait(Liveness.HangGuard);
                agg.Construct();
            });
            var dispose = OnOwnThread(() =>
            {
                start.Wait(Liveness.HangGuard);
                Thread.SpinWait(spins);
                agg.Dispose();
            });
            start.Set();

            var both = Task.WhenAll(construct, dispose);
            (await Task.WhenAny(both, Task.Delay(TimeSpan.FromSeconds(3)))).Should().BeSameAs(both,
                $"iteration {iteration} must not hang");
            (await dispose).Should().BeNull();
            agg.Status.Should().Be(ConstructionStatus.Disposed);
            ((IAggregateSlots)agg).EnumerateSlots()
                .All(slot => slot.Status == ConstructionStatus.Disposed).Should().BeTrue();
        }
    }

    /// <summary>
    /// LIFE-015 (#1166, case D): two aggregates whose slot factories dispose
    /// each other from their construct hooks do not deadlock. Both Construct()
    /// calls finish and both aggregates end Disposed.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-015")]
    public async Task LIFE_015_Aggregates_Disposing_Each_Other_From_Construct_Hooks_Finish()
    {
        using var hub = new TestHub();
        using var barrier = new Barrier(2);
        IComponentVM? first = null;
        IComponentVM? second = null;
        first = BuildAggregate(1, "first", hub, n =>
        {
            barrier.SignalAndWait(Liveness.HangGuard).Should().BeTrue();
            second!.Dispose();
            return PlainSlot(hub, "first-c1");
        });
        second = BuildAggregate(1, "second", hub, n =>
        {
            barrier.SignalAndWait(Liveness.HangGuard).Should().BeTrue();
            first.Dispose();
            return PlainSlot(hub, "second-c1");
        });

        var constructFirst = OnOwnThread(first.Construct);
        var constructSecond = OnOwnThread(second.Construct);
        var both = Task.WhenAll(constructFirst, constructSecond);
        (await Task.WhenAny(both, Task.Delay(TimeSpan.FromSeconds(5)))).Should().BeSameAs(both,
            "a wait on the other aggregate's slot lock must not close a deadlock");

        (await constructFirst).Should().BeNull();
        (await constructSecond).Should().BeNull();
        first.Status.Should().Be(ConstructionStatus.Disposed);
        second.Status.Should().Be(ConstructionStatus.Disposed);
    }

    /// <summary>
    /// AGG-007 (spec/08 §4, #1166): a foreign Dispose() that publishes Disposed
    /// after the aggregate's slot replacement passed its preflight, but before
    /// the slots are assigned, wins. No candidate is committed to the disposed
    /// aggregate: none is a slot when Disposed is published or afterward, and
    /// every candidate ends Disposed with no parent. The internal seam holds
    /// the replacement just before its terminal check and slot assignment.
    /// </summary>
    [Theory, Trait("Conformance", "AGG-007")]
    [InlineData(1, false)]
    [InlineData(1, true)]
    [InlineData(2, false)]
    [InlineData(3, true)]
    [InlineData(4, false)]
    [InlineData(5, true)]
    [InlineData(6, false)]
    [InlineData(6, true)]
    public async Task Foreign_Dispose_Before_Slot_Assignment_Commits_No_Slot(int arity, bool reconstruct)
    {
        using var hub = new TestHub();
        var candidates = new System.Collections.Concurrent.ConcurrentQueue<IComponentVM>();
        var collect = false;
        var agg = BuildAggregate(arity, "agg", hub, n =>
        {
            var slot = PlainSlot(hub, $"c{n}");
            if (Volatile.Read(ref collect)) candidates.Enqueue(slot);
            return slot;
        });
        if (reconstruct) agg.Construct();
        Volatile.Write(ref collect, true);
        IComponentVM[]? slotsAtDisposed = null;
        hub.Messages.Subscribe(message =>
        {
            if (message is ConstructionStatusChangedMessage { SenderName: "agg", Status: ConstructionStatus.Disposed })
                slotsAtDisposed = ((IAggregateSlots)agg).EnumerateSlots().ToArray();
        });
        using var inWindow = new ManualResetEventSlim();
        var probe = (ComponentVMBase)agg;
        probe.BeforeCommitUnlessDisposingForTesting = () =>
        {
            probe.BeforeCommitUnlessDisposingForTesting = null;
            inWindow.Set();
            // The construct hook holds its lease, so the foreign disposal
            // publishes Disposed now and defers its slot cascade to the lease.
            SpinWait.SpinUntil(() => agg.Status == ConstructionStatus.Disposed, Liveness.HangGuard)
                .Should().BeTrue("the foreign disposal publishes Disposed while the hook runs");
        };

        var transition = OnOwnThread(reconstruct ? agg.Reconstruct : agg.Construct);
        inWindow.Wait(Liveness.HangGuard).Should().BeTrue();
        var dispose = OnOwnThread(agg.Dispose);
        await Task.WhenAll(transition, dispose).WaitAsync(Liveness.HangGuard);

        (await transition).Should().BeNull("a transition superseded by Disposed returns without error");
        (await dispose).Should().BeNull();
        agg.Status.Should().Be(ConstructionStatus.Disposed);
        candidates.Should().HaveCount(arity);
        slotsAtDisposed.Should().NotBeNull().And.NotIntersectWith(candidates,
            "no candidate is a slot when the aggregate publishes Disposed");
        ((IAggregateSlots)agg).EnumerateSlots().Should().NotIntersectWith(candidates,
            "no slot is committed to a disposed aggregate (spec/08 §4)");
        foreach (var candidate in candidates)
        {
            candidate.Status.Should().Be(ConstructionStatus.Disposed);
            candidate.GetParent().Should().BeNull();
        }
        ((IAggregateSlots)agg).EnumerateSlots()
            .All(slot => slot.Status == ConstructionStatus.Disposed).Should().BeTrue();
    }
}
#pragma warning restore CA1715
