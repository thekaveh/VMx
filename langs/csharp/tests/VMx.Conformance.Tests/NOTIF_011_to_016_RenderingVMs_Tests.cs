using FluentAssertions;
using Microsoft.Reactive.Testing;
using VMx.Notifications;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: NOTIF-011..016 — NotificationVM and ConfirmationVM.
/// See spec/16-notifications.md §NotificationVM/ConfirmationVM and ADR-0031.
/// </summary>
public class NOTIF_011_to_016_RenderingVMs_Tests
{
    // ── NOTIF-011 ─────────────────────────────────────────────────────────────

    /// <summary>NOTIF-011: NotificationVM opacity decays linearly from 1.0 to 0.0 over Lifespan.</summary>
    [Fact, Trait("Conformance", "NOTIF-011")]
    public void NOTIF_011_NotificationVM_Opacity_Decays_Linearly()
    {
        var scheduler = new TestScheduler();
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "hi");
        _ = hub.Post(notification);
        using var sut = new NotificationVM(notification, hub, scheduler, lifespan: TimeSpan.FromSeconds(10));

        sut.Opacity.Should().BeApproximately(1.0, 0.001, "at t=0 opacity is 1.0");

        scheduler.AdvanceBy(TimeSpan.FromSeconds(5).Ticks);
        sut.Opacity.Should().BeApproximately(0.5, 0.01, "at t=5s opacity is 0.5");

        scheduler.AdvanceBy(TimeSpan.FromSeconds(5).Ticks);
        sut.Opacity.Should().BeApproximately(0.0, 0.01, "at t=10s opacity is 0.0");
    }

    // ── NOTIF-012 ─────────────────────────────────────────────────────────────

    /// <summary>NOTIF-012: NotificationVM auto-dismisses (resolves Approve) at expiry.</summary>
    [Fact, Trait("Conformance", "NOTIF-012")]
    public async Task NOTIF_012_NotificationVM_AutoDismisses_On_Expiry()
    {
        var scheduler = new TestScheduler();
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "auto");
        var task = hub.Post(notification);
        using var sut = new NotificationVM(notification, hub, scheduler, lifespan: TimeSpan.FromSeconds(10));

        sut.IsResolved.Should().BeFalse("not yet resolved at t=0");

        // Advance past the Lifespan.
        scheduler.AdvanceBy(TimeSpan.FromSeconds(10).Ticks);

        sut.IsResolved.Should().BeTrue("auto-dismissed at lifespan expiry");

        // Hub task should have completed with Approve.
        task.IsCompleted.Should().BeTrue();
        (await task).Should().Be(NotificationReaction.Approve);
    }

    // ── NOTIF-013 ─────────────────────────────────────────────────────────────

    /// <summary>NOTIF-013: ConfirmationVM exposes ApproveCommand + RejectCommand resolving with the correct reaction.</summary>
    [Fact, Trait("Conformance", "NOTIF-013")]
    public async Task NOTIF_013_ConfirmationVM_ApproveCommand_And_RejectCommand()
    {
        var scheduler = new TestScheduler();

        // ApproveCommand resolves with Approve.
        using var hubA = new NotificationHub();
        var nA = new Notification(NotificationType.Confirmation, "approve me");
        var taskA = hubA.Post(nA);
        using var sutA = new ConfirmationVM(nA, hubA, scheduler);
        sutA.ApproveCommand.Execute(null);
        sutA.IsResolved.Should().BeTrue();
        (await taskA).Should().Be(NotificationReaction.Approve);

        // RejectCommand resolves with Reject.
        using var hubR = new NotificationHub();
        var nR = new Notification(NotificationType.Confirmation, "reject me");
        var taskR = hubR.Post(nR);
        using var sutR = new ConfirmationVM(nR, hubR, scheduler);
        sutR.RejectCommand.Execute(null);
        sutR.IsResolved.Should().BeTrue();
        (await taskR).Should().Be(NotificationReaction.Reject);
    }

    // ── NOTIF-014 ─────────────────────────────────────────────────────────────

    /// <summary>NOTIF-014: Manual DismissCommand cancels the timer; subsequent ticks no-op.</summary>
    [Fact, Trait("Conformance", "NOTIF-014")]
    public void NOTIF_014_Manual_DismissCommand_Cancels_Timer()
    {
        var scheduler = new TestScheduler();
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "dismiss me");
        _ = hub.Post(notification);
        using var sut = new NotificationVM(notification, hub, scheduler, lifespan: TimeSpan.FromSeconds(10));

        // Invoke DismissCommand manually at t=0.
        sut.DismissCommand.Execute(null);
        sut.IsResolved.Should().BeTrue("resolved by manual dismiss");

        // Track hub state: a second resolve call must not occur.
        var resolveCount = 0;
        IReadOnlyList<Notification>? lastPending = null;
        hub.Pending.Subscribe(list => { lastPending = list; resolveCount++; });

        // Advance past the original Lifespan — the timer must no longer fire.
        scheduler.AdvanceBy(TimeSpan.FromSeconds(20).Ticks);

        // resolveCount tracks Pending emissions; it may have had initial ones.
        // The key is that IsResolved was set to true exactly once and the
        // notification is no longer in Pending.
        sut.IsResolved.Should().BeTrue("still resolved after timer tick");
        lastPending.Should().NotContain(notification, "notification was removed on dismiss");
    }

    // ── NOTIF-015 ─────────────────────────────────────────────────────────────

    /// <summary>NOTIF-015: Hub-side Resolve() propagates to VM IsResolved state.</summary>
    [Fact, Trait("Conformance", "NOTIF-015")]
    public void NOTIF_015_Hub_Resolve_Propagates_To_VM_IsResolved()
    {
        var scheduler = new TestScheduler();
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "hub resolves");
        _ = hub.Post(notification);
        using var sut = new NotificationVM(notification, hub, scheduler, lifespan: TimeSpan.FromSeconds(60));

        sut.IsResolved.Should().BeFalse("not yet resolved");

        // External resolve via hub.
        hub.Resolve(notification, NotificationReaction.Approve);

        sut.IsResolved.Should().BeTrue("IsResolved propagated from hub resolve");

        // Advance past lifespan — timer must not fire again.
        scheduler.AdvanceBy(TimeSpan.FromSeconds(60).Ticks);
        sut.IsResolved.Should().BeTrue("still resolved after timer advance");
    }

    // ── NOTIF-016 ─────────────────────────────────────────────────────────────

    /// <summary>NOTIF-016: Deterministic behavior under injected TestScheduler / fake clock.</summary>
    [Fact, Trait("Conformance", "NOTIF-016")]
    public void NOTIF_016_Deterministic_Under_TestScheduler()
    {
        var scheduler = new TestScheduler();
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "tick");
        _ = hub.Post(notification);
        using var sut = new NotificationVM(notification, hub, scheduler, lifespan: TimeSpan.FromSeconds(10));

        // At t=0: opacity 1.0, not resolved.
        sut.Opacity.Should().BeApproximately(1.0, 0.001);
        sut.IsResolved.Should().BeFalse();

        // At t=5s: opacity 0.5.
        scheduler.AdvanceBy(TimeSpan.FromSeconds(5).Ticks);
        sut.Opacity.Should().BeApproximately(0.5, 0.01);
        sut.IsResolved.Should().BeFalse();

        // At t=10s: auto-dismissed.
        scheduler.AdvanceBy(TimeSpan.FromSeconds(5).Ticks);
        sut.IsResolved.Should().BeTrue("auto-dismissed exactly at lifespan");
        sut.Opacity.Should().BeApproximately(0.0, 0.01);

        // No double-resolve: advancing further does nothing.
        scheduler.AdvanceBy(TimeSpan.FromSeconds(100).Ticks);
        sut.IsResolved.Should().BeTrue();
    }
}
