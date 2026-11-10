using System.Reactive.Concurrency;
using FluentAssertions;
using Microsoft.Reactive.Testing;
using VMx.Services;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: DLY-001..DLY-005 — <see cref="DelayedTask"/> over a
/// virtual-time scheduler (spec/11 §6.3, ADR-0219).
/// </summary>
public class DLY_001_to_005_DelayedTaskTests
{
    private static void Advance(TestScheduler scheduler, double seconds) =>
        scheduler.AdvanceBy(TimeSpan.FromSeconds(seconds).Ticks);

    [Fact]
    [Trait("Conformance", "DLY-001")]
    public void DLY_001_Scheduled_Action_Runs_Once_At_Its_Due_Time()
    {
        var scheduler = new TestScheduler();
        using var task = new DelayedTask(scheduler);
        var runs = 0;
        bool? pendingInsideAction = null;

        task.Schedule(TimeSpan.FromSeconds(10), () =>
        {
            runs++;
            pendingInsideAction = task.IsPending;
        });
        task.IsPending.Should().BeTrue();

        Advance(scheduler, 9);
        runs.Should().Be(0);
        task.IsPending.Should().BeTrue();

        Advance(scheduler, 1);
        runs.Should().Be(1);
        pendingInsideAction.Should().BeFalse();
        task.IsPending.Should().BeFalse();

        Advance(scheduler, 10);
        runs.Should().Be(1);
    }

    [Fact]
    [Trait("Conformance", "DLY-001")]
    public void DLY_001_Action_Can_Reschedule_Itself_As_A_Polling_Loop()
    {
        var scheduler = new TestScheduler();
        using var task = new DelayedTask(scheduler);
        var runTimes = new List<TimeSpan>();

        void Poll()
        {
            runTimes.Add(TimeSpan.FromTicks(scheduler.Clock));
            if (runTimes.Count < 3) task.Schedule(TimeSpan.FromSeconds(5), Poll);
        }

        task.Schedule(TimeSpan.FromSeconds(5), Poll);
        Advance(scheduler, 30);

        runTimes.Should().Equal(TimeSpan.FromSeconds(5), TimeSpan.FromSeconds(10), TimeSpan.FromSeconds(15));
        task.IsPending.Should().BeFalse();
    }

    [Fact]
    [Trait("Conformance", "DLY-002")]
    public void DLY_002_Second_Schedule_Replaces_Pending_Action_And_Restarts_Delay()
    {
        var scheduler = new TestScheduler();
        using var task = new DelayedTask(scheduler);
        var aRuns = 0;
        var bRuns = 0;

        task.Schedule(TimeSpan.FromSeconds(10), () => aRuns++);
        Advance(scheduler, 6);
        task.Schedule(TimeSpan.FromSeconds(10), () => bRuns++);
        Advance(scheduler, 9);

        aRuns.Should().Be(0);
        bRuns.Should().Be(0);
        task.IsPending.Should().BeTrue();

        Advance(scheduler, 1);
        bRuns.Should().Be(1);

        Advance(scheduler, 10);
        aRuns.Should().Be(0);
        bRuns.Should().Be(1);
    }

    [Fact]
    [Trait("Conformance", "DLY-003")]
    public void DLY_003_Cancel_Prevents_The_Pending_Action()
    {
        var scheduler = new TestScheduler();
        using var task = new DelayedTask(scheduler);

        task.Cancel();
        task.IsPending.Should().BeFalse();

        var cancelledRuns = 0;
        task.Schedule(TimeSpan.FromSeconds(10), () => cancelledRuns++);
        Advance(scheduler, 4);
        task.Cancel();
        task.IsPending.Should().BeFalse();
        Advance(scheduler, 7);
        cancelledRuns.Should().Be(0);

        TimeSpan? newRunAt = null;
        task.Schedule(TimeSpan.FromSeconds(10), () => newRunAt = TimeSpan.FromTicks(scheduler.Clock));
        Advance(scheduler, 9);
        newRunAt.Should().BeNull();
        Advance(scheduler, 1);
        newRunAt.Should().Be(TimeSpan.FromSeconds(21));
        cancelledRuns.Should().Be(0);
    }

    [Fact]
    [Trait("Conformance", "DLY-004")]
    public void DLY_004_Dispose_Cancels_Pending_Action_And_Later_Calls_Are_Inert()
    {
        var scheduler = new TestScheduler();
        var task = new DelayedTask(scheduler);
        var runs = 0;
        task.Schedule(TimeSpan.FromSeconds(10), () => runs++);

        task.Dispose();
        task.Dispose();
        task.IsPending.Should().BeFalse();
        Advance(scheduler, 11);
        runs.Should().Be(0);

        var act = () =>
        {
            task.Schedule(TimeSpan.FromSeconds(1), () => runs++);
            task.Cancel();
            task.Schedule(TimeSpan.FromSeconds(1), () => runs++);
        };
        act.Should().NotThrow();
        task.IsPending.Should().BeFalse();
        Advance(scheduler, 5);
        runs.Should().Be(0);

        var otherRuns = 0;
        scheduler.Schedule(TimeSpan.FromSeconds(1), () => otherRuns++);
        Advance(scheduler, 1);
        otherRuns.Should().Be(1);
    }

    [Fact]
    [Trait("Conformance", "DLY-005")]
    public void DLY_005_Failing_Action_Stays_Isolated_And_Task_Stays_Usable()
    {
        var scheduler = new TestScheduler();
        using var task = new DelayedTask(scheduler);

        task.Schedule(TimeSpan.FromSeconds(1), () => throw new InvalidOperationException("boom"));
        var advance = () => Advance(scheduler, 2);
        advance.Should().NotThrow();
        task.IsPending.Should().BeFalse();

        var secondRuns = 0;
        task.Schedule(TimeSpan.FromSeconds(1), () => secondRuns++);
        Advance(scheduler, 2);
        secondRuns.Should().Be(1);
        task.IsPending.Should().BeFalse();
    }
}
