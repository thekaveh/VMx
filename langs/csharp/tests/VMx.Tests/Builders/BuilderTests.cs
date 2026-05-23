using FluentAssertions;
using VMx.Builders;
using VMx.Components;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Builders;

/// <summary>
/// Unit tests verifying the four builder invariants for ComponentVM&lt;string&gt;.
/// Conformance-level IDs (BLD-001..004) live in VMx.Conformance.Tests.
/// </summary>
public class BuilderTests
{
    // ── Helpers ──────────────────────────────────────────────────────────────

    private static (TestHub hub, TestDispatcher dispatcher) MakeServices()
        => (new TestHub(), new TestDispatcher());

    private static ComponentVM<string> BuildMinimal(TestHub hub, TestDispatcher dispatcher,
        string name = "vm1", string model = "m")
        => ComponentVM<string>.Builder()
            .Name(name)
            .Model(model)
            .Services(hub, dispatcher)
            .Build();

    // ── Immutability (BLD-001 invariant) ──────────────────────────────────────

    /// <summary>
    /// Every fluent setter returns a NEW builder instance.
    /// </summary>
    [Fact]
    public void Setter_Returns_New_Builder_Instance()
    {
        var b1 = ComponentVM<string>.Builder();
        var b2 = b1.Name("x");

        object.ReferenceEquals(b1, b2).Should().BeFalse(
            "each setter must return a distinct builder (immutability / BLD-001)");
    }

    /// <summary>
    /// The original builder is unaffected by a setter call on a derived builder.
    /// Verified by confirming b1 still raises on Build() due to missing Name.
    /// </summary>
    [Fact]
    public void Original_Builder_Unchanged_After_Setter()
    {
        var b1 = ComponentVM<string>.Builder();
        _ = b1.Name("x"); // discard the derived builder; b1 must be unaffected

        var act = () => b1.Build();
        act.Should().Throw<BuilderValidationException>()
            .Which.MissingField.Should().Be("Name");
    }

    /// <summary>
    /// The derived builder carries the updated value: building with it produces a VM
    /// whose Name equals the value passed to the setter.
    /// </summary>
    [Fact]
    public void Derived_Builder_Carries_Updated_Value()
    {
        var (hub, dispatcher) = MakeServices();
        var vm = ComponentVM<string>.Builder()
            .Name("x")
            .Model("m")
            .Services(hub, dispatcher)
            .Build();

        vm.Name.Should().Be("x");
    }

    // ── Validation (BLD-002 invariant) ────────────────────────────────────────

    [Fact]
    public void Build_Without_Name_Raises_BuilderValidationException()
    {
        var (hub, dispatcher) = MakeServices();
        var act = () => ComponentVM<string>.Builder()
            .Model("m")
            .Services(hub, dispatcher)
            .Build();

        act.Should().Throw<BuilderValidationException>()
            .Which.MissingField.Should().Be("Name");
    }

    [Fact]
    public void Build_Without_Model_Raises_BuilderValidationException()
    {
        var (hub, dispatcher) = MakeServices();
        var act = () => ComponentVM<string>.Builder()
            .Name("vm")
            .Services(hub, dispatcher)
            .Build();

        act.Should().Throw<BuilderValidationException>()
            .Which.MissingField.Should().Be("Model");
    }

    [Fact]
    public void Build_Without_Services_Raises_BuilderValidationException()
    {
        var act = () => ComponentVM<string>.Builder()
            .Name("vm")
            .Model("m")
            .Build();

        // "Hub" or "Dispatcher" — either is the first services field missing.
        act.Should().Throw<BuilderValidationException>()
            .Which.MissingField.Should().BeOneOf("Hub", "Dispatcher");
    }

    // ── Repeated Build() calls (BLD-003 invariant) ───────────────────────────

    [Fact]
    public void Repeated_Build_Produces_Distinct_Equivalent_VMs()
    {
        var (hub, dispatcher) = MakeServices();
        var builder = ComponentVM<string>.Builder()
            .Name("vm1")
            .Hint("hint1")
            .Model("model1")
            .Services(hub, dispatcher);

        var vmA = builder.Build();
        var vmB = builder.Build();

        object.ReferenceEquals(vmA, vmB).Should().BeFalse("each Build() must produce a new instance");
        vmA.Name.Should().Be(vmB.Name);
        vmA.Hint.Should().Be(vmB.Hint);
        vmA.Type.Should().Be(vmB.Type);
        vmA.Model.Should().Be(vmB.Model);
    }

    // ── Default values (BLD-004 invariant) ───────────────────────────────────

    [Fact]
    public void Defaults_Applied_When_Optional_Fields_Not_Set()
    {
        var (hub, dispatcher) = MakeServices();
        var vm = BuildMinimal(hub, dispatcher);

        vm.Hint.Should().BeEmpty("Hint defaults to empty string");
        vm.Type.Should().Be(ViewModelType.Component,
            "Type defaults to Component for ComponentVM<M>");
        // Parent is internal; proxy check: CanSelect() is false when no parent is set.
        vm.CanSelect().Should().BeFalse("no parent was set so CanSelect() must be false");
    }
}
