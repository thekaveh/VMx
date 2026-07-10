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
