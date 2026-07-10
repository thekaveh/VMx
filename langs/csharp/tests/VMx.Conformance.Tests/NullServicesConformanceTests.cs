using System.Reactive.Concurrency;
using FluentAssertions;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for null-object service variants, NULL-001..003.
/// See spec/03-messages.md, spec/11-threading.md, ADR-0017.
/// </summary>
public class NullServicesConformanceTests
{
    // ── NULL-001 ────────────────────────────────────────────────────────────

    /// <summary>NULL-001: NullMessageHub.Send is a no-op, Messages is empty.</summary>
    [Fact, Trait("Conformance", "NULL-001")]
    public void NULL_001_NullMessageHub_Is_Safe_NoOp()
    {
        var hub = NullMessageHub.Instance;
        var observed = new List<IMessage>();
        var completed = false;

        using var sub = hub.Messages.Subscribe(observed.Add, () => completed = true);

        for (var i = 0; i < 5; i++)
        {
            hub.Send(ConstructionStatusChangedMessage.Create(this, "x", ConstructionStatus.Constructed));
        }

        var bodyRan = false;
        hub.Batch(() =>
        {
            bodyRan = true;
            hub.Send(ConstructionStatusChangedMessage.Create(this, "x", ConstructionStatus.Constructed));
        });

        observed.Should().BeEmpty();
        completed.Should().BeTrue("the empty observable completes on subscribe");
        bodyRan.Should().BeTrue("a null transaction still executes its body");
    }

    // ── NULL-002 ────────────────────────────────────────────────────────────

    /// <summary>NULL-002: NullDispatcher schedules synchronously on the calling thread.</summary>
    [Fact, Trait("Conformance", "NULL-002")]
    public void NULL_002_NullDispatcher_Schedules_Synchronously()
    {
        var dispatcher = NullDispatcher.Instance;
        var fgRan = false;
        var bgRan = false;

        dispatcher.Foreground.Schedule(() => fgRan = true);
        fgRan.Should().BeTrue();

        dispatcher.Background.Schedule(() => bgRan = true);
        bgRan.Should().BeTrue();
    }

    // ── NULL-003 ────────────────────────────────────────────────────────────

    /// <summary>NULL-003: null variants exist and are total for every core contract.</summary>
    [Fact, Trait("Conformance", "NULL-003")]
#pragma warning disable CA1859 // The test deliberately works via the contract type, not the concrete null.
    public void NULL_003_Null_Convention_Satisfied()
    {
        // IMessageHub → NullMessageHub
        IMessageHub hub = NullMessageHub.Instance;
        hub.Send(ConstructionStatusChangedMessage.Create(this, "x", ConstructionStatus.Destructed));
        hub.Messages.Should().NotBeNull();

        // IDispatcher → NullDispatcher
        IDispatcher dispatcher = NullDispatcher.Instance;
        dispatcher.Foreground.Should().NotBeNull();
        dispatcher.Background.Should().NotBeNull();
    }
#pragma warning restore CA1859
}
