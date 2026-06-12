using System.Reactive.Linq;
using System.Reactive.Subjects;
using FluentAssertions;
using VMx.Builders;
using VMx.Commands;
using VMx.Components;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for builder semantics: BLD-001..005.
/// Representative VM: <see cref="ComponentVM{M}"/> with M = string.
/// See spec/10-builders.md and spec/12-conformance.md §Builders.
/// </summary>
public class BuilderConformanceTests
{
    // ── Helpers ──────────────────────────────────────────────────────────────

    private static (TestHub hub, TestDispatcher dispatcher) MakeServices()
        => (new TestHub(), new TestDispatcher());

    // ── BLD-001 — Setter returns a new builder instance ───────────────────────

    /// <summary>
    /// BLD-001: Given a freshly created builder b1, when b2 = b1.Name("x"),
    /// then b1 and b2 are different instances and b1 does not carry the update.
    /// </summary>
    [Fact, Trait("Conformance", "BLD-001")]
    public void BLD_001_Setter_Returns_New_Builder_Instance()
    {
        var b1 = ComponentVM<string>.Builder();
        var b2 = b1.Name("x");

        // b1 and b2 must be distinct objects.
        object.ReferenceEquals(b1, b2).Should().BeFalse(
            "each setter must return a new builder instance");

        // b1 is still empty — it never had Name set.
        // Verified observationally: Build() on b1 raises for missing "Name".
        var actB1 = () => b1.Build();
        actB1.Should().Throw<BuilderValidationException>()
            .Which.MissingField.Should().Be("Name",
                "b1 must still be missing Name after b2 = b1.Name(\"x\")");

        // b2 carries the updated Name — verify by completing the build.
        var (hub, dispatcher) = MakeServices();
        var vm = b2.Model("m").Services(hub, dispatcher).Build();
        vm.Name.Should().Be("x", "b2.Name(\"x\") must have propagated to the built VM");
    }

    // ── BLD-002 — Required fields validated on Build ──────────────────────────

    /// <summary>
    /// BLD-002: Given a builder missing the required Services call,
    /// when Build() is called, then BuilderValidationException is raised and
    /// its MissingField property identifies the missing field.
    /// </summary>
    [Fact, Trait("Conformance", "BLD-002")]
    public void BLD_002_Missing_Required_Field_Raises_BuilderValidationException()
    {
        // Build without Services (hub + dispatcher).
        var act = () => ComponentVM<string>.Builder()
            .Name("vm1")
            .Model("initial")
            // deliberately omitting .Services(hub, dispatcher)
            .Build();

        act.Should().Throw<BuilderValidationException>(
                "Build() must raise when a required field is missing")
            .Which.MissingField.Should().BeOneOf("Hub", "Dispatcher",
                "the exception must identify the first missing services field by name");
    }

    // ── BLD-003 — Repeated identical Build calls produce equivalent VMs ───────

    /// <summary>
    /// BLD-003: Given a fully-configured builder, when Build() is called twice,
    /// then the two VMs are distinct instances but carry equivalent field values.
    /// </summary>
    [Fact, Trait("Conformance", "BLD-003")]
    public void BLD_003_Repeated_Build_Calls_Produce_Equivalent_But_Distinct_VMs()
    {
        var (hub, dispatcher) = MakeServices();
        var builder = ComponentVM<string>.Builder()
            .Name("vm1")
            .Hint("hint1")
            .Model("model1")
            .Services(hub, dispatcher);

        var vmA = builder.Build();
        var vmB = builder.Build();

        object.ReferenceEquals(vmA, vmB).Should().BeFalse(
            "each Build() call must produce a new VM instance");
        vmA.Name.Should().Be(vmB.Name, "Name must be equal across builds");
        vmA.Hint.Should().Be(vmB.Hint, "Hint must be equal across builds");
        vmA.Type.Should().Be(vmB.Type, "Type must be equal across builds");
        vmA.Model.Should().Be(vmB.Model, "Model must be equal across builds");
    }

    // ── BLD-004 — Field defaults applied when not set ─────────────────────────

    /// <summary>
    /// BLD-004: Given a builder configured with only the required fields,
    /// when Build() is called, then optional fields default as specified:
    /// Hint == "", Parent == null (verified via CanSelect() == false),
    /// Type == Component (the type derived from ComponentVM&lt;M&gt;).
    /// </summary>
    [Fact, Trait("Conformance", "BLD-004")]
    public void BLD_004_Default_Values_Applied_When_Fields_Not_Set()
    {
        var (hub, dispatcher) = MakeServices();
        var vm = ComponentVM<string>.Builder()
            .Name("vm1")
            .Model("initial")
            .Services(hub, dispatcher)
            .Build();

        vm.Hint.Should().BeEmpty("Hint must default to empty string per spec/10-builders.md");
        vm.Type.Should().Be(ViewModelType.Component,
            "Type must default to Component for ComponentVM<M>");
        // Parent is an internal field; observable proxy: CanSelect() is false
        // when no parent composite has been set.
        vm.CanSelect().Should().BeFalse(
            "Parent defaults to null, so CanSelect() must be false");
    }

    // ── BLD-005 — Additive setters retain prior values across repeated calls ──

    /// <summary>
    /// BLD-005: Given a RelayCommand builder b1, when b2 = b1.Triggers(o1)
    /// and b3 = b2.Triggers(o2) are called with distinct observables,
    /// then the resulting command's CanExecuteChanged fires for BOTH triggers
    /// (cumulative, not overwriting). Other setters (e.g., Name, Task)
    /// continue to overwrite per BLD-001's standard semantics. See ADR-0035.
    /// </summary>
    [Fact, Trait("Conformance", "BLD-005")]
    public void BLD_005_Additive_Setters_Retain_Prior_Values_Across_Repeated_Calls()
    {
        var trigger1 = new Subject<System.Reactive.Unit>();
        var trigger2 = new Subject<System.Reactive.Unit>();

        var cmd = RelayCommand.Builder()
            .Triggers(trigger1)
            .Triggers(trigger2)
            .Build();

        var firings = 0;
        cmd.CanExecuteChanged += (_, _) => firings++;

        trigger1.OnNext(default);
        firings.Should().Be(1, "first trigger must fire CanExecuteChanged");

        trigger2.OnNext(default);
        firings.Should().Be(2,
            "second trigger must ALSO fire CanExecuteChanged — Triggers is additive");

        // Insertion order (catalog And-clause): derive both triggers from ONE
        // parent emission and record which trigger's chain delivers first —
        // the merged stream subscribes its sources in insertion order, so
        // o1's Do must run before o2's. (A sequential OnNext/OnNext probe is
        // vacuous: it passes regardless of subscription order.)
        var parent = new Subject<System.Reactive.Unit>();
        var via = new List<string>();
        var o1 = parent.Do(_ => via.Add("via-o1"));
        var o2 = parent.Do(_ => via.Add("via-o2"));
        var orderCmd = RelayCommand.Builder().Triggers(o1).Triggers(o2).Build();
        orderCmd.CanExecuteChanged += (_, _) => { };
        parent.OnNext(default);
        via.Should().Equal("via-o1", "via-o2");

        // Non-additive setters overwrite on repeated calls (catalog And-clause).
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = Components.ComponentVM<string>.Builder()
            .Name("first").Name("second").Services(hub, dispatcher).Model("m").Build();
        vm.Name.Should().Be("second", "Name() must overwrite, not accumulate");
    }
}
