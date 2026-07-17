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
            else
            {
                // A scenario added to message-ordering.json must be exercised,
                // not silently skipped (parity with the Python suite's fail-loud).
                Assert.Fail($"Unknown message-ordering scenario id: '{scenario.Id}'");
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

    [Fact, Trait("Conformance", "HUB-008")]
    public void HUB_008_Nested_Batches_Defer_And_Preserve_FIFO()
    {
        using var hub = new MessageHub();
        using var rec = new RecordedMessages<Stub>(hub.Messages);

        hub.Batch(() =>
        {
            hub.Send(new Stub("A"));
            hub.Batch(() => hub.Send(new Stub("B")));
            hub.Send(new Stub("C"));
            rec.Items.Should().BeEmpty("the outermost batch has not exited");
        });

        rec.Items.Select(m => m.Tag).Should().Equal("A", "B", "C");
    }

    [Fact, Trait("Conformance", "HUB-009")]
    public void HUB_009_Batch_Error_Drains_Then_Rethrows_Original()
    {
        using var hub = new MessageHub();
        using var rec = new RecordedMessages<Stub>(hub.Messages);
        var sentinel = new InvalidOperationException("sentinel");

        Action act = () => hub.Batch(() =>
        {
            hub.Send(new Stub("A"));
            throw sentinel;
        });

        act.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(sentinel);
        rec.Items.Select(m => m.Tag).Should().Equal("A");
    }

    [Fact, Trait("Conformance", "HUB-010")]
    public void HUB_010_Reentrant_Send_Joins_Iterative_FIFO_Drain()
    {
        using var hub = new MessageHub();
        var trace = new List<string>();
        using var first = hub.Messages.OfType<Stub>().Subscribe(message =>
        {
            trace.Add($"first:{message.Tag}");
            if (message.Tag == "A") hub.Send(new Stub("B"));
        });
        using var second = hub.Messages.OfType<Stub>()
            .Subscribe(message => trace.Add($"second:{message.Tag}"));

        hub.Send(new Stub("A"));

        trace.Should().Equal("first:A", "second:A", "first:B", "second:B");
    }

    [Fact, Trait("Conformance", "HUB-011")]
    public void HUB_011_Subscriber_Failure_Does_Not_Abort_Batch_Drain()
    {
        using var hub = new MessageHub();
        var seen = new List<string>();
        using var bad = hub.Messages.OfType<Stub>()
            .Subscribe(_ => throw new InvalidOperationException("bad"));
        using var good = hub.Messages.OfType<Stub>().Subscribe(message => seen.Add(message.Tag));

        Action act = () => hub.Batch(() =>
        {
            hub.Send(new Stub("A"));
            hub.Send(new Stub("B"));
        });

        act.Should().NotThrow();
        seen.Should().Equal("A", "B");
    }

    [Fact, Trait("Conformance", "HUB-012")]
    public void HUB_012_Dispose_During_Batch_Drops_Queued_Messages()
    {
        var hub = new MessageHub();
        var seen = new List<string>();
        var completed = false;
        using var subscription = hub.Messages.OfType<Stub>().Subscribe(
            message => seen.Add(message.Tag),
            () => completed = true);

        hub.Batch(() =>
        {
            hub.Send(new Stub("A"));
            hub.Dispose();
            hub.Send(new Stub("B"));
        });
        hub.Send(new Stub("C"));

        seen.Should().BeEmpty();
        completed.Should().BeTrue();
    }

    [Fact, Trait("Conformance", "HUB-013")]
    public void HUB_013_Ordinary_Send_Remains_Synchronous()
    {
        using var hub = new MessageHub();
        var delivered = false;
        using var subscription = hub.Messages.Subscribe(_ => delivered = true);

        hub.Send(new Stub("A"));

        delivered.Should().BeTrue("ordinary Send must deliver before returning");
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
