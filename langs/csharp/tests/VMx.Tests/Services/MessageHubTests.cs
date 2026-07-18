using FluentAssertions;
using System.Reactive.Linq;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Services;

public class MessageHubTests
{
    private sealed record Stub(string Tag) : IMessage
    {
        public string SenderName => Tag;
        public object SenderObject => Tag;
    }

    [Fact]
    public void Send_Delivers_To_Current_Subscriber()
    {
        using var hub = new MessageHub();
        using var rec = new RecordedMessages<Stub>(hub.Messages);
        hub.Send(new Stub("A"));
        rec.Items.Should().ContainSingle().Which.Tag.Should().Be("A");
    }

    [Fact]
    public void Late_Subscriber_Does_Not_See_Prior_Messages()
    {
        using var hub = new MessageHub();
        hub.Send(new Stub("pre"));
        using var rec = new RecordedMessages<Stub>(hub.Messages);
        hub.Send(new Stub("post"));
        rec.Items.Should().ContainSingle().Which.Tag.Should().Be("post");
    }

    [Fact]
    public void Single_Producer_FIFO()
    {
        using var hub = new MessageHub();
        using var rec = new RecordedMessages<Stub>(hub.Messages);
        hub.Send(new Stub("A"));
        hub.Send(new Stub("B"));
        hub.Send(new Stub("C"));
        rec.Items.Select(m => m.Tag).Should().Equal("A", "B", "C");
    }

    [Fact]
    public void Subscriber_Exception_Does_Not_Break_Hub()
    {
        using var hub = new MessageHub();
        var goodCount = 0;
        var bad = hub.Messages.Subscribe(_ => throw new InvalidOperationException("bad"));
        var good = hub.Messages.Subscribe(_ => goodCount++);
        hub.Send(new Stub("A"));
        hub.Send(new Stub("B"));
        goodCount.Should().Be(2, "the surviving subscriber sees both messages");
        bad.Dispose(); good.Dispose();
    }

    [Fact]
    public void Send_After_Dispose_Is_Silently_Dropped()
    {
        var hub = new MessageHub();
        var received = 0;
        using var sub = hub.Messages.Subscribe(_ => received++);

        hub.Dispose();
        var act = () => hub.Send(new Stub("late"));

        act.Should().NotThrow("shutdown-time sends are dropped, not faulted");
        received.Should().Be(0);
    }

    [Fact]
    public async Task Concurrent_Producer_Waits_For_Batch_Then_Delivers_On_Its_Own_Thread()
    {
        using var hub = new MessageHub();
        using var batchEntered = new ManualResetEventSlim();
        using var releaseBatch = new ManualResetEventSlim();
        using var sendStarted = new ManualResetEventSlim();
        using var sendFinished = new ManualResetEventSlim();
        var producerThread = 0;
        var deliveryThread = 0;
        using var subscription = hub.Messages.Subscribe(_ =>
            deliveryThread = Environment.CurrentManagedThreadId);

        var batchTask = Task.Run(() => hub.Batch(() =>
        {
            batchEntered.Set();
            releaseBatch.Wait();
        }));
        batchEntered.Wait();
        var sendTask = Task.Run(() =>
        {
            producerThread = Environment.CurrentManagedThreadId;
            sendStarted.Set();
            hub.Send(new Stub("concurrent"));
            sendFinished.Set();
        });
        sendStarted.Wait();

        var wasBlocked = false;
        try
        {
            wasBlocked = !sendFinished.Wait(TimeSpan.FromMilliseconds(50));
        }
        finally
        {
            releaseBatch.Set();
            await Task.WhenAll(batchTask, sendTask);
        }

        wasBlocked.Should().BeTrue("the active transaction serializes other producers");
        deliveryThread.Should().Be(producerThread);
    }

    [Fact]
    public async Task Concurrent_Producer_Waits_For_Active_Drain_Then_Delivers_On_Its_Own_Thread()
    {
        using var hub = new MessageHub();
        using var drainEntered = new ManualResetEventSlim();
        using var releaseDrain = new ManualResetEventSlim();
        using var sendStarted = new ManualResetEventSlim();
        using var sendFinished = new ManualResetEventSlim();
        var producerThread = 0;
        var deliveryThread = 0;
        using var subscription = hub.Messages.OfType<Stub>().Subscribe(message =>
        {
            if (message.Tag == "blocker")
            {
                drainEntered.Set();
                releaseDrain.Wait();
            }
            else if (message.Tag == "concurrent")
            {
                deliveryThread = Environment.CurrentManagedThreadId;
            }
        });

        var drainer = Task.Run(() => hub.Send(new Stub("blocker")));
        drainEntered.Wait();
        var producer = Task.Run(() =>
        {
            producerThread = Environment.CurrentManagedThreadId;
            sendStarted.Set();
            hub.Send(new Stub("concurrent"));
            sendFinished.Set();
        });
        sendStarted.Wait();

        var wasBlocked = false;
        try
        {
            wasBlocked = !sendFinished.Wait(TimeSpan.FromMilliseconds(50));
        }
        finally
        {
            releaseDrain.Set();
            await Task.WhenAll(drainer, producer);
        }

        wasBlocked.Should().BeTrue("the active drain serializes other producers");
        deliveryThread.Should().Be(producerThread);
    }

    [Fact]
    public async Task Concurrent_Dispose_Waits_For_Active_Delivery_Before_Completing_Stream()
    {
        var hub = new MessageHub();
        using var deliveryEntered = new ManualResetEventSlim();
        using var releaseDelivery = new ManualResetEventSlim();
        using var disposeStarted = new ManualResetEventSlim();
        var inDelivery = 0;
        var completionDuringDelivery = 0;
        var completionCount = 0;
        using var subscription = hub.Messages.Subscribe(
            _ =>
            {
                Volatile.Write(ref inDelivery, 1);
                deliveryEntered.Set();
                releaseDelivery.Wait();
                Volatile.Write(ref inDelivery, 0);
            },
            () =>
            {
                if (Volatile.Read(ref inDelivery) != 0)
                    Interlocked.Exchange(ref completionDuringDelivery, 1);
                Interlocked.Increment(ref completionCount);
            });

        var send = Task.Run(() => hub.Send(new Stub("blocking")));
        deliveryEntered.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue();
        var dispose = Task.Run(() =>
        {
            disposeStarted.Set();
            hub.Dispose();
        });
        disposeStarted.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue();

        var disposeReturnedBeforeRelease = false;
        try
        {
            disposeReturnedBeforeRelease = await Task.WhenAny(
                dispose,
                Task.Delay(TimeSpan.FromMilliseconds(50))) == dispose;
        }
        finally
        {
            releaseDelivery.Set();
        }
        await Task.WhenAll(send, dispose).WaitAsync(TimeSpan.FromSeconds(5));

        disposeReturnedBeforeRelease.Should().BeFalse(
            "terminal delivery must serialize behind the active OnNext callback");
        completionDuringDelivery.Should().Be(0);
        completionCount.Should().Be(1);
    }

    [Fact]
    public void Reentrant_Dispose_Completes_After_InFlight_Message_Reaches_Subscribers()
    {
        var hub = new MessageHub();
        var trace = new List<string>();
        using var first = hub.Messages.Subscribe(
            _ =>
            {
                trace.Add("first:start");
                hub.Dispose();
                trace.Add("first:end");
            },
            () => trace.Add("first:completed"));
        using var second = hub.Messages.Subscribe(
            _ => trace.Add("second:message"),
            () => trace.Add("second:completed"));

        hub.Send(new Stub("dispose"));

        trace.Should().Equal(
            "first:start",
            "first:end",
            "second:message",
            "first:completed",
            "second:completed");
    }

    [Fact]
    public async Task Opposing_Hub_Callbacks_Do_Not_Deadlock()
    {
        using var left = new MessageHub();
        using var right = new MessageHub();
        using var callbacksEntered = new Barrier(2);
        var innerDeliveries = 0;
        using var leftSubscription = left.Messages.OfType<Stub>().Subscribe(message =>
        {
            if (message.Tag == "outer")
            {
                callbacksEntered.SignalAndWait();
                right.Send(new Stub("inner"));
            }
            else
            {
                Interlocked.Increment(ref innerDeliveries);
            }
        });
        using var rightSubscription = right.Messages.OfType<Stub>().Subscribe(message =>
        {
            if (message.Tag == "outer")
            {
                callbacksEntered.SignalAndWait();
                left.Send(new Stub("inner"));
            }
            else
            {
                Interlocked.Increment(ref innerDeliveries);
            }
        });

        var sends = Task.WhenAll(
            Task.Run(() => left.Send(new Stub("outer"))),
            Task.Run(() => right.Send(new Stub("outer"))));

        var completed = await Task.WhenAny(sends, Task.Delay(TimeSpan.FromSeconds(2)));
        completed.Should().BeSameAs(sends, "nested cross-hub sends must not form a wait cycle");
        await sends;
        innerDeliveries.Should().Be(2);
    }

    [Fact]
    public async Task Opposing_Hub_Callbacks_Can_Dispose_Each_Other_Without_Deadlock()
    {
        var left = new MessageHub();
        var right = new MessageHub();
        using var callbacksEntered = new Barrier(2);
        var leftCompletions = 0;
        var rightCompletions = 0;
        using var leftSubscription = left.Messages.Subscribe(
            _ =>
            {
                callbacksEntered.SignalAndWait();
                right.Dispose();
            },
            () => Interlocked.Increment(ref leftCompletions));
        using var rightSubscription = right.Messages.Subscribe(
            _ =>
            {
                callbacksEntered.SignalAndWait();
                left.Dispose();
            },
            () => Interlocked.Increment(ref rightCompletions));

        var sends = Task.WhenAll(
            Task.Run(() => left.Send(new Stub("outer"))),
            Task.Run(() => right.Send(new Stub("outer"))));

        var completed = await Task.WhenAny(sends, Task.Delay(TimeSpan.FromSeconds(2)));
        completed.Should().BeSameAs(sends, "terminal deferral must not form a cross-hub wait cycle");
        await sends;
        leftCompletions.Should().Be(1);
        rightCompletions.Should().Be(1);
    }

    [Fact]
    public async Task Opposing_Hub_Callback_Batches_Do_Not_Deadlock_And_Defer_Delivery()
    {
        using var left = new MessageHub();
        using var right = new MessageHub();
        using var callbacksEntered = new Barrier(2);
        var innerDeliveries = 0;
        var deliveryInsideBorrowedScope = 0;
        var leftBorrowedScope = 0;
        var rightBorrowedScope = 0;
        using var leftSubscription = left.Messages.OfType<Stub>().Subscribe(message =>
        {
            if (message.Tag == "outer")
            {
                callbacksEntered.SignalAndWait();
                right.Batch(() =>
                {
                    Volatile.Write(ref rightBorrowedScope, 1);
                    try { right.Send(new Stub("inner")); }
                    finally { Volatile.Write(ref rightBorrowedScope, 0); }
                });
            }
            else
            {
                if (Volatile.Read(ref leftBorrowedScope) != 0)
                    Interlocked.Exchange(ref deliveryInsideBorrowedScope, 1);
                Interlocked.Increment(ref innerDeliveries);
            }
        });
        using var rightSubscription = right.Messages.OfType<Stub>().Subscribe(message =>
        {
            if (message.Tag == "outer")
            {
                callbacksEntered.SignalAndWait();
                left.Batch(() =>
                {
                    Volatile.Write(ref leftBorrowedScope, 1);
                    try { left.Send(new Stub("inner")); }
                    finally { Volatile.Write(ref leftBorrowedScope, 0); }
                });
            }
            else
            {
                if (Volatile.Read(ref rightBorrowedScope) != 0)
                    Interlocked.Exchange(ref deliveryInsideBorrowedScope, 1);
                Interlocked.Increment(ref innerDeliveries);
            }
        });

        var sends = Task.WhenAll(
            Task.Run(() => left.Send(new Stub("outer"))),
            Task.Run(() => right.Send(new Stub("outer"))));

        await sends.WaitAsync(TimeSpan.FromSeconds(5));
        innerDeliveries.Should().Be(2);
        deliveryInsideBorrowedScope.Should().Be(0,
            "the target owner cannot drain until the borrowed batch body exits");
    }

    [Theory]
    [InlineData("send")]
    [InlineData("batch")]
    [InlineData("dispose")]
    public async Task Unrelated_Hub_Callback_Waits_For_Busy_Target(string operation)
    {
        using var source = new MessageHub();
        using var target = new MessageHub();
        using var batchEntered = new ManualResetEventSlim();
        using var releaseBatch = new ManualResetEventSlim();
        using var callbackFinished = new ManualResetEventSlim();
        var deliveries = 0;
        var completions = 0;
        using var targetSubscription = target.Messages.Subscribe(
            _ => Interlocked.Increment(ref deliveries),
            () => Interlocked.Increment(ref completions));

        var targetBatch = Task.Run(() => target.Batch(() =>
        {
            batchEntered.Set();
            releaseBatch.Wait();
        }));
        batchEntered.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue();

        using var sourceSubscription = source.Messages.Subscribe(_ =>
        {
            switch (operation)
            {
                case "send":
                    target.Send(new Stub("nested"));
                    break;
                case "batch":
                    target.Batch(() => target.Send(new Stub("nested")));
                    break;
                case "dispose":
                    target.Dispose();
                    break;
            }
            callbackFinished.Set();
        });
        var sourceSend = Task.Run(() => source.Send(new Stub("outer")));

        var wasBlocked = false;
        try
        {
            wasBlocked = !callbackFinished.Wait(TimeSpan.FromMilliseconds(50));
        }
        finally
        {
            releaseBatch.Set();
            await Task.WhenAll(targetBatch, sourceSend).WaitAsync(TimeSpan.FromSeconds(5));
        }

        wasBlocked.Should().BeTrue(
            "a callback only defers when waiting would close an actual cross-hub cycle");
        if (operation == "dispose")
        {
            completions.Should().Be(1);
            deliveries.Should().Be(0);
        }
        else
        {
            deliveries.Should().Be(1);
        }
    }

    [Fact]
    public void Development_Drain_Diagnostic_Names_Message_Type()
    {
#if DEBUG
        using var hub = new MessageHub();
        using var subscription = hub.Messages.OfType<Stub>()
            .Subscribe(message => hub.Send(new Stub(message.Tag)));

        Action act = () => hub.Send(new Stub("cycle"));

        act.Should().Throw<InvalidOperationException>()
            .WithMessage("*possible publish cycle involving: Stub*");
#endif
    }
}
