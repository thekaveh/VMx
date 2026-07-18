using System.Collections.Specialized;
using FluentAssertions;
using VMx.Components;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Tests.Components;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Groups;

/// <summary>
/// Unit tests for <see cref="GroupVM{VM}"/> (non-modeled variant).
/// Conformance-level tests live in VMx.Conformance.Tests.
/// </summary>
public class GroupVMTests
{
    private sealed class BlockingTransferParent : IParentCompositeVM
    {
        internal ManualResetEventSlim Entered { get; } = new(false);
        internal ManualResetEventSlim Release { get; } = new(false);
        internal IComponentVM? Child { get; set; }
        public IComponentVM? Owner => null;
        public IParentCompositeVM? OwnerParent => null;
        public bool SupportsChildSelection => false;
        public IComponentVM? CurrentChild => null;
        public void SelectChild(IComponentVM vm) { }
        public void DeselectChild(IComponentVM vm) { }
        public bool ContainsChild(IComponentVM vm) => ReferenceEquals(vm, Child);
        public ParentTransferToken DetachForTransfer(IComponentVM vm)
        {
            Entered.Set();
            if (!Release.Wait(TimeSpan.FromSeconds(2)))
                throw new TimeoutException("transfer was not released");
            return new ParentTransferToken(() => { }, () => { });
        }
    }

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

    [Fact]
    public void Factory_Rejects_Duplicate_Identity_Without_Partial_Membership()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var child = BuildChild(hub, dispatcher);
        var group = GroupVM<ComponentVM<string>>.Builder()
            .Name("root").Services(hub, dispatcher)
            .Children(() => [child, child]).Build();

        Action construct = group.Construct;
        construct.Should().Throw<InvalidOperationException>()
            .WithMessage("*duplicate child identity*");
        group.Snapshot().Should().BeEmpty();
        ((IComponentVMInternals)child).Parent.Should().BeNull();
    }

    [Fact]
    public void Auto_Construct_Hook_Cannot_Reparent_During_Ownership_Transaction()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var source = GroupVM<ComponentVM<string>>.Builder()
            .Name("source").Services(hub, dispatcher).AutoConstructOnAdd(true)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        var destination = GroupVM<ComponentVM<string>>.Builder()
            .Name("destination").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        ComponentVM<string>? child = null;
        child = ComponentVM<string>.Builder().Name("child").Services(hub, dispatcher)
            .Model("m").OnConstruct(() => destination.Add(child!)).Build();
        source.Construct();

        Action add = () => source.Add(child);
        add.Should().Throw<InvalidOperationException>()
            .WithMessage("*ownership transaction is already in progress*");
        source.Snapshot().Should().BeEmpty();
        destination.Snapshot().Should().BeEmpty();
        ((IComponentVMInternals)child).Parent.Should().BeNull();
    }

    [Fact]
    public void Auto_Construct_Hook_Disposal_Aborts_Admission()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var group = GroupVM<ComponentVM<string>>.Builder()
            .Name("root").Services(hub, dispatcher).AutoConstructOnAdd(true)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        var child = ComponentVM<string>.Builder().Name("child").Services(hub, dispatcher)
            .Model("m").OnConstruct(group.Dispose).Build();
        group.Construct();

        Action add = () => group.Add(child);
        add.Should().Throw<InvalidOperationException>().WithMessage("*disposing*");
        group.Snapshot().Should().BeEmpty();
        ((IComponentVMInternals)child).Parent.Should().BeNull();
    }

    [Fact]
    public void Factory_Output_After_Reentrant_Disposal_Is_Rejected()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var late = BuildChild(hub, dispatcher, "late");
        GroupVM<ComponentVM<string>>? group = null;
        group = GroupVM<ComponentVM<string>>.Builder()
            .Name("root")
            .Services(hub, dispatcher)
            .Children(() =>
            {
                group!.Dispose();
                return new[] { late };
            })
            .Build();

        Action construct = group.Construct;
        construct.Should().Throw<ObjectDisposedException>();
        group.Count.Should().Be(0);
        late.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public async Task Concurrent_Admission_Cannot_Escape_Disposal_Snapshot()
    {
        var (group, hub, dispatcher) = BuildGroup();
        var late = BuildChild(hub, dispatcher, "late");
        var blocker = new BlockingTransferParent { Child = late };
        ((IComponentVMInternals)late).SetParent(blocker);
        Exception? failure = null;
        var admission = Task.Run(() =>
        {
            try { group.Add(late); }
            catch (Exception error) { failure = error; }
        });
        (await Task.Run(() => blocker.Entered.Wait(TimeSpan.FromSeconds(2))))
            .Should().BeTrue();

        group.Dispose();
        blocker.Release.Set();
        await admission.WaitAsync(TimeSpan.FromSeconds(2));

        failure.Should().BeOfType<ObjectDisposedException>();
        group.Should().BeEmpty();
        late.Status.Should().Be(ConstructionStatus.Destructed);
    }

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

    [Fact]
    public void Failed_Factory_Population_Rolls_Back_And_Retries()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var childA = BuildChild(hub, dispatcher, "a");
        var childB = BuildChild(hub, dispatcher, "b");
        var calls = 0;

        IEnumerable<ComponentVM<string>> Children()
        {
            calls++;
            yield return childA;
            if (calls == 1)
                throw new InvalidOperationException("transient factory failure");
            yield return childB;
        }

        var group = GroupVM<ComponentVM<string>>.Builder()
            .Name("g")
            .Services(hub, dispatcher)
            .Children(Children)
            .Build();

        Action first = group.Construct;
        first.Should().Throw<InvalidOperationException>()
            .WithMessage("transient factory failure");
        group.Status.Should().Be(ConstructionStatus.Destructed);
        group.Count.Should().Be(0);

        group.Construct();

        calls.Should().Be(2);
        group.Should().Equal(childA, childB);
        group.Status.Should().Be(ConstructionStatus.Constructed);
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

    [Fact]
    public void Dispose_Continues_After_Child_Failure_And_Rethrows_First_Error()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var throwing = new ThrowingDisposeVM();
        var sibling = BuildChild(hub, dispatcher, "sibling");
        var group = GroupVM<IComponentVM>.Builder()
            .Name("root")
            .Services(hub, dispatcher)
            .Children(() => [throwing, sibling])
            .Build();
        group.Construct();

        Action dispose = group.Dispose;

        dispose.Should().Throw<InvalidOperationException>()
            .WithMessage("dispose hook failure");
        throwing.Status.Should().Be(ConstructionStatus.Disposed);
        sibling.Status.Should().Be(ConstructionStatus.Disposed);
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
    public void Construct_Population_Rejects_Reentrant_Membership_Mutation()
    {
        GroupVM<ComponentVM<string>>? group = null;
        ComponentVM<string>? sibling = null;
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var mutating = ComponentVM<string>.Builder()
            .Name("mutating")
            .Services(hub, dispatcher)
            .Model("m")
            .OnConstruct(() => group!.Remove(sibling!))
            .Build();
        sibling = ComponentVM<string>.Builder()
            .Name("sibling")
            .Services(hub, dispatcher)
            .Model("s")
            .Build();
        group = GroupVM<ComponentVM<string>>.Builder()
            .Name("g")
            .Services(hub, dispatcher)
            .Children(() => new[] { mutating, sibling })
            .Build();

        var act = () => group.Construct();

        act.Should().Throw<InvalidOperationException>()
            .WithMessage("*membership transaction*");
        group.Count.Should().Be(0,
            "failed factory population must roll back the complete destination snapshot");
        mutating.Status.Should().Be(ConstructionStatus.Destructed);
        sibling.Status.Should().Be(ConstructionStatus.Destructed);
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
