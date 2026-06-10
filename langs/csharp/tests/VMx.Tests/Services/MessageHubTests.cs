using FluentAssertions;
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
}
