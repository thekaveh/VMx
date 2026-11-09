using System.Reactive.Subjects;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
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

    private static (CompositeVM<IComponentVM> Composite, IComponentVM A, IComponentVM B) DisposedComposite()
    {
        var hub = new MessageHub();
        var dispatcher = RxDispatcher.Immediate();
        IComponentVM[] kids =
        [
            ComponentVM.Builder().Name("a").Services(hub, dispatcher).Build(),
            ComponentVM.Builder().Name("b").Services(hub, dispatcher).Build(),
        ];
        var composite = CompositeVM<IComponentVM>.Builder().Name("p").Services(hub, dispatcher)
            .Children(() => kids).Build();
        composite.Construct();
        composite.Current = kids[0];
        composite.Dispose();
        return (composite, kids[0], kids[1]);
    }

    [Fact]
    public void A_disposed_composite_refuses_membership_and_selection_changes()
    {
        // Disposal contract, C# exception: membership changes and a selection
        // other than the current child raise ObjectDisposedException (#1319).
        var extra = ComponentVM.Builder().Name("x").Services(new MessageHub(), RxDispatcher.Immediate()).Build();

        var add = DisposedComposite();
        add.Composite.Invoking(c => c.Add(extra)).Should().Throw<ObjectDisposedException>();

        var remove = DisposedComposite();
        remove.Composite.Invoking(c => c.Remove(remove.B)).Should().Throw<ObjectDisposedException>();

        var clear = DisposedComposite();
        clear.Composite.Invoking(c => c.Clear()).Should().Throw<ObjectDisposedException>();
        clear.Composite.Count.Should().Be(2);

        var other = DisposedComposite();
        other.Composite.Invoking(c => c.Current = other.B).Should().Throw<ObjectDisposedException>();
        other.Composite.Current.Should().BeSameAs(other.A);

        var nullClear = DisposedComposite();
        nullClear.Composite.Invoking(c => c.Current = null).Should().Throw<ObjectDisposedException>();
        nullClear.Composite.Current.Should().BeSameAs(nullClear.A);

        var same = DisposedComposite();
        same.Composite.Current = same.A;
        same.Composite.Current.Should().BeSameAs(same.A);
    }

    [Fact]
    public void A_disposed_group_refuses_membership_changes()
    {
        var hub = new MessageHub();
        var dispatcher = RxDispatcher.Immediate();
        var a = ComponentVM.Builder().Name("a").Services(hub, dispatcher).Build();
        var group = GroupVM<IComponentVM>.Builder().Name("g").Services(hub, dispatcher)
            .Children(() => [a]).Build();
        group.Construct();
        group.Dispose();

        var extra = ComponentVM.Builder().Name("x").Services(hub, dispatcher).Build();
        group.Invoking(g => g.Add(extra)).Should().Throw<ObjectDisposedException>();
        group.Invoking(g => g.Remove(a)).Should().Throw<ObjectDisposedException>();
        group.Invoking(g => g.Clear()).Should().Throw<ObjectDisposedException>();
        group.Count.Should().Be(1);
    }

    [Fact]
    public void A_disposed_composite_refuses_index_and_move_changes()
    {
        var (composite, a, b) = DisposedComposite();
        var extra = ComponentVM.Builder().Name("x").Services(new MessageHub(), RxDispatcher.Immediate()).Build();

        composite.Invoking(c => c.Insert(0, extra)).Should().Throw<ObjectDisposedException>();
        composite.Invoking(c => c.RemoveAt(1)).Should().Throw<ObjectDisposedException>();
        composite.Invoking(c => c[1] = extra).Should().Throw<ObjectDisposedException>();
        composite.Invoking(c => c.Move(0, 1)).Should().Throw<ObjectDisposedException>();
        composite.Should().Equal(a, b);
        composite.Current.Should().BeSameAs(a);
    }

    [Fact]
    public void A_disposed_group_refuses_index_and_move_changes()
    {
        var hub = new MessageHub();
        var dispatcher = RxDispatcher.Immediate();
        var a = ComponentVM.Builder().Name("a").Services(hub, dispatcher).Build();
        var b = ComponentVM.Builder().Name("b").Services(hub, dispatcher).Build();
        var group = GroupVM<IComponentVM>.Builder().Name("g").Services(hub, dispatcher)
            .Children(() => [a, b]).Build();
        group.Construct();
        group.Dispose();

        var extra = ComponentVM.Builder().Name("x").Services(hub, dispatcher).Build();
        group.Invoking(g => g.Insert(0, extra)).Should().Throw<ObjectDisposedException>();
        group.Invoking(g => g.RemoveAt(1)).Should().Throw<ObjectDisposedException>();
        group.Invoking(g => g[1] = extra).Should().Throw<ObjectDisposedException>();
        group.Invoking(g => g.Move(0, 1)).Should().Throw<ObjectDisposedException>();
        group.Should().Equal(a, b);
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
