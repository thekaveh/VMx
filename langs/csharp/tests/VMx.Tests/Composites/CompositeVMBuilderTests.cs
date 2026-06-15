using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Composites;

/// <summary>
/// Unit tests for <see cref="CompositeVMBuilder{VM}"/> declarative hooks
/// added in spec v2.6.0: <c>Current(selector)</c> and
/// <c>OnCurrentChanged(callback)</c>. See ADR-0042 and spec/06 §3.2.
/// Conformance-level tests live in VMx.Conformance.Tests.
/// </summary>
public class CompositeVMBuilderTests
{
    // ── Helpers ──────────────────────────────────────────────────────────────

    private static ComponentVM<string> BuildChild(
        TestHub hub, TestDispatcher dispatcher, string name)
        => ComponentVM<string>.Builder()
            .Name(name).Services(hub, dispatcher).Model(name).Build();

    // ── Current(selector) — non-modeled ─────────────────────────────────────

    [Fact]
    public void Current_Selector_Drives_Initial_Selection_After_Construct()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var a = BuildChild(hub, dispatcher, "a");
        var b = BuildChild(hub, dispatcher, "b");
        var c = BuildChild(hub, dispatcher, "c");

        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(hub, dispatcher)
            .Children(() => new[] { a, b, c })
            .Current(xs => xs.Skip(1).First())
            .Build();

        composite.Construct();

        composite.Current.Should().BeSameAs(b);
    }

    [Fact]
    public void Current_Selector_Returning_Null_Leaves_Current_At_Null()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var a = BuildChild(hub, dispatcher, "a");

        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(hub, dispatcher)
            .Children(() => new[] { a })
            .Current(_ => null)
            .Build();

        composite.Construct();

        composite.Current.Should().BeNull();
    }

    [Fact]
    public void OnCurrentChanged_Does_Not_Fire_When_Selector_Returns_Null_Or_Out_Of_Set()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var observed = new List<ComponentVM<string>?>();

        // Case 1: selector returns null → no Current change, no callback.
        // Each composite owns its own child instance — Add() calls
        // SetParent(this) on the child, so sharing a child across composites
        // would silently re-point its Parent. Use distinct fixtures to keep
        // the invariant "a child VM has at most one parent" intact.
        var a1 = BuildChild(hub, dispatcher, "a1");
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite-null")
            .Services(hub, dispatcher)
            .Children(() => new[] { a1 })
            .Current(_ => null)
            .OnCurrentChanged(vm => observed.Add(vm))
            .Build();

        composite.Construct();

        observed.Should().BeEmpty();

        // Case 2: selector returns a VM not in the composite → no Current change, no callback.
        var a2 = BuildChild(hub, dispatcher, "a2");
        var foreign = BuildChild(hub, dispatcher, "foreign");
        var composite2 = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite-foreign")
            .Services(hub, dispatcher)
            .Children(() => new[] { a2 })
            .Current(_ => foreign)
            .OnCurrentChanged(vm => observed.Add(vm))
            .Build();

        composite2.Construct();

        observed.Should().BeEmpty();
    }

    // ── OnCurrentChanged(callback) — non-modeled ────────────────────────────

    [Fact]
    public void OnCurrentChanged_Fires_After_Each_Current_Change()
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
    }

    [Fact]
    public void OnCurrentChanged_Fires_Once_For_Initial_Selector()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var a = BuildChild(hub, dispatcher, "a");
        var observed = new List<ComponentVM<string>?>();

        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(hub, dispatcher)
            .Children(() => new[] { a })
            .Current(xs => xs.First())
            .OnCurrentChanged(vm => observed.Add(vm))
            .Build();

        composite.Construct();

        observed.Should().Equal(a);
    }
}
