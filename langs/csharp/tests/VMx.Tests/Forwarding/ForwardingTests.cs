using System.Collections.Specialized;
using System.ComponentModel;
using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Forwarding;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Forwarding;

/// <summary>
/// Unit tests for <see cref="ForwardingComponentVM{M}"/> and
/// <see cref="ForwardingCompositeVM{VM}"/>. Conformance-level tests live in
/// VMx.Conformance.Tests.ForwardingConformanceTests.
/// </summary>
public class ForwardingTests
{
    // ── Concrete no-op subclasses used by tests ──────────────────────────────

    private sealed class NoOpForwardingVM<M> : ForwardingComponentVM<M>
    {
        public NoOpForwardingVM(IComponentVM<M> wrapped) : base(wrapped) { }
    }

    private sealed class HintOverridingForwardingVM<M> : ForwardingComponentVM<M>
    {
        public HintOverridingForwardingVM(IComponentVM<M> wrapped) : base(wrapped) { }

        public override string Hint => "OVERRIDE";
    }

    private sealed class NoOpForwardingCompositeVM<VM> : ForwardingCompositeVM<VM>
        where VM : class, IComponentVM
    {
        public NoOpForwardingCompositeVM(ICompositeVM<VM> wrapped) : base(wrapped) { }
    }

    // ── Factory helpers ──────────────────────────────────────────────────────

    private static (ComponentVM<string> vm, TestHub hub, TestDispatcher dispatcher) BuildVm(
        string name = "vm1", string hint = "", string model = "initial")
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var builder = ComponentVM<string>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .Model(model);
        if (hint.Length > 0) builder = builder.Hint(hint);
        var vm = builder.Build();
        return (vm, hub, dispatcher);
    }

    private static (CompositeVM<ComponentVM<string>> composite, TestHub hub, TestDispatcher dispatcher)
        BuildComposite(string name = "root")
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        return (composite, hub, dispatcher);
    }

    // ── ForwardingComponentVM: identity delegation ───────────────────────────

    [Fact]
    public void ForwardingComponentVM_Delegates_Name()
    {
        var (inner, _, _) = BuildVm("myVm");
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.Name.Should().Be("myVm");
    }

    [Fact]
    public void ForwardingComponentVM_Delegates_Hint()
    {
        var (inner, _, _) = BuildVm(hint: "inner-hint");
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.Hint.Should().Be("inner-hint");
    }

    [Fact]
    public void ForwardingComponentVM_Delegates_Type()
    {
        var (inner, _, _) = BuildVm();
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.Type.Should().Be(inner.Type);
    }

    // ── ForwardingComponentVM: lifecycle delegation ──────────────────────────

    [Fact]
    public void ForwardingComponentVM_Delegates_Status()
    {
        var (inner, _, _) = BuildVm();
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.Status.Should().Be(ConstructionStatus.Destructed);
        inner.Construct();
        fwd.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void ForwardingComponentVM_Delegates_IsConstructed()
    {
        var (inner, _, _) = BuildVm();
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.IsConstructed.Should().BeFalse();
        inner.Construct();
        fwd.IsConstructed.Should().BeTrue();
    }

    [Fact]
    public void ForwardingComponentVM_Construct_Delegates_To_Wrapped()
    {
        var (inner, _, _) = BuildVm();
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.Construct();
        inner.IsConstructed.Should().BeTrue();
    }

    [Fact]
    public void ForwardingComponentVM_Destruct_Delegates_To_Wrapped()
    {
        var (inner, _, _) = BuildVm();
        inner.Construct();
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.Destruct();
        inner.IsConstructed.Should().BeFalse();
    }

    // ── ForwardingComponentVM: model delegation ──────────────────────────────

    [Fact]
    public void ForwardingComponentVM_Delegates_Model_Get()
    {
        var (inner, _, _) = BuildVm(model: "hello");
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.Model.Should().Be("hello");
    }

    [Fact]
    public void ForwardingComponentVM_Delegates_Model_Set()
    {
        var (inner, _, _) = BuildVm(model: "hello");
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.Model = "world";
        inner.Model.Should().Be("world");
    }

    // ── ForwardingComponentVM: PropertyChanged forwarding ───────────────────

    [Fact]
    public void ForwardingComponentVM_Forwards_PropertyChanged_Event()
    {
        var (inner, _, _) = BuildVm(model: "a");
        var fwd = new NoOpForwardingVM<string>(inner);

        var fired = new List<string?>();
        fwd.PropertyChanged += (_, e) => fired.Add(e.PropertyName);

        inner.Model = "b";

        fired.Should().Contain("Model");
    }

    // ── ForwardingComponentVM: Dispose delegation ────────────────────────────

    [Fact]
    public void ForwardingComponentVM_Dispose_Delegates_To_Wrapped()
    {
        var (inner, _, _) = BuildVm();
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.Dispose();
        inner.Status.Should().Be(ConstructionStatus.Disposed);
    }

    // ── Override: Hint override replaces only Hint ───────────────────────────

    [Fact]
    public void HintOverride_Returns_Override_And_Name_Still_Delegates()
    {
        var (inner, _, _) = BuildVm("myVm", hint: "inner-hint");
        var fwd = new HintOverridingForwardingVM<string>(inner);

        fwd.Hint.Should().Be("OVERRIDE");
        fwd.Name.Should().Be("myVm");
    }

    // ── ForwardingCompositeVM: constructor guard ──────────────────────────────

    [Fact]
    public void ForwardingCompositeVM_Null_Throws_ArgumentNull()
    {
        Action act = () => _ = new NoOpForwardingCompositeVM<ComponentVM<string>>(null!);
        act.Should().Throw<ArgumentNullException>();
    }

    // ── ForwardingCompositeVM: IList<VM> delegation ──────────────────────────

    [Fact]
    public void ForwardingCompositeVM_Delegates_Count()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = ComponentVM<string>.Builder().Name("c").Services(hub, dispatcher).Model("m").Build();
        composite.Add(child);
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);
        fwd.Count.Should().Be(1);
    }

    [Fact]
    public void ForwardingCompositeVM_Delegates_Indexer()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = ComponentVM<string>.Builder().Name("c").Services(hub, dispatcher).Model("m").Build();
        composite.Add(child);
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);
        fwd[0].Should().BeSameAs(child);
    }

    [Fact]
    public void ForwardingCompositeVM_Delegates_Indexer_Setter()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = ComponentVM<string>.Builder().Name("c1").Services(hub, dispatcher).Model("m1").Build();
        var c2 = ComponentVM<string>.Builder().Name("c2").Services(hub, dispatcher).Model("m2").Build();
        composite.Add(c1);
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        fwd[0] = c2;

        composite[0].Should().BeSameAs(c2);
    }

    [Fact]
    public void ForwardingCompositeVM_Iteration_Matches_Wrapped()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = ComponentVM<string>.Builder().Name("c1").Services(hub, dispatcher).Model("m1").Build();
        var c2 = ComponentVM<string>.Builder().Name("c2").Services(hub, dispatcher).Model("m2").Build();
        composite.Add(c1);
        composite.Add(c2);
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        fwd.ToList().Should().ContainInOrder(c1, c2);
    }

    // ── ForwardingCompositeVM: CollectionChanged forwarding ───────────────────

    [Fact]
    public void ForwardingCompositeVM_Forwards_CollectionChanged()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        System.Collections.Specialized.NotifyCollectionChangedEventArgs? captured = null;
        fwd.CollectionChanged += (_, e) => captured = e;

        var child = ComponentVM<string>.Builder().Name("c").Services(hub, dispatcher).Model("m").Build();
        composite.Add(child);

        captured.Should().NotBeNull();
        captured!.Action.Should().Be(System.Collections.Specialized.NotifyCollectionChangedAction.Add);
    }

    // ── ForwardingCompositeVM: Current delegation ─────────────────────────────

    [Fact]
    public void ForwardingCompositeVM_Delegates_Current_Initially_Null()
    {
        var (composite, _, _) = BuildComposite();
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);
        fwd.Current.Should().BeNull();
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Gap-fill: ForwardingComponentVM coverage
    // ──────────────────────────────────────────────────────────────────────────

    [Fact]
    public void ForwardingComponentVM_Null_Throws_ArgumentNull()
    {
        Action act = () => _ = new NoOpForwardingVM<string>(null!);
        act.Should().Throw<ArgumentNullException>().WithParameterName("wrapped");
    }

    [Fact]
    public void ForwardingComponentVM_Delegates_IsCurrent()
    {
        var (inner, _, _) = BuildVm();
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.IsCurrent.Should().Be(inner.IsCurrent);
    }

    [Fact]
    public void ForwardingComponentVM_Delegates_ModeledHint()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var inner = ComponentVM<string>.Builder()
            .Name("vm")
            .Services(hub, dispatcher)
            .Model("model-value")
            .ModeledHinter(m => $"hint:{m}")
            .Build();
        var fwd = new NoOpForwardingVM<string>(inner);

        fwd.ModeledHint.Should().Be("hint:model-value");
    }

    [Fact]
    public void ForwardingComponentVM_Delegates_All_Commands_To_Wrapped()
    {
        var (inner, _, _) = BuildVm();
        var fwd = new NoOpForwardingVM<string>(inner);

        fwd.SelectCommand.Should().BeSameAs(inner.SelectCommand);
        fwd.DeselectCommand.Should().BeSameAs(inner.DeselectCommand);
        fwd.SelectNextCommand.Should().BeSameAs(inner.SelectNextCommand);
        fwd.SelectPreviousCommand.Should().BeSameAs(inner.SelectPreviousCommand);
        fwd.ReconstructCommand.Should().BeSameAs(inner.ReconstructCommand);
    }

    [Fact]
    public void ForwardingComponentVM_Delegates_CanConstruct()
    {
        var (inner, _, _) = BuildVm();
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.CanConstruct().Should().Be(inner.CanConstruct());
    }

    [Fact]
    public void ForwardingComponentVM_Delegates_CanDestruct_Mirrors_Wrapped()
    {
        var (inner, _, _) = BuildVm();
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.CanDestruct().Should().Be(inner.CanDestruct());
        inner.Construct();
        fwd.CanDestruct().Should().Be(inner.CanDestruct());
    }

    [Fact]
    public void ForwardingComponentVM_Delegates_CanReconstruct_Mirrors_Wrapped()
    {
        var (inner, _, _) = BuildVm();
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.CanReconstruct().Should().Be(inner.CanReconstruct());
        inner.Construct();
        fwd.CanReconstruct().Should().Be(inner.CanReconstruct());
    }

    [Fact]
    public async Task ForwardingComponentVM_ConstructAsync_Delegates_To_Wrapped()
    {
        var (inner, _, _) = BuildVm();
        var fwd = new NoOpForwardingVM<string>(inner);
        await fwd.ConstructAsync();
        inner.IsConstructed.Should().BeTrue();
    }

    [Fact]
    public async Task ForwardingComponentVM_DestructAsync_Delegates_To_Wrapped()
    {
        var (inner, _, _) = BuildVm();
        inner.Construct();
        var fwd = new NoOpForwardingVM<string>(inner);
        await fwd.DestructAsync();
        inner.IsConstructed.Should().BeFalse();
    }

    [Fact]
    public async Task ForwardingComponentVM_ReconstructAsync_Delegates_To_Wrapped()
    {
        var (inner, _, _) = BuildVm();
        inner.Construct();
        var fwd = new NoOpForwardingVM<string>(inner);
        await fwd.ReconstructAsync();
        inner.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void ForwardingComponentVM_Reconstruct_Delegates_To_Wrapped()
    {
        var (inner, _, _) = BuildVm();
        inner.Construct();
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.Reconstruct();
        inner.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void ForwardingComponentVM_Select_And_Deselect_Delegate_To_Wrapped()
    {
        // Wire up a parent composite so Select() has a real selection semantic.
        var (composite, hub, dispatcher) = BuildComposite();
        var child = ComponentVM<string>.Builder().Name("c").Services(hub, dispatcher).Model("m").Build();
        composite.Add(child);
        composite.Construct();

        var fwd = new NoOpForwardingVM<string>(child);

        fwd.CanSelect().Should().BeTrue();
        fwd.Select();
        composite.Current.Should().BeSameAs(child);
        child.IsCurrent.Should().BeTrue();

        fwd.CanDeselect().Should().BeTrue();
        fwd.Deselect();
        composite.Current.Should().BeNull();
    }

    [Fact]
    public void ForwardingComponentVM_Is_A_Transparent_Container_Child()
    {
        var (inner, hub, dispatcher) = BuildVm();
        var forwarding = new NoOpForwardingVM<string>(inner);
        var composite = CompositeVM<NoOpForwardingVM<string>>.Builder()
            .Name("root")
            .Services(hub, dispatcher)
            .Children(() => [])
            .Build();

        composite.Add(forwarding);
        composite.Construct();
        forwarding.SelectCommand.Execute(null);

        composite.Current.Should().BeSameAs(forwarding);
        forwarding.IsCurrent.Should().BeTrue();
        inner.IsCurrent.Should().BeTrue();
    }

    [Fact]
    public void ForwardingComponentVM_Forwards_PropertyChanged_For_Status_On_Construct()
    {
        var (inner, _, _) = BuildVm();
        var fwd = new NoOpForwardingVM<string>(inner);

        var fired = new List<string?>();
        fwd.PropertyChanged += (_, e) => fired.Add(e.PropertyName);

        inner.Construct();

        fired.Should().Contain(nameof(IComponentVM.Status));
        fired.Should().Contain(nameof(IComponentVM.IsConstructed));
    }

    [Fact]
    public void ForwardingComponentVM_Forwards_PropertyChanged_Unsubscribe_Stops_Notifications()
    {
        var (inner, _, _) = BuildVm(model: "a");
        var fwd = new NoOpForwardingVM<string>(inner);

        var fired = new List<string?>();
        PropertyChangedEventHandler handler = (_, e) => fired.Add(e.PropertyName);

        fwd.PropertyChanged += handler;
        inner.Model = "b";
        fired.Should().NotBeEmpty();

        var beforeCount = fired.Count;
        fwd.PropertyChanged -= handler;
        inner.Model = "c";
        fired.Count.Should().Be(beforeCount, "no further notifications should arrive after unsubscribe");
    }

    [Fact]
    public void ForwardingComponentVM_Forwards_ConstructionStatusChangedMessage_Through_Hub()
    {
        var (inner, hub, _) = BuildVm();
        // PropertyChanged event on the wrapper goes via the inner VM, which
        // is the same producer that emits ConstructionStatusChangedMessage on
        // the hub. Verifying this confirms notification forwarding parity.
        var fwd = new NoOpForwardingVM<string>(inner);

        var captured = new List<IConstructionStatusChangedMessage>();
        using var sub = hub.Messages
            .OfType<IConstructionStatusChangedMessage>()
            .Subscribe(captured.Add);

        fwd.Construct();

        captured.Should().NotBeEmpty();
        captured[^1].Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void ForwardingComponentVM_Dispose_Does_Not_Throw_When_Called_Twice()
    {
        var (inner, _, _) = BuildVm();
        var fwd = new NoOpForwardingVM<string>(inner);
        fwd.Dispose();
        Action act = () => fwd.Dispose();
        act.Should().NotThrow();
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Gap-fill: ForwardingCompositeVM coverage
    // ──────────────────────────────────────────────────────────────────────────

    [Fact]
    public void ForwardingCompositeVM_Delegates_Name_Hint_Type()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("compose")
            .Hint("composite-hint")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        fwd.Name.Should().Be("compose");
        fwd.Hint.Should().Be("composite-hint");
        fwd.Type.Should().Be(composite.Type);
    }

    [Fact]
    public void ForwardingCompositeVM_Delegates_State_Properties()
    {
        var (composite, _, _) = BuildComposite();
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        fwd.IsCurrent.Should().Be(composite.IsCurrent);
        fwd.IsConstructed.Should().Be(composite.IsConstructed);
        fwd.Status.Should().Be(composite.Status);
        fwd.IsReadOnly.Should().Be(composite.IsReadOnly);
    }

    [Fact]
    public void ForwardingCompositeVM_Delegates_All_Commands_To_Wrapped()
    {
        var (composite, _, _) = BuildComposite();
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        fwd.SelectCommand.Should().BeSameAs(composite.SelectCommand);
        fwd.DeselectCommand.Should().BeSameAs(composite.DeselectCommand);
        fwd.SelectNextCommand.Should().BeSameAs(composite.SelectNextCommand);
        fwd.SelectPreviousCommand.Should().BeSameAs(composite.SelectPreviousCommand);
        fwd.ReconstructCommand.Should().BeSameAs(composite.ReconstructCommand);
    }

    [Fact]
    public void ForwardingCompositeVM_Delegates_Lifecycle_Predicates_And_Operations()
    {
        var (composite, _, _) = BuildComposite();
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        fwd.CanConstruct().Should().Be(composite.CanConstruct());
        fwd.Construct();
        composite.IsConstructed.Should().BeTrue();

        fwd.CanDestruct().Should().Be(composite.CanDestruct());
        fwd.CanReconstruct().Should().Be(composite.CanReconstruct());

        fwd.Reconstruct();
        composite.Status.Should().Be(ConstructionStatus.Constructed);

        fwd.Destruct();
        composite.IsConstructed.Should().BeFalse();
    }

    [Fact]
    public async Task ForwardingCompositeVM_Async_Lifecycle_Delegates()
    {
        var (composite, _, _) = BuildComposite();
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        await fwd.ConstructAsync();
        composite.IsConstructed.Should().BeTrue();

        await fwd.ReconstructAsync();
        composite.Status.Should().Be(ConstructionStatus.Constructed);

        await fwd.DestructAsync();
        composite.IsConstructed.Should().BeFalse();
    }

    [Fact]
    public void ForwardingCompositeVM_Delegates_Selection_Predicates_And_Methods()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = ComponentVM<string>.Builder().Name("c").Services(hub, dispatcher).Model("m").Build();
        composite.Add(child);
        composite.Construct();

        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        // Composite is root, so its own CanSelect/CanDeselect mirror wrapped (no parent).
        fwd.CanSelect().Should().Be(composite.CanSelect());
        fwd.CanDeselect().Should().Be(composite.CanDeselect());

        // Child-selection methods do delegate to the inner composite.
        fwd.CanSelectComponent(child).Should().BeTrue();
        fwd.SelectComponent(child);
        composite.Current.Should().BeSameAs(child);

        fwd.DeselectComponent(child);
        composite.Current.Should().BeNull();

        // Wrapper's Select()/Deselect() forward to inner; with no parent both are no-ops.
        fwd.Select();
        fwd.Deselect();
    }

    [Fact]
    public void ForwardingCompositeVM_Delegates_Current_Setter()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = ComponentVM<string>.Builder().Name("c").Services(hub, dispatcher).Model("m").Build();
        composite.Add(child);
        composite.Construct();

        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        fwd.Current = child;
        composite.Current.Should().BeSameAs(child);

        fwd.Current = null;
        composite.Current.Should().BeNull();
    }

    [Fact]
    public void ForwardingCompositeVM_Delegates_IndexOf_Contains_And_CopyTo()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = ComponentVM<string>.Builder().Name("c1").Services(hub, dispatcher).Model("m1").Build();
        var c2 = ComponentVM<string>.Builder().Name("c2").Services(hub, dispatcher).Model("m2").Build();
        composite.Add(c1);
        composite.Add(c2);
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        fwd.IndexOf(c2).Should().Be(1);
        fwd.Contains(c1).Should().BeTrue();

        var buffer = new ComponentVM<string>[2];
        fwd.CopyTo(buffer, 0);
        buffer[0].Should().BeSameAs(c1);
        buffer[1].Should().BeSameAs(c2);
    }

    [Fact]
    public void ForwardingCompositeVM_Delegates_Mutation_Insert_Remove_RemoveAt_Clear()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = ComponentVM<string>.Builder().Name("c1").Services(hub, dispatcher).Model("m1").Build();
        var c2 = ComponentVM<string>.Builder().Name("c2").Services(hub, dispatcher).Model("m2").Build();
        var c3 = ComponentVM<string>.Builder().Name("c3").Services(hub, dispatcher).Model("m3").Build();
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        fwd.Add(c1);
        fwd.Insert(0, c2);
        composite[0].Should().BeSameAs(c2);
        composite[1].Should().BeSameAs(c1);

        fwd.Add(c3);
        fwd.Remove(c1).Should().BeTrue();
        composite.Contains(c1).Should().BeFalse();

        fwd.RemoveAt(0);
        composite[0].Should().BeSameAs(c3);

        fwd.Clear();
        composite.Count.Should().Be(0);
    }

    [Fact]
    public void ForwardingCompositeVM_Generic_GetEnumerator_Delegates()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = ComponentVM<string>.Builder().Name("c1").Services(hub, dispatcher).Model("m1").Build();
        composite.Add(c1);
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        // Explicit generic GetEnumerator() invocation.
        using var e = fwd.GetEnumerator();
        e.MoveNext().Should().BeTrue();
        e.Current.Should().BeSameAs(c1);
        e.MoveNext().Should().BeFalse();
    }

    [Fact]
    public void ForwardingCompositeVM_Non_Generic_IEnumerable_Delegates()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = ComponentVM<string>.Builder().Name("c").Services(hub, dispatcher).Model("m").Build();
        composite.Add(child);
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        // Non-generic IEnumerable path.
        System.Collections.IEnumerable nonGeneric = fwd;
        var seen = new List<object>();
        foreach (var item in nonGeneric)
            seen.Add(item);
        seen.Should().ContainSingle().Which.Should().BeSameAs(child);
    }

    [Fact]
    public void ForwardingCompositeVM_Forwards_PropertyChanged_Subscribe_And_Unsubscribe()
    {
        var (composite, _, _) = BuildComposite();
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        var fired = new List<string?>();
        PropertyChangedEventHandler handler = (_, e) => fired.Add(e.PropertyName);
        fwd.PropertyChanged += handler;

        composite.Construct();
        fired.Should().Contain(nameof(IComponentVM.Status));

        var before = fired.Count;
        fwd.PropertyChanged -= handler;
        composite.Destruct();
        fired.Count.Should().Be(before);
    }

    [Fact]
    public void ForwardingCompositeVM_Forwards_CollectionChanged_Unsubscribe_Stops_Notifications()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        var fired = new List<NotifyCollectionChangedEventArgs>();
        NotifyCollectionChangedEventHandler handler = (_, e) => fired.Add(e);
        fwd.CollectionChanged += handler;

        var c1 = ComponentVM<string>.Builder().Name("c1").Services(hub, dispatcher).Model("m1").Build();
        composite.Add(c1);
        fired.Should().NotBeEmpty();

        var beforeCount = fired.Count;
        fwd.CollectionChanged -= handler;
        var c2 = ComponentVM<string>.Builder().Name("c2").Services(hub, dispatcher).Model("m2").Build();
        composite.Add(c2);
        fired.Count.Should().Be(beforeCount, "no further notifications should arrive after unsubscribe");
    }

    [Fact]
    public void ForwardingCompositeVM_Dispose_Cascades_To_Wrapped_And_Idempotent()
    {
        var (composite, _, _) = BuildComposite();
        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        fwd.Dispose();
        composite.Status.Should().Be(ConstructionStatus.Disposed);

        Action act = () => fwd.Dispose();
        act.Should().NotThrow();
    }
}
