using System.Reactive.Concurrency;
using Microsoft.Reactive.Testing;
using NotesShowcase.ViewModels;
using VMx.Services;
using VMx.Notifications;
using Xunit;

namespace NotesShowcase.Tests.ViewModels;

public sealed class NotificationsVMTests
{
    private static (NotificationsVM vm, NotificationHub hub, TestScheduler ts) Build(int cap = 5)
    {
        var ts = new TestScheduler();
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        var nh = new NotificationHub();
        var vm = NotificationsVM.Builder()
            .Name("notifications").Services(hub, dispatcher)
            .NotificationHub(nh).Scheduler(ts)
            .Lifespan(TimeSpan.FromSeconds(5)).Cap(cap)
            .Build();
        vm.Construct();
        return (vm, nh, ts);
    }

    [Fact]
    public void Posting_a_notification_adds_a_VM_to_Visible()
    {
        var (vm, hub, _) = Build();
        _ = hub.Post(new Notification(NotificationType.Notification, "Saved"));
        Assert.Single(vm.Visible);
        Assert.Equal("Saved", vm.Visible[0].Notification.Message);
    }

    [Fact]
    public void Cap_drops_oldest_when_exceeded()
    {
        var (vm, hub, _) = Build(cap: 5);
        for (var i = 0; i < 7; i++)
            _ = hub.Post(new Notification(NotificationType.Notification, $"n{i}"));
        Assert.Equal(5, vm.Visible.Count);
        // Two oldest dropped, so the surviving messages start at n2.
        Assert.Equal("n2", vm.Visible[0].Notification.Message);
        Assert.Equal("n6", vm.Visible[^1].Notification.Message);
    }

    [Fact]
    public void Resolved_notifications_are_removed_from_Visible()
    {
        var (vm, hub, _) = Build();
        var n = new Notification(NotificationType.Notification, "x");
        _ = hub.Post(n);
        Assert.Single(vm.Visible);
        hub.Resolve(n, NotificationReaction.Approve);
        Assert.Empty(vm.Visible);
    }

    [Fact]
    public void Auto_dismiss_when_lifespan_expires_on_test_scheduler()
    {
        var (vm, hub, ts) = Build();
        var n = new Notification(NotificationType.Notification, "x");
        _ = hub.Post(n);
        Assert.Single(vm.Visible);
        // Advance past the 5-second lifespan.
        ts.AdvanceBy(TimeSpan.FromSeconds(6).Ticks);
        Assert.Empty(vm.Visible);
    }

    [Fact]
    public void Dispose_clears_visible_and_unsubscribes()
    {
        var (vm, hub, _) = Build();
        _ = hub.Post(new Notification(NotificationType.Notification, "x"));
        Assert.Single(vm.Visible);
        vm.Dispose();
        Assert.Empty(vm.Visible);
        // After dispose, new posts must not produce updates.
        _ = hub.Post(new Notification(NotificationType.Notification, "y"));
        Assert.Empty(vm.Visible);
    }
}
