using FluentAssertions;
using VMx.Notifications;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// A throwing <c>Pending</c> subscriber must not strand the waiters that
/// <c>Resolve</c> and <c>Dispose</c> have already removed from the hub.
/// </summary>
public sealed class NotificationHubSubscriberFailureTests
{
    [Fact]
    public async Task Resolve_completes_the_waiter_when_a_pending_subscriber_throws()
    {
        var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "saved");
        var post = hub.Post(notification);
        var armed = false;
        // Pending replays its current snapshot on subscribe; throw only on the
        // emission that Resolve publishes.
        using var subscription = hub.Pending.Subscribe(_ =>
        {
            if (armed) throw new InvalidOperationException("subscriber");
        });
        armed = true;

        var resolve = () => hub.Resolve(notification, NotificationReaction.Approve);

        resolve.Should().Throw<InvalidOperationException>();
        post.IsCompleted.Should().BeTrue();
        (await post).Should().Be(NotificationReaction.Approve);
    }

    [Fact]
    public async Task Dispose_completes_waiters_when_a_pending_subscriber_throws()
    {
        var hub = new NotificationHub();
        var post = hub.Post(new Notification(NotificationType.Notification, "saved"));
        using var subscription = hub.Pending.Subscribe(
            _ => { },
            () => throw new InvalidOperationException("subscriber"));

        var dispose = () => hub.Dispose();

        dispose.Should().Throw<InvalidOperationException>();
        post.IsCompleted.Should().BeTrue();
        (await post).Should().Be(NotificationReaction.Pending);
    }
}
