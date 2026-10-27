using System.Collections.Specialized;
using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for CompositeVM covering COMP-001..011 and LIFE-013.
/// See spec/06-composite-vm.md and spec/12-conformance.md.
/// </summary>
public class CompositeVMConformanceTests
{
    private sealed class EqualByNameVM(
        string name,
        TestHub hub,
        TestDispatcher dispatcher)
        : ComponentVMBase(name, "", hub, dispatcher, null, null)
    {
        public override ViewModelType Type => ViewModelType.Component;

        public override bool Equals(object? obj) =>
            obj is EqualByNameVM other && other.Name == Name;

        public override int GetHashCode() => Name.GetHashCode(StringComparison.Ordinal);
    }

    private sealed class DisposeFailingVM(
        string name,
        TestHub hub,
        TestDispatcher dispatcher,
        Action? onConstruct = null)
        : ComponentVMBase(name, "", hub, dispatcher, onConstruct, null)
    {
        public override ViewModelType Type => ViewModelType.Component;

        protected override void OnDispose() =>
            throw new InvalidOperationException("dispose failure");
    }

    private sealed class DisposeFailingComposite(
        string name,
        TestHub hub,
        TestDispatcher dispatcher,
        bool autoConstructOnAdd = false)
        : CompositeVMBase<ComponentVM<string>>(
            name, "", hub, dispatcher, false, autoConstructOnAdd,
            null, null, null, null)
    {
        protected override void OnDispose()
        {
            base.OnDispose();
            throw new InvalidOperationException("destination dispose failure");
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

    private static ComponentVM<string> BuildChild(
        TestHub hub, TestDispatcher dispatcher, string name = "child")
        => ComponentVM<string>.Builder()
            .Name(name).Services(hub, dispatcher).Model("m").Build();

    // ── COMP-001 — Add emits CollectionChanged(action=Add) ───────────────────

    /// <summary>
    /// COMP-001: Add emits CollectionChanged with action=Add, newItems=[vm], newIndex=0.
    /// </summary>
    [Fact, Trait("Conformance", "COMP-001")]
    public void COMP_001_Add_Emits_CollectionChanged_Add()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        composite.Construct();
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

    // ── COMP-002 — Remove emits CollectionChanged(action=Remove) ─────────────

    /// <summary>
    /// COMP-002: Remove emits CollectionChanged with action=Remove, oldItems=[vm], oldIndex=0.
    /// </summary>
    [Fact, Trait("Conformance", "COMP-002")]
    public void COMP_002_Remove_Emits_CollectionChanged_Remove()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);

        NotifyCollectionChangedEventArgs? evt = null;
        composite.CollectionChanged += (_, e) => evt = e;

        composite.Remove(child);

        evt.Should().NotBeNull();
        evt!.Action.Should().Be(NotifyCollectionChangedAction.Remove);
        evt.OldItems.Should().NotBeNull();
        evt.OldItems![0].Should().BeSameAs(child);
        evt.OldStartingIndex.Should().Be(0);
    }

    // ── COMP-003 — select_component sets Current + IsCurrent + PropertyChanged ─

    /// <summary>
    /// COMP-003: select_component(vm) sets composite.Current==vm, vm.IsCurrent==true,
    /// emits PropertyChangedMessage("Current") and PropertyChangedMessage("IsCurrent").
    /// </summary>
    [Fact, Trait("Conformance", "COMP-003")]
    public void COMP_003_SelectComponent_Sets_Current_And_IsCurrent()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        var currentMessages = new List<string>();
        var isCurrentMessages = new List<IMessage>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm)
                currentMessages.Add(pcm.PropertyName);
            // Spec COMP-003: the IsCurrent PropertyChangedMessage carries Sender == vm.
            if (m is IPropertyChangedMessage<IComponentVM> pcm2 &&
                pcm2.PropertyName == nameof(ComponentVMBase.IsCurrent) &&
                ReferenceEquals(pcm2.SenderObject, child))
                isCurrentMessages.Add(m);
        });

        composite.SelectComponent(child);

        composite.Current.Should().BeSameAs(child);
        child.IsCurrent.Should().BeTrue();
        currentMessages.Should().Contain("Current");
        isCurrentMessages.Should().HaveCount(1);
    }

    // ── COMP-004 — Construct waits until all children Constructed ─────────────

    /// <summary>
    /// COMP-004: after composite.construct() returns, every child has Status==Constructed.
    /// </summary>
    [Fact, Trait("Conformance", "COMP-004")]
    public void COMP_004_Construct_Waits_Until_All_Children_Constructed()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);
        composite.Add(c2);

        composite.Construct();

        c1.Status.Should().Be(ConstructionStatus.Constructed);
        c2.Status.Should().Be(ConstructionStatus.Constructed);
        composite.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // ── COMP-005 — Destruct waits until all children Destructed; Current=null ──

    /// <summary>
    /// COMP-005: after composite.destruct() returns:
    ///   - composite.Current == null
    ///   - every child has Status == Destructed
    ///   - composite.Status == Destructed
    /// </summary>
    [Fact, Trait("Conformance", "COMP-005")]
    public void COMP_005_Destruct_Clears_Current_And_Destructs_All_Children()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);
        composite.Add(c2);
        composite.Construct();
        composite.Current = c1;

        composite.Destruct();

        composite.Current.Should().BeNull();
        c1.Status.Should().Be(ConstructionStatus.Destructed);
        c2.Status.Should().Be(ConstructionStatus.Destructed);
        composite.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // ── COMP-006 — IsCurrent change on previously-Current child dispatches on foreground

    /// <summary>
    /// COMP-006: when Current changes, IsCurrent change on previously-Current child
    /// is observable on the foreground scheduler.
    /// The message is emitted synchronously but can be observed via ObserveOn(foreground).
    /// </summary>
    [Fact, Trait("Conformance", "COMP-006")]
    public void COMP_006_IsCurrent_Change_On_Previous_Dispatches_On_Foreground()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("root").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        var vmA = BuildChild(hub, dispatcher, "vmA");
        var vmB = BuildChild(hub, dispatcher, "vmB");
        composite.Add(vmA);
        composite.Add(vmB);
        composite.Construct();
        composite.Current = vmA;

        // Observe IsCurrent changes for vmA on the foreground scheduler.
        var observedOnForeground = new List<string>();
        hub.Messages
            .ObserveOn(dispatcher.Foreground)
            .Subscribe(m =>
            {
                if (m is IPropertyChangedMessage<IComponentVM> pcm
                    && pcm.PropertyName == "IsCurrent"
                    && ReferenceEquals(pcm.SenderObject, vmA))
                    observedOnForeground.Add("vmA.IsCurrent");
            });

        // Changing current: vmA's IsCurrent will flip to false.
        composite.Current = vmB;

        // Before advancing scheduler: messages not yet delivered to our foreground observer.
        // Advance to deliver.
        dispatcher.ForegroundScheduler.AdvanceBy(1);

        observedOnForeground.Should().Contain("vmA.IsCurrent",
            "IsCurrent change on previously-Current child should be observable on foreground scheduler");
    }

    // ── COMP-007 — Modeled composite maps model factory to children ───────────

    /// <summary>
    /// COMP-007: after construct() on a CompositeVM&lt;M,VM&gt;:
    ///   - composite.Count == 2
    ///   - composite[0].Model == m1, composite[1].Model == m2
    /// </summary>
    [Fact, Trait("Conformance", "COMP-007")]
    public void COMP_007_Modeled_Composite_Maps_Model_Factory_To_Children()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var m1 = "model1";
        var m2 = "model2";

        var composite = CompositeVMOfM<string, ComponentVM<string>>.Builder()
            .Name("root").Services(hub, dispatcher)
            .ChildrenModels(() => [m1, m2])
            .ChildModelToChildViewModel(m => ComponentVM<string>.Builder()
                .Name(m).Services(hub, dispatcher).Model(m).Build())
            .Build();

        composite.Construct();

        composite.Count.Should().Be(2);
        composite[0].Model.Should().Be(m1);
        composite[1].Model.Should().Be(m2);
    }

    // ── COMP-008 — can_select_component returns false for non-children ─────────

    /// <summary>
    /// COMP-008: can_select_component(vmB) returns false when vmB is not in the composite.
    /// Calling select_component(vmB) raises.
    /// </summary>
    [Fact, Trait("Conformance", "COMP-008")]
    public void COMP_008_CanSelectComponent_False_For_Non_Children()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var vmA = BuildChild(hub, dispatcher, "vmA");
        composite.Add(vmA);
        composite.Construct();

        var vmB = BuildChild(hub, dispatcher, "vmB");

        composite.CanSelectComponent(vmB).Should().BeFalse();

        var act = () => composite.SelectComponent(vmB);
        act.Should().Throw<InvalidOperationException>();
    }

    // ── COMP-009 — Current setter raises on non-child assignment ──────────────

    /// <summary>
    /// COMP-009: assigning a non-child to Current raises; Current remains null.
    /// </summary>
    [Fact, Trait("Conformance", "COMP-009")]
    public void COMP_009_Current_Setter_Raises_On_Non_Child_Assignment()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var vmA = BuildChild(hub, dispatcher, "vmA");
        composite.Add(vmA);
        composite.Construct();

        var vmB = BuildChild(hub, dispatcher, "vmB");

        var act = () => composite.Current = vmB;
        act.Should().Throw<InvalidOperationException>();
        composite.Current.Should().BeNull();
    }

    // ── COMP-010 — AsyncSelection dispatches Current change via foreground ─────

    /// <summary>
    /// COMP-010: with AsyncSelection(true), select_component does NOT change Current
    /// synchronously; advancing the foreground scheduler completes the dispatch.
    /// </summary>
    [Fact, Trait("Conformance", "COMP-010")]
    public void COMP_010_AsyncSelection_Dispatches_Via_Foreground()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("root").Services(hub, dispatcher)
            .AsyncSelection(true)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        var vmA = BuildChild(hub, dispatcher, "vmA");
        composite.Add(vmA);
        composite.Construct();

        // Act: select synchronously — Current should NOT change yet.
        composite.SelectComponent(vmA);

        composite.Current.Should().BeNull("Current must not change synchronously with AsyncSelection");

        // After advancing the foreground scheduler, Current is set.
        dispatcher.ForegroundScheduler.AdvanceBy(1);

        composite.Current.Should().BeSameAs(vmA);
    }

    // ── COMP-011 — deselect_component raises when vm is not Current ───────────

    /// <summary>
    /// COMP-011: deselect_component(vmB) raises when vmB is not Current.
    /// </summary>
    [Fact, Trait("Conformance", "COMP-011")]
    public void COMP_011_DeselectComponent_Raises_When_Not_Current()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var vmA = BuildChild(hub, dispatcher, "vmA");
        var vmB = BuildChild(hub, dispatcher, "vmB");
        composite.Add(vmA);
        composite.Add(vmB);
        composite.Construct();
        composite.Current = vmA;

        var act = () => composite.DeselectComponent(vmB);
        act.Should().Throw<InvalidOperationException>();
        composite.Current.Should().BeSameAs(vmA);
    }

    // ── LIFE-013 — Dispose cascade depth-first ────────────────────────────────

    /// <summary>
    /// LIFE-013: dispose on a parent disposes children depth-first.
    /// Build a 2-level composite tree; dispose root; every descendant = Disposed.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-013")]
    public void LIFE_013_Dispose_Cascade()
    {
        // Build a 2-level composite tree:
        //   root (CompositeVM)
        //     ├── child1 (CompositeVM)
        //     │     ├── grandchild1a
        //     │     └── grandchild1b
        //     └── child2 (CompositeVM)
        //           └── grandchild2a

        var hub = new TestHub();
        var dispatcher = new TestDispatcher();

        ComponentVM<string> MakeLeaf(string name)
            => ComponentVM<string>.Builder()
                .Name(name).Services(hub, dispatcher).Model("m").Build();

        // Build root as CompositeVM<IComponentVM> so it can hold inner composites.
        var grandchild1a = MakeLeaf("gc1a");
        var grandchild1b = MakeLeaf("gc1b");
        var grandchild2a = MakeLeaf("gc2a");

        var root = CompositeVM<IComponentVM>.Builder()
            .Name("root").Services(hub, dispatcher)
            .Children(() => Array.Empty<IComponentVM>())
            .Build();

        var child1 = CompositeVM<ComponentVM<string>>.Builder()
            .Name("child1").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        child1.Add(grandchild1a);
        child1.Add(grandchild1b);

        var child2 = CompositeVM<ComponentVM<string>>.Builder()
            .Name("child2").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        child2.Add(grandchild2a);

        root.Add(child1);
        root.Add(child2);

        // Construct the full tree.
        grandchild1a.Construct();
        grandchild1b.Construct();
        grandchild2a.Construct();
        child1.Construct();
        child2.Construct();
        root.Construct();

        // Record disposal order.
        var disposalOrder = new List<string>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IConstructionStatusChangedMessage csm &&
                csm.Status == ConstructionStatus.Disposed)
                disposalOrder.Add(csm.SenderName);
        });

        // Act: dispose root.
        root.Dispose();

        // Assert: every node is disposed.
        grandchild1a.Status.Should().Be(ConstructionStatus.Disposed);
        grandchild1b.Status.Should().Be(ConstructionStatus.Disposed);
        grandchild2a.Status.Should().Be(ConstructionStatus.Disposed);
        child1.Status.Should().Be(ConstructionStatus.Disposed);
        child2.Status.Should().Be(ConstructionStatus.Disposed);
        root.Status.Should().Be(ConstructionStatus.Disposed);

        // Assert depth-first: grandchildren appear before their parent,
        // and children appear before root.
        disposalOrder.IndexOf("gc1a").Should().BeLessThan(disposalOrder.IndexOf("child1"));
        disposalOrder.IndexOf("gc1b").Should().BeLessThan(disposalOrder.IndexOf("child1"));
        disposalOrder.IndexOf("gc2a").Should().BeLessThan(disposalOrder.IndexOf("child2"));
        disposalOrder.IndexOf("child1").Should().BeLessThan(disposalOrder.IndexOf("root"));
        disposalOrder.IndexOf("child2").Should().BeLessThan(disposalOrder.IndexOf("root"));
    }

    /// <summary>
    /// LIFE-013: a failing child disposal hook does not stop later siblings
    /// or the parent's teardown; the first failure propagates afterwards.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-013")]
    public void LIFE_013_Child_Dispose_Failure_Completes_Siblings_And_Parent_First()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var failing = new DisposeFailingVM("failing", hub, dispatcher);
        var later = new DisposeFailingVM("later", hub, dispatcher);
        var sibling = ComponentVM<string>.Builder()
            .Name("sibling").Services(hub, dispatcher).Model("m").Build();
        var root = CompositeVM<IComponentVM>.Builder()
            .Name("root").Services(hub, dispatcher)
            .Children(() => new IComponentVM[] { failing, sibling, later })
            .Build();
        root.Construct();
        failing.Status.Should().Be(ConstructionStatus.Constructed);

        var dispose = () => root.Dispose();

        dispose.Should().Throw<InvalidOperationException>().WithMessage("dispose failure");
        failing.Status.Should().Be(ConstructionStatus.Disposed);
        sibling.Status.Should().Be(ConstructionStatus.Disposed);
        later.Status.Should().Be(ConstructionStatus.Disposed);
        root.Status.Should().Be(ConstructionStatus.Disposed);
    }

    /// <summary>
    /// LIFE-013: a failing parent disposal hook still lets every child finish
    /// disposal before the failure propagates.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-013")]
    public void LIFE_013_Parent_Dispose_Hook_Failure_Still_Disposes_Children()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var parent = new DisposeFailingComposite("parent", hub, dispatcher);
        var a = ComponentVM<string>.Builder().Name("a").Services(hub, dispatcher).Model("a").Build();
        var b = ComponentVM<string>.Builder().Name("b").Services(hub, dispatcher).Model("b").Build();
        parent.Add(a);
        parent.Add(b);
        parent.Construct();

        var dispose = () => parent.Dispose();

        dispose.Should().Throw<InvalidOperationException>().WithMessage("destination dispose failure");
        a.Status.Should().Be(ConstructionStatus.Disposed);
        b.Status.Should().Be(ConstructionStatus.Disposed);
        parent.Status.Should().Be(ConstructionStatus.Disposed);
    }

    // ── COMP-025 — Current(selector) drives initial-current during construct ──

    /// <summary>
    /// COMP-025: Current(selector) runs once during construct, after all children
    /// reach Constructed and before the composite reaches Constructed. The
    /// selector's return value becomes Current. See spec/06 §3.2 and ADR-0042.
    /// </summary>
    [Fact, Trait("Conformance", "COMP-025")]
    public void COMP_025_Current_Selector_Drives_Initial_Selection()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var a = BuildChild(hub, dispatcher, "a");
        var b = BuildChild(hub, dispatcher, "b");
        var c = BuildChild(hub, dispatcher, "c");

        var selectorCalls = 0;
        CompositeVM<ComponentVM<string>>? self = null;
        var childStatusesInSelector = new List<ConstructionStatus>();
        var compositeStatusInSelector = ConstructionStatus.Disposed;
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(hub, dispatcher)
            .Children(() => new[] { a, b, c })
            .Current(xs =>
            {
                selectorCalls++;
                childStatusesInSelector.AddRange(xs.Select(x => x.Status));
                compositeStatusInSelector = self!.Status;
                return xs.Skip(1).First();
            })
            .Build();
        self = composite;

        composite.Construct();

        composite.Current.Should().BeSameAs(b);
        selectorCalls.Should().Be(1, "the selector must run exactly once during construct");
        childStatusesInSelector.Should().Equal(
            [ConstructionStatus.Constructed, ConstructionStatus.Constructed, ConstructionStatus.Constructed],
            "the selector runs after every child reached Constructed");
        compositeStatusInSelector.Should().Be(ConstructionStatus.Constructing,
            "the selector runs before the composite reaches Constructed");

        // A null-returning selector leaves Current null and publishes no
        // PropertyChangedMessage("Current").
        var hub2 = new TestHub();
        var a2 = BuildChild(hub2, dispatcher, "a");
        var b2 = BuildChild(hub2, dispatcher, "b");
        var c2 = BuildChild(hub2, dispatcher, "c");
        var propNames = new List<string>();
        hub2.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm)
                propNames.Add(pcm.PropertyName);
        });

        var composite2 = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite2")
            .Services(hub2, dispatcher)
            .Children(() => new[] { a2, b2, c2 })
            .Current(_ => (ComponentVM<string>?)null)
            .Build();

        composite2.Construct();

        composite2.Current.Should().BeNull();
        propNames.Should().NotContain("Current",
            "a null-returning Current selector must publish no PropertyChangedMessage(\"Current\")");
    }

    // ── COMP-026 — OnCurrentChanged fires after each Current transition ──────

    /// <summary>
    /// COMP-026: OnCurrentChanged(callback) is invoked synchronously after every
    /// Current transition. Receives the new Current value (may be null). See
    /// spec/06 §3.2 and ADR-0042.
    /// </summary>
    [Fact, Trait("Conformance", "COMP-026")]
    public void COMP_026_OnCurrentChanged_Fires_After_Each_Change()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var a = BuildChild(hub, dispatcher, "a");
        var b = BuildChild(hub, dispatcher, "b");
        var c = BuildChild(hub, dispatcher, "c");
        var observed = new List<ComponentVM<string>?>();
        var order = new List<string>();
        CompositeVM<ComponentVM<string>>? composite = null;

        composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(hub, dispatcher)
            .Children(() => new[] { a, b, c })
            .OnCurrentChanged(vm =>
            {
                observed.Add(vm);
                order.Add($"callback:{vm?.Name ?? "null"}");
            })
            .Build();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm
                && pcm.PropertyName == "Current"
                && ReferenceEquals(pcm.SenderObject, composite))
            {
                order.Add($"message:{composite!.Current?.Name ?? "null"}");
            }
        });

        composite.Construct();
        composite.Current.Should().BeNull();
        composite.SelectComponent(b);
        composite.DeselectComponent(b);

        observed.Should().Equal(b, null);
        order.Should().Equal(
            ["message:b", "callback:b", "message:null", "callback:null"],
            "each callback runs after its PropertyChangedMessage(\"Current\") is published");

        // Combined Current(first) + OnCurrentChanged: the initial-selector
        // assignment fires the hook exactly once with the first child.
        var hub2 = new TestHub();
        var a2 = BuildChild(hub2, dispatcher, "a");
        var b2 = BuildChild(hub2, dispatcher, "b");
        var observed2 = new List<ComponentVM<string>?>();

        var composite2 = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite2")
            .Services(hub2, dispatcher)
            .Children(() => new[] { a2, b2 })
            .Current(xs => xs.First())
            .OnCurrentChanged(vm => observed2.Add(vm))
            .Build();

        composite2.Construct();

        observed2.Should().Equal(a2);

        CompositeVM<ComponentVM<string>>? reentrant = null;
        var reentrantHub = new TestHub();
        var reentrantChild = BuildChild(reentrantHub, dispatcher, "reentrant");
        var callbackStatuses = new List<ConstructionStatus>();
        reentrant = CompositeVM<ComponentVM<string>>.Builder()
            .Name("reentrant-composite")
            .Services(reentrantHub, dispatcher)
            .Children(() => new[] { reentrantChild })
            .OnCurrentChanged(selected =>
            {
                callbackStatuses.Add(selected!.Status);
                reentrant!.Dispose();
            })
            .Build();
        reentrant.Construct();

        reentrant.SelectComponent(reentrantChild);

        callbackStatuses.Should().Equal(ConstructionStatus.Constructed);
        reentrant.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact, Trait("Conformance", "COMP-026")]
    public async Task COMP_026_Opposing_Current_Callbacks_Do_Not_Deadlock()
    {
        var dispatcher = new TestDispatcher();
        using var barrier = new Barrier(2);
        CompositeVM<ComponentVM<string>>? compositeA = null;
        CompositeVM<ComponentVM<string>>? compositeB = null;
        var hubA = new TestHub();
        var hubB = new TestHub();
        var childA = BuildChild(hubA, dispatcher, "a");
        var childB = BuildChild(hubB, dispatcher, "b");
        var firstA = 1;
        var firstB = 1;

        compositeA = CompositeVM<ComponentVM<string>>.Builder()
            .Name("a").Services(hubA, dispatcher).Children(() => [childA])
            .OnCurrentChanged(_ =>
            {
                if (Interlocked.Exchange(ref firstA, 0) == 0) return;
                barrier.SignalAndWait(HangGuard).Should().BeTrue();
                if (!ReferenceEquals(compositeB!.Current, childB))
                    compositeB.SelectComponent(childB);
            }).Build();
        compositeB = CompositeVM<ComponentVM<string>>.Builder()
            .Name("b").Services(hubB, dispatcher).Children(() => [childB])
            .OnCurrentChanged(_ =>
            {
                if (Interlocked.Exchange(ref firstB, 0) == 0) return;
                barrier.SignalAndWait(HangGuard).Should().BeTrue();
                if (!ReferenceEquals(compositeA!.Current, childA))
                    compositeA.SelectComponent(childA);
            }).Build();
        compositeA.Construct();
        compositeB.Construct();

        // The selections block in each other's callbacks by design, so they run
        // on dedicated threads: progress must not depend on thread-pool injection
        // under the parallel runner. Each callback waits for the other, so the
        // cross-selections always overlap. The waits are hang guards only.
        var taskA = Task.Factory.StartNew(
            () => compositeA.SelectComponent(childA),
            CancellationToken.None,
            TaskCreationOptions.LongRunning,
            TaskScheduler.Default);
        var taskB = Task.Factory.StartNew(
            () => compositeB.SelectComponent(childB),
            CancellationToken.None,
            TaskCreationOptions.LongRunning,
            TaskScheduler.Default);
        await Task.WhenAll(taskA, taskB).WaitAsync(HangGuard);

        compositeA.Current.Should().BeSameAs(childA);
        compositeB.Current.Should().BeSameAs(childB);
    }

    [Fact, Trait("Conformance", "COMP-026")]
    public async Task COMP_026_Collection_And_Current_Callbacks_Do_Not_Deadlock()
    {
        var dispatcher = new TestDispatcher();
        using var bTransactionEntered = new ManualResetEventSlim();
        using var aCallbackEntered = new ManualResetEventSlim();
        var hubA = new TestHub();
        var hubB = new TestHub();
        var b = CompositeVM<ComponentVM<string>>.Builder()
            .Name("b").Services(hubB, dispatcher).Children(() => []).Build();
        var aItem = BuildChild(hubA, dispatcher, "a-item");
        CompositeVM<ComponentVM<string>>? a = null;
        a = CompositeVM<ComponentVM<string>>.Builder()
            .Name("a").Services(hubA, dispatcher).Children(() => [aItem])
            .OnCurrentChanged(_ =>
            {
                aCallbackEntered.Set();
                bTransactionEntered.Wait(HangGuard).Should().BeTrue();
                b.Dispose();
            }).Build();
        a.Construct();
        b.Construct();
        var bItem = BuildChild(hubB, dispatcher, "b-item");
        bItem.Construct();
        b.CollectionChanged += (_, _) =>
        {
            bTransactionEntered.Set();
            b.SelectComponent(bItem);
        };

        var taskA = Task.Run(() => a.SelectComponent(aItem));
        aCallbackEntered.Wait(HangGuard).Should().BeTrue();
        var taskB = Task.Run(() => Record.Exception(() => b.Add(bItem)));

        await Task.WhenAll(taskA, taskB).WaitAsync(HangGuard);
        (await taskB).Should().BeNull();
        b.Status.Should().Be(ConstructionStatus.Disposed);
        bItem.Status.Should().Be(ConstructionStatus.Disposed);
    }

    /// <summary>
    /// COMP-026: while one child's current-flag notification is blocked, a
    /// later assignment from another thread completes and exactly the final
    /// current child keeps its current flag.
    /// </summary>
    [Fact, Trait("Conformance", "COMP-026")]
    public async Task COMP_026_Blocked_Current_Flag_Notification_Leaves_One_Current_Flag()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite").Services(hub, dispatcher).Children(() => []).Build();
        var first = BuildChild(hub, dispatcher, "first");
        var second = BuildChild(hub, dispatcher, "second");
        var third = BuildChild(hub, dispatcher, "third");
        composite.Add(first);
        composite.Add(second);
        composite.Add(third);
        composite.Current = first;
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        first.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(first.IsCurrent) && !first.IsCurrent)
            {
                entered.Set();
                release.Wait(HangGuard);
            }
        };

        var selectSecond = Task.Run(() => composite.Current = second);
        entered.Wait(HangGuard).Should().BeTrue();
        var selectThird = Task.Run(() => composite.Current = third);
        await selectThird.WaitAsync(HangGuard);
        release.Set();
        await selectSecond.WaitAsync(HangGuard);

        composite.Current.Should().BeSameAs(third);
        first.IsCurrent.Should().BeFalse();
        second.IsCurrent.Should().BeFalse();
        third.IsCurrent.Should().BeTrue();
    }

    [Fact]
    public void Auto_Construct_Rollback_Destructs_Child_After_Destination_Disposal()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        CompositeVM<ComponentVM<string>>? destination = null;
        var child = ComponentVM<string>.Builder().Name("child")
            .Services(hub, dispatcher).Model("m")
            .OnConstruct(() => destination!.Dispose()).Build();
        destination = CompositeVM<ComponentVM<string>>.Builder()
            .Name("destination").Services(hub, dispatcher)
            .Children(() => []).AutoConstructOnAdd(true).Build();
        destination.Construct();

        Action add = () => destination.Add(child);

        add.Should().Throw<ObjectDisposedException>();
        destination.Should().BeEmpty();
        child.Status.Should().Be(ConstructionStatus.Destructed);
        destination.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    [Trait("Conformance", "COMP-040")]
    [Trait("Conformance", "LIFE-015")]
    public void COMP_040_Population_Disposal_Rolls_Back_Constructed_Child()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        CompositeVM<ComponentVM<string>>? destination = null;
        var child = ComponentVM<string>.Builder().Name("child")
            .Services(hub, dispatcher).Model("m")
            .OnConstruct(() => destination!.Dispose()).Build();
        destination = CompositeVM<ComponentVM<string>>.Builder()
            .Name("destination").Services(hub, dispatcher)
            .Children(() => [child]).Build();

        Action construct = () => destination.Construct();

        construct.Should().Throw<Exception>();
        destination.Should().BeEmpty();
        child.Status.Should().Be(ConstructionStatus.Destructed);
        destination.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public void Attachment_Error_Precedes_Destination_Deferred_Disposal_Error()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var destination = new DisposeFailingComposite(
            "destination", hub, dispatcher, autoConstructOnAdd: true);
        var child = ComponentVM<string>.Builder().Name("child")
            .Services(hub, dispatcher).Model("m")
            .OnConstruct(() =>
            {
                destination.Dispose();
                throw new InvalidOperationException("attachment failure");
            }).Build();
        destination.Construct();

        Action add = () => destination.Add(child);

        add.Should().Throw<InvalidOperationException>().WithMessage("attachment failure");
        destination.Status.Should().Be(ConstructionStatus.Disposed);
        destination.Should().BeEmpty();
    }

    private sealed class HookCleanupProbeVM(
        string name,
        TestHub hub,
        TestDispatcher dispatcher,
        System.Collections.Concurrent.ConcurrentQueue<string> log,
        Action? onConstruct = null)
        : ComponentVMBase(name, "", hub, dispatcher, onConstruct, null)
    {
        private int _cleanups;
        public int Cleanups => _cleanups;
        public override ViewModelType Type => ViewModelType.Component;

        protected override void OnDispose()
        {
            Interlocked.Increment(ref _cleanups);
            log.Enqueue($"cleanup:{Name}");
        }
    }

    /// <summary>
    /// LIFE-015: a foreign disposal requested during an admitted construct
    /// hook does not overlap it; cleanup runs exactly once after the hook
    /// releases, and the container performs no post-hook lifecycle work.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-015")]
    public async Task LIFE_015_Disposal_Waits_For_Admitted_Hook_And_Cleans_Once()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var log = new System.Collections.Concurrent.ConcurrentQueue<string>();
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        var composite = new CleanupProbeComposite("composite", hub, dispatcher, log, () =>
        {
            log.Enqueue("hook-enter");
            entered.Set();
            release.Wait(HangGuard).Should().BeTrue();
            log.Enqueue("hook-exit");
        });
        var constructed = 0;
        hub.Messages.Subscribe(m =>
        {
            if (m is IConstructionStatusChangedMessage csm
                && csm.Status == ConstructionStatus.Constructed)
                Interlocked.Increment(ref constructed);
        });

        var construct = Task.Factory.StartNew(
            () => Record.Exception(composite.Construct),
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
        entered.Wait(HangGuard).Should().BeTrue();
        var dispose = Task.Factory.StartNew(
            () => Record.Exception(composite.Dispose),
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
        // Give the foreign disposal time to be requested while the hook is held.
        await Task.Delay(100);
        log.Should().NotContain("cleanup:composite",
            "terminal cleanup must not overlap the admitted hook");
        release.Set();
        await Task.WhenAll(construct, dispose).WaitAsync(HangGuard);
        (await dispose).Should().BeNull();
        composite.Dispose();

        log.Should().Equal(["hook-enter", "hook-exit", "cleanup:composite"],
            "cleanup runs once, only after the admitted hook releases its lease");
        composite.Cleanups.Should().Be(1);
        composite.Status.Should().Be(ConstructionStatus.Disposed);
        constructed.Should().Be(0,
            "terminal supersession prevents post-hook container lifecycle work");
    }

    private sealed class CleanupProbeComposite(
        string name,
        TestHub hub,
        TestDispatcher dispatcher,
        System.Collections.Concurrent.ConcurrentQueue<string> log,
        Action onConstruct)
        : CompositeVMBase<IComponentVM>(
            name, "", hub, dispatcher, false, false, onConstruct, null, null, null)
    {
        private int _cleanups;
        public int Cleanups => _cleanups;

        protected override void OnDispose()
        {
            base.OnDispose();
            Interlocked.Increment(ref _cleanups);
            log.Enqueue($"cleanup:{Name}");
        }
    }

    /// <summary>
    /// LIFE-015 (container cascade): the child cascade of a foreign disposal is
    /// terminal cleanup too, so it must not overlap the composite's admitted
    /// construct hook, and no child work may begin after the hook returns.
    /// </summary>
    [Fact]
    [Trait("Conformance", "LIFE-015")]
    public async Task LIFE_015_Child_Cascade_Waits_For_Admitted_Container_Hook()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var log = new System.Collections.Concurrent.ConcurrentQueue<string>();
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        var first = new HookCleanupProbeVM("first", hub, dispatcher, log);
        var second = new HookCleanupProbeVM("second", hub, dispatcher, log);
        var composite = CompositeVM<IComponentVM>.Builder()
            .Name("composite").Services(hub, dispatcher)
            .Children(() => Array.Empty<IComponentVM>())
            .OnConstruct(() =>
            {
                log.Enqueue("hook-enter");
                entered.Set();
                release.Wait(HangGuard).Should().BeTrue();
                log.Enqueue("hook-exit");
            })
            .Build();
        composite.Add(first);
        composite.Add(second);
        var constructedNames = new System.Collections.Concurrent.ConcurrentQueue<string>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IConstructionStatusChangedMessage csm
                && csm.Status == ConstructionStatus.Constructed)
                constructedNames.Enqueue(csm.SenderName);
        });

        var construct = Task.Factory.StartNew(
            () => Record.Exception(composite.Construct),
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
        entered.Wait(HangGuard).Should().BeTrue();
        var dispose = Task.Factory.StartNew(
            () => Record.Exception(composite.Dispose),
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
        // Give the foreign disposal time to be requested while the hook is held.
        await Task.Delay(100);
        log.Should().NotContain(e => e.StartsWith("cleanup:", StringComparison.Ordinal),
            "terminal cleanup must not overlap the admitted hook");
        release.Set();
        await Task.WhenAll(construct, dispose).WaitAsync(HangGuard);
        (await dispose).Should().BeNull();
        composite.Dispose();

        var entries = log.ToList();
        entries.Should().Contain("hook-exit");
        entries.FindIndex(e => e.StartsWith("cleanup:", StringComparison.Ordinal))
            .Should().BeGreaterThan(entries.IndexOf("hook-exit"),
                "terminal cleanup runs only after the admitted hook releases");
        first.Cleanups.Should().Be(1);
        second.Cleanups.Should().Be(1);
        composite.Status.Should().Be(ConstructionStatus.Disposed);
        first.Status.Should().Be(ConstructionStatus.Disposed);
        second.Status.Should().Be(ConstructionStatus.Disposed);
        constructedNames.Should().BeEmpty(
            "terminal supersession prevents post-hook container lifecycle work");
    }

    /// <summary>
    /// LIFE-015 (container cascade, cycle-broken deferral): two composites whose
    /// admitted construct hooks each dispose the other's composite. The wait
    /// graph defers one disposal to its hook's lease release; the deferred
    /// disposal includes the child cascade. Every child is cleaned once, only
    /// after its own container's hook exits, and nothing reaches Constructed.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-015")]
    public async Task LIFE_015_Opposing_Container_Disposal_Defers_Child_Cascade_To_Hook_Release()
    {
        var log = new System.Collections.Concurrent.ConcurrentQueue<string>();
        using var barrier = new Barrier(2);
        var composites = new CompositeVM<IComponentVM>[2];
        var children = new HookCleanupProbeVM[2][];
        var constructedNames = new System.Collections.Concurrent.ConcurrentQueue<string>();
        for (var index = 0; index < 2; index++)
        {
            var hub = new TestHub();
            var dispatcher = new TestDispatcher();
            var self = index;
            composites[index] = CompositeVM<IComponentVM>.Builder()
                .Name($"composite{index}").Services(hub, dispatcher)
                .Children(() => Array.Empty<IComponentVM>())
                .OnConstruct(() =>
                {
                    log.Enqueue($"hook-enter:{self}");
                    barrier.SignalAndWait(HangGuard).Should().BeTrue();
                    composites[1 - self].Dispose();
                    log.Enqueue($"hook-exit:{self}");
                })
                .Build();
            children[index] =
            [
                new HookCleanupProbeVM($"{index}a", hub, dispatcher, log),
                new HookCleanupProbeVM($"{index}b", hub, dispatcher, log),
            ];
            composites[index].Add(children[index][0]);
            composites[index].Add(children[index][1]);
            hub.Messages.Subscribe(m =>
            {
                if (m is IConstructionStatusChangedMessage csm
                    && csm.Status == ConstructionStatus.Constructed)
                    constructedNames.Enqueue(csm.SenderName);
            });
        }

        var transitions = Task.WhenAll(
            Task.Factory.StartNew(() => Record.Exception(composites[0].Construct),
                CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default),
            Task.Factory.StartNew(() => Record.Exception(composites[1].Construct),
                CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default));
        (await Task.WhenAny(transitions, Task.Delay(HangGuard)))
            .Should().BeSameAs(transitions, "opposing container disposals must not deadlock");
        await transitions;

        var entries = log.ToList();
        for (var index = 0; index < 2; index++)
        {
            var hookExit = entries.IndexOf($"hook-exit:{index}");
            hookExit.Should().BeGreaterThanOrEqualTo(0);
            foreach (var child in children[index])
            {
                entries.IndexOf($"cleanup:{child.Name}").Should().BeGreaterThan(hookExit,
                    "a child cascade never overlaps its container's admitted hook");
                child.Cleanups.Should().Be(1);
                child.Status.Should().Be(ConstructionStatus.Disposed);
            }
            composites[index].Status.Should().Be(ConstructionStatus.Disposed);
        }
        constructedNames.Should().BeEmpty(
            "terminal supersession prevents post-hook container lifecycle work");
    }

    /// <summary>
    /// LIFE-015 (same-thread re-entrancy): a composite disposed from inside its
    /// own admitted construct hook, on the hook's thread, cascades immediately,
    /// exactly as the base disposes immediately on the owner thread. The
    /// superseded construct then publishes no Constructed for anyone.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-015")]
    public void LIFE_015_Same_Thread_Container_Disposal_Inside_Hook_Cascades_Immediately()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var log = new System.Collections.Concurrent.ConcurrentQueue<string>();
        var first = new HookCleanupProbeVM("first", hub, dispatcher, log);
        var second = new HookCleanupProbeVM("second", hub, dispatcher, log);
        CompositeVM<IComponentVM>? composite = null;
        composite = CompositeVM<IComponentVM>.Builder()
            .Name("composite").Services(hub, dispatcher)
            .Children(() => Array.Empty<IComponentVM>())
            .OnConstruct(() =>
            {
                log.Enqueue("hook-enter");
                composite!.Dispose();
                log.Enqueue("dispose-returned");
                log.Enqueue("hook-exit");
            })
            .Build();
        composite.Add(first);
        composite.Add(second);
        var constructedNames = new List<string>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IConstructionStatusChangedMessage csm
                && csm.Status == ConstructionStatus.Constructed)
                constructedNames.Add(csm.SenderName);
        });

        _ = Record.Exception(composite.Construct);
        composite.Dispose();

        log.Should().Equal(
            ["hook-enter", "cleanup:first", "cleanup:second", "dispose-returned", "hook-exit"],
            "an owner-thread disposal is not deferred behind its own hook");
        first.Cleanups.Should().Be(1);
        second.Cleanups.Should().Be(1);
        composite.Status.Should().Be(ConstructionStatus.Disposed);
        constructedNames.Should().BeEmpty();
    }

    /// <summary>
    /// LIFE-015: opposing admitted hooks that each dispose the other's VM
    /// complete without deadlock, and each VM is cleaned exactly once.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-015")]
    public async Task LIFE_015_Opposing_Foreign_Hook_Disposal_Does_Not_Deadlock()
    {
        var log = new System.Collections.Concurrent.ConcurrentQueue<string>();
        using var barrier = new Barrier(2);
        HookCleanupProbeVM? first = null;
        HookCleanupProbeVM? second = null;
        first = new HookCleanupProbeVM("first", new TestHub(), new TestDispatcher(), log, () =>
        {
            barrier.SignalAndWait(HangGuard);
            second!.Dispose();
        });
        second = new HookCleanupProbeVM("second", new TestHub(), new TestDispatcher(), log, () =>
        {
            barrier.SignalAndWait(HangGuard);
            first.Dispose();
        });

        var transitions = Task.WhenAll(
            Task.Factory.StartNew(first.Construct, CancellationToken.None,
                TaskCreationOptions.LongRunning, TaskScheduler.Default),
            Task.Factory.StartNew(second.Construct, CancellationToken.None,
                TaskCreationOptions.LongRunning, TaskScheduler.Default));
        (await Task.WhenAny(transitions, Task.Delay(HangGuard)))
            .Should().BeSameAs(transitions, "opposing foreign hook waits must not deadlock");
        await transitions;

        first.Status.Should().Be(ConstructionStatus.Disposed);
        second.Status.Should().Be(ConstructionStatus.Disposed);
        first.Cleanups.Should().Be(1);
        second.Cleanups.Should().Be(1);
    }

    // ── COMP-027 — Add sets child Parent; Remove clears it ───────────────────

    /// <summary>
    /// COMP-027: Adding a child to a Constructed composite sets the child's internal
    /// Parent back-reference (the child becomes selectable and Select() delegates
    /// through it); removing the child clears Parent (no longer selectable, Select()
    /// is a no-op). Parent is not observable, so the wiring is asserted through the
    /// public selection surface. See spec/05 §6.1, spec/01 §1.3, and ADR-0050.
    /// </summary>
    [Fact, Trait("Conformance", "COMP-027")]
    public void COMP_027_Add_Sets_Parent_Remove_Clears_It()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        composite.Construct();

        var child = BuildChild(hub, dispatcher, "c");
        child.Construct();

        // No parent yet → not selectable.
        child.CanSelect().Should().BeFalse("a VM with no Parent is not selectable");

        // Add wires Parent → selectable, and Select() delegates through it.
        composite.Add(child);
        child.CanSelect().Should().BeTrue("Add set the child's Parent to the composite");
        child.Select();
        composite.Current.Should().BeSameAs(child);
        child.IsCurrent.Should().BeTrue();

        // Deselect, then remove: Remove clears Parent → not selectable, Select() no-op.
        child.Deselect();
        composite.Current.Should().BeNull();
        composite.Remove(child).Should().BeTrue();
        child.CanSelect().Should().BeFalse("Remove cleared the child's Parent");
        child.Select(); // no-op: Parent is null
        composite.Current.Should().BeNull("a parentless child's Select() is a no-op");
    }

    // ── COMP-038..041 — Exclusive transactional parent ownership ────────────

    [Fact, Trait("Conformance", "COMP-038")]
    public void COMP_038_Add_Transfers_Child_From_Previous_Parent()
    {
        var (oldParent, hub, dispatcher) = BuildComposite("old");
        var child = BuildChild(hub, dispatcher, "c");
        oldParent.Add(child);
        oldParent.Construct();

        var group = GroupVM<ComponentVM<string>>.Builder()
            .Name("group")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();

        group.Add(child);

        oldParent.Should().BeEmpty();
        group.Should().ContainSingle(item => ReferenceEquals(item, child));
        child.Status.Should().Be(ConstructionStatus.Constructed);
        oldParent.Remove(child).Should().BeFalse();

        var nextParent = CompositeVM<ComponentVM<string>>.Builder()
            .Name("next")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        nextParent.Construct();
        nextParent.Add(child);

        group.Should().BeEmpty();
        child.CanSelect().Should().BeTrue("the composite is now the only parent");
        child.Select();
        nextParent.Current.Should().BeSameAs(child);
    }

    [Fact, Trait("Conformance", "COMP-039")]
    public void COMP_039_Duplicate_And_Cycle_Rejection_Is_Mutation_Free()
    {
        var (parent, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        parent.Add(child);
        var events = 0;
        parent.CollectionChanged += (_, _) => events++;

        Action duplicate = () => parent.Add(child);

        duplicate.Should().Throw<InvalidOperationException>();
        parent.Should().ContainSingle(item => ReferenceEquals(item, child));
        events.Should().Be(0);

        var outer = CompositeVM<IComponentVM>.Builder()
            .Name("outer")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<IComponentVM>())
            .Build();
        var inner = CompositeVM<IComponentVM>.Builder()
            .Name("inner")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<IComponentVM>())
            .Build();
        outer.Add(inner);

        Action cycle = () => inner.Add(outer);

        cycle.Should().Throw<InvalidOperationException>();
        outer.Should().ContainSingle(item => ReferenceEquals(item, inner));
        inner.Should().BeEmpty();

        // Self-attach is rejected with the same mutation-free guarantee.
        var selfEvents = 0;
        var outerStatus = outer.Status;
        outer.CollectionChanged += (_, _) => selfEvents++;
        Action selfAttach = () => outer.Add(outer);

        selfAttach.Should().Throw<InvalidOperationException>();
        outer.Should().ContainSingle(item => ReferenceEquals(item, inner));
        outer.Status.Should().Be(outerStatus);
        outer.Current.Should().BeNull();
        selfEvents.Should().Be(0);
    }

    [Fact, Trait("Conformance", "COMP-039")]
    public void COMP_039_Membership_Uses_Identity_When_Children_Override_Equality()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var child = new EqualByNameVM("same", hub, dispatcher);
        var foreign = new EqualByNameVM("same", hub, dispatcher);
        var composite = CompositeVM<EqualByNameVM>.Builder()
            .Name("composite")
            .Services(hub, dispatcher)
            .Children(() => [])
            .Build();
        composite.Add(child);
        child.Construct();

        composite.Contains(foreign).Should().BeFalse();
        composite.IndexOf(foreign).Should().Be(-1);
        composite.CanSelectComponent(foreign).Should().BeFalse();
        ((Action)(() => composite.Current = foreign)).Should().Throw<InvalidOperationException>();
        composite.Remove(foreign).Should().BeFalse();
        composite.Should().ContainSingle(item => ReferenceEquals(item, child));

        var groupChild = new EqualByNameVM("group-same", hub, dispatcher);
        var groupForeign = new EqualByNameVM("group-same", hub, dispatcher);
        var group = GroupVM<EqualByNameVM>.Builder()
            .Name("group")
            .Services(hub, dispatcher)
            .Children(() => [])
            .Build();
        group.Add(groupChild);

        group.Contains(groupForeign).Should().BeFalse();
        group.IndexOf(groupForeign).Should().Be(-1);
        group.Remove(groupForeign).Should().BeFalse();
        group.Should().ContainSingle(item => ReferenceEquals(item, groupChild));
    }

    [Fact, Trait("Conformance", "COMP-040")]
    public void COMP_040_Failed_Transfer_Restores_Parent_Index_And_Current()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var child = ComponentVM<string>.Builder()
            .Name("failing")
            .Services(hub, dispatcher)
            .Model("m")
            .OnConstruct(() => throw new InvalidOperationException("boom"))
            .Build();
        var sibling = BuildChild(hub, dispatcher, "sibling");
        var oldParent = CompositeVM<ComponentVM<string>>.Builder()
            .Name("old")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        oldParent.Add(sibling);
        oldParent.Add(child);
        oldParent.Current = child;

        var destination = GroupVM<ComponentVM<string>>.Builder()
            .Name("destination")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .AutoConstructOnAdd(true)
            .Build();
        destination.Construct();
        var events = new List<string>();
        oldParent.CollectionChanged += (_, _) => events.Add("old");
        destination.CollectionChanged += (_, _) => events.Add("new");

        Action transfer = () => destination.Add(child);

        transfer.Should().Throw<InvalidOperationException>().WithMessage("boom");
        oldParent.Should().Equal(sibling, child);
        oldParent.Current.Should().BeSameAs(child);
        child.IsCurrent.Should().BeTrue();
        child.Status.Should().Be(ConstructionStatus.Destructed);
        destination.Should().BeEmpty();
        events.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "COMP-040")]
    public void COMP_040_Reentrant_Structural_Mutation_Is_Rejected_Before_Mutation()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        CompositeVM<ComponentVM<string>>? oldParent = null;
        CompositeVM<ComponentVM<string>>? destination = null;
        var intruder = BuildChild(hub, dispatcher, "intruder");
        var sibling = BuildChild(hub, dispatcher, "sibling");
        var hookErrors = new List<Exception?>();
        var moving = ComponentVM<string>.Builder()
            .Name("moving").Services(hub, dispatcher).Model("m")
            .OnConstruct(() =>
            {
                hookErrors.Add(Record.Exception(() => destination!.Add(intruder)));
                hookErrors.Add(Record.Exception(() => oldParent!.Remove(sibling)));
            })
            .Build();
        oldParent = CompositeVM<ComponentVM<string>>.Builder()
            .Name("old").Services(hub, dispatcher).Children(() => []).Build();
        oldParent.Add(sibling);
        oldParent.Add(moving);
        destination = CompositeVM<ComponentVM<string>>.Builder()
            .Name("destination").Services(hub, dispatcher).Children(() => [])
            .AutoConstructOnAdd(true).Build();
        destination.Construct();

        destination.Add(moving);

        hookErrors.Should().HaveCount(2);
        hookErrors.Should().AllSatisfy(error => error.Should().BeOfType<InvalidOperationException>(),
            "re-entrant structural mutation of either protected container is rejected");
        destination.Should().Equal(moving);
        oldParent.Should().Equal(sibling);
        intruder.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact, Trait("Conformance", "COMP-040")]
    public void COMP_040_Replacement_Rollback_Precedes_Deferred_Destination_Disposal()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        CompositeVM<ComponentVM<string>>? destination = null;
        var displaced = BuildChild(hub, dispatcher, "displaced");
        var replacement = ComponentVM<string>.Builder()
            .Name("replacement").Services(hub, dispatcher).Model("m")
            .OnConstruct(() => destination!.Dispose())
            .Build();
        destination = CompositeVM<ComponentVM<string>>.Builder()
            .Name("destination").Services(hub, dispatcher).Children(() => [])
            .AutoConstructOnAdd(true).Build();
        destination.Construct();
        destination.Add(displaced);

        Action replace = () => destination[0] = replacement;

        replace.Should().Throw<ObjectDisposedException>();
        destination.Status.Should().Be(ConstructionStatus.Disposed);
        displaced.Status.Should().Be(ConstructionStatus.Disposed,
            "the displaced member is restored before the terminal membership snapshot");
        replacement.Status.Should().Be(ConstructionStatus.Destructed,
            "the rejected replacement is rolled back, not cascaded");
    }

    [Fact, Trait("Conformance", "COMP-040")]
    public void COMP_040_Lifecycle_Compensation_Failure_Is_Surfaced()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        CompositeVM<ComponentVM<string>>? destination = null;
        var displaced = BuildChild(hub, dispatcher, "displaced");
        var replacement = ComponentVM<string>.Builder()
            .Name("replacement").Services(hub, dispatcher).Model("m")
            .OnConstruct(() => destination!.Dispose())
            .OnDestruct(() => throw new InvalidOperationException("compensation failure"))
            .Build();
        destination = CompositeVM<ComponentVM<string>>.Builder()
            .Name("destination").Services(hub, dispatcher).Children(() => [])
            .AutoConstructOnAdd(true).Build();
        destination.Construct();
        destination.Add(displaced);

        Action replace = () => destination[0] = replacement;

        var failure = replace.Should().Throw<AggregateException>().Which;
        failure.Flatten().InnerExceptions.Should().Contain(error =>
            error is InvalidOperationException && error.Message == "compensation failure",
            "a failed lifecycle compensation is surfaced rather than swallowed");
    }

    [Fact, Trait("Conformance", "COMP-040")]
    public void COMP_040_Defers_Old_Composite_Disposal_Until_Transfer_Commits()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var oldParent = CompositeVM<ComponentVM<string>>.Builder()
            .Name("old")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        var destination = GroupVM<ComponentVM<string>>.Builder()
            .Name("destination")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .AutoConstructOnAdd(true)
            .Build();
        var child = ComponentVM<string>.Builder()
            .Name("child")
            .Services(hub, dispatcher)
            .Model("m")
            .OnConstruct(oldParent.Dispose)
            .Build();
        oldParent.Add(child);
        destination.Construct();

        destination.Add(child);

        oldParent.Status.Should().Be(ConstructionStatus.Disposed);
        oldParent.Should().BeEmpty();
        destination.Should().ContainSingle(item => ReferenceEquals(item, child));
        child.Status.Should().Be(ConstructionStatus.Constructed);
        child.Parent.Should().BeSameAs(destination);
    }

    [Fact, Trait("Conformance", "COMP-040")]
    public void COMP_040_Rolls_Back_Before_Deferred_Old_Group_Disposal()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var oldParent = GroupVM<ComponentVM<string>>.Builder()
            .Name("old")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        var destination = CompositeVM<ComponentVM<string>>.Builder()
            .Name("destination")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .AutoConstructOnAdd(true)
            .Build();
        var child = ComponentVM<string>.Builder()
            .Name("child")
            .Services(hub, dispatcher)
            .Model("m")
            .OnConstruct(() =>
            {
                oldParent.Dispose();
                throw new InvalidOperationException("boom");
            })
            .Build();
        oldParent.Add(child);
        destination.Construct();

        Action transfer = () => destination.Add(child);

        transfer.Should().Throw<InvalidOperationException>().WithMessage("boom");
        oldParent.Status.Should().Be(ConstructionStatus.Disposed);
        oldParent.Should().ContainSingle(item => ReferenceEquals(item, child));
        destination.Should().BeEmpty();
        child.Status.Should().Be(ConstructionStatus.Disposed);
        child.Parent.Should().BeSameAs(oldParent);
    }

    [Fact, Trait("Conformance", "COMP-040")]
    public void COMP_040_Deferred_Disposal_Failure_Follows_Committed_Transfer_Events()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var oldParent = GroupVM<ComponentVMBase>.Builder()
            .Name("old").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVMBase>()).Build();
        var destination = CompositeVM<ComponentVMBase>.Builder()
            .Name("destination").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVMBase>())
            .AutoConstructOnAdd(true).Build();
        var moving = new DisposeFailingVM("moving", hub, dispatcher, oldParent.Dispose);
        var failingSibling = new DisposeFailingVM("failing-sibling", hub, dispatcher);
        oldParent.Add(moving);
        oldParent.Add(failingSibling);
        destination.Construct();
        var events = new List<string>();
        oldParent.CollectionChanged += (_, _) => events.Add("old:remove");
        destination.CollectionChanged += (_, _) => events.Add("new:add");

        Action transfer = () => destination.Add(moving);

        transfer.Should().Throw<InvalidOperationException>().WithMessage("dispose failure");
        events.Should().Equal("old:remove", "new:add");
        oldParent.Status.Should().Be(ConstructionStatus.Disposed);
        failingSibling.Status.Should().Be(ConstructionStatus.Disposed);
        destination.Should().ContainSingle(item => ReferenceEquals(item, moving));
        moving.Parent.Should().BeSameAs(destination);
    }

    [Fact, Trait("Conformance", "COMP-040")]
    public void COMP_040_Attachment_Failure_Precedes_Deferred_Disposal_Failure()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var oldParent = GroupVM<ComponentVMBase>.Builder()
            .Name("old").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVMBase>()).Build();
        var destination = CompositeVM<ComponentVMBase>.Builder()
            .Name("destination").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVMBase>())
            .AutoConstructOnAdd(true).Build();
        var moving = new DisposeFailingVM("moving", hub, dispatcher, () =>
        {
            oldParent.Dispose();
            throw new InvalidOperationException("attachment failure");
        });
        oldParent.Add(moving);
        destination.Construct();

        Action transfer = () => destination.Add(moving);

        transfer.Should().Throw<InvalidOperationException>().WithMessage("attachment failure");
        oldParent.Status.Should().Be(ConstructionStatus.Disposed);
        moving.Status.Should().Be(ConstructionStatus.Disposed);
        oldParent.Should().ContainSingle(item => ReferenceEquals(item, moving));
        destination.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "COMP-040")]
    public void COMP_040_Late_Disposal_Failure_Does_Not_Retry_Committed_Population()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var oldParent = GroupVM<ComponentVMBase>.Builder()
            .Name("old").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVMBase>()).Build();
        var moving = new DisposeFailingVM("moving", hub, dispatcher, oldParent.Dispose);
        var failingSibling = new DisposeFailingVM("failing-sibling", hub, dispatcher);
        oldParent.Add(moving);
        oldParent.Add(failingSibling);
        var factoryCalls = 0;
        var destination = CompositeVM<ComponentVMBase>.Builder()
            .Name("destination").Services(hub, dispatcher)
            .Children(() =>
            {
                factoryCalls++;
                return [moving];
            })
            .Build();
        var events = new List<string>();
        oldParent.CollectionChanged += (_, _) => events.Add("old:remove");
        destination.CollectionChanged += (_, _) => events.Add("new:add");

        Action firstConstruct = destination.Construct;

        firstConstruct.Should().Throw<InvalidOperationException>().WithMessage("dispose failure");
        events.Should().Equal("old:remove", "new:add");
        factoryCalls.Should().Be(1);
        destination.Should().ContainSingle(item => ReferenceEquals(item, moving));

        destination.Construct();

        factoryCalls.Should().Be(1);
        destination.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact, Trait("Conformance", "COMP-040")]
    public async Task COMP_040_Concurrent_Old_Parent_Disposal_Waits_For_Transfer_Commit()
    {
        // The transfer hook and the disposal block their threads by design, so
        // they run on dedicated threads: the test thread's progress must not
        // depend on thread-pool injection under the parallel runner. Timeouts
        // below are hang guards only; each wait resumes on its event.
        using var hookEntered = new ManualResetEventSlim();
        using var releaseHook = new ManualResetEventSlim();
        using var disposalStarted = new ManualResetEventSlim();
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var oldParent = GroupVM<ComponentVM<string>>.Builder()
            .Name("old").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        var destination = CompositeVM<ComponentVM<string>>.Builder()
            .Name("destination").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .AutoConstructOnAdd(true).Build();
        var child = ComponentVM<string>.Builder()
            .Name("child").Services(hub, dispatcher).Model("m")
            .OnConstruct(() =>
            {
                hookEntered.Set();
                releaseHook.Wait(HangGuard).Should().BeTrue();
            })
            .Build();
        oldParent.Add(child);
        destination.Construct();

        var transfer = Task.Factory.StartNew(
            () => destination.Add(child),
            CancellationToken.None,
            TaskCreationOptions.LongRunning,
            TaskScheduler.Default);
        hookEntered.Wait(HangGuard).Should().BeTrue();
        var disposal = Task.Factory.StartNew(
            () =>
            {
                disposalStarted.Set();
                oldParent.Dispose();
            },
            CancellationToken.None,
            TaskCreationOptions.LongRunning,
            TaskScheduler.Default);
        disposalStarted.Wait(HangGuard).Should().BeTrue();
        var earlyCompletion = await Task.WhenAny(disposal, Task.Delay(TimeSpan.FromMilliseconds(50)));
        earlyCompletion.Should().NotBe(disposal);

        releaseHook.Set();
        await Task.WhenAll(transfer, disposal).WaitAsync(HangGuard);
        oldParent.Status.Should().Be(ConstructionStatus.Disposed);
        oldParent.Should().BeEmpty();
        destination.Should().ContainSingle(item => ReferenceEquals(item, child));
        child.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact, Trait("Conformance", "COMP-040")]
    public void COMP_040_Lazy_Population_Rolls_Back_As_One_Transaction()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var first = BuildChild(hub, dispatcher, "first");
        var blocker = ComponentVM<string>.Builder()
            .Name("bulk-failing")
            .Services(hub, dispatcher)
            .Model("m")
            .OnConstruct(() => throw new InvalidOperationException("boom"))
            .Build();
        var oldParent = CompositeVM<ComponentVM<string>>.Builder()
            .Name("bulk-old")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        oldParent.Add(first);
        var batch = new List<ComponentVM<string>> { first, blocker };
        var destination = GroupVM<ComponentVM<string>>.Builder()
            .Name("bulk-destination")
            .Services(hub, dispatcher)
            .Children(() => batch)
            .Build();
        var events = new List<string>();
        oldParent.CollectionChanged += (_, _) => events.Add("old");
        destination.CollectionChanged += (_, _) => events.Add("new");

        Action populate = destination.Construct;

        populate.Should().Throw<InvalidOperationException>().WithMessage("boom");
        oldParent.Should().ContainSingle(item => ReferenceEquals(item, first));
        first.Status.Should().Be(ConstructionStatus.Destructed);
        destination.Should().BeEmpty();
        events.Should().BeEmpty();

        batch.Clear();
        destination.Construct();
        destination.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "COMP-040")]
    public void COMP_040_Reservation_Failure_Preserves_Preexisting_Destination_Children()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();

        foreach (var useGroup in new[] { false, true })
        {
            var moving = BuildChild(hub, dispatcher, useGroup ? "group-moving" : "composite-moving");
            var blocker = BuildChild(hub, dispatcher, useGroup ? "group-blocker" : "composite-blocker");
            var oldParent = CompositeVM<ComponentVM<string>>.Builder()
                .Name(useGroup ? "group-old" : "composite-old")
                .Services(hub, dispatcher)
                .Children(() => Array.Empty<ComponentVM<string>>())
                .Build();
            oldParent.Add(moving);
            var candidates = new List<ComponentVM<string>>();

            if (useGroup)
            {
                var destination = GroupVM<ComponentVM<string>>.Builder()
                    .Name("group-destination").Services(hub, dispatcher)
                    .Children(() => candidates).Build();
                destination.Add(blocker);
                candidates.AddRange([moving, blocker]);

                destination.Invoking(candidate => candidate.Construct())
                    .Should().Throw<InvalidOperationException>();
                destination.Should().ContainSingle().Which.Should().BeSameAs(blocker);
                blocker.GetParent()!.Owner.Should().BeSameAs(destination);
            }
            else
            {
                var destination = CompositeVM<ComponentVM<string>>.Builder()
                    .Name("composite-destination").Services(hub, dispatcher)
                    .Children(() => candidates).Build();
                destination.Add(blocker);
                candidates.AddRange([moving, blocker]);

                destination.Invoking(candidate => candidate.Construct())
                    .Should().Throw<InvalidOperationException>();
                destination.Should().ContainSingle().Which.Should().BeSameAs(blocker);
                blocker.GetParent()!.Owner.Should().BeSameAs(destination);
            }

            oldParent.Should().ContainSingle().Which.Should().BeSameAs(moving);
        }
    }

    [Fact, Trait("Conformance", "COMP-041")]
    public void COMP_041_Transfer_Publishes_Old_Remove_Before_New_Add()
    {
        var (oldParent, hub, dispatcher) = BuildComposite("old");
        var child = BuildChild(hub, dispatcher);
        oldParent.Add(child);
        var destination = GroupVM<ComponentVM<string>>.Builder()
            .Name("destination")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        var observed = new List<string>();
        oldParent.CollectionChanged += (_, args) =>
        {
            args.Action.Should().Be(NotifyCollectionChangedAction.Remove);
            oldParent.Should().NotContain(child);
            destination.Should().Contain(child);
            observed.Add("old:remove");
        };
        destination.CollectionChanged += (_, args) =>
        {
            args.Action.Should().Be(NotifyCollectionChangedAction.Add);
            oldParent.Should().NotContain(child);
            destination.Should().Contain(child);
            observed.Add("new:add");
        };

        destination.Add(child);

        observed.Should().Equal("old:remove", "new:add");
    }

    [Fact, Trait("Conformance", "COMP-041")]
    public void COMP_041_Throwing_Current_Callback_Does_Not_Suppress_Transfer_Events()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var oldParent = CompositeVM<ComponentVM<string>>.Builder()
            .Name("old")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .OnCurrentChanged(current =>
            {
                if (current is null) throw new InvalidOperationException("callback boom");
            })
            .Build();
        var child = BuildChild(hub, dispatcher);
        oldParent.Add(child);
        oldParent.Current = child;
        var destination = GroupVM<ComponentVM<string>>.Builder()
            .Name("destination")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        var observed = new List<string>();
        oldParent.CollectionChanged += (_, _) => observed.Add("old:remove");
        destination.CollectionChanged += (_, _) => observed.Add("new:add");

        destination.Invoking(group => group.Add(child))
            .Should().Throw<InvalidOperationException>().WithMessage("callback boom");

        observed.Should().Equal("old:remove", "new:add");
        oldParent.Should().BeEmpty();
        destination.Should().ContainSingle().Which.Should().BeSameAs(child);
        child.GetParent()!.Owner.Should().BeSameAs(destination);
    }

    [Fact]
    public void Bulk_Transfer_Remove_Callback_Does_Not_Retain_Ownership_Coordinator()
    {
        var (oldParent, hub, dispatcher) = BuildComposite("old");
        var first = BuildChild(hub, dispatcher, "first");
        var second = BuildChild(hub, dispatcher, "second");
        var secondOldParent = CompositeVM<ComponentVM<string>>.Builder()
            .Name("second-old").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        oldParent.Add(first);
        secondOldParent.Add(second);
        var destination = GroupVM<ComponentVM<string>>.Builder()
            .Name("destination").Services(hub, dispatcher)
            .Children(() => [first, second]).Build();

        var unrelated = BuildChild(hub, dispatcher, "unrelated");
        var unrelatedOld = GroupVM<ComponentVM<string>>.Builder()
            .Name("unrelated-old").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        unrelatedOld.Add(unrelated);
        var unrelatedDestination = GroupVM<ComponentVM<string>>.Builder()
            .Name("unrelated-destination").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        using var workerDone = new ManualResetEventSlim();
        Thread? worker = null;
        var callbackObservedProgress = false;

        oldParent.CollectionChanged += (_, args) =>
        {
            if (args.Action != NotifyCollectionChangedAction.Remove || worker is not null) return;
            worker = new Thread(() =>
            {
                unrelatedDestination.Add(unrelated);
                workerDone.Set();
            });
            worker.Start();
            callbackObservedProgress = workerDone.Wait(HangGuard);
        };

        destination.Construct();

        worker.Should().NotBeNull();
        worker!.Join(HangGuard).Should().BeTrue();
        callbackObservedProgress.Should().BeTrue();
        unrelatedOld.Should().BeEmpty();
        unrelatedDestination.Should().ContainSingle().Which.Should().BeSameAs(unrelated);
    }

    [Fact]
    public void Colliding_Bulk_Wait_Does_Not_Block_Unrelated_Callback_Transfer()
    {
        var (oldParent, hub, dispatcher) = BuildComposite("old");
        var child = BuildChild(hub, dispatcher, "child");
        oldParent.Add(child);
        var firstDestination = GroupVM<ComponentVM<string>>.Builder()
            .Name("first-destination").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        using var bulkFactoryEntered = new ManualResetEventSlim();
        var bulkDestination = GroupVM<ComponentVM<string>>.Builder()
            .Name("bulk-destination").Services(hub, dispatcher)
            .Children(() =>
            {
                bulkFactoryEntered.Set();
                return [child];
            }).Build();

        var unrelated = BuildChild(hub, dispatcher, "unrelated");
        var unrelatedOld = GroupVM<ComponentVM<string>>.Builder()
            .Name("unrelated-old").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        unrelatedOld.Add(unrelated);
        var unrelatedDestination = GroupVM<ComponentVM<string>>.Builder()
            .Name("unrelated-destination").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        using var unrelatedDone = new ManualResetEventSlim();
        Thread? bulkWorker = null;
        var callbackObservedProgress = false;

        oldParent.CollectionChanged += (_, args) =>
        {
            if (args.Action != NotifyCollectionChangedAction.Remove || bulkWorker is not null) return;
            bulkWorker = new Thread(bulkDestination.Construct);
            bulkWorker.Start();
            bulkFactoryEntered.Wait(HangGuard).Should().BeTrue();
            SpinWait.SpinUntil(
                () => (bulkWorker.ThreadState & ThreadState.WaitSleepJoin) != 0,
                HangGuard).Should().BeTrue();

            var unrelatedWorker = new Thread(() =>
            {
                unrelatedDestination.Add(unrelated);
                unrelatedDone.Set();
            });
            unrelatedWorker.Start();
            callbackObservedProgress = unrelatedDone.Wait(HangGuard);
            unrelatedWorker.Join(HangGuard);
        };

        firstDestination.Add(child);

        bulkWorker.Should().NotBeNull();
        bulkWorker!.Join(HangGuard).Should().BeTrue();
        callbackObservedProgress.Should().BeTrue();
        bulkDestination.Should().ContainSingle().Which.Should().BeSameAs(child);
        unrelatedOld.Should().BeEmpty();
        unrelatedDestination.Should().ContainSingle().Which.Should().BeSameAs(unrelated);
    }
}
