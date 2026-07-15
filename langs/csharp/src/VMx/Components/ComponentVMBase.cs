using System.ComponentModel;
using System.Reactive;
using System.Reactive.Disposables;
using System.Reactive.Subjects;
using System.Runtime.ExceptionServices;
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
    /// <summary>The component that owns this child collection.</summary>
    IComponentVM? Owner { get; }

    /// <summary>The owner's own parent, used for identity-based cycle checks.</summary>
    IParentCompositeVM? OwnerParent { get; }

    /// <summary>True when children can select/deselect into a parent-owned current slot.</summary>
    bool SupportsChildSelection { get; }

    /// <summary>The currently selected child, or null.</summary>
    IComponentVM? CurrentChild { get; }

    /// <summary>Selects the given child (typed as IComponentVM).</summary>
    void SelectChild(IComponentVM vm);

    /// <summary>Deselects the given child.</summary>
    void DeselectChild(IComponentVM vm);

    /// <summary>Whether this parent contains the exact child identity.</summary>
    bool ContainsChild(IComponentVM vm);

    /// <summary>Stage-detaches a child without publishing the removal.</summary>
    ParentTransferToken DetachForTransfer(IComponentVM vm);
}

/// <summary>
/// One-shot transaction returned by an old parent while a new parent attempts
/// to take ownership of a child.
/// </summary>
internal sealed class ParentTransferToken
{
    private readonly Action _commit;
    private readonly Action _rollback;
    private bool _finished;

    internal ParentTransferToken(Action commit, Action rollback)
    {
        _commit = commit;
        _rollback = rollback;
    }

    internal void Commit()
    {
        if (_finished) throw new InvalidOperationException("Parent transfer token is already finished.");
        _finished = true;
        _commit();
    }

    internal void Rollback()
    {
        if (_finished) throw new InvalidOperationException("Parent transfer token is already finished.");
        _finished = true;
        _rollback();
    }
}

/// <summary>
/// Internal interface allowing composites to set Parent and IsCurrent on children
/// without exposing these mutators on the public IComponentVM contract.
/// </summary>
internal interface IComponentVMInternals
{
    IParentCompositeVM? Parent { get; }
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

    internal static IParentCompositeVM? GetParent(this IComponentVM vm)
        => (vm as IComponentVMInternals)?.Parent;

    internal static void SetIsCurrent(this IComponentVM vm, bool value)
        => (vm as IComponentVMInternals)?.SetIsCurrent(value);
}

/// <summary>Shared identity validation and old-parent staging for container mutations.</summary>
internal static class ComponentOwnership
{
    internal static ParentTransferToken? BeginTransfer(
        IComponentVM child,
        IParentCompositeVM destination)
    {
        if (destination.ContainsChild(child))
            throw new InvalidOperationException(
                $"Cannot add '{child.Name}': the destination already contains that identity.");

        for (IParentCompositeVM? cursor = destination; cursor is not null; cursor = cursor.OwnerParent)
        {
            if (cursor.Owner is not null && ReferenceEquals(cursor.Owner, child))
                throw new InvalidOperationException(
                    $"Cannot add '{child.Name}': the operation would create a parent cycle.");
        }

        return child.GetParent()?.DetachForTransfer(child);
    }
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
    private readonly List<IDisposable> _ownedResources = [];

    /// <summary>
    /// The dispatcher supplied at construction. <c>private protected</c> so
    /// same-assembly container subclasses can schedule on it without re-storing
    /// their own copy.
    /// </summary>
    private protected readonly IDispatcher _dispatcher;
    private readonly bool _background;

    // ── Lifecycle state ─────────────────────────────────────────────────────
    // _gate serializes every lifecycle state transition — the _status RMW, the
    // hub publish, and the status-trigger emission inside SetStatus — against
    // Dispose(). A background completion (Construct/Destruct dispatched on the
    // background scheduler) therefore cannot interleave with disposal: it
    // observes the terminal Disposed state and aborts instead of resurrecting
    // the VM, publishing a post-dispose status message, or calling OnNext on a
    // disposed Subject (VMX-001/054; spec/02 invariant 3 — Disposed is terminal).
    private readonly object _gate = new();

    // volatile so the unlocked fast-path reads (Status, IsConstructed, the Can*
    // predicates, the idempotent lifecycle guards) never observe a stale value
    // written by a transition completing on the background scheduler.
    private volatile ConstructionStatus _status = ConstructionStatus.Destructed;
    private volatile bool _inFlight;
    private readonly List<TaskCompletionSource<bool>> _lifecycleWaiters = [];
    private Task? _deferredLifecycleTask;

    // ── Selection state ─────────────────────────────────────────────────────
    private bool _isCurrent;

    // ── Status-change trigger (drives command CanExecute re-evaluation) ─────
    private readonly Subject<Unit> _statusTrigger = new();
    private bool _triggerDisposed;

    // ── Commands (lazily built on first access — VMX-018) ───────────────────
    private ICommand? _selectCommand;
    private ICommand? _deselectCommand;
    private ICommand? _selectNextCommand;
    private ICommand? _selectPreviousCommand;
    private ICommand? _reconstructCommand;

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
    /// Defers the parent's terminal lifecycle transition until asynchronous child
    /// transitions have settled. A synchronously completed task is observed
    /// immediately so hook failures retain their existing throw behavior.
    /// </summary>
    protected void CompleteLifecycleHookAfter(Task task)
    {
        if (task.IsCompleted)
        {
            task.GetAwaiter().GetResult();
            return;
        }

        lock (_gate)
        {
            if (_deferredLifecycleTask is not null)
                throw new InvalidOperationException("A lifecycle hook already deferred completion.");
            _deferredLifecycleTask = task;
        }
    }

    /// <summary>Transitions children sequentially and validates their settled state.</summary>
    protected static async Task TransitionChildrenAsync(
        IEnumerable<IComponentVM> children,
        bool construct,
        Action? after = null)
    {
        foreach (var child in children)
        {
            if (construct)
            {
                await child.ConstructAsync().ConfigureAwait(false);
                if (child.Status != ConstructionStatus.Constructed)
                    throw new InvalidOperationException(
                        $"Child '{child.Name}' did not reach Constructed.");
            }
            else
            {
                await child.DestructAsync().ConfigureAwait(false);
                if (child.Status != ConstructionStatus.Destructed)
                    throw new InvalidOperationException(
                        $"Child '{child.Name}' did not reach Destructed.");
            }
        }

        after?.Invoke();
    }

    /// <summary>
    /// Called by <see cref="Dispose()"/> after the status reaches Disposed,
    /// before command disposal. Override for additional cleanup.
    /// Base implementation is empty.
    /// </summary>
    protected virtual void OnDispose() { }

    // ── Parent (set by CompositeVM when a child is added) ───────────────────
    internal IParentCompositeVM? Parent { get; set; }

    // ── IComponentVMInternals explicit implementation ─────────────────────────
    IParentCompositeVM? IComponentVMInternals.Parent => Parent;
    void IComponentVMInternals.SetParent(IParentCompositeVM? parent) => Parent = parent;
    void IComponentVMInternals.SetIsCurrent(bool value) => IsCurrent = value;

    // ── IComponentVM: identity ──────────────────────────────────────────────
    /// <inheritdoc/>
    public string Name { get; }

    /// <inheritdoc/>
    public string Hint { get; }

    /// <inheritdoc/>
    public IMessageHub Hub => _hub;

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
            // Post-dispose guard: spec/02 invariant 3 — Disposed is terminal.
            // A selection change on an already-disposed VM is a silent no-op
            // (no INPC raise, no hub PropertyChangedMessage), mirroring Swift
            // (VMX-006). Reads the terminal state under the same _gate the
            // lifecycle-race guards use.
            if (IsDisposed()) return;

            // Idempotent-set guard: spec/03-messages.md mandates that a property
            // assignment to the same value MUST NOT emit a PropertyChanged hub
            // message (HUB-005). The guard also avoids redundant INPC raises.
            if (_isCurrent == value) return;
            _isCurrent = value;
            NotifyPropertyChanged(nameof(IsCurrent));
        }
    }

    // ── IComponentVM: commands (lazily built + cached — VMX-018) ────────────
    /// <inheritdoc/>
    public ICommand SelectCommand => _selectCommand ??= BuildCommand(CanSelect, Select);

    /// <inheritdoc/>
    public ICommand DeselectCommand => _deselectCommand ??= BuildCommand(CanDeselect, Deselect);

    /// <inheritdoc/>
    public ICommand SelectNextCommand =>
        _selectNextCommand ??= BuildCommand(CanSelectNext, SelectNext);

    /// <inheritdoc/>
    public ICommand SelectPreviousCommand =>
        _selectPreviousCommand ??= BuildCommand(CanSelectPrevious, SelectPrevious);

    /// <inheritdoc/>
    public ICommand ReconstructCommand =>
        _reconstructCommand ??= BuildCommand(CanReconstruct, Reconstruct);

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

        // Built-in commands are built lazily on first access (VMX-018) — see
        // BuildCommand. Eager construction allocated five RelayCommands plus
        // five status-trigger subscriptions per VM, four of which are
        // permanently inert on a leaf VM.
    }

    /// <summary>
    /// Builds a built-in command, wiring the status trigger so its
    /// <c>CanExecuteChanged</c> re-fires on every lifecycle transition (VMX-104).
    /// After disposal the trigger Subject is completed/disposed, so a command
    /// built post-dispose is built without it rather than subscribing to a
    /// disposed Subject.
    /// </summary>
    private RelayCommand BuildCommand(Func<bool> predicate, Action task)
    {
        var builder = RelayCommand.Builder().Predicate(predicate).Task(task);
        if (!_triggerDisposed)
            builder = builder.Triggers(_statusTrigger);
        return builder.Build();
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
        lock (_gate)
        {
            // Idempotent: already Constructed → no-op (no message).
            if (_status == ConstructionStatus.Constructed) return;

            // Validate the transition (will throw for illegal states like Disposed).
            LifecycleTransitionValidator.Require(_status, "construct");

            // Concurrency guard: cannot re-enter while in-flight.
            if (_inFlight)
                throw new StatusTransitionException(_status, "construct");
            _inFlight = true;

            // Emit Constructing synchronously so subscribers immediately observe the
            // transition starting; then run the actual work on the selected scheduler.
            SetStatus(ConstructionStatus.Constructing);
        }

        if (_background)
        {
            _dispatcher.Background.Schedule(Unit.Default, (_, _) =>
            {
                // Dispose() may have run between scheduling and execution.
                // Re-check the terminal state under _gate and abort if disposed
                // (spec/02 invariant 3): no OnConstruct(), no marshalled emission.
                if (IsDisposed())
                {
                    ClearInFlight();
                    return Disposable.Empty;
                }

                try
                {
                    OnConstruct();
                }
                catch (Exception error)
                {
                    // VMX-007: roll _status back to Destructed (marshalled onto the
                    // foreground per VMX-025; SetStatus re-checks Disposed under
                    // _gate) and clear the in-flight guard so a throwing background
                    // hook leaves the VM recoverable, then re-throw. Under the
                    // immediate/test scheduler the rollback runs inline and the
                    // exception surfaces to the caller. C# async lifecycle waiters
                    // receive the same error only after the foreground rollback has
                    // been published (ADR-0109).
                    _dispatcher.Foreground.Schedule(Unit.Default, (_, _) =>
                    {
                        try
                        {
                            SetStatus(ConstructionStatus.Destructed);
                        }
                        finally
                        {
                            FailInFlight(error);
                        }
                        return Disposable.Empty;
                    });
                    throw;
                }

                var deferred = TakeDeferredLifecycleTask();
                if (deferred is not null)
                {
                    CompleteDeferredLifecycle(
                        deferred,
                        ConstructionStatus.Constructed,
                        ConstructionStatus.Destructed);
                    return Disposable.Empty;
                }

                // VMX-025: marshal the terminal Constructed emission onto the
                // foreground scheduler so subscribers observe the status change on
                // the foreground (UI) thread, not the background (pool) thread.
                // SetStatus re-checks Disposed under _gate, so a Dispose() landing
                // before this marshalled emission runs still aborts the transition
                // — no resurrection, no post-dispose publish, no OnNext on a
                // disposed Subject (VMX-001/054).
                _dispatcher.Foreground.Schedule(Unit.Default, (_, _) =>
                {
                    try
                    {
                        SetStatus(ConstructionStatus.Constructed);
                    }
                    finally
                    {
                        ClearInFlight();
                    }
                    return Disposable.Empty;
                });
                return Disposable.Empty;
            });
            // Return immediately — caller does not wait for background work.
        }
        else
        {
            var completionDeferred = false;
            try
            {
                try
                {
                    OnConstruct();
                }
                catch
                {
                    // VMX-007: a throwing construct hook must not wedge the VM in
                    // the transient Constructing state. Roll _status back to the
                    // prior settled state (Destructed) under _gate, then re-throw so
                    // the caller sees the original failure. The VM is left
                    // recoverable instead of unrecoverable-except-via-Dispose.
                    SetStatus(ConstructionStatus.Destructed);
                    throw;
                }
                var deferred = TakeDeferredLifecycleTask();
                if (deferred is not null)
                {
                    completionDeferred = true;
                    CompleteDeferredLifecycle(
                        deferred,
                        ConstructionStatus.Constructed,
                        ConstructionStatus.Destructed);
                    return;
                }
                SetStatus(ConstructionStatus.Constructed);
            }
            finally
            {
                if (!completionDeferred)
                    ClearInFlight();
            }
        }
    }

    /// <inheritdoc/>
    public Task ConstructAsync()
    {
        lock (_gate)
        {
            // Idempotent like Construct(): already Constructed emits no message.
            if (_status == ConstructionStatus.Constructed) return Task.CompletedTask;
            // Container cascades may join a background transition they started
            // while staging an atomic population. Do not start it a second time.
            if (_status == ConstructionStatus.Constructing && _inFlight)
                return RegisterLifecycleWaiter().Task;
        }

        var tcs = RegisterLifecycleWaiter();
        try
        {
            Construct();
        }
        catch
        {
            RemoveLifecycleWaiter(tcs);
            throw;
        }

        CompleteWaiterIfSettled(tcs);
        return tcs.Task;
    }

    // ── Lifecycle: Destruct ─────────────────────────────────────────────────
    /// <inheritdoc/>
    public void Destruct()
    {
        lock (_gate)
        {
            if (_status == ConstructionStatus.Destructed) return;

            LifecycleTransitionValidator.Require(_status, "destruct");

            if (_inFlight)
                throw new StatusTransitionException(_status, "destruct");
            _inFlight = true;

            // Emit Destructing synchronously so subscribers see the transition start;
            // the actual OnDestruct runs on the selected scheduler.
            SetStatus(ConstructionStatus.Destructing);
        }

        if (_background)
        {
            _dispatcher.Background.Schedule(Unit.Default, (_, _) =>
            {
                // Dispose() may have run between scheduling and execution.
                // Re-check the terminal state under _gate and abort if disposed
                // (spec/02 invariant 3): no OnDestruct(), no marshalled emission.
                if (IsDisposed())
                {
                    ClearInFlight();
                    return Disposable.Empty;
                }

                try
                {
                    OnDestruct();
                }
                catch (Exception error)
                {
                    // VMX-007: roll _status back to Constructed (marshalled onto the
                    // foreground per VMX-025; SetStatus re-checks Disposed under
                    // _gate) and clear the in-flight guard so a throwing background
                    // hook leaves the VM recoverable, then re-throw. C# async
                    // lifecycle waiters receive the same error only after that
                    // rollback publication (ADR-0109).
                    _dispatcher.Foreground.Schedule(Unit.Default, (_, _) =>
                    {
                        try
                        {
                            SetStatus(ConstructionStatus.Constructed);
                        }
                        finally
                        {
                            FailInFlight(error);
                        }
                        return Disposable.Empty;
                    });
                    throw;
                }

                var deferred = TakeDeferredLifecycleTask();
                if (deferred is not null)
                {
                    CompleteDeferredLifecycle(
                        deferred,
                        ConstructionStatus.Destructed,
                        ConstructionStatus.Constructed);
                    return Disposable.Empty;
                }

                // VMX-025: marshal the terminal Destructed emission onto the
                // foreground scheduler so subscribers observe the status change on
                // the foreground (UI) thread, not the background (pool) thread.
                // SetStatus re-checks Disposed under _gate, so a Dispose() landing
                // before this marshalled emission runs still aborts the transition
                // — no resurrection, no post-dispose publish, no OnNext on a
                // disposed Subject (VMX-001/054).
                _dispatcher.Foreground.Schedule(Unit.Default, (_, _) =>
                {
                    try
                    {
                        SetStatus(ConstructionStatus.Destructed);
                    }
                    finally
                    {
                        ClearInFlight();
                    }
                    return Disposable.Empty;
                });
                return Disposable.Empty;
            });
        }
        else
        {
            var completionDeferred = false;
            try
            {
                try
                {
                    OnDestruct();
                }
                catch
                {
                    // VMX-007: roll _status back to the prior settled state
                    // (Constructed) under _gate, then re-throw. The VM is left
                    // recoverable instead of wedged in Destructing.
                    SetStatus(ConstructionStatus.Constructed);
                    throw;
                }
                var deferred = TakeDeferredLifecycleTask();
                if (deferred is not null)
                {
                    completionDeferred = true;
                    CompleteDeferredLifecycle(
                        deferred,
                        ConstructionStatus.Destructed,
                        ConstructionStatus.Constructed);
                    return;
                }
                SetStatus(ConstructionStatus.Destructed);
            }
            finally
            {
                if (!completionDeferred)
                    ClearInFlight();
            }
        }
    }

    /// <inheritdoc/>
    public Task DestructAsync()
    {
        lock (_gate)
        {
            // Idempotent like Destruct(): already Destructed emits no message.
            if (_status == ConstructionStatus.Destructed) return Task.CompletedTask;
            // Internal cascades join an already-running background transition.
            if (_status == ConstructionStatus.Destructing && _inFlight)
                return RegisterLifecycleWaiter().Task;
        }

        var tcs = RegisterLifecycleWaiter();
        try
        {
            Destruct();
        }
        catch
        {
            RemoveLifecycleWaiter(tcs);
            throw;
        }

        CompleteWaiterIfSettled(tcs);
        return tcs.Task;
    }

    // ── Lifecycle: Reconstruct ──────────────────────────────────────────────
    /// <inheritdoc/>
    public void Reconstruct()
    {
        lock (_gate)
        {
            LifecycleTransitionValidator.Require(_status, "reconstruct");

            if (_inFlight)
                throw new StatusTransitionException(_status, "reconstruct");
            _inFlight = true;

            SetStatus(ConstructionStatus.Destructing);
        }

        var completionDeferred = false;
        try
        {
            try
            {
                OnDestruct();
            }
            catch
            {
                // VMX-007: a failed destruct phase rolls back to Constructed (the
                // state reconstruct started from) so the VM stays recoverable.
                SetStatus(ConstructionStatus.Constructed);
                throw;
            }
            var deferredDestruct = TakeDeferredLifecycleTask();
            if (deferredDestruct is not null)
            {
                completionDeferred = true;
                ContinueReconstructAfterDeferredDestruct(deferredDestruct);
                return;
            }

            completionDeferred = ContinueReconstructWithConstructPhase();
        }
        finally
        {
            if (!completionDeferred)
                ClearInFlight();
        }
    }

    /// <inheritdoc/>
    public Task ReconstructAsync()
    {
        var tcs = RegisterLifecycleWaiter();
        try
        {
            Reconstruct();
        }
        catch
        {
            RemoveLifecycleWaiter(tcs);
            throw;
        }

        CompleteWaiterIfSettled(tcs);
        return tcs.Task;
    }

    private bool ContinueReconstructWithConstructPhase()
    {
        SetStatus(ConstructionStatus.Destructed);
        SetStatus(ConstructionStatus.Constructing);
        try
        {
            OnConstruct();
        }
        catch
        {
            SetStatus(ConstructionStatus.Destructed);
            throw;
        }

        var deferredConstruct = TakeDeferredLifecycleTask();
        if (deferredConstruct is not null)
        {
            CompleteDeferredLifecycle(
                deferredConstruct,
                ConstructionStatus.Constructed,
                ConstructionStatus.Destructed);
            return true;
        }

        SetStatus(ConstructionStatus.Constructed);
        return false;
    }

    private void ContinueReconstructAfterDeferredDestruct(Task task)
    {
        _ = task.ContinueWith(
            completed =>
            {
                _dispatcher.Foreground.Schedule(Unit.Default, (_, _) =>
                {
                    if (IsDisposed())
                    {
                        ClearInFlight();
                        return Disposable.Empty;
                    }

                    if (completed.Status != TaskStatus.RanToCompletion)
                    {
                        SetStatus(ConstructionStatus.Constructed);
                        FinishInFlightFrom(completed);
                        return Disposable.Empty;
                    }

                    try
                    {
                        if (!ContinueReconstructWithConstructPhase())
                            ClearInFlight();
                    }
                    catch (Exception error)
                    {
                        FailInFlight(error);
                    }
                    return Disposable.Empty;
                });
            },
            CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
    }

    // ── Lifecycle: Dispose ──────────────────────────────────────────────────

    /// <summary>
    /// Disposes every child while preserving the first failure for the parent
    /// override to rethrow after its explicit base cleanup. A failing child
    /// must not strand its siblings or parent during a LIFE-013 cascade.
    /// </summary>
    protected static ExceptionDispatchInfo? DisposeChildren(
        IEnumerable<IDisposable?> children)
    {
        ExceptionDispatchInfo? firstError = null;
        foreach (var child in children)
        {
            if (child is null) continue;
            try
            {
                child.Dispose();
            }
            catch (Exception error)
            {
                firstError ??= ExceptionDispatchInfo.Capture(error);
            }
        }

        return firstError;
    }

    /// <inheritdoc/>
    public virtual void Dispose()
    {
        lock (_gate)
        {
            if (_status == ConstructionStatus.Disposed) return;
            SetStatus(ConstructionStatus.Disposed);
            CompleteLifecycleWaitersLocked();
        }

        // Subclass cleanup hook, matching Python `_on_dispose` (base.py) and
        // TS `_onDispose` (componentVMBase.ts). Runs immediately after the
        // status reaches Disposed and *before* the status trigger is
        // completed, so a subclass override can still publish a final
        // status value or touch hub-published subjects during cleanup.
        try
        {
            try
            {
                OnDispose();
            }
            finally
            {
                DisposeOwnedResources();
            }
        }
        finally
        {
            // Tear down the status trigger under _gate so the flag flip and the
            // Subject disposal cannot interleave with an in-flight background
            // SetStatus: that transition either completes its guarded OnNext before
            // this runs, or observes Disposed/_triggerDisposed under the same lock
            // and skips it — never an OnNext on a disposed Subject (VMX-001).
            lock (_gate)
            {
                if (!_triggerDisposed)
                {
                    _triggerDisposed = true;
                    _statusTrigger.OnCompleted();
                    _statusTrigger.Dispose();
                }
            }

            (_selectCommand as IDisposable)?.Dispose();
            (_deselectCommand as IDisposable)?.Dispose();
            (_selectNextCommand as IDisposable)?.Dispose();
            (_selectPreviousCommand as IDisposable)?.Dispose();
            (_reconstructCommand as IDisposable)?.Dispose();
        }
    }

    // ── Selection predicates ────────────────────────────────────────────────
    /// <inheritdoc/>
    public bool CanSelect() =>
        Parent is not null &&
        Parent.SupportsChildSelection &&
        !ReferenceEquals(Parent.CurrentChild, this) &&
        _status == ConstructionStatus.Constructed;

    /// <inheritdoc/>
    public void Select() => Parent?.SelectChild(this);

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

    /// <summary>
    /// Reads the terminal-state flag under <see cref="_gate"/> so a background
    /// completion observes a concurrently in-progress <see cref="Dispose()"/> and
    /// aborts its transition rather than resurrecting the VM (VMX-001/054).
    /// </summary>
    protected bool IsDisposed()
    {
        lock (_gate)
        {
            return _status == ConstructionStatus.Disposed;
        }
    }

    private void ClearInFlight()
    {
        lock (_gate)
        {
            _inFlight = false;
            CompleteLifecycleWaitersLocked();
        }
    }

    private void FailInFlight(Exception error)
    {
        lock (_gate)
        {
            _inFlight = false;
            foreach (var waiter in _lifecycleWaiters)
                waiter.TrySetException(error);
            _lifecycleWaiters.Clear();
        }
    }

    private void FinishInFlightFrom(Task completed)
    {
        if (completed.IsCanceled)
        {
            lock (_gate)
            {
                _inFlight = false;
                foreach (var waiter in _lifecycleWaiters)
                    waiter.TrySetCanceled();
                _lifecycleWaiters.Clear();
            }
            return;
        }

        if (completed.Exception is { } failure)
        {
            FailInFlight(failure.InnerException ?? failure);
            return;
        }

        ClearInFlight();
    }

    private Task? TakeDeferredLifecycleTask()
    {
        lock (_gate)
        {
            var task = _deferredLifecycleTask;
            _deferredLifecycleTask = null;
            return task;
        }
    }

    private void CompleteDeferredLifecycle(
        Task task,
        ConstructionStatus successStatus,
        ConstructionStatus rollbackStatus)
    {
        _ = task.ContinueWith(
            completed =>
            {
                _dispatcher.Foreground.Schedule(Unit.Default, (_, _) =>
                {
                    try
                    {
                        SetStatus(completed.Status == TaskStatus.RanToCompletion
                            ? successStatus
                            : rollbackStatus);
                    }
                    finally
                    {
                        FinishInFlightFrom(completed);
                    }
                    return Disposable.Empty;
                });
            },
            CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
    }

    private TaskCompletionSource<bool> RegisterLifecycleWaiter()
    {
        var waiter = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        lock (_gate)
        {
            _lifecycleWaiters.Add(waiter);
        }
        return waiter;
    }

    private void RemoveLifecycleWaiter(TaskCompletionSource<bool> waiter)
    {
        lock (_gate)
        {
            _lifecycleWaiters.Remove(waiter);
        }
    }

    private void CompleteWaiterIfSettled(TaskCompletionSource<bool> waiter)
    {
        lock (_gate)
        {
            if (_inFlight || !IsSettled(_status)) return;
            _lifecycleWaiters.Remove(waiter);
            waiter.TrySetResult(true);
        }
    }

    private void CompleteLifecycleWaitersLocked()
    {
        if (!IsSettled(_status) || _lifecycleWaiters.Count == 0) return;
        foreach (var waiter in _lifecycleWaiters)
            waiter.TrySetResult(true);
        _lifecycleWaiters.Clear();
    }

    private static bool IsSettled(ConstructionStatus status) =>
        status is ConstructionStatus.Constructed or
            ConstructionStatus.Destructed or
            ConstructionStatus.Disposed;

    private void SetStatus(ConstructionStatus newStatus)
    {
        // The terminal check, the _status write, the hub publish and the
        // status-trigger OnNext all run under _gate so the whole transition is
        // atomic with respect to Dispose() — a background transition racing
        // Dispose() can neither resurrect the VM, publish a post-dispose status
        // message, nor OnNext a disposed Subject (VMX-001/054; spec/02 invariant
        // 3: Disposed is terminal).
        lock (_gate)
        {
            if (_status == ConstructionStatus.Disposed) return;

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
    }

    /// <summary>
    /// Publishes one hub message followed by one local <see cref="PropertyChanged"/>
    /// event for an already-assigned, equality-gated property.
    /// </summary>
    protected void NotifyPropertyChanged(string propertyName)
    {
        lock (_gate)
        {
            if (_status == ConstructionStatus.Disposed) return;
        }

        // External observers run outside the lifecycle gate. Once admitted by
        // the terminal-state check, both channels complete even when a hub
        // observer disposes this VM re-entrantly.
        try
        {
            _hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, propertyName));
        }
        finally
        {
            RaisePropertyChanged(propertyName);
        }
    }

    /// <summary>Raises only the local <see cref="PropertyChanged"/> event.</summary>
    protected void RaisePropertyChanged(string propertyName)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

    /// <summary>Registers a disposable for terminal VM cleanup and returns it.</summary>
    protected T Own<T>(T resource) where T : IDisposable
    {
        bool disposeNow;
        lock (_gate)
        {
            disposeNow = _status == ConstructionStatus.Disposed;
            if (!disposeNow)
                _ownedResources.Add(resource);
        }
        if (disposeNow)
            TryDispose(resource);
        return resource;
    }

    /// <summary>Registers a cleanup action for terminal VM cleanup.</summary>
    protected IDisposable Own(Action cleanup) => Own(Disposable.Create(cleanup));

    private void DisposeOwnedResources()
    {
        IDisposable[] resources;
        lock (_gate)
        {
            resources = [.. _ownedResources];
            _ownedResources.Clear();
        }
        for (var index = resources.Length - 1; index >= 0; index--)
            TryDispose(resources[index]);
    }

    private static void TryDispose(IDisposable resource)
    {
        try
        {
            resource.Dispose();
        }
        catch
        {
            // Terminal cleanup is best-effort; one failure must not block the rest.
        }
    }
}
