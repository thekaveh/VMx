using System.Reactive.Concurrency;
using System.Reactive.Linq;
using FluentAssertions;
using Microsoft.Reactive.Testing;
using VMx.Notifications;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: NOTIF-021 — a subscriber or handler failure during the
/// lifespan timer or a decay tick never reaches the scheduler.
/// See spec/16-notifications.md §6 and ADR-0257.
/// </summary>
public class NOTIF_021_TimerFailureRoute_Tests
{
    private static readonly TimeSpan Lifespan = TimeSpan.FromSeconds(10);

    /// <summary>NOTIF-021: a Pending subscriber that throws at expiry does not escape the scheduler.</summary>
    [Fact, Trait("Conformance", "NOTIF-021")]
    public void NOTIF_021_Pending_Subscriber_Failure_At_Expiry_Is_Contained()
    {
        var scheduler = new TestScheduler();
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "expiry");
        var post = hub.Post(notification);
        using var sut = new NotificationVM(notification, hub, scheduler, Lifespan);
        var changed = new List<string>();
        sut.PropertyChanged += (_, e) => changed.Add(e.PropertyName!);
        using var failing = hub.Pending.Subscribe(list =>
        {
            if (list.Count == 0) throw new InvalidOperationException("subscriber failure");
        });

        Action advance = () => scheduler.AdvanceBy(Lifespan.Ticks);

        advance.Should().NotThrow();
        sut.IsResolved.Should().BeTrue();
        post.IsCompleted.Should().BeTrue();
        changed.Should().Contain(nameof(NotificationVM.IsResolved));
    }

    /// <summary>NOTIF-021: a PropertyChanged handler that throws during a decay tick does not stop the tick.</summary>
    [Fact, Trait("Conformance", "NOTIF-021")]
    public void NOTIF_021_Decay_Tick_Handler_Failure_Keeps_The_Tick_Running()
    {
        var scheduler = new TestScheduler();
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "decay");
        _ = hub.Post(notification);
        using var sut = new NotificationVM(
            notification, hub, scheduler, Lifespan, TimeSpan.FromSeconds(1));
        var remainingRaises = 0;
        var failedOnce = false;
        sut.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName != nameof(NotificationVM.RemainingTime)) return;
            remainingRaises++;
            if (failedOnce) return;
            failedOnce = true;
            throw new InvalidOperationException("handler failure");
        };

        Action firstTick = () => scheduler.AdvanceBy(TimeSpan.FromSeconds(1).Ticks);
        firstTick.Should().NotThrow();
        failedOnce.Should().BeTrue();
        var raisesAfterFirstTick = remainingRaises;

        Action secondTick = () => scheduler.AdvanceBy(TimeSpan.FromSeconds(1).Ticks);
        secondTick.Should().NotThrow();
        remainingRaises.Should().Be(raisesAfterFirstTick + 1);
        sut.IsResolved.Should().BeFalse();
    }

    /// <summary>NOTIF-021: Dismiss raises the IsResolved change even when hub.Resolve throws.</summary>
    [Fact, Trait("Conformance", "NOTIF-021")]
    public void NOTIF_021_Dismiss_Raises_IsResolved_When_Hub_Resolve_Throws()
    {
        var scheduler = new TestScheduler();
        var hub = new ThrowingResolveHub();
        var notification = new Notification(NotificationType.Notification, "resolve");
        using var sut = new NotificationVM(notification, hub, scheduler, Lifespan);
        var changed = new List<string>();
        sut.PropertyChanged += (_, e) => changed.Add(e.PropertyName!);

        // The manual command keeps its route: the hub failure still reaches the caller.
        Action dismiss = () => sut.DismissCommand.Execute(null);

        dismiss.Should().Throw<InvalidOperationException>();
        sut.IsResolved.Should().BeTrue();
        changed.Should().Contain(nameof(NotificationVM.IsResolved));
    }

    /// <summary>NOTIF-021: an OnExpire override is not contained; its failure still reaches the scheduler (ADR-0257).</summary>
    [Fact, Trait("Conformance", "NOTIF-021")]
    public void OnExpire_Override_Failure_Still_Reaches_The_Scheduler()
    {
        var scheduler = new TestScheduler();
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "override");
        _ = hub.Post(notification);
        using var sut = new OverridingExpiryVM(notification, hub, scheduler, Lifespan);

        Action advance = () => scheduler.AdvanceBy(Lifespan.Ticks);

        advance.Should().Throw<InvalidOperationException>().WithMessage("override failure");
    }

    /// <summary>NOTIF-021: a PropertyChanged handler that throws on IsResolved at auto-dismiss is contained.</summary>
    [Fact, Trait("Conformance", "NOTIF-021")]
    public void NOTIF_021_IsResolved_Handler_Failure_At_Auto_Dismiss_Is_Contained()
    {
        var scheduler = new TestScheduler();
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "is-resolved");
        var post = hub.Post(notification);
        using var sut = new NotificationVM(notification, hub, scheduler, Lifespan);
        var changed = new List<string>();
        sut.PropertyChanged += (_, e) =>
        {
            changed.Add(e.PropertyName!);
            if (e.PropertyName == nameof(NotificationVM.IsResolved))
                throw new InvalidOperationException("is-resolved handler failure");
        };

        Action advance = () => scheduler.AdvanceBy(Lifespan.Ticks);

        advance.Should().NotThrow();
        sut.IsResolved.Should().BeTrue();
        post.IsCompleted.Should().BeTrue();
        changed.Should().Contain(nameof(NotificationVM.IsResolved));
    }

    /// <summary>A NotificationVM whose OnExpire override throws.</summary>
    private sealed class OverridingExpiryVM : NotificationVM
    {
        public OverridingExpiryVM(Notification notification, INotificationHub hub, IScheduler scheduler, TimeSpan lifespan)
            : base(notification, hub, scheduler, lifespan)
        {
        }

        protected override void OnExpire() => throw new InvalidOperationException("override failure");
    }

    /// <summary>A hub whose Resolve always throws and whose Pending never emits.</summary>
    private sealed class ThrowingResolveHub : INotificationHub
    {
        public Task<NotificationReaction> Post(Notification notification) =>
            new TaskCompletionSource<NotificationReaction>().Task;

        public void Resolve(Notification notification, NotificationReaction reaction) =>
            throw new InvalidOperationException("resolve failure");

        public IObservable<IReadOnlyList<Notification>> Pending { get; } =
            Observable.Never<IReadOnlyList<Notification>>();
    }
}
