using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Composites;

/// <summary>
/// Unit tests specific to the modeled variant <see cref="CompositeVMOfM{M,VM}"/>
/// (COMP-007 and related). Non-modeled tests are in <see cref="CompositeVMTests"/>.
/// </summary>
public class ModeledCompositeVMTests
{
    private sealed record Model(int Id, string Label);

    private static (CompositeVMOfM<Model, ComponentVM<Model>> composite, TestHub hub, TestDispatcher dispatcher)
        BuildModeled(string name = "root")
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var models = new[] { new Model(1, "A"), new Model(2, "B") };
        var composite = CompositeVMOfM<Model, ComponentVM<Model>>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .ChildrenModels(() => models)
            .ChildModelToChildViewModel(m => ComponentVM<Model>.Builder()
                .Name($"vm-{m.Id}").Services(hub, dispatcher).Model(m).Build())
            .Build();
        return (composite, hub, dispatcher);
    }

    // ── Children populated from model factory ───────────────────────────────

    [Fact]
    public void Construct_Populates_Children_From_Model_Factory()
    {
        var (composite, _, _) = BuildModeled();

        composite.Construct();

        composite.Count.Should().Be(2);
    }

    [Fact]
    public void Construct_Maps_Models_To_ViewModels()
    {
        var (composite, _, _) = BuildModeled();

        composite.Construct();

        composite[0].Model.Id.Should().Be(1);
        composite[1].Model.Id.Should().Be(2);
    }

    [Fact]
    public void Construct_All_Children_Reach_Constructed()
    {
        var (composite, _, _) = BuildModeled();

        composite.Construct();

        composite[0].Status.Should().Be(ConstructionStatus.Constructed);
        composite[1].Status.Should().Be(ConstructionStatus.Constructed);
        composite.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void Destruct_All_Children_Reach_Destructed()
    {
        var (composite, _, _) = BuildModeled();
        composite.Construct();

        composite.Destruct();

        composite[0].Status.Should().Be(ConstructionStatus.Destructed);
        composite[1].Status.Should().Be(ConstructionStatus.Destructed);
        composite.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // ── Factory evaluated lazily ─────────────────────────────────────────────

    [Fact]
    public void Children_Factory_Not_Evaluated_Before_Construct()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var evaluations = 0;
        var composite = CompositeVMOfM<Model, ComponentVM<Model>>.Builder()
            .Name("c").Services(hub, dispatcher)
            .ChildrenModels(() => { evaluations++; return [new Model(1, "X")]; })
            .ChildModelToChildViewModel(m => ComponentVM<Model>.Builder()
                .Name("v").Services(hub, dispatcher).Model(m).Build())
            .Build();

        evaluations.Should().Be(0);

        composite.Construct();

        evaluations.Should().Be(1);
    }

    // ── Builder validation ───────────────────────────────────────────────────

    [Fact]
    public void Builder_Throws_When_ChildrenModels_Missing()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var act = () => CompositeVMOfM<Model, ComponentVM<Model>>.Builder()
            .Name("x").Services(hub, dispatcher)
            .ChildModelToChildViewModel(m => ComponentVM<Model>.Builder()
                .Name("v").Services(hub, dispatcher).Model(m).Build())
            .Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>()
            .Which.MissingField.Should().Be("ChildrenModels");
    }

    [Fact]
    public void Builder_Throws_When_Mapper_Missing()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var act = () => CompositeVMOfM<Model, ComponentVM<Model>>.Builder()
            .Name("x").Services(hub, dispatcher)
            .ChildrenModels(() => [])
            .Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>()
            .Which.MissingField.Should().Be("ChildModelToChildViewModel");
    }

    // ── Type ──────────────────────────────────────────────────────────────────

    [Fact]
    public void Type_Is_Composite()
    {
        var (composite, _, _) = BuildModeled();
        composite.Type.Should().Be(ViewModelType.Composite);
    }
}
