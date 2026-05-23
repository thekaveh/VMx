using FluentAssertions;
using VMx.Lifecycle;
using VMx.Messages;
using Xunit;

namespace VMx.Tests.Messages;

public class MessageRecordTests
{
    [Fact]
    public void PropertyChangedMessage_Create_Sets_All_Fields()
    {
        var sender = new object();
        var msg = PropertyChangedMessage<object>.Create(sender, "name", "Model");
        msg.Sender.Should().BeSameAs(sender);
        msg.SenderName.Should().Be("name");
        msg.PropertyName.Should().Be("Model");
        msg.SenderObject.Should().BeSameAs(sender);
    }

    [Fact]
    public void PropertyChangedMessage_Equal_When_Same_Values()
    {
        var sender = new object();
        var a = PropertyChangedMessage<object>.Create(sender, "x", "P");
        var b = PropertyChangedMessage<object>.Create(sender, "x", "P");
        a.Should().Be(b, "records have value equality");
    }

    [Fact]
    public void ConstructionStatusChangedMessage_Create_Sets_All_Fields()
    {
        var sender = new object();
        var msg = ConstructionStatusChangedMessage.Create(sender, "vm1", ConstructionStatus.Constructed);
        msg.Sender.Should().BeSameAs(sender);
        msg.SenderName.Should().Be("vm1");
        msg.Status.Should().Be(ConstructionStatus.Constructed);
        msg.SenderObject.Should().BeSameAs(sender);
    }
}
