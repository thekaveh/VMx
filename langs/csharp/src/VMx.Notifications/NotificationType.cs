namespace VMx.Notifications;

/// <summary>Classification of a <see cref="Notification"/>. See spec/16-notifications.md.</summary>
public enum NotificationType
{
    /// <summary>Something failed; user attention required.</summary>
    Error,

    /// <summary>Informational; user acknowledgement is enough.</summary>
    Notification,

    /// <summary>A decision is required (Approve/Reject).</summary>
    Confirmation,
}
