using System.Collections.Specialized;
using FluentAssertions;
using VMx.Collections;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Collections;

/// <summary>
/// Unit tests for <see cref="ServicedObservableCollection{T}"/>.
/// Conformance-level tests live in VMx.Conformance.Tests.
/// </summary>
public class ServicedObservableCollectionTests
{
    // ── Null-hub fallback ────────────────────────────────────────────────────

    [Fact]
    public void NoHub_Add_RaisesLocalEventWithoutError()
    {
        var sut = new ServicedObservableCollection<string>();
        var events = new List<NotifyCollectionChangedEventArgs>();
        sut.CollectionChanged += (_, args) => events.Add(args);

        sut.Add("hello");

        events.Should().ContainSingle()
            .Which.Action.Should().Be(NotifyCollectionChangedAction.Add);
    }

    [Fact]
    public void NoHub_Clear_RaisesResetEventWithoutError()
    {
        var sut = new ServicedObservableCollection<int>();
        sut.Add(1); sut.Add(2);
        var events = new List<NotifyCollectionChangedEventArgs>();
        sut.CollectionChanged += (_, args) => events.Add(args);

        sut.Clear();

        events.Should().ContainSingle()
            .Which.Action.Should().Be(NotifyCollectionChangedAction.Reset);
    }

    [Fact]
    public void NoHub_AllMutations_NeverThrow()
    {
        var sut = new ServicedObservableCollection<int>();
        var act = () =>
        {
            sut.Add(1);
            sut.Add(2);
            sut.Remove(1);
            sut[0] = 99;
            sut.Clear();
        };
        act.Should().NotThrow();
    }

    // ── Hub wiring ───────────────────────────────────────────────────────────

    [Fact]
    public void Hub_Add_PublishesAddMessage()
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<string>("col", hub);
        var msgs = new List<IMessage>();
        hub.Messages.Subscribe(msgs.Add);

        sut.Add("x");

        msgs.Should().ContainSingle();
        var m = (CollectionChangedMessage<string>)msgs[0];
        m.Action.Should().Be(NotifyCollectionChangedAction.Add);
        m.NewItems.Should().ContainSingle().Which.Should().Be("x");
        m.Index.Should().Be(0);
    }

    [Fact]
    public void Hub_Remove_PublishesRemoveMessage()
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<string>("col", hub);
        sut.Add("y");

        var msgs = new List<IMessage>();
        hub.Messages.Subscribe(msgs.Add);
        sut.Remove("y");

        msgs.Should().ContainSingle();
        var m = (CollectionChangedMessage<string>)msgs[0];
        m.Action.Should().Be(NotifyCollectionChangedAction.Remove);
        m.OldItems.Should().ContainSingle().Which.Should().Be("y");
    }

    [Fact]
    public void Hub_Replace_PublishesReplaceMessage()
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<string>("col", hub);
        sut.Add("old");

        var msgs = new List<IMessage>();
        hub.Messages.Subscribe(msgs.Add);
        sut[0] = "new";

        msgs.Should().ContainSingle();
        var m = (CollectionChangedMessage<string>)msgs[0];
        m.Action.Should().Be(NotifyCollectionChangedAction.Replace);
        m.NewItems.Should().ContainSingle().Which.Should().Be("new");
        m.OldItems.Should().ContainSingle().Which.Should().Be("old");
    }

    [Fact]
    public void Hub_Clear_PublishesResetMessage()
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<string>("col", hub);
        sut.Add("a");

        var msgs = new List<IMessage>();
        hub.Messages.Subscribe(msgs.Add);
        sut.Clear();

        msgs.Should().ContainSingle();
        var m = (CollectionChangedMessage<string>)msgs[0];
        m.Action.Should().Be(NotifyCollectionChangedAction.Reset);
        m.NewItems.Should().BeEmpty();
        m.OldItems.Should().BeEmpty();
        m.Index.Should().Be(-1);
    }

    [Fact]
    public void Hub_BothLocalAndHubObserveBothAdd()
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<int>("col", hub);

        var localSaw = false;
        var hubSaw = false;
        sut.CollectionChanged += (_, _) => localSaw = true;
        hub.Messages.Subscribe(_ => hubSaw = true);

        sut.Add(42);

        localSaw.Should().BeTrue();
        hubSaw.Should().BeTrue();
    }

    // ── Large-N stress ───────────────────────────────────────────────────────

    [Fact]
    public void Stress_10k_Adds_And_Clears_NoError()
    {
        const int N = 10_000;
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<int>("stress", hub);
        int hubCount = 0;
        hub.Messages.Subscribe(_ => hubCount++);

        for (int i = 0; i < N; i++) sut.Add(i);
        sut.Clear();

        sut.Should().BeEmpty();
        // N adds + 1 clear = N+1 messages
        hubCount.Should().Be(N + 1);
    }

    // ── Default name ─────────────────────────────────────────────────────────

    [Fact]
    public void DefaultName_IsFallback()
    {
        var sut = new ServicedObservableCollection<int>();
        sut.Name.Should().NotBeNullOrEmpty();
    }
}
