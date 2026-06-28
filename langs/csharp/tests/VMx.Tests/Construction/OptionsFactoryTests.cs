using FluentAssertions;
using VMx.Builders;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Construction;

/// <summary>
/// Verifies the additive positional-options construction form (ADR-0055 / VMX-020):
/// each <c>Create(options)</c> factory produces a VM equivalent to the fluent
/// builder path and validates the same required fields. The factory delegates to
/// the builder internally, so behaviour/validation are identical by construction;
/// these tests pin that contract.
/// </summary>
public class OptionsFactoryTests
{
    private static (TestHub hub, TestDispatcher dispatcher) MakeServices()
        => (new TestHub(), new TestDispatcher());

    // ── ComponentVM (non-modeled) ────────────────────────────────────────────

    [Fact]
    public void ComponentVM_Create_Matches_Builder()
    {
        var (hub, dispatcher) = MakeServices();

        var viaBuilder = ComponentVM.Builder()
            .Name("vm").Hint("h").Services(hub, dispatcher).Build();
        var viaOptions = ComponentVM.Create(new ComponentVMOptions
        {
            Name = "vm",
            Hint = "h",
            Hub = hub,
            Dispatcher = dispatcher,
        });

        viaOptions.Name.Should().Be(viaBuilder.Name);
        viaOptions.Hint.Should().Be(viaBuilder.Hint);
        viaOptions.Type.Should().Be(viaBuilder.Type);
        viaOptions.Status.Should().Be(viaBuilder.Status);
    }

    [Fact]
    public void ComponentVM_Create_Constructs_Like_Builder()
    {
        var (hub, dispatcher) = MakeServices();
        var vm = ComponentVM.Create(new ComponentVMOptions
        {
            Name = "vm",
            Hub = hub,
            Dispatcher = dispatcher,
        });

        vm.Construct();
        vm.IsConstructed.Should().BeTrue();
    }

    [Fact]
    public void ComponentVM_Create_Without_Hub_Raises_BuilderValidationException()
    {
        var act = () => ComponentVM.Create(new ComponentVMOptions { Name = "vm" });

        act.Should().Throw<BuilderValidationException>()
            .Which.MissingField.Should().BeOneOf("Hub", "Dispatcher");
    }

    [Fact]
    public void ComponentVM_Create_Without_Name_Raises_BuilderValidationException()
    {
        var (hub, dispatcher) = MakeServices();
        var act = () => ComponentVM.Create(new ComponentVMOptions
        {
            Hub = hub,
            Dispatcher = dispatcher,
        });

        act.Should().Throw<BuilderValidationException>()
            .Which.MissingField.Should().Be("Name");
    }

    // ── ComponentVM<M> (modeled) ─────────────────────────────────────────────

    [Fact]
    public void ComponentVMOfM_Create_Matches_Builder()
    {
        var (hub, dispatcher) = MakeServices();

        var viaBuilder = ComponentVM<string>.Builder()
            .Name("vm").Hint("h").Model("m").Services(hub, dispatcher).Build();
        var viaOptions = ComponentVM<string>.Create(new ComponentVMOptions<string>
        {
            Name = "vm",
            Hint = "h",
            Model = "m",
            Hub = hub,
            Dispatcher = dispatcher,
        });

        viaOptions.Name.Should().Be(viaBuilder.Name);
        viaOptions.Hint.Should().Be(viaBuilder.Hint);
        viaOptions.Type.Should().Be(viaBuilder.Type);
        viaOptions.Model.Should().Be(viaBuilder.Model);
    }

    [Fact]
    public void ComponentVMOfM_Create_Carries_Optional_Fields()
    {
        var (hub, dispatcher) = MakeServices();
        var changes = new List<string>();

        var vm = ComponentVM<string>.Create(new ComponentVMOptions<string>
        {
            Name = "vm",
            Model = "m0",
            ModeledHinter = m => $"hint:{m}",
            OnModelChanged = changes.Add,
            Hub = hub,
            Dispatcher = dispatcher,
        });

        vm.ModeledHint.Should().Be("hint:m0");
        vm.Model = "m1";
        vm.Model.Should().Be("m1");
        changes.Should().ContainSingle().Which.Should().Be("m1");
    }

    [Fact]
    public void ComponentVMOfM_Create_Without_Hub_Raises_BuilderValidationException()
    {
        var act = () => ComponentVM<string>.Create(new ComponentVMOptions<string>
        {
            Name = "vm",
            Model = "m",
        });

        act.Should().Throw<BuilderValidationException>()
            .Which.MissingField.Should().BeOneOf("Hub", "Dispatcher");
    }

    // ── CompositeVM<VM> (non-modeled) ────────────────────────────────────────

    [Fact]
    public void CompositeVM_Create_Matches_Builder_And_Populates_On_Construct()
    {
        var (hub, dispatcher) = MakeServices();

        ComponentVM Child() => ComponentVM.Create(new ComponentVMOptions
        {
            Name = "child",
            Hub = hub,
            Dispatcher = dispatcher,
        });

        var vm = CompositeVM<ComponentVM>.Create(new CompositeVMOptions<ComponentVM>
        {
            Name = "comp",
            Hint = "h",
            Hub = hub,
            Dispatcher = dispatcher,
            Children = () => new[] { Child() },
        });

        vm.Name.Should().Be("comp");
        vm.Hint.Should().Be("h");
        vm.Type.Should().Be(ViewModelType.Composite);
        vm.Count.Should().Be(0, "children factory is invoked lazily on Construct");

        vm.Construct();
        vm.Status.Should().Be(ConstructionStatus.Constructed);
        vm.Count.Should().Be(1);
    }

    [Fact]
    public void CompositeVM_Create_Without_Children_Raises_BuilderValidationException()
    {
        var (hub, dispatcher) = MakeServices();
        var act = () => CompositeVM<ComponentVM>.Create(new CompositeVMOptions<ComponentVM>
        {
            Name = "comp",
            Hub = hub,
            Dispatcher = dispatcher,
        });

        act.Should().Throw<BuilderValidationException>()
            .Which.MissingField.Should().Be("Children");
    }

    [Fact]
    public void CompositeVM_Create_Without_Hub_Raises_BuilderValidationException()
    {
        var act = () => CompositeVM<ComponentVM>.Create(new CompositeVMOptions<ComponentVM>
        {
            Name = "comp",
            Children = Array.Empty<ComponentVM>,
        });

        act.Should().Throw<BuilderValidationException>()
            .Which.MissingField.Should().BeOneOf("Hub", "Dispatcher");
    }

    // ── GroupVM<VM> (non-modeled) ────────────────────────────────────────────

    [Fact]
    public void GroupVM_Create_Matches_Builder_And_Populates_On_Construct()
    {
        var (hub, dispatcher) = MakeServices();

        ComponentVM Child() => ComponentVM.Create(new ComponentVMOptions
        {
            Name = "child",
            Hub = hub,
            Dispatcher = dispatcher,
        });

        var vm = GroupVM<ComponentVM>.Create(new GroupVMOptions<ComponentVM>
        {
            Name = "grp",
            Hub = hub,
            Dispatcher = dispatcher,
            Children = () => new[] { Child(), Child() },
        });

        vm.Name.Should().Be("grp");
        vm.Type.Should().Be(ViewModelType.Group);

        vm.Construct();
        vm.Status.Should().Be(ConstructionStatus.Constructed);
        vm.Count.Should().Be(2);
    }

    [Fact]
    public void GroupVM_Create_Without_Children_Raises_BuilderValidationException()
    {
        var (hub, dispatcher) = MakeServices();
        var act = () => GroupVM<ComponentVM>.Create(new GroupVMOptions<ComponentVM>
        {
            Name = "grp",
            Hub = hub,
            Dispatcher = dispatcher,
        });

        act.Should().Throw<BuilderValidationException>()
            .Which.MissingField.Should().Be("Children");
    }
}
