using System.Collections.Specialized;
using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for CompositeVM covering COMP-001..011 and LIFE-013.
/// See spec/06-composite-vm.md and spec/12-conformance.md.
/// </summary>
public class CompositeVMConformanceTests
{
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
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(hub, dispatcher)
            .Children(() => new[] { a, b, c })
            .Current(xs => { selectorCalls++; return xs.Skip(1).First(); })
            .Build();

        composite.Construct();

        composite.Current.Should().BeSameAs(b);
        selectorCalls.Should().Be(1, "the selector must run exactly once during construct");

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
        var observed = new List<ComponentVM<string>?>();

        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(hub, dispatcher)
            .Children(() => new[] { a, b })
            .OnCurrentChanged(vm => observed.Add(vm))
            .Build();

        composite.Construct();
        composite.SelectComponent(b);
        composite.DeselectComponent(b);

        observed.Should().Equal(b, null);

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
}
