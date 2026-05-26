using System.Reactive.Subjects;

namespace VMx.Notifications;

/// <summary>Default <see cref="INotificationHub"/> implementation.</summary>
public sealed class NotificationHub : INotificationHub, IDisposable
{
    private readonly object _lock = new();
    private readonly List<Notification> _pending = new();
    private readonly Dictionary<Notification, TaskCompletionSource<NotificationReaction>> _waiters = new();
    private readonly BehaviorSubject<IReadOnlyList<Notification>> _pendingSubject =
        new(Array.Empty<Notification>());

    /// <inheritdoc/>
    public IObservable<IReadOnlyList<Notification>> Pending => _pendingSubject;

    /// <inheritdoc/>
    public Task<NotificationReaction> Post(Notification notification)
    {
        var tcs = new TaskCompletionSource<NotificationReaction>(TaskCreationOptions.RunContinuationsAsynchronously);
        IReadOnlyList<Notification> snapshot;
        lock (_lock)
        {
            _pending.Add(notification);
            _waiters[notification] = tcs;
            snapshot = _pending.ToArray();
        }
        _pendingSubject.OnNext(snapshot);
        return tcs.Task;
    }

    /// <inheritdoc/>
    public void Resolve(Notification notification, NotificationReaction reaction)
    {
        TaskCompletionSource<NotificationReaction>? tcs;
        IReadOnlyList<Notification> snapshot;
        lock (_lock)
        {
            if (!_waiters.TryGetValue(notification, out tcs)) return;
            _waiters.Remove(notification);
            _pending.Remove(notification);
            snapshot = _pending.ToArray();
        }
        _pendingSubject.OnNext(snapshot);
        tcs.TrySetResult(reaction);
    }

    /// <summary>Completes the <see cref="Pending"/> observable and resolves any in-flight waiters with Pending.</summary>
    public void Dispose()
    {
        TaskCompletionSource<NotificationReaction>[] waiters;
        lock (_lock)
        {
            waiters = _waiters.Values.ToArray();
            _waiters.Clear();
            _pending.Clear();
        }
        foreach (var w in waiters) w.TrySetResult(NotificationReaction.Pending);
        _pendingSubject.OnCompleted();
        _pendingSubject.Dispose();
    }
}
