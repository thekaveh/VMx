using System.Reactive.Subjects;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Properties;
using VMx.Services;
using Xunit;

namespace VMx.Tests;

/// <summary>
/// Members documented as inert after disposal stay inert (disposal contract).
/// </summary>
public sealed class PostDisposeInertnessTests
{
    [Fact]
    public void A_disposed_child_does_not_change_its_parents_selection()
    {
        using var hub = new MessageHub();
        var dispatcher = RxDispatcher.Immediate();
        IComponentVM[] kids =
        [
            ComponentVM.Builder().Name("a").Services(hub, dispatcher).Build(),
            ComponentVM.Builder().Name("b").Services(hub, dispatcher).Build(),
        ];
        var parent = CompositeVM<IComponentVM>.Builder().Name("p").Services(hub, dispatcher)
            .Children(() => kids).Build();
        parent.Construct();
        parent.Current = kids[0];
        kids[0].Dispose();
        kids[1].Dispose();

        kids[0].CanDeselect().Should().BeFalse();
        kids[0].Deselect();
        kids[1].Select();

        parent.Current.Should().BeSameAs(kids[0]);
    }

    [Fact]
    public void A_disposed_derived_property_rejects_writes()
    {
        var writes = new List<int>();
        using var source = new BehaviorSubject<int>(1);
        var property = DerivedProperty.From<int, int>(source, v => v, _ => true, writes.Add);
        property.Dispose();

        property.CanSet(7).Should().BeFalse();
        var write = () => property.SetValue(7);
        write.Should().Throw<InvalidOperationException>();
        writes.Should().BeEmpty();
    }
}
