using System.Reactive;
using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Runtime.ExceptionServices;
using System.Windows.Input;
using VMx.Commands;
using VMx.Internal;
using VMx.Messages;
using VMx.Services;

namespace VMx.Forms;

/// <summary>
/// ViewModel that wraps a mutable domain model with an edit lifecycle:
/// snapshot on construct, allow mutation, then either Approve (persist) or Deny (revert).
///
/// See spec/20-form-vm.md and ADR-0030.
/// </summary>
/// <typeparam name="TM">Domain model type. Record types are recommended for structural equality.</typeparam>
public sealed class FormVM<TM> : IDisposable
    where TM : notnull
{
    private readonly Func<TM, Task> _persister;
    private readonly Func<TM, TM> _snapshotter;
    private readonly Dictionary<string, Func<TM, string?>> _validators;
    private readonly Func<TM, IReadOnlyDictionary<string, string?>>? _modelValidator;
    private readonly Func<TM, TM>? _resetOnApproved;
    private readonly bool _strict;
    private readonly IMessageHub _hub;
    private readonly Subject<TM> _onApproved = new();
    private readonly Subject<Exception> _approveErrors = new();
    private readonly Subject<IReadOnlyDictionary<string, string>> _errorsChanged = new();
    private readonly Subject<Unit> _canExecuteChangedTrigger = new();
    private readonly object _stateGate = new();
    // The form's publication scope as one resource of the shared wait-for
    // graph (spec/20 §5.5, ADR-0176). Waits on it name a publisher thread.
    private readonly object _publicationScope = new();

    private TM _model;
    private TM _snapshot;
    private Dictionary<string, string> _errors;
    private volatile bool _disposed;
    // Single-flight approval admission (spec/20 §5.3, ADR-0143): set when an
    // approve call is admitted, cleared when that approval settles.
    private bool _approvalInFlight;
    // Publication scopes (spec/20 §5.5, ADR-0176), per thread. A thread holds
    // a scope while it delivers an update's ErrorsChanged or an approval's
    // settlement notifications. Scopes nest on one thread. Another thread's
    // SetModel, deny, approve admission, settlement and Dispose wait while
    // any other thread holds one. Each entry also keeps that thread's queue:
    // the calls of its approval's pre-publication window (ADR-0174) and other
    // threads' updates whose wait would have closed a wait-for cycle.
    private readonly Dictionary<int, Publisher> _publishers = new();
    // Threads that wait for a publication scope, so a publisher knows when it
    // must release graph edges.
    private int _scopeWaiters;
    // Advances on every enqueue, so a preparation callback that queues another
    // update makes the outer call stale (spec/20 §5.4).
    private long _queueGeneration;
    // The thread running an approval's post-persist commit (reset callback,
    // snapshotter, validators) before settlement step 1, or 0. The
    // pre-publication window opens with this commit; only one approval is in
    // flight, so at most one commit runs at a time.
    private int _commitWindowThreadId;
    // Updates, admission notifications and ApproveErrors deliveries in
    // progress. They deliver outside a scope or after it, so a Dispose on
    // another thread defers the teardown until the last of them ends.
    private int _activeMutations;
    // A Dispose deferred the teardown. It runs when no delivery is active and
    // no thread holds a publication scope.
    private bool _teardownPending;
    // Failure-atomic updates (spec/20 §5.4, ADR-0144): every commit of model,
    // snapshot, or errors advances this generation. Updates prepare and commit
    // under the re-entrant _stateGate, so other threads wait; only a callback
    // re-entering on the preparing thread can commit meanwhile, which makes the
    // outer update's prepared result stale.
    private long _commitGeneration;

    // ── Builder factory ───────────────────────────────────────────────────────

    /// <summary>
    /// Returns an empty <see cref="FormVMBuilder{TM}"/> for fluent construction.
    /// See ADR-0035 §2 FV1 / FV2.
    /// </summary>
    public static FormVMBuilder<TM> Builder() => FormVMBuilder<TM>.Empty;

    // ── Constructors ──────────────────────────────────────────────────────────

    /// <summary>
    /// Creates a <see cref="FormVM{TM}"/> with a delegate persister.
    /// </summary>
    /// <param name="initial">Initial domain model value; also becomes the initial Snapshot.</param>
    /// <param name="persister">Consumer-supplied async persist delegate. Throw on failure.</param>
    /// <param name="hub">Message hub for DenyCommand hub messages. Defaults to <see cref="NullMessageHub.Instance"/>.</param>
    /// <param name="strict">
    /// When <c>true</c>, <see cref="ApproveCommand"/>.<c>CanExecute</c> returns <c>false</c> when
    /// <see cref="IsDirty"/> is <c>false</c>. Defaults to <c>false</c>.
    /// </param>
    /// <param name="snapshotter">
    /// Custom snapshot function. Defaults to a deep clone via a
    /// <see cref="System.Text.Json"/> round-trip (so a nested-object mutation is
    /// tracked by <see cref="IsDirty"/> and reverted by <see cref="DenyCommand"/>).
    /// Inject this as the escape hatch for models JSON cannot round-trip.
    /// </param>
    /// <param name="validators">Optional field validators keyed by field/property name.</param>
    /// <param name="modelValidator">Optional model-level validator returning field-name errors.</param>
    /// <param name="resetOnApproved">Optional post-persist callback that derives the next pristine model.</param>
    public FormVM(
        TM initial,
        Func<TM, Task> persister,
        IMessageHub? hub = null,
        bool strict = false,
        Func<TM, TM>? snapshotter = null,
        IReadOnlyDictionary<string, Func<TM, string?>>? validators = null,
        Func<TM, IReadOnlyDictionary<string, string?>>? modelValidator = null,
        Func<TM, TM>? resetOnApproved = null)
    {
        ThrowHelper.ThrowIfNull(initial, nameof(initial));
        ThrowHelper.ThrowIfNull(persister, nameof(persister));

        _persister = persister;
        _hub = hub ?? NullMessageHub.Instance;
        _strict = strict;
        _snapshotter = snapshotter ?? DefaultSnapshotter;
        _validators = CopyValidators(validators);
        _modelValidator = modelValidator;
        _resetOnApproved = resetOnApproved;

        // Construction runs the same preparation as an update (spec/20 §5.4):
        // a failing snapshotter or validator fails construction.
        var snapshot = _snapshotter(initial);
        var errors = Validate(initial);
        _model = initial;
        _snapshot = snapshot;
        _errors = errors;

        IObservable<Unit> canExecuteTrigger = _canExecuteChangedTrigger;

        DenyCommand = RelayCommand.Builder()
            .Task(Deny)
            .Build();

        ApproveCommand = RelayCommand.Builder()
            .Task(ApproveCommandExecute)
            .Predicate(CanApprove)
            .Triggers(canExecuteTrigger)
            .Build();
    }

    // Approval is disabled while invalid, while strict and pristine, and while
    // another approval is in flight (spec/20 §5, §5.3, §9).
    private bool CanApprove()
    {
        lock (_stateGate)
            return !_approvalInFlight && _errors.Count == 0 && (!_strict || !Equals(_model, _snapshot));
    }

    // Fire-and-forget command entry-point. ApproveCommand.Execute() is void, so a
    // persister failure cannot propagate to the caller; route the faulted Task to
    // the ApproveErrors channel instead of discarding it (a discarded faulted Task
    // would otherwise surface only as an UnobservedTaskException at GC) (VMX-008).
    // Await ApproveAsync() to observe the failure inline.
    private void ApproveCommandExecute()
    {
        _ = ApproveInternalAsync().ContinueWith(
            t =>
            {
                // A cancelled persister is a non-success outcome too (spec/20
                // §5.3); a cancelled Task carries no Exception, so report one.
                EmitApproveError(t.IsCanceled
                    ? new TaskCanceledException(t)
                    : t.Exception!.GetBaseException());
            },
            CancellationToken.None,
            TaskContinuationOptions.NotOnRanToCompletion | TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
    }

    /// <summary>
    /// Creates a <see cref="FormVM{TM}"/> with an <see cref="IFormPersister{TM}"/> interface collaborator.
    /// </summary>
    public FormVM(
        TM initial,
        IFormPersister<TM> persister,
        IMessageHub? hub = null,
        bool strict = false,
        Func<TM, TM>? snapshotter = null,
        IReadOnlyDictionary<string, Func<TM, string?>>? validators = null,
        Func<TM, IReadOnlyDictionary<string, string?>>? modelValidator = null,
        Func<TM, TM>? resetOnApproved = null)
        : this(
            initial,
            persister is null ? throw new ArgumentNullException(nameof(persister)) : (Func<TM, Task>)(model => persister.PersistAsync(model)),
            hub,
            strict,
            snapshotter,
            validators,
            modelValidator,
            resetOnApproved)
    {
    }

    // ── Properties ────────────────────────────────────────────────────────────

    /// <summary>Live, editable model. Set via <see cref="SetModel"/> to mutate.</summary>
    public TM Model { get { lock (_stateGate) return _model; } }

    /// <summary>Read-only snapshot captured at construction (updated after a successful Approve).</summary>
    public TM Snapshot { get { lock (_stateGate) return _snapshot; } }

    /// <summary>
    /// <c>true</c> when <see cref="Model"/> is structurally not equal to <see cref="Snapshot"/>.
    /// Uses <see cref="object.Equals(object?, object?)"/>; record types provide structural equality.
    /// </summary>
    public bool IsDirty { get { lock (_stateGate) return !Equals(_model, _snapshot); } }

    /// <summary>Current validation errors keyed by field/property name.</summary>
    public IReadOnlyDictionary<string, string> Errors
    {
        get { lock (_stateGate) return new Dictionary<string, string>(_errors); }
    }

    /// <summary><c>true</c> when the current model has no validation errors.</summary>
    public bool IsValid { get { lock (_stateGate) return _errors.Count == 0; } }

    /// <summary>
    /// Reverts <see cref="Model"/> to <see cref="Snapshot"/> and publishes
    /// <see cref="FormRevertedMessage"/> + <see cref="PropertyChangedMessage{TSender}"/> on the hub.
    /// </summary>
    public ICommand DenyCommand { get; }

    /// <summary>
    /// Invokes the persister delegate; on success advances <see cref="Snapshot"/> and fires <see cref="OnApproved"/>.
    /// On failure, no state mutation occurs. <see cref="ApproveAsync"/> rethrows the
    /// persister exception; <c>ApproveCommand.Execute()</c> routes it to
    /// <see cref="ApproveErrors"/> (FORM-015, chapter 20 §8.2).
    /// In strict mode, <c>CanExecute</c> is <c>false</c> when <see cref="IsDirty"/> is <c>false</c>.
    /// One approval runs at a time: <c>CanExecute</c> is <c>false</c> while an approval
    /// is in flight, and <c>CanExecuteChanged</c> fires once when an approval is
    /// admitted and once when it settles (chapter 20 §5.3).
    /// </summary>
    public ICommand ApproveCommand { get; }

    /// <summary>
    /// Observable that emits the persisted model value after each successful persist.
    /// </summary>
    public IObservable<TM> OnApproved => _onApproved.AsObservable();

    /// <summary>
    /// Observable that surfaces the persister exception when the approve
    /// <em>command</em> (<c>ApproveCommand.Execute()</c>) fails. That path is
    /// fire-and-forget (<see cref="ICommand.Execute"/> is <c>void</c>), so the
    /// failure cannot propagate to the caller; it is emitted here instead of
    /// being discarded with the faulted <see cref="Task"/> (VMX-008). The
    /// awaitable <see cref="ApproveAsync"/> path keeps its throw behavior — await
    /// it directly to handle the error inline. Completes on <see cref="Dispose"/>.
    /// </summary>
    public IObservable<Exception> ApproveErrors => _approveErrors.AsObservable();

    /// <summary>Observable that emits when the effective validation error map changes.</summary>
    public IObservable<IReadOnlyDictionary<string, string>> ErrorsChanged => _errorsChanged.AsObservable();

    /// <summary>Returns the current validation error for a field, if any.</summary>
    public string? FieldError(string field)
    {
        lock (_stateGate)
            return _errors.TryGetValue(field, out var error) ? error : null;
    }

    /// <summary>
    /// Awaitable entry-point to the approve flow. Invokes the persister, advances
    /// <see cref="Snapshot"/> on success, and fires <see cref="OnApproved"/>.
    /// Throws when the persister throws (no state mutation occurs on failure).
    /// Use this in tests and orchestrators that need to await the full cycle.
    /// A call made while the form is invalid, disposed, or already approving
    /// completes without invoking the persister (chapter 20 §5.3); await the
    /// in-flight call and approve again to save after it.
    /// </summary>
    public Task ApproveAsync() => ApproveInternalAsync();

    // ── Public mutation ───────────────────────────────────────────────────────

    /// <summary>
    /// Replaces the current <see cref="Model"/>. Updating the model may change <see cref="IsDirty"/>;
    /// in strict mode it also fires <see cref="ICommand.CanExecuteChanged"/> on <see cref="ApproveCommand"/>.
    /// The update is failure-atomic (chapter 20 §5.4): the model's equality and the
    /// validators run before anything is committed, so an exception they throw
    /// propagates to the caller with the form unchanged and nothing published.
    /// A call that the approving thread makes from the post-persist commit or a
    /// settlement observer is prepared, then queued, and replays after the
    /// <see cref="OnApproved"/> delivery returns (chapter 20 §5.3, ADR-0174).
    /// A call from another thread waits while a thread publishes the form's
    /// notifications. When that wait would close a wait-for cycle, the call is
    /// prepared, queued on the publishing thread, and returns before it takes
    /// effect (chapter 20 §5.5, ADR-0176).
    /// </summary>
    public void SetModel(TM model)
    {
        // Inert after Dispose (like ApproveAsync/Deny): a post-dispose call would
        // otherwise emit on disposed validation subjects and throw
        // ObjectDisposedException (parity with the TS/Swift no-op).
        var caller = Environment.CurrentManagedThreadId;
        var admitted = false;
        var retry = false;
        QueuedUpdate[] replay = [];
        ExceptionDispatchInfo? failure = null;
        try
        {
            ApplySetModel(model, caller, ref admitted, ref retry, ref replay);
        }
        catch (Exception error)
        {
            failure = ExceptionDispatchInfo.Capture(error);
        }
        FinishUpdate(admitted, failure, replay);
        if (retry) SetModel(model);
    }

    private void ApplySetModel(
        TM model, int caller, ref bool admitted, ref bool retry, ref QueuedUpdate[] replay)
    {
        bool canExecuteChanged;
        Dictionary<string, string>? publishedErrors = null;
        var outerPrePublishing = false;
        lock (_stateGate)
        {
            var publisher = WaitForForeignScopes(caller);
            if (_disposed) return;
            // Reject a null model before any deferral, so the caller sees
            // the error (failure-atomic).
            ThrowHelper.ThrowIfNull(model, nameof(model));
            var queue = publisher != 0 || InPrePublicationWindow(caller);
            _activeMutations++;
            admitted = true;

            // Preparation (spec/20 §5.2, §5.4) runs every consumer callback
            // and changes no form state, so a callback failure propagates
            // with nothing committed or published, and a callback reading
            // the form sees the previous state. A call inside the approval's
            // pre-publication window, or one whose wait was refused, runs the
            // full preparation and is then queued (§5.3, §5.5): equality never
            // skips the enqueue, because earlier queued calls can change the
            // live model before this one replays.
            var generation = _commitGeneration;
            var queueGeneration = _queueGeneration;
            var live = _model;
            var snapshot = _snapshot;
            var errors = _errors;
            if (Equals(live, model) && !queue) return;
            var wasDirty = !Equals(live, snapshot);
            var nextErrors = Validate(model);
            var isDirty = !Equals(model, snapshot);

            // A callback re-entered on this thread and disposed the form or
            // made another update (committed or queued): the prepared
            // result is stale, and the newest update stands.
            if (IsStale(generation, queueGeneration)) return;
            if (queue)
            {
                retry = !TryEnqueueLocked(publisher, caller, QueuedUpdate.Set(model));
                return;
            }

            // Commit in one step, before any notification.
            canExecuteChanged = (_strict && isDirty != wasDirty) ||
                (nextErrors.Count == 0) != (errors.Count == 0);
            _model = model;
            _errors = nextErrors;
            _commitGeneration++;
            // Update scope (spec/20 §5.5): the error map is delivered without
            // the state lock, while other threads' form calls wait, so error
            // maps reach observers in commit order.
            if (!SameErrors(nextErrors, errors))
            {
                publishedErrors = new Dictionary<string, string>(nextErrors);
                outerPrePublishing = EnterScopeLocked(caller);
            }
        }

        if (publishedErrors is not null)
        {
            // The teardown claim cannot succeed here: this update still
            // counts in _activeMutations, so its EndMutation runs a deferred
            // teardown. Keep the update inside that count.
            try { _errorsChanged.OnNext(publishedErrors); }
            finally { replay = ExitScope(caller, outerPrePublishing, out _); }
        }
        if (canExecuteChanged)
            _canExecuteChangedTrigger.OnNext(Unit.Default);
        _hub.Send(PropertyChangedMessage<FormVM<TM>>.Create(
            this,
            nameof(FormVM<TM>),
            nameof(Model)));
    }

    // Ends an update (spec/20 §5.5): the queue its outermost scope took
    // replays after its last notification and before it returns. Each item
    // replays in isolation. The update's own failure wins over a replay
    // failure, which wins over a deferred teardown failure.
    private void FinishUpdate(bool admitted, ExceptionDispatchInfo? failure, QueuedUpdate[] replay)
    {
        var replayFailure = Replay(replay);
        failure ??= replayFailure;
        if (admitted) EndMutation(mutationFailed: failure is not null);
        failure?.Throw();
    }

    // ── IDisposable ───────────────────────────────────────────────────────────

    /// <summary>
    /// Completes the <see cref="OnApproved"/> observable and disposes resources.
    /// While another thread publishes the form's notifications, this waits for
    /// it. When that wait would close a wait-for cycle, it marks the form
    /// disposed and returns; the publishing thread completes the teardown when
    /// its publication ends (chapter 20 §5.5, ADR-0176).
    /// </summary>
    public void Dispose()
    {
        var caller = Environment.CurrentManagedThreadId;
        var tearDown = false;
        lock (_stateGate)
        {
            var publisher = WaitForForeignScopes(caller);
            if (_disposed) return;
            _disposed = true;
            // A refused wait leaves the teardown to the publisher, after its
            // outermost scope ends. A delivery in progress outside a scope
            // defers it to that delivery's end.
            if (publisher == 0 && _activeMutations == 0)
                tearDown = true;
            else
                _teardownPending = true;
            // No waiter waits for a scope of a disposed form, so every edge on
            // it goes before the waiters wake.
            if (_scopeWaiters > 0) WaitForGraph.Shared.ReleaseWaiters(_publicationScope);
            Monitor.PulseAll(_stateGate);
        }
        if (tearDown) TearDown();
    }

    // A teardown deferred by Dispose runs when the last active delivery ends
    // and no thread holds a scope. If that delivery is already throwing, its
    // exception wins: the teardown still runs every step, but its own failure
    // is not rethrown over it.
    private void EndMutation(bool mutationFailed)
    {
        bool tearDown;
        lock (_stateGate)
        {
            _activeMutations--;
            tearDown = ClaimTeardownLocked();
        }
        if (tearDown) TearDown(rethrowFailure: !mutationFailed);
    }

    // Called under _stateGate.
    private bool ClaimTeardownLocked()
    {
        if (!_teardownPending || _activeMutations != 0) return false;
        foreach (var publisher in _publishers.Values)
            if (publisher.Depth > 0) return false;
        _teardownPending = false;
        return true;
    }

    private void TearDown(bool rethrowFailure = true)
    {
        var firstError = TearDownSteps();
        if (rethrowFailure) firstError?.Throw();
    }

    private ExceptionDispatchInfo? TearDownSteps()
    {
        // Best-effort terminal teardown (mirrors ComponentVMBase.Dispose): a
        // throwing OnCompleted observer must not abort the rest and leak the
        // remaining subjects or the two commands' live trigger subscriptions.
        // Capture the first failure and run every step.
        ExceptionDispatchInfo? firstError = null;
        FirstFailure.Capture(ref firstError, _approveErrors.OnCompleted);
        FirstFailure.Capture(ref firstError, _approveErrors.Dispose);
        FirstFailure.Capture(ref firstError, _onApproved.OnCompleted);
        FirstFailure.Capture(ref firstError, _onApproved.Dispose);
        FirstFailure.Capture(ref firstError, _errorsChanged.OnCompleted);
        FirstFailure.Capture(ref firstError, _errorsChanged.Dispose);
        FirstFailure.Capture(ref firstError, _canExecuteChangedTrigger.OnCompleted);
        FirstFailure.Capture(ref firstError, _canExecuteChangedTrigger.Dispose);
        if (DenyCommand is IDisposable d1)
            FirstFailure.Capture(ref firstError, d1.Dispose);
        if (ApproveCommand is IDisposable d2)
            FirstFailure.Capture(ref firstError, d2.Dispose);
        return firstError;
    }

    // ApproveErrors is delivered without a lock and opens no scope (spec/20
    // §5.5). A Dispose during the delivery defers the teardown to its end.
    private void EmitApproveError(Exception error)
    {
        lock (_stateGate)
        {
            if (_disposed) return;
            _activeMutations++;
        }
        var failed = false;
        try
        {
            _approveErrors.OnNext(error);
        }
        catch
        {
            failed = true;
            throw;
        }
        finally
        {
            EndMutation(failed);
        }
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    private void Deny()
    {
        var caller = Environment.CurrentManagedThreadId;
        var admitted = false;
        var retry = false;
        QueuedUpdate[] replay = [];
        ExceptionDispatchInfo? failure = null;
        try
        {
            ApplyDeny(caller, ref admitted, ref retry, ref replay);
        }
        catch (Exception error)
        {
            failure = ExceptionDispatchInfo.Capture(error);
        }
        FinishUpdate(admitted, failure, replay);
        if (retry) Deny();
    }

    private void ApplyDeny(int caller, ref bool admitted, ref bool retry, ref QueuedUpdate[] replay)
    {
        bool canExecuteChanged;
        Dictionary<string, string>? publishedErrors = null;
        var outerPrePublishing = false;
        lock (_stateGate)
        {
            var publisher = WaitForForeignScopes(caller);
            if (_disposed) return;
            var queue = publisher != 0 || InPrePublicationWindow(caller);
            _activeMutations++;
            admitted = true;

            // Preparation (spec/20 §5.4): the equality, snapshotter, and
            // validator callbacks change no form state, so a failure
            // propagates from DenyCommand.Execute() with nothing reverted
            // or published. Inside the approval's pre-publication window, or
            // after a refused wait, the prepared revert is discarded and the
            // deny is queued (§5.3, §5.5).
            var generation = _commitGeneration;
            var queueGeneration = _queueGeneration;
            var live = _model;
            var snapshot = _snapshot;
            var errors = _errors;
            var wasDirty = !Equals(live, snapshot);
            var nextModel = _snapshotter(snapshot);
            var nextErrors = Validate(nextModel);
            var isDirty = !Equals(nextModel, snapshot);

            // Same-thread re-entry disposed the form or made another update
            // (committed or queued): the prepared revert is stale.
            if (IsStale(generation, queueGeneration)) return;
            if (queue)
            {
                retry = !TryEnqueueLocked(publisher, caller, QueuedUpdate.Deny);
                return;
            }

            _model = nextModel;
            _errors = nextErrors;
            _commitGeneration++;
            canExecuteChanged = (_strict && wasDirty != isDirty) ||
                (nextErrors.Count == 0) != (errors.Count == 0);
            if (!SameErrors(nextErrors, errors))
            {
                publishedErrors = new Dictionary<string, string>(nextErrors);
                outerPrePublishing = EnterScopeLocked(caller);
            }
        }

        if (publishedErrors is not null)
        {
            // The teardown claim cannot succeed here: this update still
            // counts in _activeMutations, so its EndMutation runs a deferred
            // teardown. Keep the update inside that count.
            try { _errorsChanged.OnNext(publishedErrors); }
            finally { replay = ExitScope(caller, outerPrePublishing, out _); }
        }
        _hub.Send(new FormRevertedMessage(this, nameof(FormVM<TM>)));
        _hub.Send(PropertyChangedMessage<FormVM<TM>>.Create(this, nameof(FormVM<TM>), nameof(Model)));
        if (canExecuteChanged)
            _canExecuteChangedTrigger.OnNext(Unit.Default);
    }

    // Approval runs single-flight (spec/20 §5.3, ADR-0143). Admission and the
    // in-flight mark are one critical section; the mark is cleared before any
    // settlement notification, so a settlement observer may approve again. No
    // lock is held while the persister runs or while observers are notified.
    //
    // A queued update that fails when it replays does not fail the settled
    // approval in place (spec/20 §5.3, ADR-0174): every replay still runs, and
    // the first replay failure is raised after them through this approval's
    // own failure route (the awaiter, or ApproveErrors once on the command
    // path). A failure the approval already carries wins, and the replay
    // failures are discarded.
    private async Task ApproveInternalAsync()
    {
        var replayFailure = new FirstReplayFailure();
        await ApproveCoreAsync(replayFailure).ConfigureAwait(false);
        replayFailure.Error?.Throw();
    }

    private async Task ApproveCoreAsync(FirstReplayFailure replayFailure)
    {
        // Admission. A disposed, invalid, or already-approving form refuses the
        // call: the persister is not invoked and nothing is emitted (the
        // disposed guard is symmetric with Deny). Admission waits for another
        // thread's publication scope; a wait that would close a wait-for cycle
        // admits the call without waiting (spec/20 §5.5).
        var caller = Environment.CurrentManagedThreadId;
        TM current;
        lock (_stateGate)
        {
            _ = WaitForForeignScopes(caller);
            if (_disposed || _errors.Count != 0 || _approvalInFlight) return;
            _approvalInFlight = true;
            current = _model;
            // The admission notification opens no scope (spec/20 §5.5), so a
            // Dispose on another thread defers its teardown until it returns.
            _activeMutations++;
        }

        var admissionFailed = false;
        try
        {
            _canExecuteChangedTrigger.OnNext(Unit.Default);
        }
        catch
        {
            // A throwing admission observer abandons this approval before the
            // persister runs; release the mark so the form is not left busy,
            // and tell observers that saw the admission edge (#732). The
            // original failure wins over one from the release notification.
            admissionFailed = true;
            lock (_stateGate)
                _approvalInFlight = false;
            try { _canExecuteChangedTrigger.OnNext(Unit.Default); }
            catch { /* The admission failure is the one the caller sees. */ }
            throw;
        }
        finally
        {
            EndMutation(admissionFailed);
        }

        // An admission observer may have disposed the form; a disposed form
        // never invokes the persister.
        if (_disposed) return;

        try
        {
            // May throw — intentional. No state mutation if this throws.
            await _persister(current).ConfigureAwait(false);
        }
        catch
        {
            SettleFailedApproval();
            throw;
        }

        // Dispose() may have run during the await. It suppresses settlement:
        // the subjects are completed and disposed, and emitting would throw
        // inside an unobserved task.
        if (_disposed) return;

        // The pre-publication window opens with the post-persist commit
        // (spec/20 §5.3, ADR-0174): a SetModel or deny that the reset callback,
        // the snapshotter, or a validator makes on this thread is queued, not
        // committed, so it publishes nothing while the commit runs and the
        // reset cannot overwrite it.
        caller = Environment.CurrentManagedThreadId;
        lock (_stateGate)
            _commitWindowThreadId = caller;

        // Success: either atomically install the configured pristine reset
        // state, or preserve the legacy snapshot-advance behavior.
        TM? nextModel = default;
        TM nextSnapshot;
        Dictionary<string, string>? nextErrors = null;
        try
        {
            if (_resetOnApproved is not null)
            {
                // Prepare everything before assigning any field. A reset or
                // snapshotter failure therefore leaves local state untouched
                // even though persistence has already succeeded.
                var reset = _resetOnApproved(current);
                nextModel = _snapshotter(reset);
                nextSnapshot = _snapshotter(reset);
                nextErrors = Validate(nextModel);
            }
            else
            {
                nextSnapshot = _snapshotter(current);
            }
        }
        catch
        {
            // The window ends with the commit failure. The calls it already
            // queued replay after the failed settlement's CanExecuteChanged,
            // and the commit failure wins over theirs.
            CloseCommitWindow();
            SettleFailedApproval();
            throw;
        }

        var errorsChanged = false;
        IReadOnlyDictionary<string, string>? publishedErrors = null;
        bool outerPrePublishing;
        lock (_stateGate)
        {
            // A settlement waits for another thread's scope. A wait that would
            // close a wait-for cycle commits at once and opens a second scope
            // (spec/20 §5.5).
            _ = WaitForForeignScopes(caller);
            _commitWindowThreadId = 0;
            if (_disposed)
            {
                // Disposal suppresses settlement; a queued call would replay
                // as a no-op on the disposed form.
                ClearQueueLocked(caller);
                return;
            }
            // Settlement step 1: the commit and clearing the mark are atomic.
            // The commit is authoritative (§5.1, §5.3). An update whose callback
            // started this approval re-entrantly is now stale (§5.4).
            _approvalInFlight = false;
            _commitGeneration++;
            outerPrePublishing = EnterScopeLocked(caller);
            _publishers[caller].PrePublishing = true;
            if (_resetOnApproved is not null)
            {
                _model = nextModel!;
                _snapshot = nextSnapshot;
                if (!SameErrors(nextErrors!, _errors))
                {
                    _errors = nextErrors!;
                    errorsChanged = true;
                    publishedErrors = new Dictionary<string, string>(_errors);
                }
            }
            else
            {
                _snapshot = nextSnapshot;
            }
        }

        try
        {
            // Settlement steps 2-4: ErrorsChanged when the commit changed the
            // error map, exactly one CanExecuteChanged (it also carries any
            // strict/validity change), then the outcome. A disposing observer
            // stops the remaining notifications. A nested approval admitted
            // here suspends this window while it delivers OnApproved (§5.5).
            if (errorsChanged)
                _errorsChanged.OnNext(publishedErrors!);
            if (!_disposed)
                _canExecuteChangedTrigger.OnNext(Unit.Default);
            if (!_disposed)
            {
                lock (_stateGate)
                    _publishers[caller].PrePublishing = false;
                _onApproved.OnNext(current);
            }
        }
        finally
        {
            // The queued updates replay here, after the OnApproved delivery
            // returns. A settlement observer failure propagates past this
            // block and wins over a replay failure.
            var queued = ExitScope(caller, outerPrePublishing, out var tearDown);
            replayFailure.Record(Replay(queued));
            if (tearDown) replayFailure.Record(TearDownSteps());
        }
    }

    // Ends a post-persist commit that failed before settlement step 1.
    private void CloseCommitWindow()
    {
        lock (_stateGate)
            _commitWindowThreadId = 0;
    }

    // Settles an approval whose persister failed or was cancelled, or whose
    // reset transaction failed: clear the mark, then raise CanExecuteChanged
    // once inside a settlement scope. The caller routes the failure to its one
    // channel (the awaiter, or ApproveErrors on the command path). Disposal
    // suppresses settlement.
    private void SettleFailedApproval()
    {
        var caller = Environment.CurrentManagedThreadId;
        bool outerPrePublishing;
        lock (_stateGate)
        {
            _ = WaitForForeignScopes(caller);
            if (_disposed)
            {
                ClearQueueLocked(caller);
                return;
            }
            _approvalInFlight = false;
            outerPrePublishing = EnterScopeLocked(caller);
        }

        try
        {
            _canExecuteChangedTrigger.OnNext(Unit.Default);
        }
        catch (Exception)
        {
            // The caller rethrows the approval failure next. That failure is
            // the first error and wins: an observer that throws from this
            // notification must not replace it (§5.3 step 4, FORM-033).
        }
        finally
        {
            // Calls a failed post-persist commit queued replay here, before
            // the caller routes the failure. That failure wins, so a replay
            // or deferred teardown failure is discarded (spec/20 §5.3,
            // ADR-0174).
            var queued = ExitScope(caller, outerPrePublishing, out var tearDown);
            _ = Replay(queued);
            if (tearDown) _ = TearDownSteps();
        }
    }

    // Called under _stateGate. Waits while another thread holds a publication
    // scope (spec/20 §5.5, ADR-0176). Each pass records an edge to one
    // publisher in the shared wait-for graph, so a cycle through any mix of
    // form, hub, lifecycle, membership and ownership waits is visible.
    // Returns 0 once no other thread holds a scope or the form is disposed.
    // Returns the publisher's thread when the wait would close a live cycle;
    // the caller then takes its §5.5 result instead of waiting. The caller's
    // own scopes never block it.
    private int WaitForForeignScopes(int caller)
    {
        var waiting = false;
        try
        {
            while (!_disposed)
            {
                var owner = ForeignPublisherLocked(caller);
                if (owner == 0) return 0;
                if (!WaitForGraph.Shared.TryBeginWait(_publicationScope, owner, caller)) return owner;
                if (!waiting)
                {
                    waiting = true;
                    _scopeWaiters++;
                }
                Monitor.Wait(_stateGate);
            }
            return 0;
        }
        finally
        {
            if (waiting)
            {
                WaitForGraph.Shared.EndWait(caller);
                _scopeWaiters--;
            }
        }
    }

    // Called under _stateGate.
    private int ForeignPublisherLocked(int caller)
    {
        foreach (var entry in _publishers)
            if (entry.Key != caller && entry.Value.Depth > 0) return entry.Key;
        return 0;
    }

    // Called under _stateGate after WaitForForeignScopes. A caller inside its
    // own thread's pre-publication window (spec/20 §5.3): the post-persist
    // commit, or settlement steps 2 and 3 of its innermost scope.
    private bool InPrePublicationWindow(int caller) =>
        (_publishers.TryGetValue(caller, out var publisher) && publisher.Depth > 0 && publisher.PrePublishing) ||
        _commitWindowThreadId == caller;

    // Called under _stateGate after a preparation.
    private bool IsStale(long generation, long queueGeneration) =>
        _disposed || _commitGeneration != generation || _queueGeneration != queueGeneration;

    // Called under _stateGate. Queues a prepared update on the caller's own
    // queue (publisher 0) or on the queue of the publisher whose scope its
    // wait was refused for (spec/20 §5.5). Returns false when that publisher
    // released its scope while a preparation callback waited: the caller then
    // runs again as a new call.
    private bool TryEnqueueLocked(int publisher, int caller, QueuedUpdate update)
    {
        Publisher? target;
        if (publisher == 0)
        {
            if (!_publishers.TryGetValue(caller, out target))
                _publishers[caller] = target = new Publisher();
        }
        else if (!_publishers.TryGetValue(publisher, out target) || target.Depth == 0)
        {
            return false;
        }
        target.Queue.Add(update);
        _queueGeneration++;
        return true;
    }

    // Called under _stateGate. Drops the caller's queue after a disposal
    // suppressed its settlement; each queued call would replay as a no-op.
    private void ClearQueueLocked(int caller)
    {
        if (!_publishers.TryGetValue(caller, out var publisher)) return;
        publisher.Queue.Clear();
        if (publisher.Depth == 0) _publishers.Remove(caller);
    }

    // Called under _stateGate after WaitForForeignScopes. Opens a scope on the
    // caller's thread and returns the enclosing scope's pre-publishing flag
    // for ExitScope.
    private bool EnterScopeLocked(int caller)
    {
        if (!_publishers.TryGetValue(caller, out var publisher))
            _publishers[caller] = publisher = new Publisher();
        publisher.Depth++;
        return publisher.PrePublishing;
    }

    // Closes a scope on the caller's thread. The outermost exit removes the
    // graph edges that name this thread, wakes the waiting threads, and
    // returns this thread's queue for the caller to replay (spec/20 §5.3 and
    // §5.5, ADR-0174, ADR-0176). It also claims a teardown that a refused
    // Dispose left to this publisher.
    private QueuedUpdate[] ExitScope(int caller, bool outerPrePublishing, out bool tearDown)
    {
        lock (_stateGate)
        {
            tearDown = false;
            var publisher = _publishers[caller];
            publisher.PrePublishing = outerPrePublishing;
            if (--publisher.Depth > 0) return [];
            QueuedUpdate[] queued = [.. publisher.Queue];
            _publishers.Remove(caller);
            if (_scopeWaiters > 0)
                WaitForGraph.Shared.ReleaseWaiters(_publicationScope, moreOwners: ScopeHoldersLocked());
            Monitor.PulseAll(_stateGate);
            tearDown = ClaimTeardownLocked();
            return queued;
        }
    }

    // Called under _stateGate: the threads that still hold a scope, for the
    // edges that must survive a wake.
    private Dictionary<int, int> ScopeHoldersLocked()
    {
        var holders = new Dictionary<int, int>();
        foreach (var entry in _publishers)
            if (entry.Value.Depth > 0) holders[entry.Key] = entry.Value.Depth;
        return holders;
    }

    // Replays, in call order, the updates taken from a publisher's queue.
    // Each replay is a new call that prepares again against the state at
    // replay time, and runs in isolation: a failure does not stop the later
    // replays. The first failure is returned for the caller to route.
    private ExceptionDispatchInfo? Replay(QueuedUpdate[] queued)
    {
        ExceptionDispatchInfo? firstFailure = null;
        foreach (var update in queued)
        {
            if (update.IsDeny)
                FirstFailure.Capture(ref firstFailure, Deny);
            else
                FirstFailure.Capture(ref firstFailure, () => SetModel(update.Model));
        }

        return firstFailure;
    }

    // One thread's publication state: its open scopes, whether its innermost
    // settlement is in its pre-publication window, and its queue.
    private sealed class Publisher
    {
        public int Depth { get; set; }

        public bool PrePublishing { get; set; }

        public List<QueuedUpdate> Queue { get; } = [];
    }

    // A queued SetModel candidate or a queued deny.
    private readonly struct QueuedUpdate
    {
        private QueuedUpdate(bool isDeny, TM model)
        {
            IsDeny = isDeny;
            Model = model;
        }

        public bool IsDeny { get; }

        public TM Model { get; }

        public static QueuedUpdate Deny => new(true, default!);

        public static QueuedUpdate Set(TM model) => new(false, model);
    }

    // The first replay failure of one approval call.
    private sealed class FirstReplayFailure
    {
        public ExceptionDispatchInfo? Error { get; private set; }

        public void Record(ExceptionDispatchInfo? failure) => Error ??= failure;
    }

    // Cached per closed generic (one instance per TM): System.Text.Json caches
    // serialization metadata against the options instance, so reusing a single
    // instance avoids a per-call metadata rebuild (and CA1869).
    private static readonly System.Text.Json.JsonSerializerOptions DefaultSnapshotJsonOptions =
        new() { IncludeFields = true };

    /// <summary>
    /// Default deep-clone snapshotter: a <see cref="System.Text.Json"/> serialize→deserialize
    /// round-trip. A deep clone is required so the snapshot does not share nested
    /// mutable state with the live model — otherwise an in-place mutation of a
    /// nested object would be invisible to <see cref="IsDirty"/> and could not be
    /// reverted by <see cref="DenyCommand"/> (VMX-064). <c>System.Text.Json</c> is
    /// in the BCL, so no extra package is taken.
    /// <para>
    /// For models JSON cannot round-trip (delegates, cyclic graphs, non-public or
    /// non-default-constructible members, live handles, …) inject a custom
    /// <c>snapshotter</c> via the constructor or builder — that hook is the
    /// documented escape hatch and always overrides this default.
    /// </para>
    /// </summary>
    private static TM DefaultSnapshotter(TM model)
    {
        var json = System.Text.Json.JsonSerializer.Serialize(model, DefaultSnapshotJsonOptions);
        return System.Text.Json.JsonSerializer.Deserialize<TM>(json, DefaultSnapshotJsonOptions)!;
    }

    private Dictionary<string, string> Validate(TM model)
    {
        var errors = new Dictionary<string, string>();
        foreach (var kvp in _validators)
        {
            var error = kvp.Value(model);
            if (error is not null)
                errors[kvp.Key] = error;
        }

        if (_modelValidator is not null)
        {
            foreach (var kvp in _modelValidator(model))
            {
                if (kvp.Value is null)
                    errors.Remove(kvp.Key);
                else
                    errors[kvp.Key] = kvp.Value;
            }
        }

        return errors;
    }

    private static bool SameErrors(
        Dictionary<string, string> left,
        Dictionary<string, string> right)
    {
        if (left.Count != right.Count) return false;
        foreach (var kvp in left)
        {
            if (!right.TryGetValue(kvp.Key, out var other) || other != kvp.Value)
                return false;
        }

        return true;
    }

    private static Dictionary<string, Func<TM, string?>> CopyValidators(
        IReadOnlyDictionary<string, Func<TM, string?>>? validators)
    {
        var copy = new Dictionary<string, Func<TM, string?>>();
        if (validators is null) return copy;
        foreach (var kvp in validators)
            copy[kvp.Key] = kvp.Value;
        return copy;
    }
}
