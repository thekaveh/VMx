using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Services;
using Xunit;

namespace VMx.Tests.Composites;

/// <summary>
/// A null child in a selection call gets the documented selection error, not a
/// <see cref="NullReferenceException"/> (spec/06 §3.1, #1467). A null value is
/// never a child.
/// </summary>
public class NullChildSelectionTests
{
    private static (CompositeVM<ComponentVM<string>> Composite, ComponentVM<string> A) Setup()
    {
        ComponentVM<string> Child(string name) => ComponentVM<string>.Builder()
            .Name(name)
            .Services(NullMessageHub.Instance, NullDispatcher.Instance)
            .Model(name)
            .Build();
        var a = Child("a");
        var b = Child("b");
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(NullMessageHub.Instance, NullDispatcher.Instance)
            .Children(() => [a, b])
            .Build();
        composite.Construct();
        return (composite, a);
    }

    [Fact]
    public void CanSelectComponent_Of_Null_Returns_False()
    {
        var (composite, _) = Setup();

        composite.CanSelectComponent(null!).Should().BeFalse();
    }

    [Fact]
    public void SelectComponent_Of_Null_Raises_The_Predicate_Error_And_Keeps_Current()
    {
        var (composite, a) = Setup();
        composite.Current = a;

        var act = () => composite.SelectComponent(null!);

        act.Should().Throw<InvalidOperationException>().WithMessage("*can_select_component returned false*");
        composite.Current.Should().BeSameAs(a);
    }

    [Fact]
    public void DeselectComponent_Of_Null_With_A_Current_Child_Raises_The_Not_Current_Error()
    {
        var (composite, a) = Setup();
        composite.Current = a;

        var act = () => composite.DeselectComponent(null!);

        act.Should().Throw<InvalidOperationException>().WithMessage("*not the current selection*");
        composite.Current.Should().BeSameAs(a);
    }

    [Fact]
    public void DeselectComponent_Of_Null_With_No_Current_Child_Does_Nothing()
    {
        var (composite, _) = Setup();

        var act = () => composite.DeselectComponent(null!);

        act.Should().NotThrow();
        composite.Current.Should().BeNull();
    }
}
