using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Runtime.ExceptionServices;

namespace VMx.Notifications;

/// <summary>
/// Default <see cref="INotificationHub"/> implementation. See spec/16-notifications.md and ADR-0013.
/// </summary>
public sealed class NotificationHub : INotificationHub, IDisposable
{
    [ThreadStatic]
    private static int s_deliveryDepth;

    private sealed class PendingEmission(IReadOnlyList<Notification>? snapshot = null, bool complete = false)
    {
        public IReadOnlyList<Notification>? Snapshot { get; } = snapshot;
        public bool Complete { get; } = complete;
        public ManualResetEventSlim Completed { get; } = new(false);
        public Exception? Error { get; set; }
    }

    private readonly object _lock = new();
    private readonly List<Notification> _pending = new();
    private readonly Dictionary<Notification, TaskCompletionSource<NotificationReaction>> _waiters = new();
    private readonly BehaviorSubject<IReadOnlyList<Notification>> _pendingSubject =
        new(Array.Empty<Notification>());
    private readonly Queue<PendingEmission> _emissions = new();
    private bool _disposed;
    private int _emitterThreadId;

    /// <inheritdoc/>
    public IObservable<IReadOnlyList<Notification>> Pending => _pendingSubject.AsObservable();

    /// <inheritdoc/>
    public Task<NotificationReaction> Post(Notification notification)
    {
        var tcs = new TaskCompletionSource<NotificationReaction>(TaskCreationOptions.RunContinuationsAsynchronously);
        PendingEmission emission;
        bool shouldEmit;
        bool shouldWait;
        lock (_lock)
        {
            if (_disposed)
            {
                tcs.TrySetResult(NotificationReaction.Pending);
                return tcs.Task;
            }
            if (_waiters.TryGetValue(notification, out var existing))
                return existing.Task;
            _pending.Add(notification);
            _waiters[notification] = tcs;
            (emission, shouldEmit, shouldWait) = QueueEmissionLocked(new(_pending.ToArray()));
        }
        PublishEmission(emission, shouldEmit, shouldWait);
        return tcs.Task;
    }

    /// <inheritdoc/>
    public void Resolve(Notification notification, NotificationReaction reaction)
    {
        TaskCompletionSource<NotificationReaction>? tcs;
        PendingEmission emission;
        bool shouldEmit;
        bool shouldWait;
        lock (_lock)
        {
            if (!_waiters.Remove(notification, out tcs)) return;
            _pending.Remove(notification);
            (emission, shouldEmit, shouldWait) = QueueEmissionLocked(new(_pending.ToArray()));
        }
        PublishEmission(emission, shouldEmit, shouldWait);
        tcs.TrySetResult(reaction);
    }

    /// <summary>
    /// Completes the <see cref="Pending"/> observable and resolves any in-flight waiters with Pending.
    /// Idempotent: subsequent calls are a no-op.
    /// </summary>
    public void Dispose()
    {
        TaskCompletionSource<NotificationReaction>[] waiters;
        PendingEmission emission;
        bool shouldEmit;
        bool shouldWait;
        lock (_lock)
        {
            if (_disposed) return;
            _disposed = true;
            waiters = _waiters.Values.ToArray();
            _waiters.Clear();
            _pending.Clear();
            (emission, shouldEmit, shouldWait) = QueueEmissionLocked(new(complete: true));
        }
        PublishEmission(emission, shouldEmit, shouldWait);
        foreach (var waiter in waiters)
            waiter.TrySetResult(NotificationReaction.Pending);
    }

    private (PendingEmission Emission, bool ShouldEmit, bool ShouldWait) QueueEmissionLocked(
        PendingEmission emission)
    {
        var caller = Environment.CurrentManagedThreadId;
        _emissions.Enqueue(emission);
        if (_emitterThreadId == 0)
        {
            _emitterThreadId = caller;
            return (emission, true, false);
        }
        return (emission, false, _emitterThreadId != caller && s_deliveryDepth == 0);
    }

    private void PublishEmission(PendingEmission emission, bool shouldEmit, bool shouldWait)
    {
        if (shouldEmit)
            DrainEmissions();
        else if (shouldWait)
            emission.Completed.Wait();
        if (emission.Error is not null)
            ExceptionDispatchInfo.Capture(emission.Error).Throw();
        emission.Completed.Dispose();
    }

    private void DrainEmissions()
    {
        while (true)
        {
            PendingEmission emission;
            lock (_lock)
            {
                if (_emissions.Count == 0)
                {
                    _emitterThreadId = 0;
                    Monitor.PulseAll(_lock);
                    return;
                }
                emission = _emissions.Dequeue();
            }
            try
            {
                s_deliveryDepth++;
                if (emission.Complete)
                {
                    _pendingSubject.OnCompleted();
                    _pendingSubject.Dispose();
                }
                else
                {
                    _pendingSubject.OnNext(emission.Snapshot!);
                }
            }
            catch (Exception error)
            {
                emission.Error = error;
                PendingEmission[] abandoned;
                lock (_lock)
                {
                    abandoned = _emissions.ToArray();
                    _emissions.Clear();
                    _emitterThreadId = 0;
                    Monitor.PulseAll(_lock);
                }
                foreach (var item in abandoned)
                {
                    item.Error = error;
                    item.Completed.Set();
                }
                throw;
            }
            finally
            {
                s_deliveryDepth--;
                emission.Completed.Set();
            }
        }
    }
}
