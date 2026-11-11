using FluentAssertions;
using VMx.Aggregates;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// AGG-008 (spec/08 §2 and §4, ADR-0224): a fixed-slot population that its
/// preflight refuses disposes the candidates that nobody owns. It keeps the
/// owned candidate's status and parent, and the old slots stay unchanged.
/// </summary>
public class AGG_008_RefusedPopulationCleanup_Tests
{
    private static readonly TestHub Hub = new();
    private static readonly TestDispatcher Dispatcher = new();

    private static ComponentVM<string> Leaf(string name)
        => ComponentVM<string>.Builder().Name(name).Services(Hub, Dispatcher).Model(name).Build();

    /// <summary>A component that a constructed composite owns.</summary>
    private static (ComponentVM<string> Component, CompositeVM<ComponentVM<string>> Owner) Owned(string name)
    {
        var component = Leaf(name);
        var owner = CompositeVM<ComponentVM<string>>.Builder()
            .Name("owner").Services(Hub, Dispatcher)
            .Children(() => [component]).Build();
        owner.Construct();
        component.Status.Should().Be(ConstructionStatus.Constructed);
        return (component, owner);
    }

    private static void ShouldBeOwnedBy(ComponentVM<string> component, CompositeVM<ComponentVM<string>> owner)
    {
        component.Status.Should().Be(ConstructionStatus.Constructed);
        component.GetParent()!.Owner.Should().BeSameAs(owner);
        owner.Snapshot().Should().ContainSingle().Which.Should().BeSameAs(component);
    }

    [Fact]
    [Trait("Conformance", "AGG-008")]
    public void Refused_Construct_Disposes_The_Unowned_Candidates()
    {
        var fresh = Leaf("fresh");
        var (borrowed, owner) = Owned("borrowed");
        var aggregate = AggregateVM2<ComponentVM<string>, ComponentVM<string>>.Builder()
            .Name("aggregate").Services(Hub, Dispatcher)
            .Component1(() => fresh).Component2(() => borrowed).Build();

        aggregate.Invoking(a => a.Construct())
            .Should().Throw<InvalidOperationException>().WithMessage("*already has a parent*");

        fresh.Status.Should().Be(ConstructionStatus.Disposed);
        ShouldBeOwnedBy(borrowed, owner);
        aggregate.Component1.Should().BeNull();
        aggregate.Component2.Should().BeNull();
    }

    [Fact]
    [Trait("Conformance", "AGG-008")]
    public void Refused_Reconstruct_Disposes_The_Fresh_Candidates_And_Keeps_The_Old_Slots()
    {
        var first = Leaf("first");
        var second = Leaf("second");
        var replacement = Leaf("replacement");
        var (borrowed, owner) = Owned("borrowed");
        var calls1 = 0;
        var calls2 = 0;
        var aggregate = AggregateVM2<ComponentVM<string>, ComponentVM<string>>.Builder()
            .Name("aggregate").Services(Hub, Dispatcher)
            .Component1(() => ++calls1 == 1 ? first : replacement)
            .Component2(() => ++calls2 == 1 ? second : borrowed)
            .Build();
        aggregate.Construct();

        aggregate.Invoking(a => a.Reconstruct())
            .Should().Throw<InvalidOperationException>().WithMessage("*already has a parent*");

        aggregate.Component1.Should().BeSameAs(first);
        aggregate.Component2.Should().BeSameAs(second);
        foreach (var old in new[] { first, second })
        {
            old.GetParent()!.Owner.Should().BeSameAs(aggregate);
            old.Status.Should().Be(ConstructionStatus.Destructed);
        }
        replacement.Status.Should().Be(ConstructionStatus.Disposed);
        replacement.GetParent().Should().BeNull();
        ShouldBeOwnedBy(borrowed, owner);
    }
}
