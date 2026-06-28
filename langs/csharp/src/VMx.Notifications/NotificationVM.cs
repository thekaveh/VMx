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
/// See spec/16-notifications.md §NotificationVM and ADR-0031.
/// </summary>
public class NotificationVM : IDisposable
{
    private readonly INotificationHub _hub;
    private readonly IScheduler _scheduler;
    private readonly TimeSpan _lifespan;
    private readonly DateTimeOffset _start;
    private IDisposable? _timerSub;
    private IDisposable? _pendingSub;
    private bool _isResolved;
    private bool _disposed;

    /// <summary>
    /// Creates a <see cref="NotificationVM"/>.
    /// </summary>
    /// <param name="notification">The notification to render.</param>
    /// <param name="hub">Hub used to resolve the notification.</param>
    /// <param name="scheduler">Scheduler for time advancement. Inject a TestScheduler in tests.</param>
    /// <param name="lifespan">Override the default 60-second lifespan.</param>
    public NotificationVM(
        Notification notification,
        INotificationHub hub,
        IScheduler scheduler,
        TimeSpan? lifespan = null)
    {
        Notification = notification ?? throw new ArgumentNullException(nameof(notification));
        _hub = hub ?? throw new ArgumentNullException(nameof(hub));
        _scheduler = scheduler ?? throw new ArgumentNullException(nameof(scheduler));
        _lifespan = lifespan ?? TimeSpan.FromSeconds(60);
        _start = _scheduler.Now;

        DismissCommand = RelayCommand.Builder()
            .Task(Dismiss)
            .Build();

        // Schedule auto-dismiss at Lifespan expiry. The scheduler MUST be
        // asynchronous (the production default is): a synchronous scheduler
        // would block this constructor for the whole lifespan and invoke the
        // virtual OnExpire on a partially-constructed derived instance.
        _timerSub = _scheduler.Schedule(_lifespan, OnExpire);

        // Subscribe to hub Pending: if our notification was present and then disappears
        // (external resolve), stop the timer and mark resolved.
        _pendingSub = hub.Pending
            .SkipWhile(list => !list.Contains(notification))
            .Skip(1)
            .Where(list => !list.Contains(notification))
            .Take(1)
            .Subscribe(_ => NotifyExternalResolve());
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
    public bool IsResolved => _isResolved;

    /// <summary>
    /// Resolves the notification with <see cref="NotificationReaction.Approve"/>
    /// and cancels the lifespan timer.
    /// </summary>
    public ICommand DismissCommand { get; }

    /// <summary>
    /// Notifies the VM that the hub has resolved the notification externally.
    /// Sets <see cref="IsResolved"/> and cancels the timer.
    /// </summary>
    public void NotifyExternalResolve()
    {
        if (_isResolved) return;
        _isResolved = true;
        _timerSub?.Dispose();
        _timerSub = null;
    }

    /// <inheritdoc/>
    public void Dispose()
    {
        Dispose(true);
    }

    /// <summary>Subclasses override to perform additional dispose work.</summary>
    protected virtual void Dispose(bool disposing)
    {
        if (_disposed) return;
        _disposed = true;
        if (disposing)
        {
            _timerSub?.Dispose();
            _timerSub = null;
            _pendingSub?.Dispose();
            _pendingSub = null;
            if (DismissCommand is IDisposable d) d.Dispose();
        }
    }

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
        if (_isResolved) return;
        _isResolved = true;
        _timerSub?.Dispose();
        _timerSub = null;
        _hub.Resolve(Notification, NotificationReaction.Approve);
    }

    /// <summary>
    /// Resolves the notification with the given <paramref name="reaction"/>
    /// and cancels the timer. Idempotent.
    /// </summary>
    protected void ResolveWith(NotificationReaction reaction)
    {
        if (_isResolved) return;
        _isResolved = true;
        _timerSub?.Dispose();
        _timerSub = null;
        _hub.Resolve(Notification, reaction);
    }
}
