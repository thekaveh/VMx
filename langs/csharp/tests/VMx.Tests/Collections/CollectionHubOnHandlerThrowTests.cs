using FluentAssertions;
using VMx.Collections;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Collections;

/// <summary>
/// A throwing local handler does not suppress the hub message, and the first
/// failure wins (spec/21-collections.md §2.5, ADR-0171, #1051).
/// </summary>
public class CollectionHubOnHandlerThrowTests
{
    private sealed class LocalFailure() : Exception("local");

    private sealed class HubFailure() : Exception("hub");

    /// <summary>A hub whose Send records the message, then throws.</summary>
    private sealed class ThrowingHub : IMessageHub
    {
        public List<IMessage> Sent { get; } = [];

        public IObservable<IMessage> Messages => throw new NotSupportedException();

        public void Send<TMessage>(TMessage message) where TMessage : IMessage
        {
            Sent.Add(message);
            throw new HubFailure();
        }
    }

    [Fact]
    public void ServicedCollection_LocalFailureWinsOverHubFailure()
    {
        var hub = new ThrowingHub();
        var list = new ServicedObservableCollection<int>(hub);
        list.CollectionChanged += (_, _) => throw new LocalFailure();

        ((Action)(() => list.Add(1))).Should().Throw<LocalFailure>();

        list.Should().Equal(1);
        hub.Sent.Should().ContainSingle();
    }

    [Fact]
    public void ServicedCollection_HubFailureStillPropagatesWithoutLocalFailure()
    {
        var hub = new ThrowingHub();
        var list = new ServicedObservableCollection<int>(hub);

        ((Action)(() => list.Add(1))).Should().Throw<HubFailure>();

        list.Should().Equal(1);
    }

    [Fact]
    public void ServicedCollection_ThrowingHandlerKeepsPublishingOnLaterMutations()
    {
        var hub = new TestHub();
        var messages = new List<IMessage>();
        hub.Messages.Subscribe(messages.Add);
        var list = new ServicedObservableCollection<int>(hub);
        list.CollectionChanged += (_, _) => throw new LocalFailure();

        ((Action)(() => list.Add(1))).Should().Throw<LocalFailure>();
        ((Action)(() => list.Add(2))).Should().Throw<LocalFailure>();

        list.Should().Equal(1, 2);
        messages.Should().HaveCount(2);
    }

    [Fact]
    public void ServicedCollection_NoHubStillRethrowsLocalFailure()
    {
        var list = new ServicedObservableCollection<int>();
        list.CollectionChanged += (_, _) => throw new LocalFailure();

        ((Action)(() => list.Add(1))).Should().Throw<LocalFailure>();

        list.Should().Equal(1);
    }

    [Fact]
    public void Dictionary_ThrowingItemAddedStillRaisesCollectionChangedOnce()
    {
        var dict = new ObservableDictionary<string, int, string>();
        var collectionChanged = 0;
        dict.ItemAdded += (_, _) => throw new LocalFailure();
        dict.CollectionChanged += (_, _) => collectionChanged++;

        ((Action)(() => dict.Add("a", 1, "one"))).Should().Throw<LocalFailure>();

        collectionChanged.Should().Be(1);
        dict.ContainsKey("a", 1).Should().BeTrue();
    }

    [Fact]
    public void Dictionary_FirstLocalFailureWinsOverLaterFailures()
    {
        var hub = new ThrowingHub();
        var dict = new ObservableDictionary<string, int, string>(hub);
        dict.ItemAdded += (_, _) => throw new LocalFailure();
        dict.CollectionChanged += (_, _) => throw new InvalidOperationException("second");

        ((Action)(() => dict.Add("a", 1, "one"))).Should().Throw<LocalFailure>();

        hub.Sent.Should().ContainSingle()
            .Which.Should().BeOfType<CollectionChangedMessage<KeyValuePair<(string, int), string>>>()
            .Which.NewIndex.Should().Be(0);
    }
}
