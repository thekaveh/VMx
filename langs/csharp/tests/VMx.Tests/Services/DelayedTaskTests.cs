using System.Reactive.Concurrency;
using FluentAssertions;
using Microsoft.Reactive.Testing;
using VMx.Services;
using Xunit;

namespace VMx.Tests.Services;

public class DelayedTaskTests
{
    [Fact]
    public void Constructor_Rejects_Null_Scheduler()
    {
        var act = () => new DelayedTask(null!);
        act.Should().Throw<ArgumentNullException>();
    }

    [Fact]
    public void Schedule_Rejects_Null_Action()
    {
        using var task = new DelayedTask(new TestScheduler());
        var act = () => task.Schedule(TimeSpan.FromSeconds(1), null!);
        act.Should().Throw<ArgumentNullException>();
        task.IsPending.Should().BeFalse();
    }

    [Fact]
    public void Negative_Delay_Runs_At_The_Next_Opportunity_Not_Inline()
    {
        var scheduler = new TestScheduler();
        using var task = new DelayedTask(scheduler);
        var runs = 0;

        task.Schedule(TimeSpan.FromSeconds(-5), () => runs++);
        runs.Should().Be(0);
        task.IsPending.Should().BeTrue();

        scheduler.AdvanceBy(1);
        runs.Should().Be(1);
        task.IsPending.Should().BeFalse();
    }

    [Fact]
    public void Dispose_Does_Not_Dispose_The_Scheduler()
    {
        var scheduler = new TestScheduler();
        var task = new DelayedTask(scheduler);
        task.Schedule(TimeSpan.FromSeconds(1), () => { });
        task.Dispose();

        var otherRuns = 0;
        scheduler.Schedule(TimeSpan.FromSeconds(1), () => otherRuns++);
        scheduler.AdvanceBy(TimeSpan.FromSeconds(1).Ticks);
        otherRuns.Should().Be(1);
    }

    [Fact]
    public void Polling_Loop_Reschedules_Itself_On_The_Default_Scheduler()
    {
        using var task = new DelayedTask(DefaultScheduler.Instance);
        using var done = new ManualResetEventSlim();
        var runs = 0;

        void Poll()
        {
            if (Interlocked.Increment(ref runs) < 3) task.Schedule(TimeSpan.FromMilliseconds(10), Poll);
            else done.Set();
        }

        task.Schedule(TimeSpan.FromMilliseconds(10), Poll);

        done.Wait(TimeSpan.FromSeconds(10)).Should().BeTrue();
        Volatile.Read(ref runs).Should().Be(3);
        task.IsPending.Should().BeFalse();
    }

    [Fact]
    public async Task Cancel_From_Another_Thread_Stops_A_Pending_Real_Time_Action()
    {
        using var task = new DelayedTask(DefaultScheduler.Instance);
        var runs = 0;

        task.Schedule(TimeSpan.FromMilliseconds(200), () => Interlocked.Increment(ref runs));
        await Task.Run(task.Cancel).WaitAsync(TimeSpan.FromSeconds(10));
        task.IsPending.Should().BeFalse();

        await Task.Delay(400);
        Volatile.Read(ref runs).Should().Be(0);
    }
}
