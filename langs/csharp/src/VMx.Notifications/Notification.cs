namespace VMx.Notifications;

/// <summary>
/// Immutable notification value. Two <see cref="Notification"/> instances with
/// identical <see cref="Type"/> and <see cref="Message"/> are still different
/// instances (identity-distinct per spec/16-notifications.md).
/// </summary>
public sealed class Notification
{
    /// <summary>Creates a new notification.</summary>
    public Notification(NotificationType type, string message)
    {
        Type = type;
        Message = message;
    }

    /// <summary>Notification classification.</summary>
    public NotificationType Type { get; }

    /// <summary>Human-readable message.</summary>
    public string Message { get; }
}
