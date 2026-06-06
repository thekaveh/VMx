using System.Reactive.Linq;

namespace VMx.Notifications;

/// <summary>
/// Null-object variant per ADR-0017 (see also ADR-0013).
/// <see cref="Post"/> returns <see cref="NotificationReaction.Approve"/>
/// immediately; <see cref="Resolve"/> is a no-op; <see cref="Pending"/>
/// emits an empty list once and completes.
/// </summary>
public sealed class NullNotificationHub : INotificationHub
{
    /// <summary>Shared singleton instance.</summary>
    public static NullNotificationHub Instance { get; } = new();

    private NullNotificationHub() { }

    /// <inheritdoc/>
    public IObservable<IReadOnlyList<Notification>> Pending { get; } =
        Observable.Return<IReadOnlyList<Notification>>(Array.Empty<Notification>());

    /// <inheritdoc/>
    public Task<NotificationReaction> Post(Notification notification)
        => Task.FromResult(NotificationReaction.Approve);

    /// <inheritdoc/>
    public void Resolve(Notification notification, NotificationReaction reaction)
    {
        // intentional no-op per ADR-0017
    }
}
