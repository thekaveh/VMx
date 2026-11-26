using FluentAssertions;
using VMx.Components;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// LIFE-023..LIFE-024 — a child-transition walk that closes a cycle. A walk
/// that lists its own view-model, or that would join a view-model whose walk
/// waits back on the walking one, raises the flavor's usage error and starts
/// no child, so no view-model is left <c>Constructing</c> (spec/02 §6.1,
/// ADR-0255). LIFE-020 covers the diamond control, where two walks share a
/// child and all three view-models still construct.
/// </summary>
public class LIFE_023_024_WalkCycles_Tests
{
    /// <summary>A consumer leaf VM whose construct walk lists <see cref="ConstructMembers"/>.</summary>
    private sealed class LeafVM(string name, IMessageHub hub, IDispatcher dispatcher)
        : ComponentVMBase(name, hub, dispatcher)
    {
        public IReadOnlyList<IComponentVM> ConstructMembers { get; set; } = [];

        public override ViewModelType Type => ViewModelType.Component;

        protected override void OnConstruct()
            => CompleteLifecycleHookAfter(TransitionChildrenAsync(ConstructMembers, construct: true));

        protected override void OnDestruct()
            => CompleteLifecycleHookAfter(TransitionChildrenAsync(ConstructMembers, construct: false));
    }

    private static ComponentVM Leaf(string name, IMessageHub hub, Action? onConstruct = null)
    {
        var builder = ComponentVM.Builder()
            .Name(name)
            .Services(hub, NullDispatcher.Instance);
        if (onConstruct is not null) builder = builder.OnConstruct(onConstruct);
        return builder.Build();
    }

    // LIFE-023 — a walk that lists its own view-model fails with the usage
    // error before it starts any child, and the walking VM rolls back.
    [Fact, Trait("Conformance", "LIFE-023")]
    public void LIFE_023_Walk_Listing_Its_Own_View_Model_Fails_And_Starts_No_Child()
    {
        using var hub = new TestHub();
        var siblingRuns = 0;
        var sibling = Leaf("sibling", hub, onConstruct: () => siblingRuns++);
        var walker = new LeafVM("walker", hub, NullDispatcher.Instance);
        walker.ConstructMembers = [walker, sibling];

        Assert.Throws<InvalidOperationException>(walker.Construct);

        walker.Status.Should().Be(ConstructionStatus.Destructed);
        sibling.Status.Should().Be(ConstructionStatus.Destructed);
        siblingRuns.Should().Be(0);
    }

    // LIFE-024 — two leaves whose walks list each other: construct() on one of
    // them fails with the cycle error, and both end Destructed (settled).
    [Fact, Trait("Conformance", "LIFE-024")]
    public void LIFE_024_Two_Walks_That_List_Each_Other_Both_Settle()
    {
        using var hub = new TestHub();
        var p = new LeafVM("p", hub, NullDispatcher.Instance);
        var q = new LeafVM("q", hub, NullDispatcher.Instance);
        p.ConstructMembers = [q];
        q.ConstructMembers = [p];

        Assert.Throws<InvalidOperationException>(p.Construct);

        p.Status.Should().Be(ConstructionStatus.Destructed);
        q.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // LIFE-024 — a leaf whose walk lists its own group: the group's construct()
    // fails with the cycle error, and the group rolls back to Destructed.
    [Fact, Trait("Conformance", "LIFE-024")]
    public void LIFE_024_Leaf_Walking_Its_Own_Group_Fails_The_Group_And_Rolls_It_Back()
    {
        using var hub = new TestHub();
        var leaf = new LeafVM("leaf", hub, NullDispatcher.Instance);
        var group = GroupVM<ComponentVMBase>.Create(new GroupVMOptions<ComponentVMBase>
        {
            Name = "group",
            Hub = hub,
            Dispatcher = NullDispatcher.Instance,
            Children = () => [leaf],
        });
        leaf.ConstructMembers = [group];

        Assert.Throws<InvalidOperationException>(group.Construct);

        group.Status.Should().Be(ConstructionStatus.Destructed);
        // The group populated the leaf and joined its construct, so the leaf's
        // wait resumes on another thread when the group settles (ADR-0255).
        Assert.True(SpinWait.SpinUntil(
            () => leaf.Status == ConstructionStatus.Destructed, Liveness.HangGuard));
    }

    // LIFE-020 — the diamond control: a and b both walk c, and all three
    // view-models construct, with c's construct hook run once.
    [Fact, Trait("Conformance", "LIFE-020")]
    public void LIFE_020_Diamond_Walks_Construct_All_Three_View_Models()
    {
        using var hub = new TestHub();
        var cRuns = 0;
        var c = Leaf("c", hub, onConstruct: () => cRuns++);
        var a = new LeafVM("a", hub, NullDispatcher.Instance) { ConstructMembers = [c] };
        var b = new LeafVM("b", hub, NullDispatcher.Instance) { ConstructMembers = [c] };

        a.Construct();
        b.Construct();

        a.Status.Should().Be(ConstructionStatus.Constructed);
        b.Status.Should().Be(ConstructionStatus.Constructed);
        c.Status.Should().Be(ConstructionStatus.Constructed);
        cRuns.Should().Be(1);
    }
}
