using System.ComponentModel;
using System.Reactive;
using System.Reactive.Subjects;
using System.Windows.Input;
using VMx.Commands;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;

namespace VMx.Components;

/// <summary>
/// Abstract base class for all ComponentVM variants. Implements <see cref="IComponentVM"/>:
/// lifecycle state machine (Construct/Destruct/Reconstruct/Dispose), hub messaging,
/// INPC events, built-in commands, and selection predicates.
///
/// See spec/05-component-vm.md and spec/02-lifecycle.md.
/// </summary>
public abstract class ComponentVMBase : IComponentVM
{
    private readonly IMessageHub _hub;

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

    // ── Parent (set by CompositeVM when a child is added) ───────────────────
    internal ICompositeVM<IComponentVM>? Parent { get; set; }

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
            if (_isCurrent == value) return;
            _isCurrent = value;
            RaisePropertyChanged(nameof(IsCurrent));
            _hub.Send(PropertyChangedMessage<ComponentVMBase>.Create(this, Name, nameof(IsCurrent)));
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
        Action? onDestruct)
    {
        Name = name;
        Hint = hint;
        _hub = hub;
        _onConstruct = onConstruct;
        _onDestruct = onDestruct;

        // Suppress unused warning — dispatcher kept for future async overloads.
        _ = dispatcher;

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

        try
        {
            SetStatus(ConstructionStatus.Constructing);
            _onConstruct?.Invoke();
            SetStatus(ConstructionStatus.Constructed);
        }
        finally
        {
            _inFlight = false;
        }
    }

    /// <inheritdoc/>
    public Task ConstructAsync()
    {
        Construct();
        return Task.CompletedTask;
    }

    // ── Lifecycle: Destruct ─────────────────────────────────────────────────
    /// <inheritdoc/>
    public void Destruct()
    {
        // Idempotent: already Destructed → no-op.
        if (_status == ConstructionStatus.Destructed) return;

        // Validate.
        LifecycleTransitionValidator.Require(_status, "destruct");

        if (_inFlight)
            throw new StatusTransitionException(_status, "destruct");
        _inFlight = true;

        try
        {
            SetStatus(ConstructionStatus.Destructing);
            _onDestruct?.Invoke();
            SetStatus(ConstructionStatus.Destructed);
        }
        finally
        {
            _inFlight = false;
        }
    }

    /// <inheritdoc/>
    public Task DestructAsync()
    {
        Destruct();
        return Task.CompletedTask;
    }

    // ── Lifecycle: Reconstruct ──────────────────────────────────────────────
    /// <inheritdoc/>
    public void Reconstruct()
    {
        // Validate: must be Constructed.
        LifecycleTransitionValidator.Require(_status, "reconstruct");

        if (_inFlight)
            throw new StatusTransitionException(_status, "reconstruct");
        _inFlight = true;

        try
        {
            // Destruct phase
            SetStatus(ConstructionStatus.Destructing);
            _onDestruct?.Invoke();
            SetStatus(ConstructionStatus.Destructed);

            // Construct phase
            SetStatus(ConstructionStatus.Constructing);
            _onConstruct?.Invoke();
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
    public void Dispose()
    {
        // Idempotent: already Disposed → no-op (no message).
        if (_status == ConstructionStatus.Disposed) return;

        SetStatus(ConstructionStatus.Disposed);

        // Complete and dispose the trigger subject.
        if (!_triggerDisposed)
        {
            _triggerDisposed = true;
            _statusTrigger.OnCompleted();
            _statusTrigger.Dispose();
        }

        // Dispose commands.
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
        !ReferenceEquals(Parent.Current, this) &&
        _status == ConstructionStatus.Constructed;

    /// <inheritdoc/>
#pragma warning disable CA1716 // 'Select' is the spec-mandated name per spec/05-component-vm.md
    public void Select() => Parent?.SelectComponent(this);
#pragma warning restore CA1716

    /// <inheritdoc/>
    public bool CanDeselect() =>
        Parent is not null &&
        ReferenceEquals(Parent.Current, this);

    /// <inheritdoc/>
    public void Deselect() => Parent?.DeselectComponent(this);

    private bool CanSelectNext() => false; // requires parent enumeration — Task 7
    private void SelectNext() { }

    private bool CanSelectPrevious() => false; // requires parent enumeration — Task 7
    private void SelectPrevious() { }

    // ── Helpers ─────────────────────────────────────────────────────────────
    private void SetStatus(ConstructionStatus newStatus)
    {
        _status = newStatus;

        // Emit hub message.
        _hub.Send(ConstructionStatusChangedMessage.Create(this, Name, newStatus));

        // Raise INPC for Status and IsConstructed.
        RaisePropertyChanged(nameof(Status));
        RaisePropertyChanged(nameof(IsConstructed));

        // Fire command trigger so predicates are re-evaluated.
        if (!_triggerDisposed)
            _statusTrigger.OnNext(Unit.Default);
    }

    /// <summary>Raises <see cref="PropertyChanged"/> for the named property.</summary>
    protected void RaisePropertyChanged(string propertyName)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

    /// <summary>Access to the hub for subclasses (modeled base needs it).</summary>
    protected IMessageHub Hub => _hub;
}
