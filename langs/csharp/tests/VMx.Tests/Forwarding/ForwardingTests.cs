using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Forwarding;
using VMx.Lifecycle;
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
}
