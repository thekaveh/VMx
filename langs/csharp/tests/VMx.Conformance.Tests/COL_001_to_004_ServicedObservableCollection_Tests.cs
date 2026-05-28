using System.Collections.Specialized;
using FluentAssertions;
using VMx.Collections;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: COL-001..COL-004 — ServicedObservableCollection&lt;T&gt;.
/// See spec/21-collections.md §2 and ADR-0024.
/// </summary>
public class COL_001_to_004_ServicedObservableCollectionTests
{
    // ── COL-001 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// COL-001: Inserting an item raises the local CollectionChanged event AND
    /// publishes a CollectionChangedMessage to the hub.
    /// </summary>
    [Fact, Trait("Conformance", "COL-001")]
    public void COL_001_PublishesToHubAfterLocalEventOnAdd()
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<string>("sut", hub);

        var localEvents = new List<NotifyCollectionChangedEventArgs>();
        var hubMessages = new List<IMessage>();

        sut.CollectionChanged += (_, args) => localEvents.Add(args);
        hub.Messages.Subscribe(msg => hubMessages.Add(msg));

        sut.Add("alpha");

        // Local event
        localEvents.Should().ContainSingle()
            .Which.Action.Should().Be(NotifyCollectionChangedAction.Add);
        localEvents[0].NewItems!.Cast<object>().Should().ContainSingle()
            .Which.Should().Be("alpha");

        // Hub message
        hubMessages.Should().ContainSingle();
        var msg = (CollectionChangedMessage<string>)hubMessages[0];
        msg.Action.Should().Be(NotifyCollectionChangedAction.Add);
        msg.NewItems.Should().ContainSingle().Which.Should().Be("alpha");
        msg.Index.Should().Be(0);
        msg.SenderName.Should().Be("sut");
    }

    // ── COL-002 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// COL-002: Remove and Replace both raise the local event AND publish to the hub.
    /// </summary>
    [Fact, Trait("Conformance", "COL-002")]
    public void COL_002_PublishesOnRemoveAndReplace()
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<string>("sut", hub);
        sut.Add("a");
        sut.Add("b");

        // ---- Remove ----
        var localEvents = new List<NotifyCollectionChangedEventArgs>();
        var hubMessages = new List<IMessage>();
        sut.CollectionChanged += (_, args) => localEvents.Add(args);
        hub.Messages.Subscribe(msg => hubMessages.Add(msg));

        sut.Remove("a");

        localEvents.Should().ContainSingle()
            .Which.Action.Should().Be(NotifyCollectionChangedAction.Remove);
        hubMessages.Should().ContainSingle();
        var removeMsg = (CollectionChangedMessage<string>)hubMessages[0];
        removeMsg.Action.Should().Be(NotifyCollectionChangedAction.Remove);
        removeMsg.OldItems.Should().ContainSingle().Which.Should().Be("a");

        // ---- Replace ----
        localEvents.Clear();
        hubMessages.Clear();

        sut[0] = "b_replaced";

        localEvents.Should().ContainSingle()
            .Which.Action.Should().Be(NotifyCollectionChangedAction.Replace);
        hubMessages.Should().ContainSingle();
        var replaceMsg = (CollectionChangedMessage<string>)hubMessages[0];
        replaceMsg.Action.Should().Be(NotifyCollectionChangedAction.Replace);
        replaceMsg.NewItems.Should().ContainSingle().Which.Should().Be("b_replaced");
        replaceMsg.OldItems.Should().ContainSingle().Which.Should().Be("b");
    }

    // ── COL-003 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// COL-003: When no hub is injected, mutations still raise the local event
    /// without error and without any hub publication.
    /// </summary>
    [Fact, Trait("Conformance", "COL-003")]
    public void COL_003_NullHubFallback_NoPublicationNoError()
    {
        // null hub — behaves like a plain ObservableCollection<T>
        var sut = new ServicedObservableCollection<int>(hub: null);

        var localEvents = new List<NotifyCollectionChangedEventArgs>();
        sut.CollectionChanged += (_, args) => localEvents.Add(args);

        // All mutations must not throw
        sut.Add(1);
        sut.Add(2);
        sut.Remove(1);
        sut[0] = 99;
        sut.Clear();

        // Local events were still raised for every mutation (5 ops)
        localEvents.Should().HaveCount(5);
    }

    // ── COL-004 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// COL-004: The hub message is published synchronously on the calling thread
    /// (no dispatcher marshaling in the base type).
    /// </summary>
    [Fact, Trait("Conformance", "COL-004")]
    public void COL_004_FiresOnCallerThread_NoMarshal()
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<int>("sut", hub);

        int? capturedThreadId = null;
        int callerThreadId = Environment.CurrentManagedThreadId;

        hub.Messages.Subscribe(_ => capturedThreadId = Environment.CurrentManagedThreadId);

        sut.Add(42);

        capturedThreadId.Should().Be(callerThreadId);
    }
}
