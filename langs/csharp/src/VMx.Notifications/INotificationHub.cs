namespace VMx.Notifications;

/// <summary>
/// Async notification / confirmation hub. See spec/16-notifications.md and ADR-0013.
/// </summary>
public interface INotificationHub
{
    /// <summary>
    /// Posts a notification. Returns a task that completes when
    /// <see cref="Resolve"/> is called for this exact instance.
    /// </summary>
    Task<NotificationReaction> Post(Notification notification);

    /// <summary>
    /// Resolves a previously-posted notification with the given reaction.
    /// Resolving a notification not in <see cref="Pending"/> is a no-op.
    /// </summary>
    void Resolve(Notification notification, NotificationReaction reaction);

    /// <summary>
    /// Hot stream of the current pending list, emitted on every change.
    /// </summary>
    IObservable<IReadOnlyList<Notification>> Pending { get; }
}
