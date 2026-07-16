using System.Collections.ObjectModel;
using System.Reactive.Concurrency;
using System.Reactive.Linq;
using VMx.Builders;
using VMx.Components;
using VMx.Messages;
using VMx.Services;
using VMx.Notifications;

namespace NotesShowcase.ViewModels;

/// <summary>
/// Subscribes to an <see cref="INotificationHub"/> and surfaces the most recent
/// notifications as a bounded collection of <see cref="NotificationVM"/>s.
///
/// Cap = 5 (plan §3.a.10). Each <see cref="NotificationVM"/> handles its own
/// auto-dismiss via its <c>Lifespan</c>; this VM observes hub.Pending and
/// removes resolved items.
/// </summary>
public sealed class NotificationsVM : ComponentVMBase
{
    /// <summary>Default maximum number of concurrently rendered notifications.</summary>
    public const int DefaultCap = 5;

    private readonly INotificationHub _notificationHub;
    private readonly IDispatcher _dispatcher;
    private readonly IScheduler _scheduler;
    private readonly TimeSpan? _lifespan;
    private readonly int _cap;
    private readonly ObservableCollection<NotificationVM> _visible = new();
    private readonly Dictionary<Notification, NotificationVM> _map = new();
    private IDisposable? _pendingSub;
    private bool _ownDisposed;

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Component;

    /// <summary>Public hub accessor.</summary>
    public new IMessageHub Hub => base.Hub;

    /// <summary>Bounded list of currently-rendered notifications (newest first).</summary>
    public ObservableCollection<NotificationVM> Visible => _visible;

    /// <summary>Maximum number of concurrently rendered notifications.</summary>
    public int Cap => _cap;

    private NotificationsVM(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        INotificationHub notificationHub,
        IScheduler scheduler,
        TimeSpan? lifespan,
        int cap)
        : base(name, hint, hub, dispatcher, onConstruct: null, onDestruct: null)
    {
        _notificationHub = notificationHub;
        _dispatcher = dispatcher;
        _scheduler = scheduler;
        _lifespan = lifespan;
        _cap = cap;
    }

    /// <inheritdoc/>
    protected override void OnConstruct()
    {
        // live binding: posts arrive from background
        // continuations and auto-dismiss timers (pool threads), and
        // SyncFromPending mutates the ItemsSource-bound collection — INCC
        // off the UI thread crashes Avalonia. Marshal.
        _pendingSub = _notificationHub.Pending
            .ObserveOn(_dispatcher.Foreground)
            .Subscribe(SyncFromPending);
        base.OnConstruct();
    }

    /// <inheritdoc/>
    protected override void OnDestruct()
    {
        _pendingSub?.Dispose();
        _pendingSub = null;
        ClearVisible();
        base.OnDestruct();
    }

    private void SyncFromPending(IReadOnlyList<Notification> pending)
    {
        // Add VMs for new pending notifications, respecting cap.
        foreach (var n in pending)
        {
            if (_map.ContainsKey(n)) continue;
            var vm = new NotificationVM(n, _notificationHub, _scheduler, _lifespan);
            _map[n] = vm;
            _visible.Add(vm);
            // Drop oldest while we're over cap.
            while (_visible.Count > _cap)
            {
                var oldest = _visible[0];
                _visible.RemoveAt(0);
                var keyToRemove = _map.FirstOrDefault(kv => ReferenceEquals(kv.Value, oldest)).Key;
                if (keyToRemove is not null) _map.Remove(keyToRemove);
                oldest.Dispose();
            }
        }
        // Remove VMs whose notifications are no longer pending.
        var stillPending = new HashSet<Notification>(pending, ReferenceEqualityComparer.Instance);
        var toRemove = _map.Keys.Where(k => !stillPending.Contains(k)).ToList();
        foreach (var key in toRemove)
        {
            var vm = _map[key];
            _map.Remove(key);
            _visible.Remove(vm);
            vm.Dispose();
        }
        NotifyPropertyChanged(nameof(Visible));
    }

    private void ClearVisible()
    {
        foreach (var vm in _visible) vm.Dispose();
        _visible.Clear();
        _map.Clear();
    }

    /// <inheritdoc/>
    public override void Dispose()
    {
        if (_ownDisposed) { base.Dispose(); return; }
        _ownDisposed = true;
        _pendingSub?.Dispose();
        ClearVisible();
        base.Dispose();
    }

    /// <summary>Returns a new empty builder.</summary>
    public static NotificationsVMBuilder Builder() => NotificationsVMBuilder.Empty;

    /// <summary>Immutable fluent builder.</summary>
    public sealed class NotificationsVMBuilder
    {
        private readonly string? _name;
        private readonly string _hint;
        private readonly IMessageHub? _hub;
        private readonly IDispatcher? _dispatcher;
        private readonly INotificationHub? _notificationHub;
        private readonly IScheduler? _scheduler;
        private readonly TimeSpan? _lifespan;
        private readonly int _cap;

        internal static readonly NotificationsVMBuilder Empty = new();
        private NotificationsVMBuilder()
        {
            _hint = "";
            _cap = DefaultCap;
        }
        private NotificationsVMBuilder(
            string? name, string hint,
            IMessageHub? hub, IDispatcher? dispatcher,
            INotificationHub? notificationHub, IScheduler? scheduler,
            TimeSpan? lifespan, int cap)
        {
            _name = name; _hint = hint;
            _hub = hub; _dispatcher = dispatcher;
            _notificationHub = notificationHub; _scheduler = scheduler;
            _lifespan = lifespan; _cap = cap;
        }

        /// <summary>Sets the required Name.</summary>
        public NotificationsVMBuilder Name(string name) => new(name, _hint, _hub, _dispatcher, _notificationHub, _scheduler, _lifespan, _cap);
        /// <summary>Sets the optional Hint.</summary>
        public NotificationsVMBuilder Hint(string hint) => new(_name, hint, _hub, _dispatcher, _notificationHub, _scheduler, _lifespan, _cap);
        /// <summary>Sets the required Services.</summary>
        public NotificationsVMBuilder Services(IMessageHub hub, IDispatcher dispatcher) => new(_name, _hint, hub, dispatcher, _notificationHub, _scheduler, _lifespan, _cap);
        /// <summary>Sets the required NotificationHub.</summary>
        public NotificationsVMBuilder NotificationHub(INotificationHub hub) => new(_name, _hint, _hub, _dispatcher, hub, _scheduler, _lifespan, _cap);
        /// <summary>Sets the optional Scheduler for notification timers (default <see cref="DefaultScheduler.Instance"/>).</summary>
        public NotificationsVMBuilder Scheduler(IScheduler scheduler) => new(_name, _hint, _hub, _dispatcher, _notificationHub, scheduler, _lifespan, _cap);
        /// <summary>Overrides the per-notification lifespan (default: 60 s from <see cref="NotificationVM"/>).</summary>
        public NotificationsVMBuilder Lifespan(TimeSpan lifespan) => new(_name, _hint, _hub, _dispatcher, _notificationHub, _scheduler, lifespan, _cap);
        /// <summary>Overrides the cap (default 5).</summary>
        public NotificationsVMBuilder Cap(int cap) => new(_name, _hint, _hub, _dispatcher, _notificationHub, _scheduler, _lifespan, cap);

        /// <summary>Builds the VM after validation.</summary>
        public NotificationsVM Build()
        {
            BuilderValidationException.Require(_name, "Name");
            BuilderValidationException.Require(_hub, "Hub");
            BuilderValidationException.Require(_dispatcher, "Dispatcher");
            BuilderValidationException.Require(_notificationHub, "NotificationHub");
            return new NotificationsVM(
                _name!, _hint, _hub!, _dispatcher!,
                _notificationHub!, _scheduler ?? DefaultScheduler.Instance,
                _lifespan, _cap);
        }
    }
}
