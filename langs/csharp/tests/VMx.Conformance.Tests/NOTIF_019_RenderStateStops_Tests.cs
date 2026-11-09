using System.Reactive.Concurrency;
using System.Reactive.Disposables;
using FluentAssertions;
using Microsoft.Reactive.Testing;
using VMx.Notifications;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: NOTIF-019 — RemainingTime and Opacity keep their values
/// from the first resolution or disposal.
/// See spec/16-notifications.md §2.3 and ADR-0197.
/// </summary>
public class NOTIF_019_RenderStateStops_Tests
{
    private static readonly TimeSpan Lifespan = TimeSpan.FromSeconds(10);

    private static (NotificationHub Hub, NotificationVM Vm) Create(TestScheduler scheduler)
    {
        var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "render");
        _ = hub.Post(notification);
        return (hub, new NotificationVM(notification, hub, scheduler, lifespan: Lifespan));
    }

    /// <summary>NOTIF-019: render state stops at dismiss and at dispose.</summary>
    [Fact, Trait("Conformance", "NOTIF-019")]
    public void NOTIF_019_RemainingTime_And_Opacity_Stop_At_Resolution_Or_Disposal()
    {
        // Dismissed at 0 s.
        var dismissedScheduler = new TestScheduler();
        var (dismissedHub, dismissed) = Create(dismissedScheduler);
        using (dismissedHub)
        using (dismissed)
        {
            dismissed.DismissCommand.Execute(null);
            dismissedScheduler.AdvanceBy(Lifespan.Ticks);
            dismissed.RemainingTime.Should().Be(Lifespan);
            dismissed.Opacity.Should().Be(1.0);
        }

        // Disposed at 0 s.
        var disposedScheduler = new TestScheduler();
        var (disposedHub, disposed) = Create(disposedScheduler);
        using (disposedHub)
        {
            disposed.Dispose();
            disposedScheduler.AdvanceBy(Lifespan.Ticks);
            disposed.RemainingTime.Should().Be(Lifespan);
            disposed.Opacity.Should().Be(1.0);
        }

        // Dismissed at 4 s.
        var lateScheduler = new TestScheduler();
        var (lateHub, late) = Create(lateScheduler);
        using (lateHub)
        using (late)
        {
            lateScheduler.AdvanceBy(TimeSpan.FromSeconds(4).Ticks);
            late.DismissCommand.Execute(null);
            lateScheduler.AdvanceBy(TimeSpan.FromSeconds(6).Ticks);
            late.RemainingTime.Should().Be(TimeSpan.FromSeconds(6));
            late.Opacity.Should().BeApproximately(0.6, 0.01);
        }
    }

    [Fact]
    public void ConfirmationVM_Approved_Keeps_Opacity()
    {
        var scheduler = new TestScheduler();
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Confirmation, "confirm");
        _ = hub.Post(notification);
        using var sut = new ConfirmationVM(notification, hub, scheduler);

        scheduler.AdvanceBy(TimeSpan.FromSeconds(60).Ticks);
        sut.ApproveCommand.Execute(null);
        scheduler.AdvanceBy(TimeSpan.FromSeconds(240).Ticks);

        sut.RemainingTime.Should().Be(TimeSpan.FromSeconds(240));
        sut.Opacity.Should().BeApproximately(0.8, 0.001);
    }

    [Fact]
    public void External_Hub_Resolve_Keeps_RemainingTime()
    {
        var scheduler = new TestScheduler();
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "external");
        _ = hub.Post(notification);
        using var sut = new NotificationVM(notification, hub, scheduler, lifespan: Lifespan);

        scheduler.AdvanceBy(TimeSpan.FromSeconds(3).Ticks);
        hub.Resolve(notification, NotificationReaction.Reject);
        scheduler.AdvanceBy(TimeSpan.FromSeconds(5).Ticks);

        sut.IsResolved.Should().BeTrue();
        sut.RemainingTime.Should().Be(TimeSpan.FromSeconds(7));
        sut.Opacity.Should().BeApproximately(0.7, 0.001);
    }

    [Fact]
    public void Resolution_Then_Disposal_Keeps_The_Resolution_Value()
    {
        var scheduler = new TestScheduler();
        var (hub, sut) = Create(scheduler);
        using (hub)
        {
            scheduler.AdvanceBy(TimeSpan.FromSeconds(2).Ticks);
            sut.DismissCommand.Execute(null);
            scheduler.AdvanceBy(TimeSpan.FromSeconds(3).Ticks);
            sut.Dispose();
            scheduler.AdvanceBy(TimeSpan.FromSeconds(5).Ticks);

            sut.RemainingTime.Should().Be(TimeSpan.FromSeconds(8));
        }
    }

    [Fact]
    public void Auto_Dismiss_Keeps_Zero_When_The_Timer_Fires_Early()
    {
        var scheduler = new EarlyTimerScheduler();
        var (hub, sut) = CreateWith(scheduler);
        using (hub)
        using (sut)
        {
            scheduler.FireNextEarly(TimeSpan.FromMilliseconds(1));

            sut.IsResolved.Should().BeTrue();
            sut.RemainingTime.Should().Be(TimeSpan.Zero);
            sut.Opacity.Should().Be(0.0);
        }
    }

    private static (NotificationHub Hub, NotificationVM Vm) CreateWith(IScheduler scheduler)
    {
        var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "render");
        _ = hub.Post(notification);
        return (hub, new NotificationVM(notification, hub, scheduler, lifespan: Lifespan));
    }

    /// <summary>
    /// Fires a timer on request while the clock is still before its due time,
    /// as a real timer with coarse ticks can (ADR-0197).
    /// </summary>
    private sealed class EarlyTimerScheduler : IScheduler
    {
        private readonly List<(DateTimeOffset Due, Action Run)> _timers = [];

        public DateTimeOffset Now { get; private set; } = new(2026, 1, 1, 0, 0, 0, TimeSpan.Zero);

        public IDisposable Schedule<TState>(TState state, Func<IScheduler, TState, IDisposable> action)
            => Schedule(state, Now, action);

        public IDisposable Schedule<TState>(TState state, TimeSpan dueTime, Func<IScheduler, TState, IDisposable> action)
            => Schedule(state, Now + dueTime, action);

        public IDisposable Schedule<TState>(TState state, DateTimeOffset dueTime, Func<IScheduler, TState, IDisposable> action)
        {
            _timers.Add((dueTime, () => action(this, state)));
            return Disposable.Empty;
        }

        public void FireNextEarly(TimeSpan early)
        {
            var (due, run) = _timers[0];
            _timers.RemoveAt(0);
            Now = due - early;
            run();
        }
    }
}
