#pragma warning disable CA1715 // Spec uses 'VM' type parameter names per ADR-0006
using FluentAssertions;
using VMx.Aggregates;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Aggregates;

/// <summary>
/// Unit tests for AggregateVM1 through AggregateVM5.
/// Conformance-level tests live in VMx.Conformance.Tests.
/// </summary>
public class AggregateVMTests
{
    private sealed class BlockingDisposeVM(
        string name,
        TestHub hub,
        TestDispatcher dispatcher,
        ManualResetEventSlim entered,
        ManualResetEventSlim release)
        : ComponentVMBase(name, "", hub, dispatcher, null, null)
    {
        public override ViewModelType Type => ViewModelType.Component;

        protected override void OnDispose()
        {
            entered.Set();
            if (!release.Wait(TimeSpan.FromSeconds(2)))
                throw new TimeoutException("test did not release blocked slot disposal");
        }
    }

    private sealed class ReentrantDisposeVM(
        string name,
        TestHub hub,
        TestDispatcher dispatcher,
        Action onDispose)
        : ComponentVMBase(name, "", hub, dispatcher, null, null)
    {
        public override ViewModelType Type => ViewModelType.Component;

        protected override void OnDispose() => onDispose();
    }

    // ── Factory helpers ──────────────────────────────────────────────────────

    private static (TestHub hub, TestDispatcher dispatcher) MakeServices()
        => (new TestHub(), new TestDispatcher());

    private static ComponentVM<string> MakeLeaf(TestHub hub, TestDispatcher dispatcher, string name = "leaf")
        => ComponentVM<string>.Builder()
            .Name(name).Services(hub, dispatcher).Model("m").Build();

    // ── AggregateVM1 ─────────────────────────────────────────────────────────

    [Fact]
    public void AggregateVM1_Type_Is_Aggregate()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM1<ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher))
            .Build();

        agg.Type.Should().Be(ViewModelType.Aggregate);
    }

    [Fact]
    public void AggregateVM1_Component1_Null_Before_Construct()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM1<ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher))
            .Build();

        agg.Component1.Should().BeNull();
    }

    [Fact]
    public void AggregateVM1_Construct_Populates_And_Constructs_Component1()
    {
        var (hub, dispatcher) = MakeServices();
        ComponentVM<string>? created = null;
        var agg = AggregateVM1<ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() =>
            {
                created = MakeLeaf(hub, dispatcher, "c1");
                return created;
            })
            .Build();

        agg.Construct();

        agg.Component1.Should().BeSameAs(created);
        agg.Component1!.Status.Should().Be(ConstructionStatus.Constructed);
        agg.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void AggregateVM1_Destruct_Destructs_Component1()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM1<ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
            .Build();

        agg.Construct();
        agg.Destruct();

        agg.Component1!.Status.Should().Be(ConstructionStatus.Destructed);
        agg.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // ── AggregateVM2 ─────────────────────────────────────────────────────────

    [Fact]
    public void AggregateVM2_Construct_Populates_Both_Components()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM2<ComponentVM<string>, ComponentVM<int>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
            .Component2(() => ComponentVM<int>.Builder().Name("c2").Services(hub, dispatcher).Model(42).Build())
            .Build();

        agg.Construct();

        agg.Component1.Should().NotBeNull();
        agg.Component2.Should().NotBeNull();
        agg.Component1!.Status.Should().Be(ConstructionStatus.Constructed);
        agg.Component2!.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void AggregateVM2_Destruct_Destructs_Both_Components()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM2<ComponentVM<string>, ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
            .Component2(() => MakeLeaf(hub, dispatcher, "c2"))
            .Build();

        agg.Construct();
        agg.Destruct();

        agg.Component1!.Status.Should().Be(ConstructionStatus.Destructed);
        agg.Component2!.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // ── AggregateVM3 ─────────────────────────────────────────────────────────

    [Fact]
    public void AggregateVM3_Construct_Populates_All_Three_Components()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM3<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
            .Component2(() => MakeLeaf(hub, dispatcher, "c2"))
            .Component3(() => MakeLeaf(hub, dispatcher, "c3"))
            .Build();

        agg.Construct();

        agg.Component1!.Status.Should().Be(ConstructionStatus.Constructed);
        agg.Component2!.Status.Should().Be(ConstructionStatus.Constructed);
        agg.Component3!.Status.Should().Be(ConstructionStatus.Constructed);
        agg.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // ── AggregateVM4 ─────────────────────────────────────────────────────────

    [Fact]
    public void AggregateVM4_Construct_Populates_All_Four_Components()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM4<
            ComponentVM<string>, ComponentVM<string>,
            ComponentVM<string>, ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
            .Component2(() => MakeLeaf(hub, dispatcher, "c2"))
            .Component3(() => MakeLeaf(hub, dispatcher, "c3"))
            .Component4(() => MakeLeaf(hub, dispatcher, "c4"))
            .Build();

        agg.Construct();

        agg.Component1!.Status.Should().Be(ConstructionStatus.Constructed);
        agg.Component2!.Status.Should().Be(ConstructionStatus.Constructed);
        agg.Component3!.Status.Should().Be(ConstructionStatus.Constructed);
        agg.Component4!.Status.Should().Be(ConstructionStatus.Constructed);
        agg.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // ── AggregateVM5 ─────────────────────────────────────────────────────────

    [Fact]
    public void AggregateVM5_Construct_Populates_All_Five_Components()
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

        agg.Construct();

        agg.Component1!.Status.Should().Be(ConstructionStatus.Constructed);
        agg.Component2!.Status.Should().Be(ConstructionStatus.Constructed);
        agg.Component3!.Status.Should().Be(ConstructionStatus.Constructed);
        agg.Component4!.Status.Should().Be(ConstructionStatus.Constructed);
        agg.Component5!.Status.Should().Be(ConstructionStatus.Constructed);
        agg.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void AggregateVM5_Destruct_Destructs_All_Five_Components()
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

        agg.Construct();
        agg.Destruct();

        agg.Component1!.Status.Should().Be(ConstructionStatus.Destructed);
        agg.Component2!.Status.Should().Be(ConstructionStatus.Destructed);
        agg.Component3!.Status.Should().Be(ConstructionStatus.Destructed);
        agg.Component4!.Status.Should().Be(ConstructionStatus.Destructed);
        agg.Component5!.Status.Should().Be(ConstructionStatus.Destructed);
        agg.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // ── Builder validation ────────────────────────────────────────────────────

    [Fact]
    public void AggregateVM1_Builder_Missing_Name_Throws()
    {
        var (hub, dispatcher) = MakeServices();
        var act = () => AggregateVM1<ComponentVM<string>>.Builder()
            .Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher))
            .Build();

        act.Should().Throw<Exception>().WithMessage("*Name*");
    }

    [Fact]
    public void AggregateVM2_Builder_Missing_Component2_Throws()
    {
        var (hub, dispatcher) = MakeServices();
        var act = () => AggregateVM2<ComponentVM<string>, ComponentVM<string>>.Builder()
            .Name("agg")
            .Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher))
            .Build();

        act.Should().Throw<Exception>().WithMessage("*Component2*");
    }

    // ── PropertyChanged on construct ──────────────────────────────────────────

    [Fact]
    public void AggregateVM1_Construct_Raises_PropertyChanged_Component1()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM1<ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher))
            .Build();

        var changedProps = new List<string>();
        agg.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName is not null) changedProps.Add(e.PropertyName);
        };

        agg.Construct();

        changedProps.Should().Contain("Component1");
    }

    // ── Hub PropertyChangedMessage on construct ───────────────────────────────

    [Fact]
    public void AggregateVM2_Construct_Emits_Hub_PropertyChangedMessages_For_Each_Slot()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM2<ComponentVM<string>, ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher, "c1"))
            .Component2(() => MakeLeaf(hub, dispatcher, "c2"))
            .Build();

        var propNames = new List<string>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm)
                propNames.Add(pcm.PropertyName);
        });

        agg.Construct();

        propNames.Should().Contain("Component1");
        propNames.Should().Contain("Component2");
    }

    // ── Reconstruct disposes the previous slot instance ───────────────────────

    [Fact]
    public void AggregateVM1_Reconstruct_Disposes_Previous_Slot()
    {
        var (hub, dispatcher) = MakeServices();
        var agg = AggregateVM1<ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => MakeLeaf(hub, dispatcher, "slot"))
            .Build();

        agg.Construct();
        var first = agg.Component1;
        first.Should().NotBeNull();
        first!.Status.Should().Be(ConstructionStatus.Constructed);

        // Reconstruct = Destruct + Construct; the fix in 560be45 disposes
        // the previous slot before the factory yields a new instance, so
        // hub subscriptions and command Subjects don't leak.
        agg.Reconstruct();

        var second = agg.Component1;
        second.Should().NotBeNull();
        second.Should().NotBeSameAs(first, "Reconstruct must produce a fresh slot");
        second!.Status.Should().Be(ConstructionStatus.Constructed);
        first.Status.Should().Be(ConstructionStatus.Disposed,
            "previous slot must be Disposed, not lingering in Destructed");
    }

    /// <summary>
    /// LIFE-013 reconstruct-disposes-prior-slots over arities 2..6 — cross-flavor
    /// parity with the Python parametric test in
    /// langs/python/tests/unit/aggregates/test_aggregate_vm.py
    /// (test_reconstruct_disposes_prior_slots_before_overwriting). Every slot of
    /// every arity must be Disposed after Reconstruct, never merely Destructed.
    /// </summary>
    [Theory]
    [InlineData(2)]
    [InlineData(3)]
    [InlineData(4)]
    [InlineData(5)]
    [InlineData(6)]
    public void AggregateVMN_Reconstruct_Disposes_Every_Previous_Slot(int arity)
    {
        var (hub, dispatcher) = MakeServices();
        ComponentVM<string>[] firstSlots;
        Action reconstruct;
        Func<ComponentVM<string>?[]> currentSlots;

        switch (arity)
        {
            case 2:
                {
                    var agg = AggregateVM2<ComponentVM<string>, ComponentVM<string>>.Builder()
                        .Name("agg2").Services(hub, dispatcher)
                        .Component1(() => MakeLeaf(hub, dispatcher, "s1"))
                        .Component2(() => MakeLeaf(hub, dispatcher, "s2"))
                        .Build();
                    agg.Construct();
                    firstSlots = [agg.Component1!, agg.Component2!];
                    reconstruct = agg.Reconstruct;
                    currentSlots = () => [agg.Component1, agg.Component2];
                    break;
                }
            case 3:
                {
                    var agg = AggregateVM3<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>>.Builder()
                        .Name("agg3").Services(hub, dispatcher)
                        .Component1(() => MakeLeaf(hub, dispatcher, "s1"))
                        .Component2(() => MakeLeaf(hub, dispatcher, "s2"))
                        .Component3(() => MakeLeaf(hub, dispatcher, "s3"))
                        .Build();
                    agg.Construct();
                    firstSlots = [agg.Component1!, agg.Component2!, agg.Component3!];
                    reconstruct = agg.Reconstruct;
                    currentSlots = () => [agg.Component1, agg.Component2, agg.Component3];
                    break;
                }
            case 4:
                {
                    var agg = AggregateVM4<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>, ComponentVM<string>>.Builder()
                        .Name("agg4").Services(hub, dispatcher)
                        .Component1(() => MakeLeaf(hub, dispatcher, "s1"))
                        .Component2(() => MakeLeaf(hub, dispatcher, "s2"))
                        .Component3(() => MakeLeaf(hub, dispatcher, "s3"))
                        .Component4(() => MakeLeaf(hub, dispatcher, "s4"))
                        .Build();
                    agg.Construct();
                    firstSlots = [agg.Component1!, agg.Component2!, agg.Component3!, agg.Component4!];
                    reconstruct = agg.Reconstruct;
                    currentSlots = () => [agg.Component1, agg.Component2, agg.Component3, agg.Component4];
                    break;
                }
            case 5:
                {
                    var agg = AggregateVM5<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>, ComponentVM<string>, ComponentVM<string>>.Builder()
                        .Name("agg5").Services(hub, dispatcher)
                        .Component1(() => MakeLeaf(hub, dispatcher, "s1"))
                        .Component2(() => MakeLeaf(hub, dispatcher, "s2"))
                        .Component3(() => MakeLeaf(hub, dispatcher, "s3"))
                        .Component4(() => MakeLeaf(hub, dispatcher, "s4"))
                        .Component5(() => MakeLeaf(hub, dispatcher, "s5"))
                        .Build();
                    agg.Construct();
                    firstSlots = [agg.Component1!, agg.Component2!, agg.Component3!, agg.Component4!, agg.Component5!];
                    reconstruct = agg.Reconstruct;
                    currentSlots = () => [agg.Component1, agg.Component2, agg.Component3, agg.Component4, agg.Component5];
                    break;
                }
            case 6:
                {
                    var agg = AggregateVM6<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>, ComponentVM<string>, ComponentVM<string>, ComponentVM<string>>.Builder()
                        .Name("agg6").Services(hub, dispatcher)
                        .Component1(() => MakeLeaf(hub, dispatcher, "s1"))
                        .Component2(() => MakeLeaf(hub, dispatcher, "s2"))
                        .Component3(() => MakeLeaf(hub, dispatcher, "s3"))
                        .Component4(() => MakeLeaf(hub, dispatcher, "s4"))
                        .Component5(() => MakeLeaf(hub, dispatcher, "s5"))
                        .Component6(() => MakeLeaf(hub, dispatcher, "s6"))
                        .Build();
                    agg.Construct();
                    firstSlots = [agg.Component1!, agg.Component2!, agg.Component3!, agg.Component4!, agg.Component5!, agg.Component6!];
                    reconstruct = agg.Reconstruct;
                    currentSlots = () => [agg.Component1, agg.Component2, agg.Component3, agg.Component4, agg.Component5, agg.Component6];
                    break;
                }
            default:
                throw new ArgumentOutOfRangeException(nameof(arity));
        }

        firstSlots.Should().AllSatisfy(s => s.Status.Should().Be(ConstructionStatus.Constructed));

        reconstruct();

        var fresh = currentSlots();
        fresh.Should().AllSatisfy(s => s.Should().NotBeNull());
        for (int i = 0; i < firstSlots.Length; i++)
        {
            fresh[i].Should().NotBeSameAs(firstSlots[i], $"slot {i + 1} must be a fresh instance");
            fresh[i]!.Status.Should().Be(ConstructionStatus.Constructed);
            firstSlots[i].Status.Should().Be(ConstructionStatus.Disposed,
                $"prior slot {i + 1} must be Disposed, not lingering in Destructed");
        }
    }

    [Fact]
    public async Task Concurrent_Reconstruct_Reserves_Shared_Candidate_Atomically()
    {
        var (hub, dispatcher) = MakeServices();
        var candidate = MakeLeaf(hub, dispatcher, "candidate");
        using var factoriesReady = new Barrier(2);
        using var disposalEntered = new ManualResetEventSlim();
        using var releaseDisposal = new ManualResetEventSlim();

        AggregateVM1<ComponentVMBase> Build(string name)
        {
            var calls = 0;
            return AggregateVM1<ComponentVMBase>.Builder()
                .Name(name).Services(hub, dispatcher)
                .Component1(() =>
                {
                    if (Interlocked.Increment(ref calls) == 1)
                        return new BlockingDisposeVM(
                            $"{name}-old", hub, dispatcher, disposalEntered, releaseDisposal);
                    if (!factoriesReady.SignalAndWait(TimeSpan.FromSeconds(2)))
                        throw new TimeoutException("candidate factories did not rendezvous");
                    return candidate;
                })
                .Build();
        }

        var first = Build("first");
        var second = Build("second");
        first.Construct();
        second.Construct();
        var attempts = new[]
        {
            Task.Run(() => Record.Exception(first.Reconstruct)),
            Task.Run(() => Record.Exception(second.Reconstruct)),
        };
        disposalEntered.Wait(TimeSpan.FromSeconds(2)).Should().BeTrue();
        releaseDisposal.Set();
        var errors = await Task.WhenAll(attempts);

        errors.Count(error => error is null).Should().Be(1);
        errors.Count(error => error is InvalidOperationException).Should().Be(1);
        new[] { first.Component1, second.Component1 }
            .Count(slot => ReferenceEquals(slot, candidate)).Should().Be(1);
    }

    [Fact]
    public void Reconstruct_Rejects_Reentrant_Attachment_Of_Reserved_Candidate()
    {
        var (hub, dispatcher) = MakeServices();
        var candidate = MakeLeaf(hub, dispatcher, "candidate");
        var destination = CompositeVM<IComponentVM>.Builder()
            .Name("destination").Services(hub, dispatcher)
            .Children(() => Array.Empty<IComponentVM>())
            .Build();
        destination.Construct();
        Exception? admissionError = null;
        var calls = 0;
        var aggregate = AggregateVM1<IComponentVM>.Builder()
            .Name("aggregate").Services(hub, dispatcher)
            .Component1(() => ++calls == 1
                ? new ReentrantDisposeVM(
                    "old", hub, dispatcher,
                    () =>
                    {
                        try { destination.Add(candidate); }
                        catch (Exception error) { admissionError = error; }
                    })
                : candidate)
            .Build();
        aggregate.Construct();

        aggregate.Reconstruct();

        admissionError.Should().BeOfType<InvalidOperationException>();
        destination.Count.Should().Be(0);
        aggregate.Component1.Should().BeSameAs(candidate);
    }

    [Fact]
    public void AggregateVM1_Reconstruct_Aborts_When_Previous_Disposal_Disposes_Parent()
    {
        var (hub, dispatcher) = MakeServices();
        var candidate = MakeLeaf(hub, dispatcher, "candidate");
        AggregateVM1<IComponentVM>? aggregate = null;
        IComponentVM? previous = null;
        var calls = 0;
        aggregate = AggregateVM1<IComponentVM>.Builder()
            .Name("aggregate").Services(hub, dispatcher)
            .Component1(() => ++calls == 1
                ? previous = new ReentrantDisposeVM(
                    "old", hub, dispatcher, () => aggregate!.Dispose())
                : candidate)
            .Build();
        aggregate.Construct();

        aggregate.Reconstruct();

        aggregate.Status.Should().Be(ConstructionStatus.Disposed);
        aggregate.Component1.Should().BeSameAs(previous);
        candidate.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public void AggregateVM2_Reconstruct_Aborts_All_Candidates_When_Previous_Disposal_Disposes_Parent()
    {
        var (hub, dispatcher) = MakeServices();
        var candidate1 = MakeLeaf(hub, dispatcher, "candidate-1");
        var candidate2 = MakeLeaf(hub, dispatcher, "candidate-2");
        AggregateVM2<IComponentVM, IComponentVM>? aggregate = null;
        IComponentVM? previous1 = null;
        IComponentVM? previous2 = null;
        var calls1 = 0;
        var calls2 = 0;
        aggregate = AggregateVM2<IComponentVM, IComponentVM>.Builder()
            .Name("aggregate").Services(hub, dispatcher)
            .Component1(() => ++calls1 == 1
                ? previous1 = new ReentrantDisposeVM(
                    "old-1", hub, dispatcher, () => aggregate!.Dispose())
                : candidate1)
            .Component2(() => ++calls2 == 1
                ? previous2 = MakeLeaf(hub, dispatcher, "old-2")
                : candidate2)
            .Build();
        aggregate.Construct();

        aggregate.Reconstruct();

        aggregate.Status.Should().Be(ConstructionStatus.Disposed);
        aggregate.Component1.Should().BeSameAs(previous1);
        aggregate.Component2.Should().BeSameAs(previous2);
        candidate1.Status.Should().Be(ConstructionStatus.Disposed);
        candidate2.Status.Should().Be(ConstructionStatus.Disposed);
    }
}
#pragma warning restore CA1715
