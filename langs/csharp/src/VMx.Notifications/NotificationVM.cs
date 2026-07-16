using System.ComponentModel;
using System.Reactive.Concurrency;
using System.Reactive.Linq;
using System.Windows.Input;
using VMx.Commands;

namespace VMx.Notifications;

/// <summary>
/// Render-side ViewModel for a <see cref="Notification"/>.
/// Exposes UI-bindable state (Opacity, RemainingTime, IsResolved, DismissCommand)
/// and auto-dismisses with <see cref="NotificationReaction.Approve"/> when
/// <see cref="Lifespan"/> expires.
///
/// <para>
/// Implements <see cref="INotifyPropertyChanged"/> so binding views repaint the
/// decaying state (VMX-135): <see cref="IsResolved"/> always raises a change on
/// resolution, and — when a <c>tickInterval</c> is supplied to the constructor —
/// <see cref="RemainingTime"/> and <see cref="Opacity"/> raise periodic changes
/// while the notification fades. Without a tick interval the two time-varying
/// properties remain poll-only (no extra scheduler work for callers that do not
/// bind the fade), preserving the previous behaviour.
/// </para>
///
/// See spec/16-notifications.md §NotificationVM and ADR-0031.
/// </summary>
public class NotificationVM : IDisposable, INotifyPropertyChanged
{
    private readonly object _gate = new();
    private readonly INotificationHub _hub;
    private readonly IScheduler _scheduler;
    private readonly TimeSpan _lifespan;
    private readonly TimeSpan _tickInterval;
    private readonly bool _emitsDecayTicks;
    private readonly DateTimeOffset _start;
    private IDisposable? _timerSub;
    private IDisposable? _pendingSub;
    private IDisposable? _tickSub;
    private bool _isResolved;
    private bool _disposed;

    /// <summary>
    /// Creates a <see cref="NotificationVM"/>.
    /// </summary>
    /// <param name="notification">The notification to render.</param>
    /// <param name="hub">Hub used to resolve the notification.</param>
    /// <param name="scheduler">Scheduler for time advancement. Inject a TestScheduler in tests.</param>
    /// <param name="lifespan">Override the default 60-second lifespan.</param>
    /// <param name="tickInterval">
    /// Optional cadence at which <see cref="RemainingTime"/> and
    /// <see cref="Opacity"/> raise <see cref="PropertyChanged"/> while the
    /// notification fades, so a binding view repaints the decay (VMX-135). When
    /// <see langword="null"/> (the default) the two properties are poll-only and
    /// no recurring scheduler work is incurred. <see cref="IsResolved"/> raises a
    /// change on resolution regardless.
    /// </param>
    public NotificationVM(
        Notification notification,
        INotificationHub hub,
        IScheduler scheduler,
        TimeSpan? lifespan = null,
        TimeSpan? tickInterval = null)
    {
        Notification = notification ?? throw new ArgumentNullException(nameof(notification));
        _hub = hub ?? throw new ArgumentNullException(nameof(hub));
        _scheduler = scheduler ?? throw new ArgumentNullException(nameof(scheduler));
        _lifespan = lifespan ?? TimeSpan.FromSeconds(60);
        _tickInterval = tickInterval ?? TimeSpan.Zero;
        _emitsDecayTicks = _tickInterval > TimeSpan.Zero && _lifespan > TimeSpan.Zero;
        _start = _scheduler.Now;

        DismissCommand = RelayCommand.Builder()
            .Task(Dismiss)
            .Build();

        // Schedule auto-dismiss at Lifespan expiry. The scheduler MUST be
        // asynchronous (the production default is): a synchronous scheduler
        // would block this constructor for the whole lifespan and invoke the
        // virtual OnExpire on a partially-constructed derived instance.
        AttachSubscription(
            ref _timerSub,
            _scheduler.Schedule(_lifespan, OnExpire));

        // VMX-135: when a tick cadence is requested, periodically raise
        // PropertyChanged for the decaying state so bound views repaint the
        // fade-out. The recurring action self-terminates once the notification
        // resolves, is disposed, or the decay completes (RemainingTime hits 0).
        if (_emitsDecayTicks)
            AttachSubscription(
                ref _tickSub,
                _scheduler.Schedule(_tickInterval, DecayTick));

        // Subscribe to hub Pending: if our notification was present and then disappears
        // (external resolve), stop the timer and mark resolved.
        AttachSubscription(
            ref _pendingSub,
            hub.Pending
                .SkipWhile(list => !list.Contains(notification))
                .Skip(1)
                .Where(list => !list.Contains(notification))
                .Take(1)
                .Subscribe(_ => NotifyExternalResolve()));
    }

    /// <summary>The notification datum consumed by this VM.</summary>
    public Notification Notification { get; }

    /// <summary>Configured lifespan (default 60 s).</summary>
    public TimeSpan Lifespan => _lifespan;

    /// <summary>Time remaining until auto-dismiss. Decays to <see cref="TimeSpan.Zero"/>.</summary>
    public TimeSpan RemainingTime
    {
        get
        {
            var elapsed = _scheduler.Now - _start;
            var remaining = _lifespan - elapsed;
            return remaining > TimeSpan.Zero ? remaining : TimeSpan.Zero;
        }
    }

    /// <summary>
    /// Opacity derived as <c>RemainingTime / Lifespan</c>. Range [0.0, 1.0].
    /// Linear decay from 1.0 to 0.0 over <see cref="Lifespan"/>.
    /// </summary>
    public double Opacity =>
        _lifespan.TotalMilliseconds <= 0.0
            ? 0.0
            : RemainingTime.TotalMilliseconds / _lifespan.TotalMilliseconds;

    /// <summary>True once the notification has been resolved (manually or by timer).</summary>
    public bool IsResolved
    {
        get
        {
            lock (_gate)
                return _isResolved;
        }
    }

    /// <summary>
    /// Resolves the notification with <see cref="NotificationReaction.Approve"/>
    /// and cancels the lifespan timer.
    /// </summary>
    public ICommand DismissCommand { get; }

    /// <inheritdoc/>
    public event PropertyChangedEventHandler? PropertyChanged;

    /// <summary>
    /// Notifies the VM that the hub has resolved the notification externally.
    /// Sets <see cref="IsResolved"/> and cancels the timer.
    /// </summary>
    public void NotifyExternalResolve()
    {
        if (!TryClaimResolution(out var timerSub, out var tickSub)) return;
        DisposeResolutionSubscriptions(timerSub, tickSub);
        RaiseResolvedChanges();
    }

    /// <inheritdoc/>
    public void Dispose()
    {
        Dispose(true);
    }

    /// <summary>Subclasses override to perform additional dispose work.</summary>
    protected virtual void Dispose(bool disposing)
    {
        IDisposable? timerSub = null;
        IDisposable? pendingSub = null;
        IDisposable? tickSub = null;
        lock (_gate)
        {
            if (_disposed) return;
            _disposed = true;
            if (!disposing) return;

            timerSub = _timerSub;
            _timerSub = null;
            pendingSub = _pendingSub;
            _pendingSub = null;
            tickSub = _tickSub;
            _tickSub = null;
        }

        timerSub?.Dispose();
        pendingSub?.Dispose();
        tickSub?.Dispose();
        if (DismissCommand is IDisposable d) d.Dispose();
    }

    /// <summary>
    /// Periodic decay tick (VMX-135): raises <see cref="PropertyChanged"/> for the
    /// time-varying state and reschedules until the notification resolves, is
    /// disposed, or the decay completes.
    /// </summary>
    private void DecayTick(Action<TimeSpan> recurse)
    {
        lock (_gate)
        {
            if (_disposed || _isResolved) return;
        }
        RaisePropertyChanged(nameof(RemainingTime));
        RaisePropertyChanged(nameof(Opacity));
        if (RemainingTime > TimeSpan.Zero)
            recurse(_tickInterval);
    }

    /// <summary>Raises <see cref="PropertyChanged"/> for the resolved + decay state.</summary>
    private void RaiseResolvedChanges()
    {
        RaisePropertyChanged(nameof(IsResolved));
        RaisePropertyChanged(nameof(RemainingTime));
        RaisePropertyChanged(nameof(Opacity));
    }

    /// <summary>Raises <see cref="PropertyChanged"/> for the named property.</summary>
    protected void RaisePropertyChanged(string propertyName)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

    /// <summary>
    /// Called when the lifespan timer fires.
    /// Default: auto-dismiss with Approve.
    /// ConfirmationVM overrides to suppress auto-dismiss.
    /// </summary>
    protected virtual void OnExpire() => Dismiss();

    /// <summary>
    /// Resolves the notification with Approve and cancels the timer.
    /// Idempotent: subsequent calls are no-ops.
    /// </summary>
    protected void Dismiss()
    {
        if (!TryClaimResolution(out var timerSub, out var tickSub)) return;
        DisposeResolutionSubscriptions(timerSub, tickSub);
        _hub.Resolve(Notification, NotificationReaction.Approve);
        RaiseResolvedChanges();
    }

    /// <summary>
    /// Resolves the notification with the given <paramref name="reaction"/>
    /// and cancels the timer. Idempotent.
    /// </summary>
    protected void ResolveWith(NotificationReaction reaction)
    {
        if (!TryClaimResolution(out var timerSub, out var tickSub)) return;
        DisposeResolutionSubscriptions(timerSub, tickSub);
        _hub.Resolve(Notification, reaction);
        RaiseResolvedChanges();
    }

    /// <summary>
    /// Atomically claims the unresolved, undisposed terminal state. External
    /// callbacks and subscription disposal happen after the lock is released.
    /// </summary>
    private bool TryClaimResolution(out IDisposable? timerSub, out IDisposable? tickSub)
    {
        lock (_gate)
        {
            if (_disposed || _isResolved)
            {
                timerSub = null;
                tickSub = null;
                return false;
            }

            _isResolved = true;
            timerSub = _timerSub;
            _timerSub = null;
            tickSub = _tickSub;
            _tickSub = null;
            return true;
        }
    }

    /// <summary>
    /// Stores a constructor-created subscription under the same gate as terminal
    /// claims. If a callback reached a terminal state before its scheduling or
    /// subscription API returned, the late handle is disposed instead.
    /// </summary>
    private void AttachSubscription(
        ref IDisposable? target,
        IDisposable subscription)
    {
        var disposeImmediately = false;
        lock (_gate)
        {
            if (_disposed || _isResolved)
                disposeImmediately = true;
            else
                target = subscription;
        }

        if (disposeImmediately)
            subscription.Dispose();
    }

    private static void DisposeResolutionSubscriptions(
        IDisposable? timerSub,
        IDisposable? tickSub)
    {
        timerSub?.Dispose();
        tickSub?.Dispose();
    }
}
