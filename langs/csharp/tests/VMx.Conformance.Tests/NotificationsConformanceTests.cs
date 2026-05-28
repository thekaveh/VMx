using FluentAssertions;
using VMx.Notifications;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for the notifications sub-package, NOTIF-001..016.
/// See spec/16-notifications.md, ADR-0013, ADR-0031.
/// </summary>
public class NotificationsConformanceTests
{
    // ── NOTIF-001 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-001: Post returns awaitable that completes on Resolve.</summary>
    [Fact, Trait("Conformance", "NOTIF-001")]
    public async Task NOTIF_001_Post_Returns_Awaitable_That_Completes_On_Resolve()
    {
        using var hub = new NotificationHub();
        var n = new Notification(NotificationType.Notification, "info");
        var task = hub.Post(n);
        hub.Resolve(n, NotificationReaction.Approve);
        var reaction = await task;
        reaction.Should().Be(NotificationReaction.Approve);
    }

    // ── NOTIF-002 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-002: Post adds the notification to Pending.</summary>
    [Fact, Trait("Conformance", "NOTIF-002")]
    public void NOTIF_002_Post_Adds_To_Pending()
    {
        using var hub = new NotificationHub();
        IReadOnlyList<Notification>? last = null;
        using var sub = hub.Pending.Subscribe(s => last = s);
        var n = new Notification(NotificationType.Notification, "info");
        _ = hub.Post(n);
        last.Should().NotBeNull();
        last!.Should().Contain(n);
    }

    // ── NOTIF-003 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-003: Resolve removes from Pending.</summary>
    [Fact, Trait("Conformance", "NOTIF-003")]
    public void NOTIF_003_Resolve_Removes_From_Pending()
    {
        using var hub = new NotificationHub();
        IReadOnlyList<Notification>? last = null;
        using var sub = hub.Pending.Subscribe(s => last = s);
        var n = new Notification(NotificationType.Notification, "info");
        _ = hub.Post(n);
        hub.Resolve(n, NotificationReaction.Approve);
        last!.Should().NotContain(n);
    }

    // ── NOTIF-004 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-004: NotificationType has Error / Notification / Confirmation.</summary>
    [Fact, Trait("Conformance", "NOTIF-004")]
    public void NOTIF_004_NotificationType_Enum_Members()
    {
        Enum.GetValues<NotificationType>().Should().BeEquivalentTo(new[]
        {
            NotificationType.Error,
            NotificationType.Notification,
            NotificationType.Confirmation,
        });
    }

    // ── NOTIF-005 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-005: NotificationReaction has Pending / Approve / Reject.</summary>
    [Fact, Trait("Conformance", "NOTIF-005")]
    public void NOTIF_005_NotificationReaction_Enum_Members()
    {
        Enum.GetValues<NotificationReaction>().Should().BeEquivalentTo(new[]
        {
            NotificationReaction.Pending,
            NotificationReaction.Approve,
            NotificationReaction.Reject,
        });
    }

    // ── NOTIF-006 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-006: The resolved task carries the reaction value.</summary>
    [Fact, Trait("Conformance", "NOTIF-006")]
    public async Task NOTIF_006_Resolved_Task_Carries_Reaction()
    {
        using var hub = new NotificationHub();
        var n = new Notification(NotificationType.Notification, "info");
        var task = hub.Post(n);
        hub.Resolve(n, NotificationReaction.Reject);
        (await task).Should().Be(NotificationReaction.Reject);
    }

    // ── NOTIF-007 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-007: Confirmation notifications can be resolved Approve or Reject.</summary>
    [Fact, Trait("Conformance", "NOTIF-007")]
    public async Task NOTIF_007_Confirmation_Approve_Or_Reject()
    {
        using var hub = new NotificationHub();
        var nA = new Notification(NotificationType.Confirmation, "x");
        var nR = new Notification(NotificationType.Confirmation, "y");
        var tA = hub.Post(nA);
        var tR = hub.Post(nR);
        hub.Resolve(nA, NotificationReaction.Approve);
        hub.Resolve(nR, NotificationReaction.Reject);
        (await tA).Should().Be(NotificationReaction.Approve);
        (await tR).Should().Be(NotificationReaction.Reject);
    }

    // ── NOTIF-008 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-008: Resolving a notification not in Pending is a no-op.</summary>
    [Fact, Trait("Conformance", "NOTIF-008")]
    public void NOTIF_008_Resolve_Unknown_NoOp()
    {
        using var hub = new NotificationHub();
        var orphan = new Notification(NotificationType.Notification, "stray");
        var act = () => hub.Resolve(orphan, NotificationReaction.Approve);
        act.Should().NotThrow();
    }

    // ── NOTIF-009 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-009: NullNotificationHub.Post resolves Approve immediately.</summary>
    [Fact, Trait("Conformance", "NOTIF-009")]
#pragma warning disable CA1859 // The test deliberately works via the INotificationHub contract.
    public async Task NOTIF_009_NullHub_Post_Resolves_Approve_Immediately()
    {
        INotificationHub hub = NullNotificationHub.Instance;
        var n = new Notification(NotificationType.Confirmation, "x");
        var task = hub.Post(n);
        task.IsCompleted.Should().BeTrue();
        (await task).Should().Be(NotificationReaction.Approve);
    }
#pragma warning restore CA1859

    // ── NOTIF-010 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-010: make_confirm helper returns true iff Approve.</summary>
    [Fact, Trait("Conformance", "NOTIF-010")]
    public async Task NOTIF_010_MakeConfirm_Helper()
    {
        using var hub = new NotificationHub();
        var confirm = ConfirmHelper.MakeConfirm(hub, "ok?");

        var pending = hub.Pending.Subscribe(snapshot =>
        {
            foreach (var n in snapshot)
                hub.Resolve(n, NotificationReaction.Approve);
        });
        var resultApprove = await confirm();
        pending.Dispose();
        resultApprove.Should().BeTrue();

        var pendingReject = hub.Pending.Subscribe(snapshot =>
        {
            foreach (var n in snapshot)
                hub.Resolve(n, NotificationReaction.Reject);
        });
        var resultReject = await confirm();
        pendingReject.Dispose();
        resultReject.Should().BeFalse();
    }

    // ── NOTIF-011 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-011: NotificationVM opacity decays linearly from 1.0 to 0.0 over Lifespan.</summary>
    [Fact(Skip = "NOTIF-011 not yet implemented"), Trait("Conformance", "NOTIF-011")]
    public void NOTIF_011_NotificationVM_Opacity_Decays_Linearly()
    {
        throw new NotImplementedException("NOTIF-011: implement NotificationVM first (Substage 4B).");
    }

    // ── NOTIF-012 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-012: NotificationVM auto-dismisses (resolves Approve) at expiry.</summary>
    [Fact(Skip = "NOTIF-012 not yet implemented"), Trait("Conformance", "NOTIF-012")]
    public void NOTIF_012_NotificationVM_AutoDismisses_On_Expiry()
    {
        throw new NotImplementedException("NOTIF-012: implement NotificationVM first (Substage 4B).");
    }

    // ── NOTIF-013 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-013: ConfirmationVM exposes ApproveCommand + RejectCommand resolving with the corresponding NotificationReaction.</summary>
    [Fact(Skip = "NOTIF-013 not yet implemented"), Trait("Conformance", "NOTIF-013")]
    public void NOTIF_013_ConfirmationVM_ApproveCommand_And_RejectCommand()
    {
        throw new NotImplementedException("NOTIF-013: implement ConfirmationVM first (Substage 4B).");
    }

    // ── NOTIF-014 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-014: Manual DismissCommand cancels the timer; subsequent ticks no-op.</summary>
    [Fact(Skip = "NOTIF-014 not yet implemented"), Trait("Conformance", "NOTIF-014")]
    public void NOTIF_014_Manual_DismissCommand_Cancels_Timer()
    {
        throw new NotImplementedException("NOTIF-014: implement NotificationVM first (Substage 4B).");
    }

    // ── NOTIF-015 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-015: Hub-side Resolve() propagates to VM IsResolved state.</summary>
    [Fact(Skip = "NOTIF-015 not yet implemented"), Trait("Conformance", "NOTIF-015")]
    public void NOTIF_015_Hub_Resolve_Propagates_To_VM_IsResolved()
    {
        throw new NotImplementedException("NOTIF-015: implement NotificationVM first (Substage 4B).");
    }

    // ── NOTIF-016 ───────────────────────────────────────────────────────────

    /// <summary>NOTIF-016: Deterministic behavior under injected TestScheduler / fake clock.</summary>
    [Fact(Skip = "NOTIF-016 not yet implemented"), Trait("Conformance", "NOTIF-016")]
    public void NOTIF_016_Deterministic_Under_TestScheduler()
    {
        throw new NotImplementedException("NOTIF-016: implement NotificationVM first (Substage 4B).");
    }
}
