using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Forwarding;
using VMx.Lifecycle;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for the Forwarding decorators, covering FWD-001..003.
/// See spec/09-forwarding.md and spec/12-conformance.md.
/// </summary>
public class ForwardingConformanceTests
{
    // ── Concrete subclasses used only in this file ───────────────────────────

    /// <summary>No-op concrete subclass of ForwardingComponentVM — no members overridden.</summary>
    private sealed class NoOpForwardingVM<M> : ForwardingComponentVM<M>
    {
        public NoOpForwardingVM(IComponentVM<M> wrapped) : base(wrapped) { }
    }

    /// <summary>
    /// Overrides only <see cref="ForwardingComponentVM{M}.Hint"/>; all other members delegate.
    /// </summary>
    private sealed class HintOverridingForwardingVM<M> : ForwardingComponentVM<M>
    {
        public HintOverridingForwardingVM(IComponentVM<M> wrapped) : base(wrapped) { }

        public override string Hint => "OVERRIDE";
    }

    /// <summary>No-op concrete subclass of ForwardingCompositeVM — no members overridden.</summary>
    private sealed class NoOpForwardingCompositeVM<VM> : ForwardingCompositeVM<VM>
        where VM : class, IComponentVM
    {
        public NoOpForwardingCompositeVM(ICompositeVM<VM> wrapped) : base(wrapped) { }
    }

    // ── Factory helpers ──────────────────────────────────────────────────────

    private static (ComponentVM<string> vm, TestHub hub, TestDispatcher dispatcher) BuildWrapped(
        string name = "inner", string hint = "inner-hint", string model = "m0")
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name(name)
            .Hint(hint)
            .Services(hub, dispatcher)
            .Model(model)
            .Build();
        return (vm, hub, dispatcher);
    }

    private static (CompositeVM<ComponentVM<string>> composite, TestHub hub, TestDispatcher dispatcher)
        BuildWrappedComposite(string name = "composite")
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .Build();
        return (composite, hub, dispatcher);
    }

    // ── FWD-001 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// FWD-001: A no-op ForwardingComponentVM subclass delegates every IComponentVM member
    /// to the wrapped instance.
    /// </summary>
    [Fact, Trait("Conformance", "FWD-001")]
    public void FWD_001_NoOp_Subclass_Delegates_Every_Member_To_Wrapped()
    {
        var (inner, hub, _) = BuildWrapped();
        inner.Construct();

        var fwd = new NoOpForwardingVM<string>(inner);

        // Identity
        fwd.Name.Should().Be(inner.Name);
        fwd.Hint.Should().Be(inner.Hint);
        fwd.Type.Should().Be(inner.Type);

        // State
        fwd.IsCurrent.Should().Be(inner.IsCurrent);
        fwd.IsConstructed.Should().Be(inner.IsConstructed);
        fwd.Status.Should().Be(inner.Status);

        // Model
        fwd.Model.Should().Be(inner.Model);
        fwd.ModeledHint.Should().Be(inner.ModeledHint);

        // Commands: reference-equal (same object forwarded)
        fwd.SelectCommand.Should().BeSameAs(inner.SelectCommand);
        fwd.DeselectCommand.Should().BeSameAs(inner.DeselectCommand);
        fwd.SelectNextCommand.Should().BeSameAs(inner.SelectNextCommand);
        fwd.SelectPreviousCommand.Should().BeSameAs(inner.SelectPreviousCommand);
        fwd.ReconstructCommand.Should().BeSameAs(inner.ReconstructCommand);

        // Can-* methods
        fwd.CanConstruct().Should().Be(inner.CanConstruct());
        fwd.CanDestruct().Should().Be(inner.CanDestruct());
        fwd.CanReconstruct().Should().Be(inner.CanReconstruct());
        fwd.CanSelect().Should().Be(inner.CanSelect());
        fwd.CanDeselect().Should().Be(inner.CanDeselect());

        // Lifecycle methods: forwarding VM delegates Destruct to inner
        fwd.Destruct();
        inner.Status.Should().Be(ConstructionStatus.Destructed);
        fwd.Status.Should().Be(ConstructionStatus.Destructed);

        // Dispose: forwarded to inner
        fwd.Dispose();
        inner.Status.Should().Be(ConstructionStatus.Disposed);
    }

    // ── FWD-002 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// FWD-002: A subclass that overrides only Hint returns the override for Hint;
    /// all other members still delegate to the wrapped VM.
    /// </summary>
    [Fact, Trait("Conformance", "FWD-002")]
    public void FWD_002_Selective_Override_Replaces_Only_That_Member()
    {
        var (inner, _, _) = BuildWrapped(name: "inner", hint: "inner-hint", model: "m1");
        var fwd = new HintOverridingForwardingVM<string>(inner);

        // Overridden member returns override value
        fwd.Hint.Should().Be("OVERRIDE");
        inner.Hint.Should().Be("inner-hint"); // wrapped unchanged

        // All other identity members still delegate
        fwd.Name.Should().Be(inner.Name);
        fwd.Type.Should().Be(inner.Type);

        // State still delegates
        fwd.IsConstructed.Should().Be(inner.IsConstructed);
        fwd.Status.Should().Be(inner.Status);
        fwd.IsCurrent.Should().Be(inner.IsCurrent);

        // Model still delegates
        fwd.Model.Should().Be(inner.Model);
        fwd.ModeledHint.Should().Be(inner.ModeledHint);

        // Commands still delegate
        fwd.SelectCommand.Should().BeSameAs(inner.SelectCommand);
        fwd.DeselectCommand.Should().BeSameAs(inner.DeselectCommand);
        fwd.SelectNextCommand.Should().BeSameAs(inner.SelectNextCommand);
        fwd.SelectPreviousCommand.Should().BeSameAs(inner.SelectPreviousCommand);
        fwd.ReconstructCommand.Should().BeSameAs(inner.ReconstructCommand);
    }

    // ── FWD-003 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// FWD-003: ForwardingCompositeVM forwards iteration and yields the same elements
    /// as the wrapped composite in the same order.
    /// </summary>
    [Fact, Trait("Conformance", "FWD-003")]
    public void FWD_003_ForwardingCompositeVM_Forwards_Iteration()
    {
        var (composite, hub, dispatcher) = BuildWrappedComposite();

        var vm1 = ComponentVM<string>.Builder()
            .Name("vm1").Services(hub, dispatcher).Model("m1").Build();
        var vm2 = ComponentVM<string>.Builder()
            .Name("vm2").Services(hub, dispatcher).Model("m2").Build();

        composite.Add(vm1);
        composite.Add(vm2);

        var fwd = new NoOpForwardingCompositeVM<ComponentVM<string>>(composite);

        // Iteration via IEnumerable<VM> yields vm1, vm2 in order
        var items = fwd.ToList();
        items.Should().HaveCount(2);
        items[0].Should().BeSameAs(vm1);
        items[1].Should().BeSameAs(vm2);
    }
}
