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
        var posted = new Notification(NotificationType.Confirmation, "real");
        _ = hub.Post(posted);
        var snapshots = new List<IReadOnlyList<Notification>>();
        using var sub = hub.Pending.Subscribe(snapshots.Add);

        var orphan = new Notification(NotificationType.Notification, "stray");
        var act = () => hub.Resolve(orphan, NotificationReaction.Approve);
        act.Should().NotThrow();

        // Catalog And-clause: Pending is unchanged — no emission beyond the
        // subscription snapshot, which still contains exactly the posted one.
        snapshots.Should().HaveCount(1);
        snapshots[0].Should().Equal(posted);
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

    // NOTIF-011..016 live in NOTIF_011_to_016_RenderingVMs_Tests.cs

    /// <summary>
    /// Regression: Post-after-Dispose returns a completed task with Pending
    /// instead of throwing ObjectDisposedException from the underlying subject.
    /// Symmetric with Resolve()'s _waiters guard.
    /// </summary>
    [Fact, Trait("Stability", "Race")]
    public async Task Post_After_Dispose_Returns_Pending()
    {
        var hub = new NotificationHub();
        hub.Dispose();
        var task = hub.Post(new Notification(NotificationType.Confirmation, "x"));
        task.IsCompleted.Should().BeTrue();
        (await task).Should().Be(NotificationReaction.Pending);
    }

    /// <summary>
    /// NOTIF-017: dispose resolves in-flight waiters with Pending, completes
    /// the Pending observable, refuses new enqueues, and is idempotent.
    /// See spec/16-notifications.md §9 and ADR-0037 §2.4.
    /// </summary>
    [Fact]
    [Trait("Conformance", "NOTIF-017")]
    public async Task NOTIF_017_Dispose_Resolves_InFlight_Waiters_With_Pending()
    {
        var hub = new NotificationHub();
        var completed = false;
        using var sub = hub.Pending.Subscribe(_ => { }, () => completed = true);
        var task = hub.Post(new Notification(NotificationType.Confirmation, "in-flight"));

        hub.Dispose();

        (await task).Should().Be(NotificationReaction.Pending);
        completed.Should().BeTrue("the Pending observable completes on dispose");

        // Subsequent post resolves immediately with Pending and does not enqueue.
        var late = hub.Post(new Notification(NotificationType.Notification, "late"));
        late.IsCompleted.Should().BeTrue();
        (await late).Should().Be(NotificationReaction.Pending);

        // Subsequent resolve is a no-op; second dispose is a no-op.
        hub.Resolve(new Notification(NotificationType.Notification, "ghost"), NotificationReaction.Approve);
        hub.Dispose();
    }

    [Fact]
    public async Task Opposing_Hub_Callbacks_Do_Not_Deadlock()
    {
        var first = new NotificationHub();
        var second = new NotificationHub();
        var firstNotification = new Notification(NotificationType.Notification, "first");
        var secondNotification = new Notification(NotificationType.Notification, "second");
        using var callbacksReady = new Barrier(2);
        using var firstSubscription = first.Pending.Subscribe(snapshot =>
        {
            if (!snapshot.Contains(firstNotification)) return;
            callbacksReady.SignalAndWait(TimeSpan.FromSeconds(1)).Should().BeTrue();
            second.Resolve(secondNotification, NotificationReaction.Approve);
        });
        using var secondSubscription = second.Pending.Subscribe(snapshot =>
        {
            if (!snapshot.Contains(secondNotification)) return;
            callbacksReady.SignalAndWait(TimeSpan.FromSeconds(1)).Should().BeTrue();
            first.Resolve(firstNotification, NotificationReaction.Approve);
        });

        var posts = new[]
        {
            Task.Run(() => first.Post(firstNotification)),
            Task.Run(() => second.Post(secondNotification)),
        };
        var allPosts = Task.WhenAll(posts);

        var completed = await Task.WhenAny(allPosts, Task.Delay(TimeSpan.FromSeconds(1)));

        completed.Should().BeSameAs(allPosts, "opposing callbacks must make progress");
        await allPosts;
    }

    [Fact]
    public async Task Duplicate_Same_Instance_Post_Returns_Existing_Waiter()
    {
        var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "same");

        var first = hub.Post(notification);
        var second = hub.Post(notification);

        second.Should().BeSameAs(first, "duplicate same-instance posts share the in-flight waiter");

        hub.Resolve(notification, NotificationReaction.Approve);

        (await first).Should().Be(NotificationReaction.Approve);
        (await second).Should().Be(NotificationReaction.Approve);
    }
}
