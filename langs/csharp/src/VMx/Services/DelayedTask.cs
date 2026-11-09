using System.Reactive.Concurrency;
using VMx.Internal;

namespace VMx.Services;

/// <summary>
/// Holds at most one pending action on an injected scheduler: the portable
/// form of a timer, a debounce and a polling loop (spec/11 §6.3, ADR-0219).
/// </summary>
/// <remarks>
/// <para>
/// <see cref="Schedule"/> replaces the pending action and restarts its delay.
/// <see cref="Cancel"/> stops it, <see cref="IsPending"/> reports it, and
/// <see cref="Dispose"/> cancels it and makes later calls inert. Disposal
/// never disposes the scheduler.
/// </para>
/// <para>
/// The action runs where the scheduler runs it, never through
/// <see cref="IDispatcher"/> (spec/11 §6.2). Pass a UI scheduler, such as a
/// <c>SynchronizationContextScheduler</c>, for UI-thread delivery. Tests pass
/// <c>Microsoft.Reactive.Testing.TestScheduler</c>.
/// </para>
/// <para>
/// All members are safe to call from any thread. After
/// <see cref="Schedule"/>, <see cref="Cancel"/> or <see cref="Dispose"/>
/// returns, the replaced or cancelled action never starts. An action that
/// already started runs to its end. A failing action is discarded on the
/// stream-fed route (spec/03 §3.6), and the task stays usable.
/// </para>
/// </remarks>
public sealed class DelayedTask : IDisposable
{
    private readonly object _gate = new();
    private readonly IScheduler _scheduler;
    private IDisposable? _handle;
    private long _generation;
    private bool _pending;
    private bool _disposed;

    /// <summary>Creates a task over <paramref name="scheduler"/>.</summary>
    /// <param name="scheduler">The clock that runs the delayed action.</param>
    /// <exception cref="ArgumentNullException"><paramref name="scheduler"/> is null.</exception>
    public DelayedTask(IScheduler scheduler)
    {
        ThrowHelper.ThrowIfNull(scheduler, nameof(scheduler));
        _scheduler = scheduler;
    }

    /// <summary>
    /// True from <see cref="Schedule"/> until the action starts,
    /// <see cref="Cancel"/> or <see cref="Dispose"/>. The running action
    /// already reads false, so it can call <see cref="Schedule"/> again.
    /// </summary>
    public bool IsPending
    {
        get
        {
            lock (_gate) return _pending;
        }
    }

    /// <summary>
    /// Cancels the pending action, if any, and schedules
    /// <paramref name="action"/> after <paramref name="delay"/>. A zero or
    /// negative delay runs the action at the scheduler's next opportunity.
    /// After disposal, the call has no effect.
    /// </summary>
    /// <param name="delay">The delay before the action runs.</param>
    /// <param name="action">The action to run once.</param>
    /// <exception cref="ArgumentNullException"><paramref name="action"/> is null.</exception>
    public void Schedule(TimeSpan delay, Action action)
    {
        ThrowHelper.ThrowIfNull(action, nameof(action));

        IDisposable? replaced;
        long generation;
        lock (_gate)
        {
            if (_disposed) return;
            replaced = _handle;
            _handle = null;
            generation = ++_generation;
            _pending = true;
        }

        replaced?.Dispose();

        IDisposable handle;
        try
        {
            handle = _scheduler.Schedule(delay < TimeSpan.Zero ? TimeSpan.Zero : delay, () => Run(generation, action));
        }
        catch
        {
            lock (_gate)
            {
                if (_generation == generation) _pending = false;
            }

            throw;
        }

        bool keep;
        lock (_gate)
        {
            // A later Schedule, Cancel or Dispose, or a run that already
            // started, makes this handle stale.
            keep = !_disposed && _pending && _generation == generation;
            if (keep) _handle = handle;
        }

        if (!keep) handle.Dispose();
    }

    /// <summary>Cancels the pending action. Has no effect when none is pending.</summary>
    public void Cancel()
    {
        IDisposable? handle;
        lock (_gate)
        {
            if (!_pending) return;
            handle = Clear();
        }

        handle?.Dispose();
    }

    /// <summary>
    /// Cancels the pending action and makes later <see cref="Schedule"/> and
    /// <see cref="Cancel"/> calls inert. A second call has no effect.
    /// </summary>
    public void Dispose()
    {
        IDisposable? handle;
        lock (_gate)
        {
            if (_disposed) return;
            _disposed = true;
            handle = Clear();
        }

        handle?.Dispose();
    }

    // Caller holds _gate. Invalidates the current generation and returns the
    // handle to cancel outside the lock.
    private IDisposable? Clear()
    {
        _generation++;
        _pending = false;
        var handle = _handle;
        _handle = null;
        return handle;
    }

    private void Run(long generation, Action action)
    {
        lock (_gate)
        {
            if (_disposed || !_pending || _generation != generation) return;
            _pending = false;
            _handle = null;
        }

        try { action(); }
        catch { /* stream-fed route: discard the failure; it never reaches the scheduler (spec/03 §3.6) */ }
    }
}
