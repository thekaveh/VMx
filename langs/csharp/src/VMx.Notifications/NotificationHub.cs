using System.Reactive.Subjects;

namespace VMx.Notifications;

/// <summary>
/// Default <see cref="INotificationHub"/> implementation. See spec/16-notifications.md and ADR-0013.
/// </summary>
public sealed class NotificationHub : INotificationHub, IDisposable
{
    private readonly object _lock = new();
    private readonly List<Notification> _pending = new();
    private readonly Dictionary<Notification, TaskCompletionSource<NotificationReaction>> _waiters = new();
    private readonly BehaviorSubject<IReadOnlyList<Notification>> _pendingSubject =
        new(Array.Empty<Notification>());
    private bool _disposed;

    /// <inheritdoc/>
    public IObservable<IReadOnlyList<Notification>> Pending => _pendingSubject;

    /// <inheritdoc/>
    public Task<NotificationReaction> Post(Notification notification)
    {
        var tcs = new TaskCompletionSource<NotificationReaction>(TaskCreationOptions.RunContinuationsAsynchronously);
        IReadOnlyList<Notification> snapshot;
        lock (_lock)
        {
            // Post after Dispose returns Pending and does not enqueue: matches the
            // shutdown semantics of Dispose() which resolves all in-flight waiters
            // with Pending. Symmetric with Resolve()'s _waiters guard.
            if (_disposed)
            {
                tcs.TrySetResult(NotificationReaction.Pending);
                return tcs.Task;
            }
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

    /// <summary>
    /// Completes the <see cref="Pending"/> observable and resolves any in-flight waiters with Pending.
    /// Idempotent: subsequent calls are a no-op.
    /// </summary>
    public void Dispose()
    {
        TaskCompletionSource<NotificationReaction>[] waiters;
        lock (_lock)
        {
            if (_disposed) return;
            _disposed = true;
            waiters = _waiters.Values.ToArray();
            _waiters.Clear();
            _pending.Clear();
        }
        foreach (var w in waiters) w.TrySetResult(NotificationReaction.Pending);
        _pendingSubject.OnCompleted();
        _pendingSubject.Dispose();
    }
}
