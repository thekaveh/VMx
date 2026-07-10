#pragma warning disable CA1859 // Interface-typed locals are the contract assertion under test.
using System.Collections.Specialized;
using FluentAssertions;
using VMx.Collections;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

public class VmCollectionMoveConformanceTests
{
    private static ComponentVM Child(TestHub hub, TestDispatcher dispatcher, string name,
        Action? onConstruct = null)
    {
        var builder = ComponentVM.Builder().Name(name).Services(hub, dispatcher);
        if (onConstruct is not null) builder = builder.OnConstruct(onConstruct);
        return builder.Build();
    }

    private static (CompositeVM<ComponentVM> composite, GroupVM<ComponentVM> group,
        ComponentVM a, ComponentVM b, ComponentVM c) Build()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var a = Child(hub, dispatcher, "a");
        var b = Child(hub, dispatcher, "b");
        var c = Child(hub, dispatcher, "c");
        var composite = CompositeVM<ComponentVM>.Builder()
            .Name("composite").Services(hub, dispatcher).Children(() => [a, b, c]).Build();
        var group = GroupVM<ComponentVM>.Builder()
            .Name("group").Services(hub, dispatcher).Children(() => [a, b, c]).Build();
        return (composite, group, a, b, c);
    }

    [Fact, Trait("Conformance", "COL-032")]
    public void COL_032_Shared_Contract_Separates_Selection()
    {
        var (composite, group, _, _, _) = Build();
        IVmCollection<ComponentVM> compositeCollection = composite;
        IVmCollection<ComponentVM> groupCollection = group;
        ISelectableVmCollection<ComponentVM> selectable = composite;

        compositeCollection.Count.Should().Be(0);
        groupCollection.Count.Should().Be(0);
        selectable.Current.Should().BeNull();
        group.Should().NotBeAssignableTo<ISelectableVmCollection<ComponentVM>>();
    }

    [Fact, Trait("Conformance", "COL-033")]
    public void COL_033_Forward_Move_Emits_One_Move_Event()
    {
        var (composite, _, a, b, c) = Build();
        composite.Construct();
        var events = new List<NotifyCollectionChangedEventArgs>();
        composite.CollectionChanged += (_, e) => events.Add(e);

        composite.Move(0, 2);

        composite.Should().Equal(b, c, a);
        events.Should().ContainSingle();
        events[0].Action.Should().Be(NotifyCollectionChangedAction.Move);
        events[0].OldStartingIndex.Should().Be(0);
        events[0].NewStartingIndex.Should().Be(2);
        events[0].NewItems![0].Should().BeSameAs(a);
    }

    [Fact, Trait("Conformance", "COL-034")]
    public void COL_034_Backward_Move_Works_For_Group()
    {
        var (_, group, a, b, c) = Build();
        group.Construct();
        NotifyCollectionChangedEventArgs? observed = null;
        group.CollectionChanged += (_, e) => observed = e;

        group.Move(2, 0);

        group.Should().Equal(c, a, b);
        observed!.Action.Should().Be(NotifyCollectionChangedAction.Move);
        observed.OldStartingIndex.Should().Be(2);
        observed.NewStartingIndex.Should().Be(0);
    }

    [Fact, Trait("Conformance", "COL-035")]
    public void COL_035_Same_Index_Is_A_True_No_Op()
    {
        var (composite, _, a, b, c) = Build();
        composite.Construct();
        var events = 0;
        composite.CollectionChanged += (_, _) => events++;

        using (composite.BatchUpdate()) composite.Move(1, 1);

        composite.Should().Equal(a, b, c);
        events.Should().Be(0);
    }

    [Fact, Trait("Conformance", "COL-036")]
    public void COL_036_Invalid_Bounds_Are_Atomic()
    {
        var (composite, _, a, b, c) = Build();
        composite.Construct();
        var events = 0;
        composite.CollectionChanged += (_, _) => events++;

        var from = () => composite.Move(-1, 0);
        var to = () => composite.Move(0, 3);

        from.Should().Throw<ArgumentOutOfRangeException>();
        to.Should().Throw<ArgumentOutOfRangeException>();
        composite.Should().Equal(a, b, c);
        events.Should().Be(0);
    }

    [Fact, Trait("Conformance", "COL-037")]
    public void COL_037_Move_Preserves_Identity_Parent_Lifecycle_And_Current()
    {
        var (composite, _, a, _, _) = Build();
        composite.Construct();
        composite.Current = a;
        var status = a.Status;

        composite.Move(0, 2);

        composite[2].Should().BeSameAs(a);
        composite.Current.Should().BeSameAs(a);
        a.IsCurrent.Should().BeTrue();
        a.CanDeselect().Should().BeTrue();
        a.Status.Should().Be(status).And.Be(ConstructionStatus.Constructed);
    }

    [Fact, Trait("Conformance", "COL-038")]
    public void COL_038_Batched_Move_Collapses_To_Reset()
    {
        var (composite, _, _, _, _) = Build();
        composite.Construct();
        var actions = new List<NotifyCollectionChangedAction>();
        composite.CollectionChanged += (_, e) => actions.Add(e.Action);

        using (composite.BatchUpdate()) composite.Move(0, 2);

        actions.Should().Equal(NotifyCollectionChangedAction.Reset);
    }

    [Fact, Trait("Conformance", "COL-039")]
    public void COL_039_Move_Does_Not_Reconstruct_Auto_Constructed_Child()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var constructs = 0;
        var child = Child(hub, dispatcher, "child", () => constructs++);
        var composite = CompositeVM<ComponentVM>.Builder()
            .Name("composite").Services(hub, dispatcher).Children(() => Array.Empty<ComponentVM>())
            .AutoConstructOnAdd(true).Build();
        composite.Construct();
        composite.Add(child);
        composite.Add(Child(hub, dispatcher, "other"));

        composite.Move(0, 1);

        constructs.Should().Be(1);
        composite[1].Should().BeSameAs(child);
    }
}
#pragma warning restore CA1859
