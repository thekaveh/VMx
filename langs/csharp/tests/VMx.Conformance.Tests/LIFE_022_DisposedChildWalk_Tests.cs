using FluentAssertions;
using VMx.Aggregates;
using VMx.Collections;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// LIFE-022 — a container walk skips a child that was disposed directly. See
/// spec/02 §6 and §6.1 and ADR-0189. A composite, group or aggregate that holds
/// a Disposed child still destructs, constructs and reconstructs. The
/// composite and the group keep the child as a member; the aggregate replaces
/// the slot from its factory at its next construct. The child-transition
/// helper skips a Disposed member in both walks. No lifecycle call reaches a
/// Disposed child.
/// </summary>
public class LIFE_022_DisposedChildWalk_Tests
{
    public enum Container
    {
        Composite,
        Group,
    }

    /// <summary>A consumer leaf VM that walks its members with the helper.</summary>
    private sealed class LeafVM(string name, IMessageHub hub, IReadOnlyList<IComponentVM> members)
        : ComponentVMBase(name, hub, NullDispatcher.Instance)
    {
        public override ViewModelType Type => ViewModelType.Component;

        protected override void OnConstruct()
            => CompleteLifecycleHookAfter(TransitionChildrenAsync(members, construct: true));

        protected override void OnDestruct()
            => CompleteLifecycleHookAfter(TransitionChildrenAsync(members, construct: false));
    }

    private static ComponentVM Leaf(IMessageHub hub, string name)
        => ComponentVM.Builder().Name(name).Services(hub, NullDispatcher.Instance).Build();

    private static (IComponentVM Box, IObservableMembershipSource<ComponentVM> Members) Box(
        Container kind, IMessageHub hub, ComponentVM a, ComponentVM b)
    {
        if (kind == Container.Composite)
        {
            var composite = CompositeVM<ComponentVM>.Builder()
                .Name("box").Services(hub, NullDispatcher.Instance)
                .Children(() => [a, b]).Build();
            return (composite, composite);
        }
        var group = GroupVM<ComponentVM>.Builder()
            .Name("box").Services(hub, NullDispatcher.Instance)
            .Children(() => [a, b]).Build();
        return (group, group);
    }

    [Theory, Trait("Conformance", "LIFE-022")]
    [InlineData(Container.Composite)]
    [InlineData(Container.Group)]
    public void LIFE_022_Container_Skips_A_Child_Disposed_While_Constructed(Container kind)
    {
        using var hub = new TestHub();
        var a = Leaf(hub, "a");
        var b = Leaf(hub, "b");
        var (box, members) = Box(kind, hub, a, b);
        box.Construct();

        b.Dispose();
        var destruct = () => box.Destruct();

        destruct.Should().NotThrow();
        box.Status.Should().Be(ConstructionStatus.Destructed);
        a.Status.Should().Be(ConstructionStatus.Destructed);
        b.Status.Should().Be(ConstructionStatus.Disposed);
        members.Snapshot().Should().Equal(a, b);

        var construct = () => box.Construct();

        construct.Should().NotThrow();
        box.Status.Should().Be(ConstructionStatus.Constructed);
        a.Status.Should().Be(ConstructionStatus.Constructed);
        b.Status.Should().Be(ConstructionStatus.Disposed);

        var reconstruct = () => box.Reconstruct();

        reconstruct.Should().NotThrow();
        box.Status.Should().Be(ConstructionStatus.Constructed);
        a.Status.Should().Be(ConstructionStatus.Constructed);
        b.Status.Should().Be(ConstructionStatus.Disposed);
        members.Snapshot().Should().Equal(a, b);
    }

    [Theory, Trait("Conformance", "LIFE-022")]
    [InlineData(Container.Composite)]
    [InlineData(Container.Group)]
    public void LIFE_022_Container_Skips_A_Child_Disposed_While_Destructed(Container kind)
    {
        using var hub = new TestHub();
        var a = Leaf(hub, "a");
        var b = Leaf(hub, "b");
        var (box, members) = Box(kind, hub, a, b);
        box.Construct();
        box.Destruct();

        b.Dispose();
        var construct = () => box.Construct();

        construct.Should().NotThrow();
        box.Status.Should().Be(ConstructionStatus.Constructed);
        a.Status.Should().Be(ConstructionStatus.Constructed);
        b.Status.Should().Be(ConstructionStatus.Disposed);
        members.Snapshot().Should().Equal(a, b);
    }

    [Fact, Trait("Conformance", "LIFE-022")]
    public void LIFE_022_Aggregate_Skips_A_Disposed_Slot_And_Replaces_It()
    {
        using var hub = new TestHub();
        var created = 0;
        var box = AggregateVM2<ComponentVM, ComponentVM>.Builder()
            .Name("box").Services(hub, NullDispatcher.Instance)
            .Component1(() => Leaf(hub, $"a{++created}"))
            .Component2(() => Leaf(hub, $"b{++created}"))
            .Build();
        box.Construct();
        var a = box.Component1!;
        var b = box.Component2!;

        b.Dispose();
        var destruct = () => box.Destruct();

        destruct.Should().NotThrow();
        box.Status.Should().Be(ConstructionStatus.Destructed);
        a.Status.Should().Be(ConstructionStatus.Destructed);
        b.Status.Should().Be(ConstructionStatus.Disposed);

        var construct = () => box.Construct();

        construct.Should().NotThrow();
        box.Status.Should().Be(ConstructionStatus.Constructed);
        box.Component2.Should().NotBeSameAs(b, "the next construct replaces the slot from its factory");
        box.Component1!.Status.Should().Be(ConstructionStatus.Constructed);
        box.Component2!.Status.Should().Be(ConstructionStatus.Constructed);

        // Reconstruct from Constructed with a Disposed slot.
        box.Component2.Dispose();
        var reconstruct = () => box.Reconstruct();

        reconstruct.Should().NotThrow();
        box.Status.Should().Be(ConstructionStatus.Constructed);
        box.Component2!.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact, Trait("Conformance", "LIFE-022")]
    public void LIFE_022_Helper_Skips_A_Disposed_Member()
    {
        using var hub = new TestHub();
        var m1 = Leaf(hub, "m1");
        var m2 = Leaf(hub, "m2");
        var leaf = new LeafVM("leaf", hub, [m1, m2]);
        leaf.Construct();

        m2.Dispose();
        var destruct = () => leaf.Destruct();

        destruct.Should().NotThrow();
        leaf.Status.Should().Be(ConstructionStatus.Destructed);
        m1.Status.Should().Be(ConstructionStatus.Destructed);
        m2.Status.Should().Be(ConstructionStatus.Disposed);

        var construct = () => leaf.Construct();

        construct.Should().NotThrow();
        leaf.Status.Should().Be(ConstructionStatus.Constructed);
        m1.Status.Should().Be(ConstructionStatus.Constructed);
        m2.Status.Should().Be(ConstructionStatus.Disposed);
    }
}
