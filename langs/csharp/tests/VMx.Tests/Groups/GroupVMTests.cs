using System.Collections.Specialized;
using FluentAssertions;
using VMx.Components;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Groups;

/// <summary>
/// Unit tests for <see cref="GroupVM{VM}"/> (non-modeled variant).
/// Conformance-level tests live in VMx.Conformance.Tests.
/// </summary>
public class GroupVMTests
{
    // ── Factory helpers ──────────────────────────────────────────────────────

    private static (GroupVM<ComponentVM<string>> group, TestHub hub, TestDispatcher dispatcher)
        BuildGroup(string name = "root")
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var group = GroupVM<ComponentVM<string>>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        return (group, hub, dispatcher);
    }

    private static ComponentVM<string> BuildChild(
        TestHub hub, TestDispatcher dispatcher, string name = "child")
        => ComponentVM<string>.Builder()
            .Name(name).Services(hub, dispatcher).Model("m").Build();

    // ── Type and identity ────────────────────────────────────────────────────

    [Fact]
    public void Type_Is_Group()
    {
        var (group, _, _) = BuildGroup();
        group.Type.Should().Be(ViewModelType.Group);
    }

    [Fact]
    public void Name_Is_Set_From_Builder()
    {
        var (group, _, _) = BuildGroup("myGroup");
        group.Name.Should().Be("myGroup");
    }

    [Fact]
    public void Initial_Count_Is_Zero()
    {
        var (group, _, _) = BuildGroup();
        group.Count.Should().Be(0);
    }

    // ── No Current property ──────────────────────────────────────────────────

    [Fact]
    public void Group_Does_Not_Expose_Current_Property()
    {
        var (group, _, _) = BuildGroup();
        var type = group.GetType();
        var currentProp = type.GetProperty("Current");
        currentProp.Should().BeNull("GroupVM must not expose a Current property");
    }

    // ── IList<VM>: Add ───────────────────────────────────────────────────────

    [Fact]
    public void Add_Increases_Count()
    {
        var (group, hub, dispatcher) = BuildGroup();
        var child = BuildChild(hub, dispatcher);
        group.Add(child);
        group.Count.Should().Be(1);
    }

    [Fact]
    public void Add_Emits_CollectionChanged_Add()
    {
        var (group, hub, dispatcher) = BuildGroup();
        var child = BuildChild(hub, dispatcher);
        NotifyCollectionChangedEventArgs? evt = null;
        group.CollectionChanged += (_, e) => evt = e;

        group.Add(child);

        evt.Should().NotBeNull();
        evt!.Action.Should().Be(NotifyCollectionChangedAction.Add);
        evt.NewItems.Should().NotBeNull();
        evt.NewItems![0].Should().BeSameAs(child);
        evt.NewStartingIndex.Should().Be(0);
    }

    // ── IList<VM>: Remove ────────────────────────────────────────────────────

    [Fact]
    public void Remove_Decreases_Count()
    {
        var (group, hub, dispatcher) = BuildGroup();
        var child = BuildChild(hub, dispatcher);
        group.Add(child);
        group.Remove(child);
        group.Count.Should().Be(0);
    }

    [Fact]
    public void Remove_Emits_CollectionChanged_Remove()
    {
        var (group, hub, dispatcher) = BuildGroup();
        var child = BuildChild(hub, dispatcher);
        group.Add(child);
        NotifyCollectionChangedEventArgs? evt = null;
        group.CollectionChanged += (_, e) => evt = e;

        group.Remove(child);

        evt.Should().NotBeNull();
        evt!.Action.Should().Be(NotifyCollectionChangedAction.Remove);
        evt.OldItems![0].Should().BeSameAs(child);
        evt.OldStartingIndex.Should().Be(0);
    }

    [Fact]
    public void Remove_Returns_False_For_Missing_Item()
    {
        var (group, hub, dispatcher) = BuildGroup();
        var child = BuildChild(hub, dispatcher);
        group.Remove(child).Should().BeFalse();
    }

    // ── IList<VM>: Insert ────────────────────────────────────────────────────

    [Fact]
    public void Insert_At_Index_Emits_CollectionChanged()
    {
        var (group, hub, dispatcher) = BuildGroup();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        group.Add(c1);

        NotifyCollectionChangedEventArgs? evt = null;
        group.CollectionChanged += (_, e) => evt = e;
        group.Insert(0, c2);

        group[0].Should().BeSameAs(c2);
        group[1].Should().BeSameAs(c1);
        evt!.Action.Should().Be(NotifyCollectionChangedAction.Add);
        evt.NewStartingIndex.Should().Be(0);
    }

    // ── IList<VM>: Clear ─────────────────────────────────────────────────────

    [Fact]
    public void Clear_Removes_All_Items_And_Emits_Reset()
    {
        var (group, hub, dispatcher) = BuildGroup();
        group.Add(BuildChild(hub, dispatcher, "c1"));
        group.Add(BuildChild(hub, dispatcher, "c2"));
        NotifyCollectionChangedEventArgs? evt = null;
        group.CollectionChanged += (_, e) => evt = e;

        group.Clear();

        group.Count.Should().Be(0);
        evt!.Action.Should().Be(NotifyCollectionChangedAction.Reset);
    }

    // ── Lifecycle: Construct ─────────────────────────────────────────────────

    [Fact]
    public void Construct_Constructs_All_Children()
    {
        var (group, hub, dispatcher) = BuildGroup();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        group.Add(c1);
        group.Add(c2);

        group.Construct();

        c1.Status.Should().Be(ConstructionStatus.Constructed);
        c2.Status.Should().Be(ConstructionStatus.Constructed);
        group.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void Destruct_Destructs_All_Children()
    {
        var (group, hub, dispatcher) = BuildGroup();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        group.Add(c1);
        group.Add(c2);
        group.Construct();

        group.Destruct();

        c1.Status.Should().Be(ConstructionStatus.Destructed);
        c2.Status.Should().Be(ConstructionStatus.Destructed);
        group.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // ── Children factory ─────────────────────────────────────────────────────

    [Fact]
    public void Children_Factory_Is_Evaluated_On_Construct()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var child = BuildChild(hub, dispatcher, "lazy");

        var group = GroupVM<ComponentVM<string>>.Builder()
            .Name("g")
            .Services(hub, dispatcher)
            .Children(() => [child])
            .Build();

        group.Count.Should().Be(0, "factory not yet evaluated");

        group.Construct();

        group.Count.Should().Be(1);
        group[0].Should().BeSameAs(child);
        child.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // ── Builder: validation ──────────────────────────────────────────────────

    [Fact]
    public void Builder_Throws_When_Name_Missing()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var act = () => GroupVM<ComponentVM<string>>.Builder()
            .Services(hub, dispatcher)
            .Build();
        act.Should().Throw<Exception>();
    }

    [Fact]
    public void Builder_Throws_When_Services_Missing()
    {
        var act = () => GroupVM<ComponentVM<string>>.Builder()
            .Name("g")
            .Build();
        act.Should().Throw<Exception>();
    }

    [Fact]
    public void Builder_Throws_When_Children_Missing()
    {
        // Per spec/10-builders.md §3 + ADR-0035: GroupVM<VM> requires a
        // Children(() => ...) factory. For an empty group, pass
        // Children(() => Array.Empty<VM>()) explicitly.
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var act = () => GroupVM<ComponentVM<string>>.Builder()
            .Name("g")
            .Services(hub, dispatcher)
            .Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>()
            .WithMessage("*Children*");
    }

    // ── Dispose cascade ──────────────────────────────────────────────────────

    [Fact]
    public void Dispose_Cascades_To_Children()
    {
        var (group, hub, dispatcher) = BuildGroup();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        group.Add(c1);
        group.Add(c2);
        group.Construct();

        group.Dispose();

        c1.Status.Should().Be(ConstructionStatus.Disposed);
        c2.Status.Should().Be(ConstructionStatus.Disposed);
        group.Status.Should().Be(ConstructionStatus.Disposed);
    }

    // ── SelectCommand / DeselectCommand present (IComponentVM baseline) ──────

    [Fact]
    public void SelectCommand_Is_Present()
    {
        var (group, _, _) = BuildGroup();
        group.SelectCommand.Should().NotBeNull();
    }

    [Fact]
    public void DeselectCommand_Is_Present()
    {
        var (group, _, _) = BuildGroup();
        group.DeselectCommand.Should().NotBeNull();
    }

    // ── SelectNextCommand / SelectPreviousCommand are no-ops ─────────────────

    [Fact]
    public void SelectNextCommand_CanExecute_Is_False()
    {
        var (group, _, _) = BuildGroup();
        group.Construct();
        // SelectNext/SelectPrevious are inherited from IComponentVM but always disabled
        // for GroupVM (no Current to navigate through).
        group.SelectNextCommand.CanExecute(null).Should().BeFalse();
    }

    [Fact]
    public void SelectPreviousCommand_CanExecute_Is_False()
    {
        var (group, _, _) = BuildGroup();
        group.Construct();
        group.SelectPreviousCommand.CanExecute(null).Should().BeFalse();
    }
}
