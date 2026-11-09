using FluentAssertions;
using VMx.Aggregates;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Aggregates;

/// <summary>
/// A population that fails before its commit disposes the candidates it built
/// and nobody owns (#1324): aggregate factories and preflight, CompositeVMOf
/// projectors, and the first recompute of filtered projections.
/// </summary>
public class FailedPopulationCleanupTests
{
    private sealed class FactoryFailure : Exception
    {
        public FactoryFailure() : base("factory failed") { }
    }

    private static readonly TestHub Hub = new();
    private static readonly TestDispatcher Dispatcher = new();

    private static ComponentVM<string> Leaf(string name)
        => ComponentVM<string>.Builder().Name(name).Services(Hub, Dispatcher).Model(name).Build();

    /// <summary>Builds an aggregate of <paramref name="arity"/> slots over <paramref name="slots"/>.</summary>
    private static (IComponentVM Aggregate, Func<IComponentVM?[]> Slots) Aggregate(
        int arity, Func<int, ComponentVM<string>> slots)
    {
        switch (arity)
        {
            case 2:
                {
                    var agg = AggregateVM2<ComponentVM<string>, ComponentVM<string>>.Builder()
                        .Name("agg").Services(Hub, Dispatcher)
                        .Component1(() => slots(1)).Component2(() => slots(2)).Build();
                    return (agg, () => [agg.Component1, agg.Component2]);
                }
            case 3:
                {
                    var agg = AggregateVM3<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>>.Builder()
                        .Name("agg").Services(Hub, Dispatcher)
                        .Component1(() => slots(1)).Component2(() => slots(2)).Component3(() => slots(3)).Build();
                    return (agg, () => [agg.Component1, agg.Component2, agg.Component3]);
                }
            case 4:
                {
                    var agg = AggregateVM4<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>,
                            ComponentVM<string>>.Builder()
                        .Name("agg").Services(Hub, Dispatcher)
                        .Component1(() => slots(1)).Component2(() => slots(2)).Component3(() => slots(3))
                        .Component4(() => slots(4)).Build();
                    return (agg, () => [agg.Component1, agg.Component2, agg.Component3, agg.Component4]);
                }
            case 5:
                {
                    var agg = AggregateVM5<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>,
                            ComponentVM<string>, ComponentVM<string>>.Builder()
                        .Name("agg").Services(Hub, Dispatcher)
                        .Component1(() => slots(1)).Component2(() => slots(2)).Component3(() => slots(3))
                        .Component4(() => slots(4)).Component5(() => slots(5)).Build();
                    return (agg, () => [agg.Component1, agg.Component2, agg.Component3, agg.Component4,
                    agg.Component5]);
                }
            default:
                {
                    var agg = AggregateVM6<ComponentVM<string>, ComponentVM<string>, ComponentVM<string>,
                            ComponentVM<string>, ComponentVM<string>, ComponentVM<string>>.Builder()
                        .Name("agg").Services(Hub, Dispatcher)
                        .Component1(() => slots(1)).Component2(() => slots(2)).Component3(() => slots(3))
                        .Component4(() => slots(4)).Component5(() => slots(5)).Component6(() => slots(6))
                        .Build();
                    return (agg, () => [agg.Component1, agg.Component2, agg.Component3, agg.Component4,
                    agg.Component5, agg.Component6]);
                }
        }
    }

    public static TheoryData<int> Arities() => new() { 2, 3, 4, 5, 6 };

    [Theory, MemberData(nameof(Arities))]
    public void Throwing_Last_Factory_On_Construct_Disposes_Earlier_Candidates(int arity)
    {
        var built = new List<ComponentVM<string>>();
        var (agg, slots) = Aggregate(arity, slot =>
        {
            if (slot == arity) throw new FactoryFailure();
            var leaf = Leaf($"s{slot}");
            built.Add(leaf);
            return leaf;
        });

        agg.Invoking(a => a.Construct()).Should().Throw<FactoryFailure>();

        built.Should().HaveCount(arity - 1);
        built.Should().OnlyContain(candidate => candidate.Status == ConstructionStatus.Disposed);
        slots().Should().OnlyContain(slot => slot == null);
    }

    [Theory, MemberData(nameof(Arities))]
    public void Owned_Last_Candidate_Disposes_Earlier_Candidates_And_Keeps_The_Owned_One(int arity)
    {
        var owner = AggregateVM1<ComponentVM<string>>.Builder()
            .Name("owner").Services(Hub, Dispatcher).Component1(() => Leaf("owned")).Build();
        owner.Construct();
        var owned = owner.Component1!;
        var built = new List<ComponentVM<string>>();
        var (agg, slots) = Aggregate(arity, slot =>
        {
            if (slot == arity) return owned;
            var leaf = Leaf($"s{slot}");
            built.Add(leaf);
            return leaf;
        });

        agg.Invoking(a => a.Construct()).Should().Throw<InvalidOperationException>();

        built.Should().OnlyContain(candidate => candidate.Status == ConstructionStatus.Disposed);
        owned.Status.Should().Be(ConstructionStatus.Constructed);
        owned.GetParent()!.Owner.Should().BeSameAs(owner);
        slots().Should().OnlyContain(slot => slot == null);
    }

    [Theory, MemberData(nameof(Arities))]
    public void Throwing_Factory_On_Reconstruct_Keeps_Old_Slots_And_Disposes_Fresh_Candidates(int arity)
    {
        var failing = false;
        var fresh = new List<ComponentVM<string>>();
        var (agg, slots) = Aggregate(arity, slot =>
        {
            if (failing && slot == arity) throw new FactoryFailure();
            var leaf = Leaf($"s{slot}");
            if (failing) fresh.Add(leaf);
            return leaf;
        });
        agg.Construct();
        var old = slots();

        failing = true;
        agg.Invoking(a => a.Reconstruct()).Should().Throw<FactoryFailure>();

        slots().Should().Equal(old);
        old.Should().OnlyContain(slot => ReferenceEquals(slot!.GetParent()!.Owner, agg));
        fresh.Should().HaveCount(arity - 1);
        fresh.Should().OnlyContain(candidate => candidate.Status == ConstructionStatus.Disposed);
    }

    [Fact]
    public void Throwing_Projector_Disposes_Earlier_Children_And_Leaves_The_Composite_Empty()
    {
        var projected = new List<ComponentVM<string>>();
        var composite = CompositeVMOfM<string, ComponentVM<string>>.Builder()
            .Name("c").Services(Hub, Dispatcher)
            .ChildrenModels(() => ["a", "b"])
            .ChildModelToChildViewModel(model =>
            {
                if (model == "b") throw new FactoryFailure();
                var leaf = Leaf(model);
                projected.Add(leaf);
                return leaf;
            })
            .Build();

        composite.Invoking(c => c.Construct()).Should().Throw<FactoryFailure>();

        projected.Should().ContainSingle().Which.Status.Should().Be(ConstructionStatus.Disposed);
        composite.Should().BeEmpty();
    }

    private static CompositeVM<ComponentVM<string>> Source()
    {
        var source = CompositeVM<ComponentVM<string>>.Builder()
            .Name("source").Services(Hub, Dispatcher).Children(() => []).Build();
        source.Add(Leaf("a"));
        return source;
    }

    [Fact]
    public void Throwing_Filter_Predicate_Detaches_From_The_Source()
    {
        var source = Source();
        var calls = 0;

        var act = () => new FilteredCompositeVM<ComponentVM<string>>(source, _ =>
        {
            calls++;
            throw new FactoryFailure();
        });

        act.Should().Throw<FactoryFailure>();
        calls = 0;
        source.Invoking(s => s.Add(Leaf("b"))).Should().NotThrow();
        calls.Should().Be(0);
    }

    [Fact]
    public void Throwing_Scorer_Detaches_From_The_Source()
    {
        var source = Source();
        var calls = 0;

        var act = () => new ScoredFilteredCompositeVM<ComponentVM<string>>(source, _ =>
        {
            calls++;
            throw new FactoryFailure();
        });

        act.Should().Throw<FactoryFailure>();
        calls = 0;
        source.Invoking(s => s.Add(Leaf("b"))).Should().NotThrow();
        calls.Should().Be(0);
    }

    [Fact]
    public void Null_Scorer_Detaches_From_The_Source()
    {
        var source = Source();

        var act = () => new ScoredFilteredCompositeVM<ComponentVM<string>>(source, null!);

        act.Should().Throw<ArgumentNullException>();
        source.Invoking(s => s.Add(Leaf("b"))).Should().NotThrow();
    }
}
