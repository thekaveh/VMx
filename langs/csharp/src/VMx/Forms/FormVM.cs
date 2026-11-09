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
/// <typeparam name="TM">
/// Domain model type. Record types are recommended for structural equality, but a
/// record's synthesized equality compares a collection field by reference. Under the
/// default snapshotter such a form is dirty at once, so override <c>Equals</c> and
/// <c>GetHashCode</c> to compare the collection element by element.
/// </typeparam>
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
    // ApproveCommand, kept typed so the form raises CanExecuteChanged through
    // the call-fed RaiseCanExecuteChanged: a failing observer still reaches
    // the form's caller after every observer has run (spec/03 §3.6 rule 5,
    // spec/20 §5.3, ADR-0191). A trigger would discard that failure.
    private readonly RelayCommand _approveCommand;
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
    // snapshot, or errors advances this generation. Updates prepare with no
    // lock held (ADR-0215), so another thread may commit meanwhile; the
    // overtaken update then runs again as a new call.
    private long _commitGeneration;
    // Update frames (spec/20 §5.4, ADR-0180, ADR-0215), per thread. A thread
    // has a frame while it prepares a SetModel or deny. A call nested in a
    // frame queues its notifications in the frame, and the outermost frame
    // sends them. The frame also counts the commits and enqueues its thread
    // makes, so a preparation callback that commits or queues another update
    // makes the outer call stale.
    private readonly Dictionary<int, UpdateFrame> _frames = new();
    // The threads that send an update's error maps in Deliver. An update or
    // approval admission made from such an ErrorsChanged observer is nested
    // too: it queues its notifications in that thread's _scopedNotices entry.
    // Only the owning thread adds to or takes from an entry.
    private readonly HashSet<int> _errorDeliveryThreads = [];
    private readonly Dictionary<int, Notices> _scopedNotices = new();

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

        DenyCommand = RelayCommand.Builder()
            .Task(Deny)
            .Build();

        _approveCommand = RelayCommand.Builder()
            .Task(ApproveCommandExecute)
            .Predicate(CanApprove)
            .Build();
        ApproveCommand = _approveCommand;
    }

    // Approval is disabled while invalid, while strict and pristine, and while
    // another approval is in flight (spec/20 §5, §5.3, §9).
    // The strict comparison runs after the lock is released (spec/20 §5.4,
    // ADR-0215).
    private bool CanApprove()
    {
        TM model;
        TM snapshot;
        lock (_stateGate)
        {
            if (_approvalInFlight || _errors.Count != 0) return false;
            if (!_strict) return true;
            model = _model;
            snapshot = _snapshot;
        }
        return !Equals(model, snapshot);
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
    /// Uses <see cref="object.Equals(object?, object?)"/>; record types provide structural
    /// equality, except that a record's synthesized equality compares a collection field by
    /// reference. The default snapshotter makes a new collection, so such a form is dirty at
    /// once unless the model overrides <c>Equals</c> to compare the collection element by element.
    /// The comparison runs with no form lock held (chapter 20 §5.4, ADR-0215).
    /// </summary>
    public bool IsDirty
    {
        get
        {
            TM model;
            TM snapshot;
            lock (_stateGate)
            {
                model = _model;
                snapshot = _snapshot;
            }
            return !Equals(model, snapshot);
        }
    }

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
    /// A call made from a preparation callback or an <see cref="ErrorsChanged"/>
    /// observer of an update is admitted at once, but its persister starts
    /// after the outermost update sends its notifications (chapter 20 §5.4,
    /// ADR-0180). Blocking on the returned task inside that callback never
    /// returns; await it after the callback returns.
    /// </summary>
    public Task ApproveAsync() => ApproveInternalAsync();

    // ── Public mutation ───────────────────────────────────────────────────────

    /// <summary>
    /// Replaces the current <see cref="Model"/>. Updating the model may change <see cref="IsDirty"/>;
    /// in strict mode it also fires <see cref="ICommand.CanExecuteChanged"/> on <see cref="ApproveCommand"/>.
    /// The update is failure-atomic (chapter 20 §5.4): the model's equality and the
    /// validators run before anything is committed, so an exception they throw
    /// propagates to the caller with the form unchanged and nothing published.
    /// These callbacks run with no form lock held, so another thread's reads and
    /// calls do not wait for them. An update that another thread's commit
    /// overtakes runs again as a new call (chapter 20 §5.4, ADR-0215).
    /// A non-strict update runs the equality once, against the live model
    /// (chapter 20 §5.2, ADR-0216).
    /// A call that the approving thread makes from the post-persist commit or a
    /// settlement observer is prepared, then queued at once, and replays after the
    /// <see cref="OnApproved"/> delivery returns (chapter 20 §5.3, ADR-0174).
    /// A call from another thread waits while a thread publishes the form's
    /// notifications. When that wait would close a wait-for cycle, the call is
    /// prepared, queued on the publishing thread, and returns before it takes
    /// effect (chapter 20 §5.5, ADR-0176).
    /// A call made from a preparation callback or an <see cref="ErrorsChanged"/>
    /// observer of another update commits at once and returns before its
    /// notifications. The outermost update on the thread sends them before it
    /// returns (chapter 20 §5.4, ADR-0180).
    /// </summary>
    public void SetModel(TM model)
    {
        // Inert after Dispose (like ApproveAsync/Deny): a post-dispose call would
        // otherwise emit on disposed validation subjects and throw
        // ObjectDisposedException (parity with the TS/Swift no-op).
        var caller = Environment.CurrentManagedThreadId;
        // An update that another thread's commit overtook runs again as a
        // new call. A loop keeps the stack flat under contention.
        bool retry;
        do
        {
            var admitted = false;
            retry = false;
            Notices? delivery = null;
            ExceptionDispatchInfo? failure = null;
            try
            {
                ApplySetModel(model, caller, ref admitted, ref retry, ref delivery);
            }
            catch (Exception error)
            {
                failure = ExceptionDispatchInfo.Capture(error);
            }
            var deliveryFailure = Deliver(delivery, caller, out var replay);
            FinishUpdate(admitted, failure ?? deliveryFailure, replay);
        }
        while (retry);
    }

    private void ApplySetModel(
        TM model, int caller, ref bool admitted, ref bool retry, ref Notices? delivery)
    {
        int publisher;
        bool queue;
        UpdateBase start;
        lock (_stateGate)
        {
            // A call in its own thread's pre-publication window joins that
            // thread's queue without waiting (spec/20 §5.5, ADR-0215).
            publisher = InPrePublicationWindow(caller) ? 0 : WaitForForeignScopes(caller);
            if (_disposed) return;
            // Reject a null model before any deferral, so the caller sees
            // the error (failure-atomic).
            ThrowHelper.ThrowIfNull(model, nameof(model));
            queue = publisher != 0 || InPrePublicationWindow(caller);
            _activeMutations++;
            admitted = true;
            start = BeginFrameLocked(caller);
        }

        var own = new Notices();
        try
        {
            // Preparation (spec/20 §5.2, §5.4) runs every consumer callback
            // with no form lock held (ADR-0215) and changes no form state, so
            // a callback failure propagates with nothing committed or
            // published, and a callback reading the form sees the previous
            // state. A call inside the approval's pre-publication window, or
            // one whose wait was refused, runs the full preparation and is
            // then queued (§5.3, §5.5): equality never skips the enqueue,
            // because earlier queued calls can change the live model before
            // this one replays. Only strict mode reads the dirty state
            // (§5.2, ADR-0216).
            var unchanged = Equals(start.Model, model);
            var wasDirty = false;
            var isDirty = false;
            Dictionary<string, string>? nextErrors = null;
            if (!unchanged || queue)
            {
                wasDirty = _strict && !Equals(start.Model, start.Snapshot);
                nextErrors = Validate(model);
                isDirty = _strict && !Equals(model, start.Snapshot);
            }

            lock (_stateGate)
            {
                if (!IsCurrentLocked(start, caller, queue, ref retry)) return;
                if (queue)
                {
                    retry = !TryEnqueueLocked(QueueOwnerLocked(publisher, caller), caller, QueuedUpdate.Set(model));
                    return;
                }
                if (unchanged) return;

                // Commit in one step, before any notification.
                var errors = nextErrors!;
                var canExecuteChanged = (_strict && isDirty != wasDirty) ||
                    (errors.Count == 0) != (start.Errors.Count == 0);
                _model = model;
                _errors = errors;
                CommitLocked(caller);
                // Update scope (spec/20 §5.5): the error map is delivered
                // without the state lock, while other threads' form calls
                // wait, so error maps reach observers in commit order.
                if (!SameErrors(errors, start.Errors))
                    own.AddErrors(new Dictionary<string, string>(errors), EnterScopeLocked(caller));
                if (canExecuteChanged)
                    own.AddAfterScope(RaiseCanExecuteChanged);
                var message = PropertyChangedMessage<FormVM<TM>>.Create(this, nameof(FormVM<TM>), nameof(Model));
                own.AddAfterScope(() => _hub.Send(message));
            }
        }
        finally
        {
            // Nothing is sent under the gate (spec/20 §5.4, §5.5): a nested
            // frame queues its notifications, and the outermost frame takes
            // them for Deliver.
            lock (_stateGate)
            {
                _frames[caller].Depth--;
                delivery = TakeNoticesLocked(own, caller);
            }
        }
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
        // remaining subjects or the two commands.
        // Capture the first failure and run every step.
        ExceptionDispatchInfo? firstError = null;
        FirstFailure.Capture(ref firstError, _approveErrors.OnCompleted);
        FirstFailure.Capture(ref firstError, _approveErrors.Dispose);
        FirstFailure.Capture(ref firstError, _onApproved.OnCompleted);
        FirstFailure.Capture(ref firstError, _onApproved.Dispose);
        FirstFailure.Capture(ref firstError, _errorsChanged.OnCompleted);
        FirstFailure.Capture(ref firstError, _errorsChanged.Dispose);
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
        // An update that another thread's commit overtook runs again as a
        // new call. A loop keeps the stack flat under contention.
        bool retry;
        do
        {
            var admitted = false;
            retry = false;
            Notices? delivery = null;
            ExceptionDispatchInfo? failure = null;
            try
            {
                ApplyDeny(caller, ref admitted, ref retry, ref delivery);
            }
            catch (Exception error)
            {
                failure = ExceptionDispatchInfo.Capture(error);
            }
            var deliveryFailure = Deliver(delivery, caller, out var replay);
            FinishUpdate(admitted, failure ?? deliveryFailure, replay);
        }
        while (retry);
    }

    private void ApplyDeny(int caller, ref bool admitted, ref bool retry, ref Notices? delivery)
    {
        int publisher;
        bool queue;
        UpdateBase start;
        lock (_stateGate)
        {
            publisher = InPrePublicationWindow(caller) ? 0 : WaitForForeignScopes(caller);
            if (_disposed) return;
            queue = publisher != 0 || InPrePublicationWindow(caller);
            _activeMutations++;
            admitted = true;
            start = BeginFrameLocked(caller);
        }

        var own = new Notices();
        try
        {
            // Preparation (spec/20 §5.4): the equality, snapshotter, and
            // validator callbacks run with no form lock held (ADR-0215) and
            // change no form state, so a failure propagates from
            // DenyCommand.Execute() with nothing reverted or published.
            // Inside the approval's pre-publication window, or after a
            // refused wait, the prepared revert is discarded and the deny is
            // queued (§5.3, §5.5). Only strict mode reads the dirty state
            // (§5.2, ADR-0216).
            var wasDirty = _strict && !Equals(start.Model, start.Snapshot);
            var nextModel = _snapshotter(start.Snapshot);
            var nextErrors = Validate(nextModel);
            var isDirty = _strict && !Equals(nextModel, start.Snapshot);

            lock (_stateGate)
            {
                if (!IsCurrentLocked(start, caller, queue, ref retry)) return;
                if (queue)
                {
                    retry = !TryEnqueueLocked(QueueOwnerLocked(publisher, caller), caller, QueuedUpdate.Deny);
                    return;
                }

                _model = nextModel;
                _errors = nextErrors;
                CommitLocked(caller);
                var canExecuteChanged = (_strict && wasDirty != isDirty) ||
                    (nextErrors.Count == 0) != (start.Errors.Count == 0);
                if (!SameErrors(nextErrors, start.Errors))
                    own.AddErrors(new Dictionary<string, string>(nextErrors), EnterScopeLocked(caller));
                var reverted = new FormRevertedMessage(this, nameof(FormVM<TM>));
                var message = PropertyChangedMessage<FormVM<TM>>.Create(this, nameof(FormVM<TM>), nameof(Model));
                own.AddAfterScope(() => _hub.Send(reverted));
                own.AddAfterScope(() => _hub.Send(message));
                if (canExecuteChanged)
                    own.AddAfterScope(RaiseCanExecuteChanged);
            }
        }
        finally
        {
            lock (_stateGate)
            {
                _frames[caller].Depth--;
                delivery = TakeNoticesLocked(own, caller);
            }
        }
    }

    private void RaiseCanExecuteChanged() => _approveCommand.RaiseCanExecuteChanged();

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
        TaskCompletionSource<Task>? nestedStart = null;
        lock (_stateGate)
        {
            _ = WaitForForeignScopes(caller);
            if (_disposed || _errors.Count != 0 || _approvalInFlight) return;
            _approvalInFlight = true;
            current = _model;
            if (IsNestedLocked(caller))
            {
                // A nested approval (spec/20 §5.4, ADR-0180) is admitted now.
                // Its admission notification and its persister start wait for
                // the outermost update. That update sends the notification
                // with the rest of its queue, then runs the start: the start
                // calls the persister on that thread before the update
                // returns, and hands the run to this call's awaiter.
                var start = nestedStart = new TaskCompletionSource<Task>();
                var captured = current;
                var approval = new NestedApproval(
                    () => start.TrySetResult(RunAdmittedAsync(captured, replayFailure)),
                    () => start.TrySetResult(Task.CompletedTask));
                var own = new Notices();
                own.AddAfterScope(() =>
                {
                    approval.Announced = true;
                    RaiseCanExecuteChanged();
                });
                own.Starts.Add(approval);
                _ = TakeNoticesLocked(own, caller);
            }
            else
            {
                // The admission notification opens no scope (spec/20 §5.5),
                // so a Dispose on another thread defers its teardown until it
                // returns.
                _activeMutations++;
            }
        }

        if (nestedStart is not null)
        {
            var run = await nestedStart.Task.ConfigureAwait(false);
            await run.ConfigureAwait(false);
            return;
        }

        RaiseAdmissionCanExecuteChanged();
        await RunAdmittedAsync(current, replayFailure).ConfigureAwait(false);
    }

    // Persists an admitted approval and settles it (spec/20 §5.3).
    private async Task RunAdmittedAsync(TM current, FirstReplayFailure replayFailure)
    {
        // An admission observer, or a callback before a nested approval's
        // start, may have disposed the form. A disposed form never invokes
        // the persister, and the approval settles silently (spec/20 §10).
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
        var caller = Environment.CurrentManagedThreadId;
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
            CommitLocked(caller);
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
                RaiseCanExecuteChanged();
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

    private void RaiseAdmissionCanExecuteChanged()
    {
        var admissionFailed = false;
        try
        {
            RaiseCanExecuteChanged();
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
            try { RaiseCanExecuteChanged(); }
            catch { /* The admission failure is the one the caller sees. */ }
            throw;
        }
        finally
        {
            EndMutation(admissionFailed);
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
            RaiseCanExecuteChanged();
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
    // own scopes never block it. A nested call (spec/20 §5.4, ADR-0180)
    // takes the same result without waiting.
    private int WaitForForeignScopes(int caller)
    {
        var waiting = false;
        try
        {
            while (!_disposed)
            {
                var owner = ForeignPublisherLocked(caller);
                if (owner == 0) return 0;
                if (IsNestedLocked(caller)) return owner;
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

    // Called under _stateGate. A call is nested (spec/20 §5.4, ADR-0180) when
    // it comes from a preparation callback of a SetModel or deny on this
    // thread, or from an ErrorsChanged observer that the outermost update on
    // this thread delivers.
    private bool IsNestedLocked(int caller) =>
        (_frames.TryGetValue(caller, out var frame) && frame.Depth > 0) || _errorDeliveryThreads.Contains(caller);

    // Called under _stateGate when a SetModel or deny is admitted: opens or
    // deepens the caller's update frame and records the state it prepares
    // against.
    private UpdateBase BeginFrameLocked(int caller)
    {
        if (!_frames.TryGetValue(caller, out var frame))
            _frames[caller] = frame = new UpdateFrame();
        frame.Depth++;
        return new UpdateBase(_commitGeneration, frame.Commits, frame.Queues, _model, _snapshot, _errors);
    }

    // Called under _stateGate for every commit of model, snapshot, or errors.
    private void CommitLocked(int caller)
    {
        _commitGeneration++;
        if (_frames.TryGetValue(caller, out var frame)) frame.Commits++;
    }

    // Called under _stateGate when a preparation completes (spec/20 §5.4,
    // ADR-0215). The checks run in order. A disposed form commits nothing. A
    // callback on this thread that committed or queued another update makes
    // the prepared result stale. A call that another thread's commit
    // overtook sets retry and runs again as a new call; a queued call is not
    // affected, because it prepares again when it replays.
    private bool IsCurrentLocked(UpdateBase start, int caller, bool queue, ref bool retry)
    {
        if (_disposed) return false;
        var frame = _frames[caller];
        if (frame.Commits != start.Commits || frame.Queues != start.Queues) return false;
        if (queue || _commitGeneration == start.Generation) return true;
        retry = true;
        return false;
    }

    // Called under _stateGate by an update frame or a nested admission. A
    // frame nested in an update on this thread queues `own` for the outermost
    // frame and returns null. The outermost frame takes the whole queue,
    // with its own notifications last. Inside the error-map phase of a
    // delivery on this thread, it queues that for the delivery instead.
    private Notices? TakeNoticesLocked(Notices own, int caller)
    {
        var delivery = new Notices();
        if (_frames.TryGetValue(caller, out var frame))
        {
            if (frame.Depth > 0)
            {
                frame.Pending.Append(own, nested: true);
                return null;
            }
            delivery = frame.Pending;
            _frames.Remove(caller);
        }
        delivery.Append(own, nested: false);
        if (_errorDeliveryThreads.Contains(caller))
        {
            if (!_scopedNotices.TryGetValue(caller, out var scoped))
                _scopedNotices[caller] = scoped = new Notices();
            scoped.Append(delivery, nested: true);
            return null;
        }
        return delivery.IsEmpty ? null : delivery;
    }

    // Sends the notifications that TakeNoticesLocked took, with no form lock
    // held (spec/20 §5.4, §5.5, ADR-0180). Each error map goes first, inside
    // the update scope its commit opened. Then the scopes close, and the
    // outermost close returns this thread's queue for the caller to replay.
    // The other notifications follow in queue order, and the persister
    // starts of nested approvals run last. A notification that a nested call
    // queued is dropped once the form is disposed. An observer failure stops
    // the remaining notifications and is returned. The scopes still close,
    // and the nested approvals are released without calling the persister,
    // because their admission notification may not have gone out (§5.3).
    private ExceptionDispatchInfo? Deliver(Notices? notices, int caller, out QueuedUpdate[] replay)
    {
        replay = [];
        if (notices is null) return null;
        ExceptionDispatchInfo? failure = null;
        try
        {
            try
            {
                if (notices.Errors.Count > 0) SendErrors(notices, caller);
            }
            finally
            {
                // The teardown claim cannot succeed here: this update still
                // counts in _activeMutations, so its EndMutation runs a
                // deferred teardown.
                for (var i = notices.Scopes.Count - 1; i >= 0; i--)
                    replay = [.. replay, .. ExitScope(caller, notices.Scopes[i], out _)];
            }
            foreach (var (send, nested) in notices.AfterScope)
                if (!nested || !_disposed) send();
        }
        catch (Exception error)
        {
            failure = ExceptionDispatchInfo.Capture(error);
        }
        finally
        {
            foreach (var approval in notices.Starts)
            {
                if (failure is null) approval.Run();
                else ReleaseNestedApproval(approval);
            }
        }
        return failure;
    }

    // Releases a nested approval that an observer failure stopped before its
    // start. The persister never runs. As for a failed top-level admission
    // (#732), observers that saw the admission edge get the release edge.
    private void ReleaseNestedApproval(NestedApproval approval)
    {
        bool notify;
        lock (_stateGate)
        {
            _approvalInFlight = false;
            notify = approval.Announced && !_disposed;
        }
        if (notify)
        {
            try { RaiseCanExecuteChanged(); }
            catch { /* The delivery failure is the one the caller sees. */ }
        }
        approval.Abandon();
    }

    // Sends the error maps of a delivery in commit order. An ErrorsChanged
    // observer may update the form on this thread; that update queues its
    // notifications here, and its error maps go out inside the scopes that
    // are still open.
    private void SendErrors(Notices notices, int caller)
    {
        lock (_stateGate) _errorDeliveryThreads.Add(caller);
        try
        {
            for (var i = 0; i < notices.Errors.Count; i++)
            {
                var (map, nested) = notices.Errors[i];
                if (!nested || !_disposed) _errorsChanged.OnNext(map);
                if (i == notices.Errors.Count - 1) TakeScopedNotices(notices, caller, stop: false);
            }
        }
        finally
        {
            // On a failure, the scopes and starts of updates queued here still
            // join the delivery.
            TakeScopedNotices(notices, caller, stop: true);
        }
    }

    private void TakeScopedNotices(Notices notices, int caller, bool stop)
    {
        lock (_stateGate)
        {
            if (_scopedNotices.TryGetValue(caller, out var scoped))
            {
                _scopedNotices.Remove(caller);
                notices.Append(scoped, nested: true);
            }
            if (stop) _errorDeliveryThreads.Remove(caller);
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

    // Called under _stateGate after a preparation. A call in its own
    // thread's pre-publication window joins that thread's queue (publisher 0),
    // even when its wait for another thread's scope was refused. Otherwise a
    // refused call joins the queue of the publisher its edge named
    // (spec/20 §5.5, ADR-0176).
    private int QueueOwnerLocked(int publisher, int caller) =>
        InPrePublicationWindow(caller) ? 0 : publisher;

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
        if (_frames.TryGetValue(caller, out var frame)) frame.Queues++;
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

    // One thread's update frames: their nesting depth, the notifications of
    // nested calls for the outermost frame, and the commits and enqueues the
    // thread made while a frame was open.
    private sealed class UpdateFrame
    {
        public int Depth { get; set; }

        public Notices Pending { get; } = new();

        public long Commits { get; set; }

        public long Queues { get; set; }
    }

    // The state an update prepares against, and its thread's counts.
    private readonly record struct UpdateBase(
        long Generation,
        long Commits,
        long Queues,
        TM Model,
        TM Snapshot,
        Dictionary<string, string> Errors);

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

    // Notifications that an update or a nested approval admission sends after
    // it releases _stateGate (spec/20 §5.4, ADR-0180). Each error map has an
    // update scope, kept as the enclosing pre-publishing flag for ExitScope.
    // A notification queued by a nested call is marked, so the delivery drops
    // it once the form is disposed. Starts hold the admitted nested
    // approvals.
    private sealed class Notices
    {
        public List<(Dictionary<string, string> Map, bool Nested)> Errors { get; } = [];

        public List<bool> Scopes { get; } = [];

        public List<(Action Send, bool Nested)> AfterScope { get; } = [];

        public List<NestedApproval> Starts { get; } = [];

        public bool IsEmpty => Errors.Count == 0 && Scopes.Count == 0 && AfterScope.Count == 0 && Starts.Count == 0;

        public void AddErrors(Dictionary<string, string> map, bool outerPrePublishing)
        {
            Errors.Add((map, false));
            Scopes.Add(outerPrePublishing);
        }

        public void AddAfterScope(Action send) => AfterScope.Add((send, false));

        public void Append(Notices other, bool nested)
        {
            foreach (var (map, wasNested) in other.Errors) Errors.Add((map, wasNested || nested));
            Scopes.AddRange(other.Scopes);
            foreach (var (send, wasNested) in other.AfterScope) AfterScope.Add((send, wasNested || nested));
            Starts.AddRange(other.Starts);
        }
    }

    // An approval admitted by a nested call (spec/20 §5.4, ADR-0180). Run
    // starts its persister after the outermost update's notifications.
    // Abandon completes its awaiter without a persister call. Announced
    // records that its admission notification was sent.
    private sealed class NestedApproval(Action run, Action abandon)
    {
        public bool Announced { get; set; }

        public void Run() => run();

        public void Abandon() => abandon();
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
