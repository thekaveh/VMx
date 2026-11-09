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
/// <c>BatchUpdate</c> keeps an exact depth when batches open and close on
/// several threads, never loses a change to a concurrent close, and a batch
/// that closes after the container's disposal raises nothing (#1344,
/// spec/06 §4.1, spec/01 §1.4).
/// </summary>
public class ContainerBatchThreadingTests
{
    private static readonly TestDispatcher Dispatcher = new();

    private static ComponentVM<string> Child(MessageHub hub, string name)
        => ComponentVM<string>.Builder().Name(name).Services(hub, Dispatcher).Model(name).Build();

    private static CompositeVM<IComponentVM> Composite(MessageHub hub)
        => CompositeVM<IComponentVM>.Builder().Name("c").Services(hub, Dispatcher).Children(() => []).Build();

    private static GroupVM<IComponentVM> Group(MessageHub hub)
        => GroupVM<IComponentVM>.Builder().Name("g").Services(hub, Dispatcher).Children(() => []).Build();

    private static List<CollectionChangedMessage<IComponentVM>> HubMessages(MessageHub hub, object sender)
    {
        var messages = new List<CollectionChangedMessage<IComponentVM>>();
        hub.Messages.OfType<CollectionChangedMessage<IComponentVM>>()
            .Where(message => ReferenceEquals(message.Sender, sender))
            .Subscribe(messages.Add);
        return messages;
    }

    [Fact]
    public void Composite_Batch_Closed_After_Dispose_Raises_No_Local_Event_And_No_Hub_Message()
    {
        using var hub = new MessageHub();
        var composite = Composite(hub);
        var messages = HubMessages(hub, composite);
        var localEvents = 0;
        composite.CollectionChanged += (_, _) => localEvents++;

        var batch = composite.BatchUpdate();
        composite.Add(Child(hub, "a"));
        composite.Dispose();
        batch.Dispose();

        localEvents.Should().Be(0);
        messages.Should().BeEmpty();
    }

    [Fact]
    public void Group_Batch_Closed_After_Dispose_Raises_No_Local_Event_And_No_Hub_Message()
    {
        using var hub = new MessageHub();
        var group = Group(hub);
        var messages = HubMessages(hub, group);
        var localEvents = 0;
        group.CollectionChanged += (_, _) => localEvents++;

        var batch = group.BatchUpdate();
        group.Add(Child(hub, "a"));
        group.Dispose();
        batch.Dispose();

        localEvents.Should().Be(0);
        messages.Should().BeEmpty();
    }

    [Fact]
    public void Concurrent_Batches_Keep_An_Exact_Depth()
    {
        using var hub = new MessageHub();
        var composite = Composite(hub);
        const int threads = 8;
        const int iterations = 200_000;
        using var start = new Barrier(threads);
        var workers = Enumerable.Range(0, threads).Select(_ => new Thread(() =>
        {
            start.SignalAndWait();
            for (var i = 0; i < iterations; i++) composite.BatchUpdate().Dispose();
        })).ToArray();
        foreach (var worker in workers) worker.Start();
        foreach (var worker in workers) worker.Join();

        var log = new List<string>();
        composite.CollectionChanged += (_, e) => log.Add($"local:{e.Action}");
        hub.Messages.OfType<CollectionChangedMessage<IComponentVM>>()
            .Where(message => ReferenceEquals(message.Sender, composite))
            .Subscribe(message => log.Add($"hub:{message.Action}"));

        var batch = composite.BatchUpdate();
        composite.Add(Child(hub, "a"));
        log.Should().BeEmpty("an open batch suppresses the per-mutation event");
        batch.Dispose();

        log.Should().Equal("local:Reset", "hub:Reset");
    }

    [Fact]
    public void Close_During_A_Raise_That_Saw_The_Open_Batch_Still_Delivers_The_Reset()
    {
        // The probe pauses a Raise after it saw the open batch and before it
        // marks the batch dirty, and closes the batch from another thread in
        // that gap. Without one lock over the depth and the dirty flag, the
        // close finds the batch clean, and the dirty flag set after it is
        // never delivered (#1344). With the lock, the close waits for the
        // Raise and then delivers one Reset.
        var delivered = new List<NotifyCollectionChangedAction>();
        var batch = new ContainerBatch(args => { lock (delivered) delivered.Add(args.Action); }, () => true);
        var handle = batch.Enter();
        using var closed = new ManualResetEventSlim();
        Thread? closer = null;
        batch.RaiseProbe = () =>
        {
            closer = new Thread(() =>
            {
                handle.Dispose();
                closed.Set();
            });
            closer.Start();
            closed.Wait(TimeSpan.FromMilliseconds(200));
        };

        batch.Raise(new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Add, "a", 0));
        batch.RaiseProbe = null;
        closer!.Join();

        lock (delivered) delivered.Should().Equal(NotifyCollectionChangedAction.Reset);
    }

    [Fact]
    public void Add_Racing_Batches_Is_Never_Lost()
    {
        using var hub = new MessageHub();
        var composite = Composite(hub);
        var lastAddStarted = 0;
        var eventsAfterLastAdd = 0;
        composite.CollectionChanged += (_, _) =>
        {
            if (Volatile.Read(ref lastAddStarted) == 1) Interlocked.Increment(ref eventsAfterLastAdd);
        };
        const int adds = 2_000;
        var stop = 0;
        var batcher = new Thread(() =>
        {
            while (Volatile.Read(ref stop) == 0) composite.BatchUpdate().Dispose();
        });
        batcher.Start();
        try
        {
            for (var i = 0; i < adds; i++)
            {
                if (i == adds - 1) Volatile.Write(ref lastAddStarted, 1);
                composite.Add(Child(hub, $"c{i}"));
            }
        }
        finally
        {
            Volatile.Write(ref stop, 1);
            batcher.Join();
        }

        Volatile.Read(ref eventsAfterLastAdd).Should().BeGreaterThan(0);
        composite.Count.Should().Be(adds);
    }
}
