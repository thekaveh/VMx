using System.Collections.Specialized;
using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Tests.Components;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Composites;

/// <summary>
/// Unit tests for <see cref="CompositeVM{VM}"/> (non-modeled variant).
/// Conformance-level tests live in VMx.Conformance.Tests.
/// </summary>
public class CompositeVMTests
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

    private static (CompositeVM<ComponentVM<string>> composite, TestHub hub, TestDispatcher dispatcher)
        BuildComposite(string name = "root", bool asyncSelection = false)
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .AsyncSelection(asyncSelection)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        return (composite, hub, dispatcher);
    }

    private static ComponentVM<string> BuildChild(TestHub hub, TestDispatcher dispatcher, string name = "child1")
        => ComponentVM<string>.Builder()
            .Name(name).Services(hub, dispatcher).Model("m").Build();

    [Fact]
    public void Factory_Rejects_Duplicate_Identity_Without_Partial_Membership()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var child = BuildChild(hub, dispatcher);
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("root").Services(hub, dispatcher)
            .Children(() => [child, child]).Build();

        Action construct = composite.Construct;
        construct.Should().Throw<InvalidOperationException>()
            .WithMessage("*duplicate child identity*");
        composite.Snapshot().Should().BeEmpty();
        ((IComponentVMInternals)child).Parent.Should().BeNull();
    }

    [Fact]
    public void Auto_Construct_Hook_Cannot_Reparent_During_Ownership_Transaction()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var source = CompositeVM<ComponentVM<string>>.Builder()
            .Name("source").Services(hub, dispatcher).AutoConstructOnAdd(true)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        var destination = CompositeVM<ComponentVM<string>>.Builder()
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
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("root").Services(hub, dispatcher).AutoConstructOnAdd(true)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        var child = ComponentVM<string>.Builder().Name("child").Services(hub, dispatcher)
            .Model("m").OnConstruct(composite.Dispose).Build();
        composite.Construct();

        Action add = () => composite.Add(child);
        add.Should().Throw<InvalidOperationException>().WithMessage("*disposing*");
        composite.Snapshot().Should().BeEmpty();
        ((IComponentVMInternals)child).Parent.Should().BeNull();
    }

    [Fact]
    public async Task Concurrent_Current_Assignments_Leave_One_Current_Flag()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var first = BuildChild(hub, dispatcher, "first");
        var second = BuildChild(hub, dispatcher, "second");
        composite.Add(first);
        composite.Add(second);
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        first.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(first.IsCurrent) && first.IsCurrent)
            {
                entered.Set();
                release.Wait(TimeSpan.FromSeconds(5));
            }
        };

        var selectFirst = Task.Run(() => composite.Current = first);
        entered.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue();
        var selectSecond = Task.Run(() => composite.Current = second);
        await Task.Delay(100);
        selectSecond.IsCompleted.Should().BeFalse();
        release.Set();
        await Task.WhenAll(selectFirst, selectSecond).WaitAsync(TimeSpan.FromSeconds(5));

        composite.Current.Should().BeSameAs(second);
        first.IsCurrent.Should().BeFalse();
        second.IsCurrent.Should().BeTrue();
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

        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("root")
            .Services(hub, dispatcher)
            .Children(Children)
            .Build();

        Action first = composite.Construct;
        first.Should().Throw<InvalidOperationException>()
            .WithMessage("transient factory failure");
        composite.Status.Should().Be(ConstructionStatus.Destructed);
        composite.Count.Should().Be(0);

        composite.Construct();

        calls.Should().Be(2);
        composite.Should().Equal(childA, childB);
        composite.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void Factory_Population_Surfaces_Lifecycle_Compensation_Failure()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var compensated = ComponentVM<string>.Builder()
            .Name("compensated").Services(hub, dispatcher).Model("m")
            .OnDestruct(() => throw new InvalidOperationException("compensation failed"))
            .Build();
        var blocker = ComponentVM<string>.Builder()
            .Name("blocker").Services(hub, dispatcher).Model("m")
            .OnConstruct(() => throw new InvalidOperationException("population failed"))
            .Build();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("root").Services(hub, dispatcher)
            .Children(() => [compensated, blocker]).Build();

        Action construct = composite.Construct;

        var failure = construct.Should().Throw<AggregateException>().Which;
        failure.InnerExceptions.Should().Contain(error => error.Message == "population failed");
        failure.InnerExceptions.Should().Contain(error => error.Message == "compensation failed");
        composite.Snapshot().Should().BeEmpty();
    }

    [Fact]
    public void Factory_Output_After_Reentrant_Disposal_Is_Rejected()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var late = BuildChild(hub, dispatcher, "late");
        CompositeVM<ComponentVM<string>>? composite = null;
        composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("root")
            .Services(hub, dispatcher)
            .Children(() =>
            {
                composite!.Dispose();
                return new[] { late };
            })
            .Build();

        Action construct = composite.Construct;
        construct.Should().Throw<ObjectDisposedException>();
        composite.Count.Should().Be(0);
        late.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public async Task Concurrent_Admission_Cannot_Escape_Disposal_Snapshot()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var late = BuildChild(hub, dispatcher, "late");
        var blocker = new BlockingTransferParent { Child = late };
        ((IComponentVMInternals)late).SetParent(blocker);
        Exception? failure = null;
        var admission = Task.Run(() =>
        {
            try { composite.Add(late); }
            catch (Exception error) { failure = error; }
        });
        (await Task.Run(() => blocker.Entered.Wait(TimeSpan.FromSeconds(2))))
            .Should().BeTrue();

        composite.Dispose();
        blocker.Release.Set();
        await admission.WaitAsync(TimeSpan.FromSeconds(2));

        failure.Should().BeOfType<ObjectDisposedException>();
        composite.Should().BeEmpty();
        late.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // ── Type and identity ────────────────────────────────────────────────────

    [Fact]
    public void Type_Is_Composite()
    {
        var (composite, _, _) = BuildComposite();
        composite.Type.Should().Be(ViewModelType.Composite);
    }

    [Fact]
    public void Name_Is_Set_From_Builder()
    {
        var (composite, _, _) = BuildComposite("root");
        composite.Name.Should().Be("root");
    }

    [Fact]
    public void Initial_Count_Is_Zero()
    {
        var (composite, _, _) = BuildComposite();
        composite.Count.Should().Be(0);
    }

    [Fact]
    public void Initial_Current_Is_Null()
    {
        var (composite, _, _) = BuildComposite();
        composite.Current.Should().BeNull();
    }

    [Fact]
    public void AsyncSelection_Drops_Selection_When_Child_Removed_Before_Dispatch()
    {
        // Regression: with AsyncSelection, a child removed between SelectComponent
        // and the deferred foreground dispatch must NOT become Current
        // (spec/06 §3 — a non-null Current is always a member of the collection).
        var (composite, hub, dispatcher) = BuildComposite(asyncSelection: true);
        var vmA = BuildChild(hub, dispatcher, "vmA");
        composite.Add(vmA);
        composite.Construct();

        composite.SelectComponent(vmA);                 // deferred
        composite.Remove(vmA);                          // removed before dispatch
        dispatcher.ForegroundScheduler.AdvanceBy(1);    // deliver

        composite.Current.Should().BeNull("a removed child must not become Current");
        vmA.IsCurrent.Should().BeFalse("the removed child's IsCurrent must not be set");
    }

    // ── IList<VM>: Add ───────────────────────────────────────────────────────

    [Fact]
    public void Add_Increases_Count()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Count.Should().Be(1);
    }

    [Fact]
    public void Add_Sets_Child_Parent()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        child.Parent.Should().BeSameAs(composite);
    }

    [Fact]
    public void Add_Emits_CollectionChanged_Add()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        NotifyCollectionChangedEventArgs? evt = null;
        composite.CollectionChanged += (_, e) => evt = e;

        composite.Add(child);

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
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Remove(child);
        composite.Count.Should().Be(0);
    }

    [Fact]
    public void Remove_Clears_Child_Parent()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Remove(child);
        child.Parent.Should().BeNull();
    }

    [Fact]
    public void Remove_Emits_CollectionChanged_Remove()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        NotifyCollectionChangedEventArgs? evt = null;
        composite.CollectionChanged += (_, e) => evt = e;

        composite.Remove(child);

        evt.Should().NotBeNull();
        evt!.Action.Should().Be(NotifyCollectionChangedAction.Remove);
        evt.OldItems![0].Should().BeSameAs(child);
        evt.OldStartingIndex.Should().Be(0);
    }

    [Fact]
    public void Remove_Returns_False_For_Missing_Item()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Remove(child).Should().BeFalse();
    }

    // ── IList<VM>: Insert ────────────────────────────────────────────────────

    [Fact]
    public void Insert_At_Index_Emits_CollectionChanged()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);

        NotifyCollectionChangedEventArgs? evt = null;
        composite.CollectionChanged += (_, e) => evt = e;
        composite.Insert(0, c2);

        composite[0].Should().BeSameAs(c2);
        composite[1].Should().BeSameAs(c1);
        evt!.Action.Should().Be(NotifyCollectionChangedAction.Add);
        evt.NewStartingIndex.Should().Be(0);
    }

    // ── IList<VM>: Clear ─────────────────────────────────────────────────────

    [Fact]
    public void Clear_Removes_All_Items_And_Emits_Reset()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        composite.Add(BuildChild(hub, dispatcher, "c1"));
        composite.Add(BuildChild(hub, dispatcher, "c2"));
        NotifyCollectionChangedEventArgs? evt = null;
        composite.CollectionChanged += (_, e) => evt = e;

        composite.Clear();

        composite.Count.Should().Be(0);
        evt!.Action.Should().Be(NotifyCollectionChangedAction.Reset);
    }

    [Fact]
    public void Clear_When_Child_Is_Current_Clears_IsCurrent_And_Fires_Hub_Message()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();
        composite.Current = child;

        var propChangedNames = new List<string>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm)
                propChangedNames.Add(pcm.PropertyName);
        });
        var raisedProps = new List<string>();
        ((System.ComponentModel.INotifyPropertyChanged)composite).PropertyChanged += (_, e) =>
        {
            if (e.PropertyName is not null) raisedProps.Add(e.PropertyName);
        };

        composite.Clear();

        child.IsCurrent.Should().BeFalse("Clear must deselect the previously-current child");
        composite.Current.Should().BeNull();
        raisedProps.Should().Contain("Current", "PropertyChanged(\"Current\") must fire");
        propChangedNames.Should().Contain("Current", "hub must publish PropertyChangedMessage for \"Current\"");
    }

    // ── Current / Selection ──────────────────────────────────────────────────

    [Fact]
    public void Current_Can_Be_Set_To_Child()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        composite.Current = child;

        composite.Current.Should().BeSameAs(child);
    }

    [Fact]
    public void Current_Set_Updates_IsCurrent_On_Child()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        composite.Current = child;

        child.IsCurrent.Should().BeTrue();
    }

    [Fact]
    public void Current_Set_Clears_IsCurrent_On_Previous()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);
        composite.Add(c2);
        composite.Construct();

        composite.Current = c1;
        composite.Current = c2;

        c1.IsCurrent.Should().BeFalse();
        c2.IsCurrent.Should().BeTrue();
    }

    [Fact]
    public void Current_Set_To_Null_Is_Legal()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();
        composite.Current = child;

        composite.Current = null;

        composite.Current.Should().BeNull();
        child.IsCurrent.Should().BeFalse();
    }

    [Fact]
    public void Current_Set_To_Non_Child_Raises()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        composite.Construct();
        var foreign = BuildChild(hub, dispatcher, "foreign");

        var act = () => composite.Current = foreign;

        act.Should().Throw<InvalidOperationException>();
    }

    [Fact]
    public void Current_Set_Emits_PropertyChangedMessage_On_Hub()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        var propMessages = new List<string>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm)
                propMessages.Add(pcm.PropertyName);
        });

        composite.Current = child;

        propMessages.Should().Contain("Current");
    }

    // ── SelectComponent / DeselectComponent / CanSelectComponent ────────────

    [Fact]
    public void SelectComponent_Sets_Current()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        composite.SelectComponent(child);

        composite.Current.Should().BeSameAs(child);
    }

    [Fact]
    public void SelectComponent_Raises_When_CanSelect_False()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var foreign = BuildChild(hub, dispatcher, "foreign");
        composite.Construct();

        var act = () => composite.SelectComponent(foreign);

        act.Should().Throw<InvalidOperationException>();
    }

    [Fact]
    public void DeselectComponent_Clears_Current()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();
        composite.Current = child;

        composite.DeselectComponent(child);

        composite.Current.Should().BeNull();
    }

    [Fact]
    public void DeselectComponent_Raises_When_Not_Current()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);
        composite.Add(c2);
        composite.Construct();
        composite.Current = c1;

        var act = () => composite.DeselectComponent(c2);

        act.Should().Throw<InvalidOperationException>();
        composite.Current.Should().BeSameAs(c1);
    }

    [Fact]
    public void CanSelectComponent_True_For_Constructed_Child()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        composite.CanSelectComponent(child).Should().BeTrue();
    }

    [Fact]
    public void CanSelectComponent_False_For_Non_Child()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var foreign = BuildChild(hub, dispatcher, "foreign");
        composite.Construct();

        composite.CanSelectComponent(foreign).Should().BeFalse();
    }

    [Fact]
    public void CanSelectComponent_False_For_Unconstructed_Child()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        // Composite is NOT constructed — child remains Destructed.

        composite.CanSelectComponent(child).Should().BeFalse();
    }

    // ── Lifecycle: Construct ─────────────────────────────────────────────────

    [Fact]
    public void Construct_With_Children_Factory_Populates_And_Constructs_Children()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("root")
            .Services(hub, dispatcher)
            .Children(() =>
            [
                BuildChild(hub, dispatcher, "c1"),
                BuildChild(hub, dispatcher, "c2"),
            ])
            .Build();

        composite.Construct();

        composite.Count.Should().Be(2);
        composite[0].Status.Should().Be(ConstructionStatus.Constructed);
        composite[1].Status.Should().Be(ConstructionStatus.Constructed);
        composite.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public async Task Construct_Remains_In_Progress_Until_Background_Child_Is_Constructed()
    {
        var hub = new TestHub();
        var dispatcher = new RealThreadDispatcher();
        using var started = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        var child = ComponentVM<string>.Builder()
            .Name("child")
            .Services(hub, dispatcher)
            .Model("m")
            .Background(true)
            .OnConstruct(() =>
            {
                started.Set();
                release.Wait();
            })
            .Build();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("root")
            .Services(hub, dispatcher)
            .Children(() => [child])
            .Build();

        composite.Construct();
        started.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue();
        var parentStatusWhileChildRuns = composite.Status;
        release.Set();
        await Task.WhenAll(dispatcher.PendingWork);
        SpinWait.SpinUntil(
            () => composite.Status == ConstructionStatus.Constructed,
            TimeSpan.FromSeconds(5)).Should().BeTrue();

        parentStatusWhileChildRuns.Should().Be(ConstructionStatus.Constructing,
            "a container cannot settle before its background child");
        child.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // ── Lifecycle: Destruct ──────────────────────────────────────────────────

    [Fact]
    public void Destruct_Sets_Current_To_Null_First()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();
        composite.Current = child;

        composite.Destruct();

        composite.Current.Should().BeNull();
        composite.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public void Destruct_Destructs_All_Children()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);
        composite.Add(c2);
        composite.Construct();

        composite.Destruct();

        c1.Status.Should().Be(ConstructionStatus.Destructed);
        c2.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public async Task Destruct_Remains_In_Progress_Until_Background_Child_Is_Destructed()
    {
        var hub = new TestHub();
        var dispatcher = new RealThreadDispatcher();
        using var started = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        var child = ComponentVM<string>.Builder()
            .Name("child")
            .Services(hub, dispatcher)
            .Model("m")
            .Background(true)
            .OnDestruct(() =>
            {
                started.Set();
                release.Wait();
            })
            .Build();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("root")
            .Services(hub, dispatcher)
            .Children(() => [child])
            .Build();
        await composite.ConstructAsync();

        composite.Destruct();
        started.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue();
        var parentStatusWhileChildRuns = composite.Status;
        release.Set();
        await Task.WhenAll(dispatcher.PendingWork);
        SpinWait.SpinUntil(
            () => composite.Status == ConstructionStatus.Destructed,
            TimeSpan.FromSeconds(5)).Should().BeTrue();

        parentStatusWhileChildRuns.Should().Be(ConstructionStatus.Destructing,
            "a container cannot settle before its background child");
        child.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public async Task Reconstruct_Waits_For_Background_Child_Destruct_Then_Construct()
    {
        var hub = new TestHub();
        var dispatcher = new RealThreadDispatcher();
        using var destructStarted = new ManualResetEventSlim();
        using var destructRelease = new ManualResetEventSlim();
        using var reconstructStarted = new ManualResetEventSlim();
        using var reconstructRelease = new ManualResetEventSlim();
        var constructCalls = 0;
        var child = ComponentVM<string>.Builder()
            .Name("child")
            .Services(hub, dispatcher)
            .Model("m")
            .Background(true)
            .OnConstruct(() =>
            {
                if (Interlocked.Increment(ref constructCalls) == 2)
                {
                    reconstructStarted.Set();
                    reconstructRelease.Wait();
                }
            })
            .OnDestruct(() =>
            {
                destructStarted.Set();
                destructRelease.Wait();
            })
            .Build();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("root")
            .Services(hub, dispatcher)
            .Children(() => [child])
            .Build();
        await composite.ConstructAsync();

        Task reconstruct;
        try
        {
            reconstruct = composite.ReconstructAsync();
            destructStarted.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue();
            composite.Status.Should().Be(ConstructionStatus.Destructing);

            destructRelease.Set();
            reconstructStarted.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue();
            composite.Status.Should().Be(ConstructionStatus.Constructing);

            reconstructRelease.Set();
            var completed = await Task.WhenAny(reconstruct, Task.Delay(TimeSpan.FromSeconds(5)));
            completed.Should().BeSameAs(reconstruct);
            await reconstruct;
        }
        finally
        {
            destructRelease.Set();
            reconstructRelease.Set();
        }

        child.Status.Should().Be(ConstructionStatus.Constructed);
        composite.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // ── Lifecycle: Dispose cascade (LIFE-013) ────────────────────────────────

    [Fact]
    public void Dispose_Disposes_All_Children()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);
        composite.Add(c2);
        composite.Construct();

        composite.Dispose();

        c1.Status.Should().Be(ConstructionStatus.Disposed);
        c2.Status.Should().Be(ConstructionStatus.Disposed);
        composite.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public void Dispose_Closes_Child_Admission_Before_Taking_The_Snapshot()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher, "child");
        var late = BuildChild(hub, dispatcher, "late");
        Exception? admissionError = null;
        using var subscription = hub.Messages.Subscribe(message =>
        {
            if (message is ConstructionStatusChangedMessage
                { SenderName: "child", Status: ConstructionStatus.Disposed })
            {
                try { composite.Add(late); }
                catch (Exception error) { admissionError = error; }
            }
        });
        composite.Add(child);

        composite.Dispose();

        admissionError.Should().BeOfType<ObjectDisposedException>();
        composite.Should().ContainSingle().Which.Should().BeSameAs(child);
        late.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public void Dispose_Continues_After_Child_Failure_And_Rethrows_First_Error()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var throwing = new ThrowingDisposeVM();
        var sibling = BuildChild(hub, dispatcher, "sibling");
        var composite = CompositeVM<IComponentVM>.Builder()
            .Name("root")
            .Services(hub, dispatcher)
            .Children(() => [throwing, sibling])
            .Build();
        composite.Construct();

        Action dispose = composite.Dispose;

        dispose.Should().Throw<InvalidOperationException>()
            .WithMessage("dispose hook failure");
        throwing.Status.Should().Be(ConstructionStatus.Disposed);
        sibling.Status.Should().Be(ConstructionStatus.Disposed);
        composite.Status.Should().Be(ConstructionStatus.Disposed);
    }

    // ── AsyncSelection ───────────────────────────────────────────────────────

    [Fact]
    public void AsyncSelection_Does_Not_Change_Current_Synchronously()
    {
        var (composite, hub, dispatcher) = BuildComposite(asyncSelection: true);
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        composite.SelectComponent(child);

        // Before advancing the scheduler: Current should still be null.
        composite.Current.Should().BeNull();
    }

    [Fact]
    public void AsyncSelection_Changes_Current_After_Scheduler_Advance()
    {
        var (composite, hub, dispatcher) = BuildComposite(asyncSelection: true);
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        composite.SelectComponent(child);
        dispatcher.AdvanceAll();

        composite.Current.Should().BeSameAs(child);
    }

    // ── Indexer ──────────────────────────────────────────────────────────────

    [Fact]
    public void Indexer_Returns_Correct_Child()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);
        composite.Add(c2);

        composite[0].Should().BeSameAs(c1);
        composite[1].Should().BeSameAs(c2);
    }

    [Fact]
    public void Construct_Population_Rejects_Reentrant_Membership_Mutation()
    {
        CompositeVM<ComponentVM<string>>? composite = null;
        ComponentVM<string>? sibling = null;
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var mutating = ComponentVM<string>.Builder()
            .Name("mutating")
            .Services(hub, dispatcher)
            .Model("m")
            .OnConstruct(() => composite!.Remove(sibling!))
            .Build();
        sibling = ComponentVM<string>.Builder()
            .Name("sibling")
            .Services(hub, dispatcher)
            .Model("s")
            .Build();
        composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("c")
            .Services(hub, dispatcher)
            .Children(() => new[] { mutating, sibling })
            .Build();

        var act = () => composite.Construct();

        act.Should().Throw<InvalidOperationException>()
            .WithMessage("*membership transaction*");
        composite.Count.Should().Be(0,
            "failed factory population must roll back the complete destination snapshot");
        mutating.Status.Should().Be(ConstructionStatus.Destructed);
        sibling.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public void Indexer_Setter_Replacing_Current_Clears_Current()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var oldChild = BuildChild(hub, dispatcher, "old");
        var newChild = BuildChild(hub, dispatcher, "new");
        composite.Add(oldChild);
        oldChild.Construct();
        composite.Current = oldChild;

        composite[0] = newChild;

        composite.Current.Should().BeNull(
            "current must be cleared when the slot holding it is replaced");
        composite[0].Should().BeSameAs(newChild);
        oldChild.Parent.Should().BeNull();
        newChild.Parent.Should().BeSameAs(composite);
    }

    [Fact]
    public void Indexer_Setter_Replacing_Non_Current_Leaves_Current_Intact()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var other = BuildChild(hub, dispatcher, "other");
        var sticky = BuildChild(hub, dispatcher, "sticky");
        var replacement = BuildChild(hub, dispatcher, "replacement");
        composite.Add(other);
        composite.Add(sticky);
        sticky.Construct();
        composite.Current = sticky;

        composite[0] = replacement;  // replace `other`, not `sticky`

        composite.Current.Should().BeSameAs(sticky,
            "current must survive when a different slot is replaced");
    }

    // ── Contains / IndexOf ────────────────────────────────────────────────────

    [Fact]
    public void Contains_Returns_True_For_Added_Child()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Contains(child).Should().BeTrue();
    }

    [Fact]
    public void IndexOf_Returns_Correct_Index()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);
        composite.Add(c2);
        composite.IndexOf(c2).Should().Be(1);
    }

    // ── Builder validation ───────────────────────────────────────────────────

    [Fact]
    public void Builder_Throws_When_Name_Missing()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var act = () => CompositeVM<ComponentVM<string>>.Builder()
            .Services(hub, dispatcher).Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>();
    }

    [Fact]
    public void Builder_Throws_When_Services_Missing()
    {
        var act = () => CompositeVM<ComponentVM<string>>.Builder()
            .Name("x").Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>();
    }

    [Fact]
    public void Builder_Throws_When_Children_Missing()
    {
        // Per spec/10-builders.md §3 + ADR-0035: non-modeled CompositeVM<VM>
        // requires a Children(() => ...) factory. For an empty composite,
        // pass Children(() => Array.Empty<VM>()) explicitly.
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var act = () => CompositeVM<ComponentVM<string>>.Builder()
            .Name("x")
            .Services(hub, dispatcher)
            .Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>()
            .WithMessage("*Children*");
    }
}
