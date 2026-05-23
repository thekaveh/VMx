using FluentAssertions;
using System.Reactive.Linq;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

public class HubConformanceTests
{
    private sealed record Stub(string Tag) : IMessage
    {
        public string SenderName => Tag;
        public object SenderObject => Tag;
    }

    [Fact, Trait("Conformance", "HUB-001")]
    public void HUB_001_Send_Delivers_To_Current_Subscribers()
    {
        using var hub = new MessageHub();
        using var rec = new RecordedMessages<Stub>(hub.Messages);
        hub.Send(new Stub("A"));
        rec.Items.Should().HaveCount(1);
    }

    [Fact, Trait("Conformance", "HUB-002")]
    public void HUB_002_Late_Subscribers_Do_Not_See_Prior()
    {
        using var hub = new MessageHub();
        hub.Send(new Stub("A"));
        using var rec = new RecordedMessages<Stub>(hub.Messages);
        hub.Send(new Stub("B"));
        rec.Items.Select(m => m.Tag).Should().Equal("B");
    }

    [Fact, Trait("Conformance", "HUB-003")]
    public void HUB_003_Single_Producer_FIFO()
    {
        using var hub = new MessageHub();
        using var rec = new RecordedMessages<Stub>(hub.Messages);
        hub.Send(new Stub("A"));
        hub.Send(new Stub("B"));
        hub.Send(new Stub("C"));
        rec.Items.Select(m => m.Tag).Should().Equal("A", "B", "C");
    }

    [Fact, Trait("Conformance", "HUB-004")]
    public void HUB_004_Subscriber_Dispose_During_Emit_Does_Not_Crash()
    {
        using var hub = new MessageHub();
        var seen = new List<string>();
        IDisposable? sub = null;
        sub = hub.Messages.OfType<Stub>().Subscribe(m =>
        {
            seen.Add(m.Tag);
            sub?.Dispose();
        });
        hub.Send(new Stub("A"));
        hub.Send(new Stub("B"));
        seen.Should().Equal("A");
    }

    [Fact, Trait("Conformance", "HUB-005")]
    public void HUB_005_Multiple_Subscribers_All_Observe()
    {
        using var hub = new MessageHub();
        using var a = new RecordedMessages<Stub>(hub.Messages);
        using var b = new RecordedMessages<Stub>(hub.Messages);
        using var c = new RecordedMessages<Stub>(hub.Messages);
        hub.Send(new Stub("X"));
        a.Items.Should().HaveCount(1);
        b.Items.Should().HaveCount(1);
        c.Items.Should().HaveCount(1);
    }

    [Fact, Trait("Conformance", "HUB-006")]
    public void HUB_006_Hub_Matches_Message_Ordering_Fixture()
    {
        var root = Fixtures.FixtureLoader.Load<OrderingFixture>("message-ordering.json");
        foreach (var scenario in root.Scenarios)
        {
            scenario.Id.Should().NotBeNullOrEmpty();
            // Single-producer FIFO scenario.
            if (scenario.Id == "single-producer-fifo")
            {
                using var hub = new MessageHub();
                using var rec = new RecordedMessages<Stub>(hub.Messages);
                foreach (var tag in scenario.ProducerSends!)
                    hub.Send(new Stub(tag));
                rec.Items.Select(m => m.Tag).Should().Equal(scenario.ExpectedObserved!);
            }
            // Late subscribe scenario.
            else if (scenario.Id == "late-subscribe-no-replay")
            {
                using var hub = new MessageHub();
                foreach (var tag in scenario.ProducerSendsBeforeSubscribe!)
                    hub.Send(new Stub(tag));
                using var rec = new RecordedMessages<Stub>(hub.Messages);
                foreach (var tag in scenario.ProducerSendsAfterSubscribe!)
                    hub.Send(new Stub(tag));
                rec.Items.Select(m => m.Tag).Should().Equal(scenario.ExpectedObserved!);
            }
            // Multi-subscriber scenario.
            else if (scenario.Id == "multiple-subscribers-same-message")
            {
                using var hub = new MessageHub();
                var subscribers = Enumerable.Range(0, scenario.SubscriberCount)
                    .Select(_ => new RecordedMessages<Stub>(hub.Messages))
                    .ToList();
                foreach (var tag in scenario.ProducerSends!)
                    hub.Send(new Stub(tag));
                foreach (var sub in subscribers)
                {
                    sub.Items.Select(m => m.Tag).Should().Equal(scenario.ExpectedObservedPerSubscriber!);
                    sub.Dispose();
                }
            }
            // Unsubscribe during emit.
            else if (scenario.Id == "unsubscribe-during-emit")
            {
                using var hub = new MessageHub();
                var seen = new List<string>();
                IDisposable? sub = null;
                sub = hub.Messages.OfType<Stub>().Subscribe(m =>
                {
                    seen.Add(m.Tag);
                    if (scenario.UnsubscribeAfterFirst) sub?.Dispose();
                });
                foreach (var tag in scenario.ProducerSends!)
                    hub.Send(new Stub(tag));
                seen.Should().Equal(scenario.ExpectedObserved!);
            }
        }
    }

    [Fact, Trait("Conformance", "HUB-007")]
    public void HUB_007_Subscriber_Handler_Raises_Does_Not_Break_Hub()
    {
        using var hub = new MessageHub();
        var goodSeen = new List<string>();
        var badSub = hub.Messages.OfType<Stub>().Subscribe(_ => throw new InvalidOperationException("bad"));
        var goodSub = hub.Messages.OfType<Stub>().Subscribe(m => goodSeen.Add(m.Tag));

        hub.Send(new Stub("A"));
        hub.Send(new Stub("B"));

        goodSeen.Should().Equal("A", "B");

        badSub.Dispose();
        goodSub.Dispose();
    }

    private sealed class OrderingFixture
    {
        public List<Scenario> Scenarios { get; init; } = new();
    }

    private sealed class Scenario
    {
        public string Id { get; init; } = "";
        public List<string>? ProducerSends { get; init; }
        public List<string>? ProducerSendsBeforeSubscribe { get; init; }
        public List<string>? ProducerSendsAfterSubscribe { get; init; }
        public List<string>? ExpectedObserved { get; init; }
        public List<string>? ExpectedObservedPerSubscriber { get; init; }
        public int SubscriberCount { get; init; }
        public bool UnsubscribeAfterFirst { get; init; }
    }
}
