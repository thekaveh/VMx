namespace VMx.Notifications;

/// <summary>User response to a <see cref="Notification"/>. See spec/16-notifications.md.</summary>
public enum NotificationReaction
{
    /// <summary>Default; the notification has not been resolved yet.</summary>
    Pending,

    /// <summary>User accepted / acknowledged the notification.</summary>
    Approve,

    /// <summary>User declined the notification.</summary>
    Reject,
}
