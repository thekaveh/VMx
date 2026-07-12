using System.Collections.Specialized;
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

    [Fact]
    public void CollectionChangedMessage_FiveParameterConstructionAndDeconstructionRemainCompatible()
    {
        var sender = new object();
        var message = new CollectionChangedMessage<int>(
            sender,
            NotifyCollectionChangedAction.Add,
            new List<int> { 1 },
            Array.Empty<int>(),
            0);

        var (actualSender, action, newItems, oldItems, index) = message;

        actualSender.Should().BeSameAs(sender);
        action.Should().Be(NotifyCollectionChangedAction.Add);
        newItems.Should().Equal(1);
        oldItems.Should().BeEmpty();
        index.Should().Be(0);
        message.OldIndex.Should().Be(-1);
        message.NewIndex.Should().Be(-1);
    }

    [Fact]
    public void CollectionChangedMessage_LegacyInterfaceImplementerReceivesCompatiblePositionDefaults()
    {
        ICollectionChangedMessage<int> message = new LegacyCollectionChangedMessage();

        message.OldIndex.Should().Be(4);
        message.NewIndex.Should().Be(4);
    }

    private sealed class LegacyCollectionChangedMessage : ICollectionChangedMessage<int>
    {
        public string SenderName => "legacy";

        public object SenderObject => this;

        public NotifyCollectionChangedAction Action => NotifyCollectionChangedAction.Replace;

        public IReadOnlyList<int> NewItems => new[] { 2 };

        public IReadOnlyList<int> OldItems => new[] { 1 };

        public int Index => 4;
    }
}
