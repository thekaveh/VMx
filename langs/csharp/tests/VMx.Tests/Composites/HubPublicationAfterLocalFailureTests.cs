using System.Collections.Specialized;
using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Composites;

/// <summary>
/// A throwing local <c>CollectionChanged</c> handler does not suppress the hub
/// <see cref="CollectionChangedMessage{T}"/> for a committed change
/// (spec/01 §1.4, #723). The call still throws the handler's exception.
/// </summary>
public class HubPublicationAfterLocalFailureTests
{
    private sealed class LocalHandlerFailure : Exception
    {
        public LocalHandlerFailure() : base("local handler failed") { }
    }

    private static readonly TestDispatcher Dispatcher = new();

    private static ComponentVM<string> Child(MessageHub hub, string name)
        => ComponentVM<string>.Builder().Name(name).Services(hub, Dispatcher).Model(name).Build();

    private static List<CollectionChangedMessage<IComponentVM>> HubMessages(MessageHub hub, object sender)
    {
        var messages = new List<CollectionChangedMessage<IComponentVM>>();
        hub.Messages.OfType<CollectionChangedMessage<IComponentVM>>()
            .Where(message => ReferenceEquals(message.Sender, sender))
            .Subscribe(messages.Add);
        return messages;
    }

    public static IEnumerable<object[]> Containers()
    {
        yield return ["composite"];
        yield return ["group"];
    }

    private static IList<IComponentVM> Container(string kind, MessageHub hub) => kind == "composite"
        ? CompositeVM<IComponentVM>.Builder().Name("c").Services(hub, Dispatcher).Children(() => []).Build()
        : GroupVM<IComponentVM>.Builder().Name("g").Services(hub, Dispatcher).Children(() => []).Build();

    private static IDisposable Batch(IList<IComponentVM> container) => container switch
    {
        CompositeVM<IComponentVM> composite => composite.BatchUpdate(),
        GroupVM<IComponentVM> group => group.BatchUpdate(),
        _ => throw new InvalidOperationException(),
    };

    private static void Move(IList<IComponentVM> container, int from, int to)
    {
        switch (container)
        {
            case CompositeVM<IComponentVM> composite: composite.Move(from, to); break;
            case GroupVM<IComponentVM> group: group.Move(from, to); break;
        }
    }

    [Theory]
    [MemberData(nameof(Containers))]
    public void Throwing_Local_Handler_Does_Not_Suppress_The_Hub_Message(string kind)
    {
        using var hub = new MessageHub();
        var container = Container(kind, hub);
        container.Add(Child(hub, "a"));
        container.Add(Child(hub, "b"));
        var messages = HubMessages(hub, container);
        var throwing = true;
        ((INotifyCollectionChanged)container).CollectionChanged += (_, _) =>
        {
            if (throwing) throw new LocalHandlerFailure();
        };

        void ExpectOneMessage(Action mutation, NotifyCollectionChangedAction action)
        {
            var before = messages.Count;
            mutation.Should().Throw<LocalHandlerFailure>("the handler's failure still reaches the caller");
            messages.Should().HaveCount(before + 1, $"{action} still publishes exactly one hub message");
            messages[^1].Action.Should().Be(action);
        }

        ExpectOneMessage(() => container.Add(Child(hub, "c")), NotifyCollectionChangedAction.Add);
        ExpectOneMessage(() => container.RemoveAt(0), NotifyCollectionChangedAction.Remove);
        ExpectOneMessage(() => Move(container, 0, 1), NotifyCollectionChangedAction.Move);
        ExpectOneMessage(container.Clear, NotifyCollectionChangedAction.Reset);

        throwing = false;
        var batch = Batch(container);
        container.Add(Child(hub, "d"));
        throwing = true;
        ExpectOneMessage(batch.Dispose, NotifyCollectionChangedAction.Reset);
    }

    [Fact]
    public void Throwing_Filter_Predicate_Does_Not_Suppress_The_Source_Hub_Message()
    {
        using var hub = new MessageHub();
        var source = CompositeVM<IComponentVM>.Builder()
            .Name("source").Services(hub, Dispatcher).Children(() => []).Build();
        var calls = 0;
        using var filtered = new FilteredCompositeVM<IComponentVM>(source, _ =>
        {
            // The initial recompute sees no items; the second add's recompute throws.
            calls++;
            if (source.Count == 2) throw new LocalHandlerFailure();
            return true;
        });
        var messages = HubMessages(hub, source);

        source.Add(Child(hub, "a"));
        var second = () => source.Add(Child(hub, "b"));

        second.Should().Throw<LocalHandlerFailure>();
        source.Count.Should().Be(2);
        messages.Should().HaveCount(2, "two committed adds publish two hub messages");
        calls.Should().BeGreaterThan(0);
    }

    // A Move takes no membership transaction, so a local handler that disposes
    // the container disposes it at once; the disposed container then publishes
    // nothing (COMP-045). A disposal deferred by a membership transaction still
    // publishes the committed change (spec/06 §4.2).
    [Theory]
    [MemberData(nameof(Containers))]
    public void Container_Disposed_During_Local_Delivery_Publishes_No_Hub_Message(string kind)
    {
        using var hub = new MessageHub();
        var container = Container(kind, hub);
        container.Add(Child(hub, "a"));
        container.Add(Child(hub, "b"));
        var messages = HubMessages(hub, container);
        ((INotifyCollectionChanged)container).CollectionChanged += (_, _) => ((IDisposable)container).Dispose();

        Move(container, 0, 1);

        ((IComponentVM)container).Status.Should().Be(VMx.Lifecycle.ConstructionStatus.Disposed);
        messages.Should().BeEmpty();
    }

    [Theory]
    [MemberData(nameof(Containers))]
    public void Throwing_Hub_Send_Does_Not_Hide_The_Earlier_Local_Failure(string kind)
    {
        var hub = new TestHub();
        var container = kind == "composite"
            ? (IList<IComponentVM>)CompositeVM<IComponentVM>.Builder()
                .Name("c").Services(hub, Dispatcher).Children(() => []).Build()
            : GroupVM<IComponentVM>.Builder()
                .Name("g").Services(hub, Dispatcher).Children(() => []).Build();
        ((INotifyCollectionChanged)container).CollectionChanged += (_, _) => throw new LocalHandlerFailure();
        hub.Messages.OfType<CollectionChangedMessage<IComponentVM>>()
            .Subscribe(_ => throw new ArgumentException("hub subscriber failed"));

        var add = () => container.Add(Child(new MessageHub(), "a"));

        add.Should().Throw<LocalHandlerFailure>("the first failure, the local one, surfaces");
    }
}
