using System.Collections;
using System.Collections.Specialized;
using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Forwarding;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Containers publish their collection changes on the hub
/// (spec/01-concepts.md §1.4, spec/06-composite-vm.md §4, spec/07-group-vm.md,
/// ADR-0142): COMP-042..045 and GRP-012..013.
/// </summary>
public class COMP_042_to_045_HubCollectionChanges_Tests
{
    private sealed class PassThroughCompositeVM(ICompositeVM<IComponentVM> wrapped)
        : ForwardingCompositeVM<IComponentVM>(wrapped);

    /// <summary>One local event or hub message, normalized for pairwise comparison.</summary>
    private sealed record Delivery(
        string Channel,
        object Sender,
        NotifyCollectionChangedAction Action,
        int OldIndex,
        int NewIndex,
        IReadOnlyList<object> NewItems,
        IReadOnlyList<object> OldItems);

    private static readonly TestDispatcher Dispatcher = new();

    private static ComponentVM<string> Child(MessageHub hub, string name)
        => ComponentVM<string>.Builder().Name(name).Services(hub, Dispatcher).Model(name).Build();

    private static CompositeVM<IComponentVM> Composite(MessageHub hub, string name = "composite")
        => CompositeVM<IComponentVM>.Builder()
            .Name(name).Services(hub, Dispatcher).Children(() => []).Build();

    private static GroupVM<IComponentVM> Group(MessageHub hub, string name = "group")
        => GroupVM<IComponentVM>.Builder()
            .Name(name).Services(hub, Dispatcher).Children(() => []).Build();

    private static List<CollectionChangedMessage<IComponentVM>> HubMessages(MessageHub hub)
    {
        var messages = new List<CollectionChangedMessage<IComponentVM>>();
        hub.Messages.OfType<CollectionChangedMessage<IComponentVM>>().Subscribe(messages.Add);
        return messages;
    }

    private static object[] Items(IList? items)
        => items?.Cast<object>().ToArray() ?? [];

    /// <summary>One log of local events and hub messages from the containers, in delivery order.</summary>
    private static List<Delivery> Interleaved(MessageHub hub, params INotifyCollectionChanged[] containers)
    {
        var log = new List<Delivery>();
        foreach (var container in containers)
        {
            container.CollectionChanged += (sender, e) => log.Add(new Delivery(
                "local", sender!, e.Action, e.OldStartingIndex, e.NewStartingIndex,
                Items(e.NewItems), Items(e.OldItems)));
        }
        hub.Messages.OfType<CollectionChangedMessage<IComponentVM>>()
            .Where(message => containers.Any(container => ReferenceEquals(container, message.Sender)))
            .Subscribe(message => log.Add(new Delivery(
                "hub", message.Sender, message.Action, message.OldIndex, message.NewIndex,
                message.NewItems.Cast<object>().ToArray(), message.OldItems.Cast<object>().ToArray())));
        return log;
    }

    private static void HubFollowsEachLocalEvent(List<Delivery> log, int localEvents)
    {
        log.Should().HaveCount(localEvents * 2);
        for (var i = 0; i < log.Count; i += 2)
        {
            var local = log[i];
            var hub = log[i + 1];
            local.Channel.Should().Be("local", $"entry {i} must be the local event");
            hub.Channel.Should().Be("hub", $"entry {i + 1} must be the hub message that follows it");
            hub.Sender.Should().BeSameAs(local.Sender);
            hub.Action.Should().Be(local.Action);
            hub.OldIndex.Should().Be(local.OldIndex);
            hub.NewIndex.Should().Be(local.NewIndex);
            hub.NewItems.Should().Equal(local.NewItems, ReferenceEquals);
            hub.OldItems.Should().Equal(local.OldItems, ReferenceEquals);
        }
    }

    // ── COMP-042 — Composite collection changes publish on the hub ─────────

    [Fact, Trait("Conformance", "COMP-042")]
    public void COMP_042_Each_Local_Event_Is_Followed_By_One_Hub_Message_From_The_Composite()
    {
        using var hub = new MessageHub();
        var parent = Composite(hub);
        var a = Child(hub, "a");
        var b = Child(hub, "b");
        var c = Child(hub, "c");
        var d = Child(hub, "d");
        var log = Interleaved(hub, parent);
        var messages = HubMessages(hub);

        parent.Add(a);
        parent.Insert(0, b);
        parent.Move(0, 1);
        parent[0] = c;
        parent.RemoveAt(1);
        parent.Remove(c).Should().BeTrue();
        parent.Add(d);
        parent.Clear();

        HubFollowsEachLocalEvent(log, 9);
        messages.Should().OnlyContain(message => ReferenceEquals(message.Sender, parent));
        // C# index replacement keeps its local Remove + Add decomposition.
        messages.Select(message => message.Action).Should().Equal(
            NotifyCollectionChangedAction.Add,
            NotifyCollectionChangedAction.Add,
            NotifyCollectionChangedAction.Move,
            NotifyCollectionChangedAction.Remove,
            NotifyCollectionChangedAction.Add,
            NotifyCollectionChangedAction.Remove,
            NotifyCollectionChangedAction.Remove,
            NotifyCollectionChangedAction.Add,
            NotifyCollectionChangedAction.Reset);
        messages[0].NewItems.Should().Equal([a], ReferenceEquals);
        messages[1].Index.Should().Be(0);
        messages[2].NewItems.Should().Equal([b], ReferenceEquals);
        (messages[2].OldIndex, messages[2].NewIndex).Should().Be((0, 1));
        messages[3].OldItems.Should().Equal([a], ReferenceEquals);
        messages[4].NewItems.Should().Equal([c], ReferenceEquals);
        messages[5].OldItems.Should().Equal([b], ReferenceEquals);
        messages[5].OldIndex.Should().Be(1);
        messages[8].Index.Should().Be(-1);
    }

    [Fact, Trait("Conformance", "COMP-042")]
    public void COMP_042_Both_Channels_Observe_The_Committed_Membership()
    {
        using var hub = new MessageHub();
        var parent = Composite(hub);
        var a = Child(hub, "a");
        var seen = new List<string>();
        parent.CollectionChanged += (_, _) => seen.Add($"local:{parent.Contains(a)}");
        hub.Messages.OfType<CollectionChangedMessage<IComponentVM>>()
            .Subscribe(_ => seen.Add($"hub:{parent.Contains(a)}"));

        parent.Add(a);
        parent.Remove(a);

        seen.Should().Equal("local:True", "hub:True", "local:False", "hub:False");
    }

    [Fact, Trait("Conformance", "COMP-042")]
    public void COMP_042_Factory_Population_Publishes_One_Message_Per_Local_Add()
    {
        using var hub = new MessageHub();
        var a = Child(hub, "a");
        var b = Child(hub, "b");
        var parent = CompositeVM<IComponentVM>.Builder()
            .Name("populated").Services(hub, Dispatcher).Children(() => [a, b]).Build();
        var log = Interleaved(hub, parent);

        parent.Construct();

        parent.Status.Should().Be(ConstructionStatus.Constructed);
        HubFollowsEachLocalEvent(log, 2);
        log.Where(entry => entry.Channel == "hub").Select(entry => entry.NewIndex)
            .Should().Equal(0, 1);
    }

    // ── COMP-043 — Composite batches publish one hub Reset ─────────────────

    [Fact, Trait("Conformance", "COMP-043")]
    public void COMP_043_Nested_Batch_Publishes_One_Reset_After_The_Local_Reset()
    {
        using var hub = new MessageHub();
        var parent = Composite(hub);
        var log = Interleaved(hub, parent);

        var outer = parent.BatchUpdate();
        parent.Add(Child(hub, "a"));
        var inner = parent.BatchUpdate();
        parent.Add(Child(hub, "b"));
        parent.Move(0, 1);
        inner.Dispose();
        log.Should().BeEmpty("nothing is published while any batch scope is active");
        outer.Dispose();

        log.Select(entry => (entry.Channel, entry.Action, entry.OldIndex, entry.NewIndex))
            .Should().Equal(
                ("local", NotifyCollectionChangedAction.Reset, -1, -1),
                ("hub", NotifyCollectionChangedAction.Reset, -1, -1));
        log[1].Sender.Should().BeSameAs(parent);
    }

    [Fact, Trait("Conformance", "COMP-043")]
    public void COMP_043_Empty_Or_Same_Index_Move_Batch_Publishes_Nothing()
    {
        using var hub = new MessageHub();
        var parent = Composite(hub);
        parent.Add(Child(hub, "a"));
        var messages = HubMessages(hub);

        parent.BatchUpdate().Dispose();
        using (parent.BatchUpdate())
            parent.Move(0, 0);

        messages.Should().BeEmpty();
    }

    // ── COMP-044 — Transfers publish removal before addition ───────────────

    [Fact, Trait("Conformance", "COMP-044")]
    public void COMP_044_Transfer_Publishes_Old_Remove_Before_New_Add()
    {
        using var hub = new MessageHub();
        var oldParent = Composite(hub, "old");
        var newParent = Group(hub, "new");
        var moved = Child(hub, "moved");
        oldParent.Add(moved);
        var log = Interleaved(hub, oldParent, newParent);

        newParent.Add(moved);

        HubFollowsEachLocalEvent(log, 2);
        log.Select(entry => (entry.Channel, entry.Sender, entry.Action)).Should().Equal(
            ("local", (object)oldParent, NotifyCollectionChangedAction.Remove),
            ("hub", (object)oldParent, NotifyCollectionChangedAction.Remove),
            ("local", (object)newParent, NotifyCollectionChangedAction.Add),
            ("hub", (object)newParent, NotifyCollectionChangedAction.Add));
        log[1].OldItems.Should().Equal([moved], ReferenceEquals);
        log[3].NewItems.Should().Equal([moved], ReferenceEquals);
    }

    [Fact, Trait("Conformance", "COMP-044")]
    public void COMP_044_Rejected_RolledBack_And_Same_Index_Mutations_Publish_Nothing()
    {
        using var hub = new MessageHub();
        var parent = Composite(hub);
        var outer = Composite(hub, "outer");
        var a = Child(hub, "a");
        parent.Add(a);
        outer.Add(parent);
        var source = Composite(hub, "source");
        var failing = ComponentVM<string>.Builder().Name("failing").Services(hub, Dispatcher)
            .Model("failing")
            .OnConstruct(() => throw new InvalidOperationException("construct failed"))
            .Build();
        source.Add(failing);
        var destination = CompositeVM<IComponentVM>.Builder()
            .Name("destination").Services(hub, Dispatcher).Children(() => [])
            .AutoConstructOnAdd(true).Build();
        destination.Construct();
        var messages = HubMessages(hub);

        ((Action)(() => parent.Add(a))).Should().Throw<InvalidOperationException>();
        ((Action)(() => parent.Add(outer))).Should().Throw<InvalidOperationException>();
        ((Action)(() => parent.Insert(99, Child(hub, "late"))))
            .Should().Throw<ArgumentOutOfRangeException>();
        ((Action)(() => parent.Move(0, 5))).Should().Throw<ArgumentOutOfRangeException>();
        ((Action)(() => destination.Add(failing)))
            .Should().Throw<InvalidOperationException>().WithMessage("construct failed");
        parent.Move(0, 0);

        source.Should().ContainSingle(item => ReferenceEquals(item, failing));
        destination.Should().BeEmpty();
        messages.Should().BeEmpty();
    }

    // ── COMP-045 — Hub transactions, disposal, and forwarding ──────────────

    [Fact, Trait("Conformance", "COMP-045")]
    public void COMP_045_Hub_Transaction_Defers_Messages_In_Mutation_Order()
    {
        using var hub = new MessageHub();
        var parent = Composite(hub);
        var messages = HubMessages(hub);
        var localEvents = 0;
        parent.CollectionChanged += (_, _) => localEvents++;

        hub.Batch(() =>
        {
            parent.Add(Child(hub, "a"));
            parent.Add(Child(hub, "b"));
            localEvents.Should().Be(2, "the local stream is not part of the hub transaction");
            messages.Should().BeEmpty("the hub transaction defers delivery");
        });

        messages.Select(message => (message.Action, message.NewIndex)).Should().Equal(
            (NotifyCollectionChangedAction.Add, 0),
            (NotifyCollectionChangedAction.Add, 1));
    }

    [Fact, Trait("Conformance", "COMP-045")]
    public void COMP_045_Disposed_Composite_Publishes_Nothing()
    {
        using var hub = new MessageHub();
        var parent = Composite(hub);
        parent.Add(Child(hub, "a"));
        var batch = parent.BatchUpdate();
        parent.Add(Child(hub, "b"));
        var messages = HubMessages(hub);

        parent.Dispose();
        batch.Dispose();
        try { parent.Add(Child(hub, "late")); }
        catch (ObjectDisposedException)
        {
            // A disposed container may reject the mutation; either way it publishes nothing.
        }

        messages.Where(message => ReferenceEquals(message.Sender, parent)).Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "COMP-045")]
    public void COMP_045_Forwarding_Wrapper_Publishes_Once_Sent_By_The_Wrapped_Composite()
    {
        using var hub = new MessageHub();
        var parent = Composite(hub);
        var wrapper = new PassThroughCompositeVM(parent);
        var messages = HubMessages(hub);

        wrapper.Add(Child(hub, "a"));
        wrapper.Move(0, 0);
        wrapper.Clear();

        messages.Select(message => message.Action).Should().Equal(
            NotifyCollectionChangedAction.Add,
            NotifyCollectionChangedAction.Reset);
        messages.Should().OnlyContain(message => ReferenceEquals(message.Sender, parent));
    }

    // ── GRP-012 — Group collection changes publish on the hub ──────────────

    [Fact, Trait("Conformance", "GRP-012")]
    public void GRP_012_Each_Local_Event_Is_Followed_By_One_Hub_Message_From_The_Group()
    {
        using var hub = new MessageHub();
        var peers = Group(hub);
        var a = Child(hub, "a");
        var b = Child(hub, "b");
        var c = Child(hub, "c");
        var d = Child(hub, "d");
        var log = Interleaved(hub, peers);
        var messages = HubMessages(hub);

        peers.Add(a);
        peers.Insert(0, b);
        peers.Move(0, 1);
        peers.Move(1, 1);
        peers[0] = c;
        peers.Remove(b).Should().BeTrue();
        peers.Remove(b).Should().BeFalse();
        peers.Add(d);
        peers.RemoveAt(0);
        peers.Clear();

        HubFollowsEachLocalEvent(log, 9);
        messages.Should().OnlyContain(message => ReferenceEquals(message.Sender, peers));
        messages.Select(message => message.Action).Should().Equal(
            NotifyCollectionChangedAction.Add,
            NotifyCollectionChangedAction.Add,
            NotifyCollectionChangedAction.Move,
            NotifyCollectionChangedAction.Remove,
            NotifyCollectionChangedAction.Add,
            NotifyCollectionChangedAction.Remove,
            NotifyCollectionChangedAction.Add,
            NotifyCollectionChangedAction.Remove,
            NotifyCollectionChangedAction.Reset);
    }

    [Fact, Trait("Conformance", "GRP-012")]
    public void GRP_012_Disposed_Group_Publishes_Nothing()
    {
        using var hub = new MessageHub();
        var peers = Group(hub);
        peers.Add(Child(hub, "a"));
        var batch = peers.BatchUpdate();
        peers.Add(Child(hub, "b"));
        var messages = HubMessages(hub);

        peers.Dispose();
        batch.Dispose();
        try { peers.Add(Child(hub, "late")); }
        catch (ObjectDisposedException)
        {
            // A disposed container may reject the mutation; either way it publishes nothing.
        }

        messages.Should().BeEmpty();
    }

    // ── GRP-013 — Group batches publish one hub Reset ──────────────────────

    [Fact, Trait("Conformance", "GRP-013")]
    public void GRP_013_Nested_Batch_Publishes_One_Reset_And_Empty_Batch_Nothing()
    {
        using var hub = new MessageHub();
        var peers = Group(hub);
        var log = Interleaved(hub, peers);

        peers.BatchUpdate().Dispose();
        var outer = peers.BatchUpdate();
        peers.Add(Child(hub, "a"));
        var inner = peers.BatchUpdate();
        peers.Add(Child(hub, "b"));
        inner.Dispose();
        log.Should().BeEmpty("nothing is published while any batch scope is active");
        outer.Dispose();

        log.Select(entry => (entry.Channel, entry.Action)).Should().Equal(
            ("local", NotifyCollectionChangedAction.Reset),
            ("hub", NotifyCollectionChangedAction.Reset));
        log[1].Sender.Should().BeSameAs(peers);

        log.Clear();
        using (peers.BatchUpdate())
            peers.Move(1, 1);
        log.Should().BeEmpty("a same-index move does not dirty the batch");
    }
}
