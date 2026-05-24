using System.ComponentModel;
using System.Reactive;
using System.Reactive.Disposables;
using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Windows.Input;
using VMx.Commands;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;

namespace VMx.Components;

/// <summary>
/// Non-generic parent reference used by ComponentVMBase.
/// Exposes only what a child needs from its parent composite for selection logic.
/// Implemented by all ICompositeVM&lt;VM&gt; concrete classes.
/// </summary>
internal interface IParentCompositeVM
{
    /// <summary>The currently selected child, or null.</summary>
    IComponentVM? CurrentChild { get; }

    /// <summary>Selects the given child (typed as IComponentVM).</summary>
    void SelectChild(IComponentVM vm);

    /// <summary>Deselects the given child.</summary>
    void DeselectChild(IComponentVM vm);
}

/// <summary>
/// Internal interface allowing composites to set Parent and IsCurrent on children
/// without exposing these mutators on the public IComponentVM contract.
/// </summary>
internal interface IComponentVMInternals
{
    void SetParent(IParentCompositeVM? parent);
    void SetIsCurrent(bool value);
}

/// <summary>
/// Extension helpers for <see cref="IComponentVM"/> → <see cref="IComponentVMInternals"/> cast.
/// Used internally by composite and group implementations.
/// </summary>
internal static class ComponentVMExtensions
{
    internal static void SetParent(this IComponentVM vm, IParentCompositeVM? parent)
        => (vm as IComponentVMInternals)?.SetParent(parent);

    internal static void SetIsCurrent(this IComponentVM vm, bool value)
        => (vm as IComponentVMInternals)?.SetIsCurrent(value);
}

/// <summary>
/// Abstract base class for all ComponentVM variants. Implements <see cref="IComponentVM"/>:
/// lifecycle state machine (Construct/Destruct/Reconstruct/Dispose), hub messaging,
/// INPC events, built-in commands, and selection predicates.
///
/// See spec/05-component-vm.md and spec/02-lifecycle.md.
/// </summary>
public abstract class ComponentVMBase : IComponentVM, IComponentVMInternals
{
    private readonly IMessageHub _hub;
    private readonly IDispatcher _dispatcher;
    private readonly bool _background;

    // ── Lifecycle state ─────────────────────────────────────────────────────
    private ConstructionStatus _status = ConstructionStatus.Destructed;
    private volatile bool _inFlight;

    // ── Selection state ─────────────────────────────────────────────────────
    private bool _isCurrent;

    // ── Status-change trigger (drives command CanExecute re-evaluation) ─────
    private readonly Subject<Unit> _statusTrigger = new();
    private bool _triggerDisposed;

    // ── Commands ────────────────────────────────────────────────────────────
    private readonly ICommand _selectCommand;
    private readonly ICommand _deselectCommand;
    private readonly ICommand _selectNextCommand;
    private readonly ICommand _selectPreviousCommand;
    private readonly ICommand _reconstructCommand;

    // ── Lifecycle callbacks ─────────────────────────────────────────────────
    private readonly Action? _onConstruct;
    private readonly Action? _onDestruct;

    // ── Virtual lifecycle hooks for subclasses (e.g. CompositeVMBase) ────────
    /// <summary>
    /// Called between the Constructing and Constructed status transitions.
    /// Override to perform additional setup (e.g. construct children).
    /// Base implementation invokes the <c>onConstruct</c> delegate.
    /// </summary>
    protected virtual void OnConstruct() => _onConstruct?.Invoke();

    /// <summary>
    /// Called between the Destructing and Destructed status transitions.
    /// Override to perform additional teardown (e.g. destruct children).
    /// Base implementation invokes the <c>onDestruct</c> delegate.
    /// </summary>
    protected virtual void OnDestruct() => _onDestruct?.Invoke();

    /// <summary>
    /// Called by <see cref="Dispose()"/> after the status reaches Disposed,
    /// before command disposal. Override for additional cleanup.
    /// Base implementation is empty.
    /// </summary>
    protected virtual void OnDispose() { }

    // ── Parent (set by CompositeVM when a child is added) ───────────────────
    internal IParentCompositeVM? Parent { get; set; }

    // ── IComponentVMInternals explicit implementation ─────────────────────────
    void IComponentVMInternals.SetParent(IParentCompositeVM? parent) => Parent = parent;
    void IComponentVMInternals.SetIsCurrent(bool value) => IsCurrent = value;

    // ── IComponentVM: identity ──────────────────────────────────────────────
    /// <inheritdoc/>
    public string Name { get; }

    /// <inheritdoc/>
    public string Hint { get; }

    /// <inheritdoc/>
    public abstract ViewModelType Type { get; }

    // ── IComponentVM: status ────────────────────────────────────────────────
    /// <inheritdoc/>
    public ConstructionStatus Status => _status;

    /// <inheritdoc/>
    public bool IsConstructed => _status == ConstructionStatus.Constructed;

    /// <inheritdoc/>
    public bool IsCurrent
    {
        get => _isCurrent;
        internal set
        {
            // Idempotent-set guard: spec/03-messages.md mandates that a property
            // assignment to the same value MUST NOT emit a PropertyChanged hub
            // message (HUB-005). The guard also avoids redundant INPC raises.
            if (_isCurrent == value) return;
            _isCurrent = value;
            RaisePropertyChanged(nameof(IsCurrent));
            _hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(IsCurrent)));
        }
    }

    // ── IComponentVM: commands ──────────────────────────────────────────────
    /// <inheritdoc/>
    public ICommand SelectCommand => _selectCommand;

    /// <inheritdoc/>
    public ICommand DeselectCommand => _deselectCommand;

    /// <inheritdoc/>
    public ICommand SelectNextCommand => _selectNextCommand;

    /// <inheritdoc/>
    public ICommand SelectPreviousCommand => _selectPreviousCommand;

    /// <inheritdoc/>
    public ICommand ReconstructCommand => _reconstructCommand;

    // ── INotifyPropertyChanged ──────────────────────────────────────────────
    /// <inheritdoc/>
    public event PropertyChangedEventHandler? PropertyChanged;

    // ── Constructor ─────────────────────────────────────────────────────────
    /// <summary>
    /// Called from the concrete builder's Build() method.
    /// </summary>
    protected ComponentVMBase(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        Action? onConstruct,
        Action? onDestruct,
        bool background = false)
    {
        Name = name;
        Hint = hint;
        _hub = hub;
        _dispatcher = dispatcher;
        _background = background;
        _onConstruct = onConstruct;
        _onDestruct = onDestruct;

        // ── Status-change trigger observable ─────────────────────────────────
        // Fires CanExecuteChanged on all built-in commands whenever Status changes.
        IObservable<Unit> statusTrigger = _statusTrigger;

        // ── Build commands ────────────────────────────────────────────────────
        _selectCommand = RelayCommand.Builder()
            .Predicate(CanSelect)
            .Task(Select)
            .Triggers(statusTrigger)
            .Build();

        _deselectCommand = RelayCommand.Builder()
            .Predicate(CanDeselect)
            .Task(Deselect)
            .Triggers(statusTrigger)
            .Build();

        _selectNextCommand = RelayCommand.Builder()
            .Predicate(CanSelectNext)
            .Task(SelectNext)
            .Triggers(statusTrigger)
            .Build();

        _selectPreviousCommand = RelayCommand.Builder()
            .Predicate(CanSelectPrevious)
            .Task(SelectPrevious)
            .Triggers(statusTrigger)
            .Build();

        _reconstructCommand = RelayCommand.Builder()
            .Predicate(CanReconstruct)
            .Task(Reconstruct)
            .Triggers(statusTrigger)
            .Build();
    }

    // ── Lifecycle: CanXxx predicates ────────────────────────────────────────
    /// <inheritdoc/>
    public bool CanConstruct() =>
        _status == ConstructionStatus.Destructed || _status == ConstructionStatus.Constructed;

    /// <inheritdoc/>
    public bool CanDestruct() =>
        _status == ConstructionStatus.Constructed || _status == ConstructionStatus.Destructed;

    /// <inheritdoc/>
    public bool CanReconstruct() =>
        _status == ConstructionStatus.Constructed;

    // ── Lifecycle: Construct ────────────────────────────────────────────────
    /// <inheritdoc/>
    public void Construct()
    {
        // Idempotent: already Constructed → no-op (no message).
        if (_status == ConstructionStatus.Constructed) return;

        // Validate the transition (will throw for illegal states like Disposed).
        LifecycleTransitionValidator.Require(_status, "construct");

        // Concurrency guard: cannot re-enter while in-flight.
        if (_inFlight)
            throw new StatusTransitionException(_status, "construct");
        _inFlight = true;

        if (_background)
        {
            // Emit Constructing synchronously so subscribers immediately observe the
            // transition starting; then schedule the actual work on the background scheduler.
            SetStatus(ConstructionStatus.Constructing);
            _dispatcher.Background.Schedule(Unit.Default, (_, _) =>
            {
                try
                {
                    OnConstruct();
                    SetStatus(ConstructionStatus.Constructed);
                }
                finally
                {
                    _inFlight = false;
                }
                return Disposable.Empty;
            });
            // Return immediately — caller does not wait for background work.
        }
        else
        {
            try
            {
                SetStatus(ConstructionStatus.Constructing);
                OnConstruct();
                SetStatus(ConstructionStatus.Constructed);
            }
            finally
            {
                _inFlight = false;
            }
        }
    }

    /// <inheritdoc/>
    public Task ConstructAsync()
    {
        if (_background)
        {
            // Subscribe to the hub BEFORE calling Construct() to avoid a race where
            // the background work finishes before the subscription is established.
            var tcs = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            var subscription = _hub.Messages
                .OfType<IConstructionStatusChangedMessage>()
                .Where(m => ReferenceEquals(m.SenderObject, this) &&
                            m.Status == ConstructionStatus.Constructed)
                .Take(1)
                .Subscribe(_ => tcs.TrySetResult(true));

            Construct();

            // If already Constructed before subscription fired (e.g. scheduler advanced
            // inline on a test scheduler), the TCS is already set; either way we wait.
            return tcs.Task.ContinueWith(_ => subscription.Dispose(), TaskScheduler.Default);
        }

        Construct();
        return Task.CompletedTask;
    }

    // ── Lifecycle: Destruct ─────────────────────────────────────────────────
    /// <inheritdoc/>
    public void Destruct()
    {
        if (_status == ConstructionStatus.Destructed) return;

        LifecycleTransitionValidator.Require(_status, "destruct");

        if (_inFlight)
            throw new StatusTransitionException(_status, "destruct");
        _inFlight = true;

        if (_background)
        {
            // Emit Destructing synchronously so subscribers see the transition start;
            // the actual OnDestruct runs on the background scheduler and the caller does
            // not wait for it.
            SetStatus(ConstructionStatus.Destructing);
            _dispatcher.Background.Schedule(Unit.Default, (_, _) =>
            {
                try
                {
                    OnDestruct();
                    SetStatus(ConstructionStatus.Destructed);
                }
                finally
                {
                    _inFlight = false;
                }
                return Disposable.Empty;
            });
        }
        else
        {
            try
            {
                SetStatus(ConstructionStatus.Destructing);
                OnDestruct();
                SetStatus(ConstructionStatus.Destructed);
            }
            finally
            {
                _inFlight = false;
            }
        }
    }

    /// <inheritdoc/>
    public Task DestructAsync()
    {
        if (_background)
        {
            // Subscribe to the hub BEFORE calling Destruct() to avoid a race where
            // the background work finishes before the subscription is established.
            var tcs = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            var subscription = _hub.Messages
                .OfType<IConstructionStatusChangedMessage>()
                .Where(m => ReferenceEquals(m.SenderObject, this) &&
                            m.Status == ConstructionStatus.Destructed)
                .Take(1)
                .Subscribe(_ => tcs.TrySetResult(true));

            Destruct();

            return tcs.Task.ContinueWith(_ => subscription.Dispose(), TaskScheduler.Default);
        }

        Destruct();
        return Task.CompletedTask;
    }

    // ── Lifecycle: Reconstruct ──────────────────────────────────────────────
    /// <inheritdoc/>
    public void Reconstruct()
    {
        LifecycleTransitionValidator.Require(_status, "reconstruct");

        if (_inFlight)
            throw new StatusTransitionException(_status, "reconstruct");
        _inFlight = true;

        try
        {
            SetStatus(ConstructionStatus.Destructing);
            OnDestruct();
            SetStatus(ConstructionStatus.Destructed);

            SetStatus(ConstructionStatus.Constructing);
            OnConstruct();
            SetStatus(ConstructionStatus.Constructed);
        }
        finally
        {
            _inFlight = false;
        }
    }

    /// <inheritdoc/>
    public Task ReconstructAsync()
    {
        Reconstruct();
        return Task.CompletedTask;
    }

    // ── Lifecycle: Dispose ──────────────────────────────────────────────────
    /// <inheritdoc/>
    public virtual void Dispose()
    {
        if (_status == ConstructionStatus.Disposed) return;

        SetStatus(ConstructionStatus.Disposed);

        if (!_triggerDisposed)
        {
            _triggerDisposed = true;
            _statusTrigger.OnCompleted();
            _statusTrigger.Dispose();
        }

        (_selectCommand as IDisposable)?.Dispose();
        (_deselectCommand as IDisposable)?.Dispose();
        (_selectNextCommand as IDisposable)?.Dispose();
        (_selectPreviousCommand as IDisposable)?.Dispose();
        (_reconstructCommand as IDisposable)?.Dispose();

        GC.SuppressFinalize(this);
    }

    // ── Selection predicates ────────────────────────────────────────────────
    /// <inheritdoc/>
    public bool CanSelect() =>
        Parent is not null &&
        !ReferenceEquals(Parent.CurrentChild, this) &&
        _status == ConstructionStatus.Constructed;

    /// <inheritdoc/>
#pragma warning disable CA1716 // 'Select' is the spec-mandated name per spec/05-component-vm.md
    public void Select() => Parent?.SelectChild(this);
#pragma warning restore CA1716

    /// <inheritdoc/>
    public bool CanDeselect() =>
        Parent is not null &&
        ReferenceEquals(Parent.CurrentChild, this);

    /// <inheritdoc/>
    public void Deselect() => Parent?.DeselectChild(this);

    private bool CanSelectNext() => false; // requires parent enumeration
    private void SelectNext() { }

    private bool CanSelectPrevious() => false; // requires parent enumeration
    private void SelectPrevious() { }

    // ── Helpers ─────────────────────────────────────────────────────────────
    private void SetStatus(ConstructionStatus newStatus)
    {
        _status = newStatus;

        _hub.Send(ConstructionStatusChangedMessage.Create(this, Name, newStatus));

        // Status and IsConstructed are computed/read-only, so they raise INPC only;
        // no PropertyChangedMessage on the hub (spec 03-messages.md restricts hub
        // PropertyChangedMessage to setter-assigned properties).
        RaisePropertyChanged(nameof(Status));
        RaisePropertyChanged(nameof(IsConstructed));

        if (!_triggerDisposed)
            _statusTrigger.OnNext(Unit.Default);
    }

    /// <summary>Raises <see cref="PropertyChanged"/> for the named property.</summary>
    protected void RaisePropertyChanged(string propertyName)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

    /// <summary>Access to the hub for subclasses (modeled base needs it).</summary>
    protected IMessageHub Hub => _hub;
}
