#pragma warning disable CA1715 // Spec uses 'VM' type parameter names per ADR-0006
using FluentAssertions;
using VMx.Aggregates;
using VMx.Components;
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
}
#pragma warning restore CA1715
