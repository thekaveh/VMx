using FluentAssertions;
using VMx.Components;
using VMx.Services;
using Xunit;

namespace VMx.Tests.Components;

/// <summary>
/// Unit tests for <see cref="ComponentVMBuilderExtensions"/>. Verifies that
/// <c>WithNullServices()</c> wires <see cref="NullMessageHub.Instance"/> and
/// <see cref="NullDispatcher.Instance"/> so the builder can <c>Build()</c>
/// without an explicit <c>Services(...)</c> call.
/// </summary>
public class ComponentVMBuilderExtensionsTests
{
    [Fact]
    public void Modeled_Builder_With_Null_Services_Builds()
    {
        var vm = ComponentVM<string>.Builder()
            .Name("vm")
            .Model("m")
            .WithNullServices()
            .Build();

        vm.Should().NotBeNull();
        vm.Name.Should().Be("vm");
        vm.Model.Should().Be("m");
    }

    [Fact]
    public void Unmodeled_Builder_With_Null_Services_Builds()
    {
        var vm = ComponentVM.Builder()
            .Name("vm")
            .WithNullServices()
            .Build();

        vm.Should().NotBeNull();
        vm.Name.Should().Be("vm");
    }

    [Fact]
    public void Readonly_Builder_With_Null_Services_Builds()
    {
        var vm = ReadonlyComponentVM<string>.Builder()
            .Name("ro")
            .Model("m")
            .WithNullServices()
            .Build();

        vm.Should().NotBeNull();
        vm.Name.Should().Be("ro");
        vm.Model.Should().Be("m");
    }

    [Fact]
    public void With_Null_Services_Is_Chainable_Before_Other_Setters()
    {
        // Ordering should be irrelevant — the builder is immutable and each
        // setter returns a new instance.
        var vm = ComponentVM<string>.Builder()
            .WithNullServices()
            .Name("vm")
            .Model("m")
            .Hint("h")
            .Build();

        vm.Name.Should().Be("vm");
        vm.Hint.Should().Be("h");
    }
}
