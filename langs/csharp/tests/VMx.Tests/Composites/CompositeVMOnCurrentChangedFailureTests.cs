using System.Collections.Specialized;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Services;
using Xunit;

namespace VMx.Tests.Composites;

/// <summary>
/// A throwing <c>OnCurrentChanged</c> callback must not lose the collection
/// event of a committed membership change.
/// </summary>
public sealed class CompositeVMOnCurrentChangedFailureTests
{
    public static TheoryData<string> Mutations => new() { "RemoveAt", "Remove", "Clear", "SetItem" };

    [Theory]
    [MemberData(nameof(Mutations))]
    public void Collection_event_survives_a_throwing_OnCurrentChanged(string mutation)
    {
        using var hub = new MessageHub();
        var dispatcher = RxDispatcher.Immediate();
        IComponentVM[] kids =
        [
            ComponentVM.Builder().Name("a").Services(hub, dispatcher).Build(),
            ComponentVM.Builder().Name("b").Services(hub, dispatcher).Build(),
        ];
        var armed = false;
        var composite = CompositeVM<IComponentVM>.Builder().Name("c").Services(hub, dispatcher)
            .Children(() => kids)
            .OnCurrentChanged(_ =>
            {
                if (armed) throw new InvalidOperationException("callback");
            })
            .Build();
        composite.Construct();
        composite.Current = kids[0];
        armed = true;
        var actions = new List<NotifyCollectionChangedAction>();
        ((INotifyCollectionChanged)composite).CollectionChanged += (_, e) => actions.Add(e.Action);

        Action mutate = mutation switch
        {
            "RemoveAt" => () => composite.RemoveAt(0),
            "Remove" => () => composite.Remove(kids[0]),
            "Clear" => () => composite.Clear(),
            _ => () => composite[0] = ComponentVM.Builder().Name("z").Services(hub, dispatcher).Build(),
        };

        mutate.Should().Throw<InvalidOperationException>().WithMessage("callback");
        actions.Should().NotBeEmpty("the committed change still reaches observers");
        composite.Current.Should().BeNull();
    }
}
