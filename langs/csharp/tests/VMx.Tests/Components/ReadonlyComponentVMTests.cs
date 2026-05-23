using System.Reflection;
using FluentAssertions;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Components;

/// <summary>
/// Unit tests for <see cref="ReadonlyComponentVM{M}"/>, focusing on
/// the read-only model contract and immutability guarantees.
/// </summary>
public class ReadonlyComponentVMTests
{
    private static (ReadonlyComponentVM<string> vm, TestHub hub, TestDispatcher dispatcher) BuildVm(
        string name = "ro1", string model = "fixedModel")
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ReadonlyComponentVM<string>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .Model(model)
            .Build();
        return (vm, hub, dispatcher);
    }

    // ── Identity ─────────────────────────────────────────────────────────────

    [Fact]
    public void Name_Is_Set_From_Builder()
    {
        var (vm, _, _) = BuildVm("readonlyVm");
        vm.Name.Should().Be("readonlyVm");
    }

    [Fact]
    public void Type_Is_ReadOnlyComponent()
    {
        var (vm, _, _) = BuildVm();
        vm.Type.Should().Be(ViewModelType.ReadOnlyComponent);
    }

    // ── Model immutability ────────────────────────────────────────────────────

    [Fact]
    public void Model_Equals_Value_From_Builder()
    {
        var (vm, _, _) = BuildVm(model: "hello");
        vm.Model.Should().Be("hello");
    }

    [Fact]
    public void Model_Has_No_Public_Setter()
    {
        var prop = typeof(ReadonlyComponentVM<string>)
            .GetProperty(nameof(ReadonlyComponentVM<string>.Model),
                BindingFlags.Public | BindingFlags.Instance);
        prop.Should().NotBeNull();
        prop!.CanWrite.Should().BeFalse("ReadonlyComponentVM.Model must not have a public setter");
        // Also verify there's no non-public setter
        prop.GetSetMethod(nonPublic: true).Should().BeNull(
            "ReadonlyComponentVM.Model must have no setter at all");
    }

    [Fact]
    public void ModeledHint_Is_Computed_From_Builder_Hinter()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ReadonlyComponentVM<int>.Builder()
            .Name("ro").Services(hub, dispatcher).Model(42)
            .ModeledHinter(n => $"val:{n}")
            .Build();
        vm.ModeledHint.Should().Be("val:42");
    }

    [Fact]
    public void ModeledHint_Defaults_To_Empty_When_No_Hinter()
    {
        var (vm, _, _) = BuildVm();
        vm.ModeledHint.Should().BeEmpty();
    }

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    [Fact]
    public void Initial_Status_Is_Destructed()
    {
        var (vm, _, _) = BuildVm();
        vm.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public void Construct_Transitions_To_Constructed()
    {
        var (vm, _, _) = BuildVm();
        vm.Construct();
        vm.Status.Should().Be(ConstructionStatus.Constructed);
        vm.IsConstructed.Should().BeTrue();
    }

    // ── Builder validation ─────────────────────────────────────────────────────

    [Fact]
    public void Builder_Throws_When_Name_Missing()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var act = () => ReadonlyComponentVM<string>.Builder()
            .Services(hub, dispatcher).Model("m").Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>()
            .Which.MissingField.Should().Be("Name");
    }

    [Fact]
    public void Builder_Throws_When_Model_Missing()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var act = () => ReadonlyComponentVM<string>.Builder()
            .Name("v").Services(hub, dispatcher).Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>()
            .Which.MissingField.Should().Be("Model");
    }

    [Fact]
    public void Builder_Is_Immutable()
    {
        var b0 = ReadonlyComponentVM<string>.Builder();
        var b1 = b0.Name("x");
        b1.Should().NotBeSameAs(b0);
    }

    // ── Name and Hint are immutable post-construction ─────────────────────────

    [Fact]
    public void Name_Has_No_Public_Setter()
    {
        var prop = typeof(ReadonlyComponentVM<string>)
            .GetProperty(nameof(ReadonlyComponentVM<string>.Name),
                BindingFlags.Public | BindingFlags.Instance);
        prop.Should().NotBeNull();
        prop!.CanWrite.Should().BeFalse();
    }

    [Fact]
    public void Hint_Has_No_Public_Setter()
    {
        var prop = typeof(ReadonlyComponentVM<string>)
            .GetProperty(nameof(ReadonlyComponentVM<string>.Hint),
                BindingFlags.Public | BindingFlags.Instance);
        prop.Should().NotBeNull();
        prop!.CanWrite.Should().BeFalse();
    }
}
