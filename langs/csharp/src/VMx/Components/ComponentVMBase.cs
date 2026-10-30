using System.ComponentModel;
using System.Reactive;
using System.Reactive.Disposables;
using System.Reactive.Subjects;
using System.Runtime.CompilerServices;
using System.Runtime.ExceptionServices;
using System.Windows.Input;
using VMx.Commands;
using VMx.Groups;
using VMx.Internal;
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
    IComponentVM OwnershipIdentity { get; }
    void SetParent(IParentCompositeVM? parent);
    void SetIsCurrent(bool value);
    bool CommitIsCurrent(bool value);
    void PublishIsCurrent();
    Task ConstructOrJoinAsync();
    Task JoinConstructAsync();
    Task? TryJoinDestructAsync();
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

    internal static IComponentVM GetOwnershipIdentity(this IComponentVM vm)
        => (vm as IComponentVMInternals)?.OwnershipIdentity ?? vm;

    internal static void SetIsCurrent(this IComponentVM vm, bool value)
        => (vm as IComponentVMInternals)?.SetIsCurrent(value);

    internal static bool CommitIsCurrent(this IComponentVM vm, bool value)
        => (vm as IComponentVMInternals)?.CommitIsCurrent(value) ?? false;

    internal static void PublishIsCurrent(this IComponentVM vm)
        => (vm as IComponentVMInternals)?.PublishIsCurrent();

    internal static Task ConstructOrJoinAsync(this IComponentVM vm)
        => vm is IComponentVMInternals internals
            ? internals.ConstructOrJoinAsync()
            : vm.ConstructAsync();

    // A custom IComponentVM exposes no join, so one still Constructing is
    // driven through its own ConstructAsync. Any other status is final: a
    // joined child is never restarted.
    internal static Task JoinConstructAsync(this IComponentVM vm)
        => vm is IComponentVMInternals internals
            ? internals.JoinConstructAsync()
            : vm.Status == ConstructionStatus.Constructing
                ? vm.ConstructAsync()
                : Task.CompletedTask;

    // Joins a destruct already in flight (#754); otherwise destructs through
    // the VM's own DestructAsync, so a forwarding decorator's override still
    // runs (spec/09). A custom IComponentVM exposes no join: its DestructAsync
    // rejects a destruct already in flight.
    internal static Task DestructOrJoinAsync(this IComponentVM vm)
        => (vm as IComponentVMInternals)?.TryJoinDestructAsync() ?? vm.DestructAsync();
}

/// <summary>Shared identity validation and old-parent staging for container mutations.</summary>
internal static class ComponentOwnership
{
    private static readonly object Coordinator = new();

    private sealed class ReservationBatch : IDisposable
    {
        private readonly OwnershipState[] _states;
        private readonly bool _exclusive;
        private bool _disposed;

        internal ReservationBatch(OwnershipState[] states, bool exclusive = false)
        {
            _states = states;
            _exclusive = exclusive;
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            if (_exclusive)
                foreach (var state in _states) state.InProgress = false;
            for (var index = _states.Length - 1; index >= 0; index--)
                Exit(_states[index]);
        }
    }

    private sealed class OwnershipState
    {
        internal readonly object Gate = new();
        internal bool InProgress;

        // Re-entrant holds by the thread that holds Gate; guarded by Gate.
        internal int HoldCount;
    }

    // Records the holder of an identity in the wait graph on its first hold, so
    // a thread that waits for the identity can see a wait-for cycle through
    // it (#1047). Call only while holding the gate.
    private static void Hold(OwnershipState state)
    {
        if (state.HoldCount++ == 0)
            MembershipTransactionWaitGraph.Shared.Acquire(state.Gate, Environment.CurrentManagedThreadId);
    }

    // Leaves the gate; the last exit removes the holder from the wait graph.
    private static void Exit(OwnershipState state)
    {
        if (--state.HoldCount == 0) MembershipTransactionWaitGraph.Shared.Release(state.Gate);
        Monitor.Exit(state.Gate);
    }

    // Waits until the holder of a blocked identity lets it go. The wait joins
    // the wait graph: a wait that would close a wait-for cycle through
    // membership transactions, ownership gates or both is refused instead of
    // deadlocking (#1047).
    private static void WaitForRelease(OwnershipState blocked)
    {
        var caller = Environment.CurrentManagedThreadId;
        var waits = MembershipTransactionWaitGraph.Shared;
        if (!waits.TryBeginWait(blocked.Gate, caller))
            throw new InvalidOperationException(
                "A component ownership transaction is in progress on a thread that " +
                "waits for this one; waiting would deadlock.");
        try
        {
            Monitor.Enter(blocked.Gate);
            Monitor.Exit(blocked.Gate);
        }
        finally
        {
            waits.EndWait(caller);
        }
    }

    private static readonly ConditionalWeakTable<IComponentVM, OwnershipState> States = new();

    private static OwnershipState StateFor(IComponentVM child)
        => States.GetValue(child.GetOwnershipIdentity(), static _ => new OwnershipState());

    private static OwnershipState[] AcquireStates(IEnumerable<IComponentVM> children)
    {
        var states = children
            .Select(StateFor)
            .Distinct()
            .ToArray();
        while (true)
        {
            var acquired = new List<OwnershipState>(states.Length);
            OwnershipState? blocked = null;
            lock (Coordinator)
            {
                foreach (var state in states)
                {
                    if (Monitor.TryEnter(state.Gate))
                    {
                        Hold(state);
                        acquired.Add(state);
                    }
                    else
                    {
                        blocked = state;
                        break;
                    }
                }
                if (blocked is null) return states;
                for (var index = acquired.Count - 1; index >= 0; index--)
                    Exit(acquired[index]);
            }

            // Never wait for one identity while retaining the coordinator or
            // another identity. Once the blocker moves, retry the complete set.
            WaitForRelease(blocked);
        }
    }

    internal static IDisposable BeginReservationBatch(IEnumerable<IComponentVM> children)
        => new ReservationBatch(AcquireStates(children));

    internal static IDisposable BeginExclusiveReservationBatch(
        IEnumerable<IComponentVM> children)
    {
        var states = AcquireStates(children);
        if (states.Any(state => state.InProgress))
        {
            for (var index = states.Length - 1; index >= 0; index--)
                Exit(states[index]);
            throw new InvalidOperationException(
                "An ownership transaction is already in progress for a reserved component.");
        }
        foreach (var state in states) state.InProgress = true;
        return new ReservationBatch(states, exclusive: true);
    }

    internal static void CommitThenPublish(
        ParentTransferToken? transfer,
        Action publish)
        => CommitThenPublish([transfer], publish);

    internal static void CommitThenPublish(
        IEnumerable<ParentTransferToken?> transfers,
        Action publish)
    {
        Exception? firstError = null;
        foreach (var transfer in transfers)
        {
            try { transfer?.Commit(); }
            catch (Exception error) { firstError ??= error; }
        }
        try { publish(); }
        catch (Exception error) { firstError ??= error; }
        if (firstError is not null) ExceptionDispatchInfo.Capture(firstError).Throw();
    }

    internal static ParentTransferToken? BeginTransfer(
        IComponentVM child,
        IParentCompositeVM destination)
    {
        var identity = child.GetOwnershipIdentity();
        var state = StateFor(identity);
        AcquireStates([identity]);
        if (state.InProgress)
        {
            Exit(state);
            throw new InvalidOperationException(
                $"Cannot transfer '{child.Name}': an ownership transaction is already in progress.");
        }
        state.InProgress = true;

        ParentTransferToken? staged;
        try
        {
            if (destination.ContainsChild(child))
                throw new InvalidOperationException(
                    $"Cannot add '{child.Name}': the destination already contains that identity.");

            for (IParentCompositeVM? cursor = destination;
                 cursor is not null;
                 cursor = cursor.OwnerParent)
            {
                if (cursor.Owner is not null &&
                    ReferenceEquals(cursor.Owner.GetOwnershipIdentity(), identity))
                    throw new InvalidOperationException(
                        $"Cannot add '{child.Name}': the operation would create a parent cycle.");
            }

            staged = child.GetParent()?.DetachForTransfer(child);
        }
        catch
        {
            state.InProgress = false;
            Exit(state);
            throw;
        }

        void Finish(bool commit)
        {
            try
            {
                if (staged is not null)
                {
                    if (commit) staged.Commit();
                    else staged.Rollback();
                }
            }
            finally
            {
                state.InProgress = false;
                Exit(state);
            }
        }

        return new ParentTransferToken(() => Finish(true), () => Finish(false));
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

    // Member VMs registered through OwnMember, disposed in registration order
    // before this VM publishes Disposed (spec/02 §7.1). Guarded by _gate.
    private readonly List<IComponentVM> _members = [];
    // Set under _gate when disposal takes the member list; a later
    // registration disposes its member at once.
    private bool _membersTaken;
    // Set under _gate when a disposal with registered members starts. Until
    // that disposal publishes Disposed, any further Dispose() on any thread
    // returns at once and does nothing (spec/02 §7.1).
    private bool _memberCascadeRunning;

    /// <summary>
    /// The dispatcher supplied at construction. <c>private protected</c> so
    /// same-assembly container subclasses can schedule on it without re-storing
    /// their own copy.
    /// </summary>
    private protected readonly IDispatcher _dispatcher;
    private readonly bool _background;

    // ── Lifecycle state ─────────────────────────────────────────────────────
    // _gate atomically admits lifecycle state transitions and orders their
    // externally observable delivery against Dispose(). Observer callbacks are
    // drained outside the gate so two VMs can safely react to each other's
    // lifecycle messages without acquiring their gates in opposing order.
    private readonly object _gate = new();
    private static readonly object s_lifecycleWaitGraphGate = new();
    private static readonly Dictionary<int, int> s_lifecycleWaitGraph = [];

    private sealed class LifecycleDelivery(Action action)
    {
        internal Action Action { get; } = action;
        internal ExceptionDispatchInfo? Failure { get; set; }
        internal ManualResetEventSlim Completed { get; } = new(false);
    }

    private sealed class LifecycleHookLease
    {
        internal int OwnerThreadId { get; } = Environment.CurrentManagedThreadId;
        internal ManualResetEventSlim Completed { get; } = new(false);
        internal Action? DeferredDisposal { get; set; }
    }

    private readonly Queue<LifecycleDelivery> _lifecycleDeliveries = [];
    private bool _lifecycleDeliveryDraining;
    private int _lifecycleDeliveryDrainerThreadId;

    // volatile so the unlocked fast-path reads (Status, IsConstructed, the Can*
    // predicates, the idempotent lifecycle guards) never observe a stale value
    // written by a transition completing on the background scheduler.
    private volatile ConstructionStatus _status = ConstructionStatus.Destructed;

    // Set only by a container's commit step: its Constructed state is
    // committed, but the Constructed status is not yet published (spec/06
    // §5.1). Cleared under _gate when any status publication starts.
    private volatile bool _constructPublicationPending;
    private volatile bool _inFlight;
    private readonly List<TaskCompletionSource<bool>> _lifecycleWaiters = [];
    private Task? _deferredLifecycleTask;
    private LifecycleHookLease? _activeHookLease;
    // Set while a container disposes its children ahead of its own terminal
    // transition, so no lifecycle hook is admitted during the cascade.
    private bool _hookAdmissionClosed;
    // Set under _gate when disposal starts, before a container disposes its
    // children. A deferred child walk then drives no further child and
    // publishes neither its success nor its rollback status (#755).
    private bool _childTransitionAbandoned;
    // The hook scope of the walk that the last lifecycle hook deferred to.
    private LifecycleHookScope? _deferredWalkScope;

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
    /// Defers this VM's terminal lifecycle status until <paramref name="task"/>
    /// settles. Call it from this VM's own <see cref="OnConstruct"/> or
    /// <see cref="OnDestruct"/> override, including the two phases of
    /// <see cref="Reconstruct"/>, with the task that
    /// <see cref="TransitionChildrenAsync(IEnumerable{IComponentVM}, bool, Action?)"/>
    /// returns (spec/02 §6.1, ADR-0162):
    /// <code>
    /// protected override void OnConstruct()
    ///     =&gt; CompleteLifecycleHookAfter(TransitionChildrenAsync([_chart, _table], construct: true));
    ///
    /// protected override void OnDestruct()
    ///     =&gt; CompleteLifecycleHookAfter(TransitionChildrenAsync([_table, _chart], construct: false));
    /// </code>
    /// While the task is pending, this VM stays <see cref="ConstructionStatus.Constructing"/>
    /// or <see cref="ConstructionStatus.Destructing"/>. When the task completes, this VM
    /// publishes its terminal status. When the task faults, this VM rolls back to its
    /// prior settled status, and the fault reaches the caller of the asynchronous
    /// lifecycle method or the background-failure path. A task that already
    /// completed is observed at once, so a synchronous failure throws from the hook.
    /// </summary>
    /// <param name="task">The work that this VM's transition waits for.</param>
    /// <exception cref="InvalidOperationException">
    /// This VM's own construct or destruct hook is not running on the calling
    /// thread, or the running hook already deferred its completion.
    /// </exception>
    protected void CompleteLifecycleHookAfter(Task task)
    {
        ThrowHelper.ThrowIfNull(task, nameof(task));
        if (!ReferenceEquals(t_lifecycleHookScope?.Owner, this))
            throw new InvalidOperationException(
                $"CompleteLifecycleHookAfter can be called only from the construct or destruct hook of '{Name}'.");

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

    internal sealed class ChildReferenceComparer : IEqualityComparer<IComponentVM>
    {
        internal static ChildReferenceComparer Instance { get; } = new();

        public bool Equals(IComponentVM? x, IComponentVM? y) => ReferenceEquals(x, y);

        public int GetHashCode(IComponentVM obj) => RuntimeHelpers.GetHashCode(obj);
    }

    /// <summary>
    /// Constructs or destructs member view-models as part of this VM's own
    /// transition (spec/02 §6.1, ADR-0162). Pass the returned task to
    /// <see cref="CompleteLifecycleHookAfter"/> from the same hook:
    /// <code>
    /// protected override void OnConstruct()
    ///     =&gt; CompleteLifecycleHookAfter(TransitionChildrenAsync([_chart, _table], construct: true));
    /// </code>
    /// <list type="bullet">
    /// <item>The walk takes <paramref name="children"/> in the given order and
    /// starts a child only after the previous child settled. To destruct in
    /// reverse, pass the reversed list.</item>
    /// <item>A child already at the target status (<see cref="ConstructionStatus.Constructed"/>
    /// or <see cref="ConstructionStatus.Destructed"/>) is skipped. A child already
    /// <see cref="ConstructionStatus.Constructing"/> or <see cref="ConstructionStatus.Destructing"/>
    /// is joined and is not started again.</item>
    /// <item>A background child keeps this VM in its transient status until the
    /// child settles. The rest of the walk then continues on this VM's
    /// foreground dispatcher.</item>
    /// <item>A child that settles at another status faults the task with an
    /// <see cref="InvalidOperationException"/>, and later children do not start.
    /// This VM then rolls back to its prior settled status. Siblings that already
    /// reached the target are not undone.</item>
    /// <item><paramref name="after"/> runs exactly once, after every child settled at
    /// the target and before this VM publishes its terminal status. A throwing
    /// <paramref name="after"/> faults the task like a failing child.</item>
    /// </list>
    /// Members are not container children: the walk sets no parent link and no
    /// selection. Register them with <see cref="OwnMember{T}"/> for disposal.
    /// </summary>
    /// <param name="children">The member view-models, in walk order.</param>
    /// <param name="construct"><see langword="true"/> to construct; <see langword="false"/> to destruct.</param>
    /// <param name="after">Optional work that runs once every child settled at the target.</param>
    /// <returns>A task that completes when the walk and <paramref name="after"/> finished.</returns>
    /// <exception cref="InvalidOperationException">
    /// No construct or destruct hook is running on the calling thread. The
    /// exception is thrown synchronously, and no child starts.
    /// </exception>
    protected static Task TransitionChildrenAsync(
        IEnumerable<IComponentVM> children,
        bool construct,
        Action? after = null)
    {
        ThrowHelper.ThrowIfNull(children, nameof(children));
        if (t_lifecycleHookScope is null)
            throw new InvalidOperationException(
                "TransitionChildrenAsync can be called only from a construct or destruct hook.");
        return TransitionChildrenAsync(children, construct, after, joined: null);
    }

    /// <summary>
    /// Transitions children sequentially. A child in <paramref name="joined"/>
    /// already started this transition (factory population) or is a late
    /// child whose auto-construct add started it: it is joined through
    /// <paramref name="join"/> (default: join only) and its settled status is
    /// final, so it is never restarted. The set is read live, so a lazy
    /// <paramref name="children"/> walk may add to it.
    /// </summary>
    private protected static async Task TransitionChildrenAsync(
        IEnumerable<IComponentVM> children,
        bool construct,
        Action? after,
        ISet<IComponentVM>? joined,
        Func<IComponentVM, Task>? join = null,
        Func<IComponentVM?>? seal = null)
    {
        // Captured synchronously while the owner's lifecycle hook runs, before
        // the first await, so the walk can return to the owner's foreground.
        var scope = t_lifecycleHookScope;
        using var walk = children.GetEnumerator();
        var walkedAll = false;
        while (true)
        {
            IComponentVM child;
            if (!walkedAll && walk.MoveNext())
            {
                child = walk.Current;
            }
            else
            {
                if (!walkedAll)
                {
                    walkedAll = true;
                    // Inline: either still inside the hook (no child yielded) or
                    // already on the owner's foreground. An abandoned walk, or one
                    // whose owner was disposed while it waited to resume, never
                    // runs its continuation: the user onDestruct or the Current
                    // selector would run after Dispose() (#735).
                    if (WalkStopped(scope)) return;
                    after?.Invoke();
                }
                // A container's commit step (spec/06 §5.1): `seal` returns a
                // child added after the walk's last scan, which the walk then
                // joins, or commits the Constructed state and returns null.
                // `after` runs once, never again.
                if (seal is null || WalkStopped(scope)) return;
                var late = seal();
                if (late is null) return;
                child = late;
            }

            // An abandoned walk (its hook threw after deferring) drives no
            // further children, matching Python and TypeScript; nor does a walk
            // whose owner was disposed, as TypeScript abandons it on dispose.
            if (WalkStopped(scope)) return;
            Task pending;
            if (construct)
            {
                var isJoined = joined is not null && joined.Contains(child);
                pending = !isJoined
                    ? child.ConstructOrJoinAsync()
                    : join is not null ? join(child) : child.JoinConstructAsync();
            }
            else
            {
                // A child already Destructing is joined, never destructed a
                // second time (spec/02 §6, #754).
                pending = child.DestructOrJoinAsync();
            }
            var resumes = !pending.IsCompleted;
            await pending.ConfigureAwait(false);
            if (construct && child.Status != ConstructionStatus.Constructed)
                throw new InvalidOperationException(
                    $"Child '{child.Name}' did not reach Constructed.");
            if (!construct && child.Status != ConstructionStatus.Destructed)
                throw new InvalidOperationException(
                    $"Child '{child.Name}' did not reach Destructed.");

            // spec/11 §3: a child that settled asynchronously resumes the walk on a
            // pool thread. Later siblings raise CollectionChanged / IsCurrent and run
            // user hooks, so the rest of the walk, and `after`, continue on the
            // owner's foreground dispatcher, like the terminal status. A walk whose
            // children all settle synchronously never hops: it stays on the caller.
            if (resumes && scope is not null)
                await new ForegroundResumption(scope.Owner);
        }
    }

    /// <summary>
    /// The container commit step: flips a construct still in flight to
    /// Constructed without publishing it. The caller holds its membership gate,
    /// so an add reads either Constructing (before the flip, and its child is
    /// joined) or Constructed (and follows the add-after-Constructed rule). The
    /// base still publishes the single Constructed status when the transition
    /// completes (spec/06 §5.1).
    /// </summary>
    private protected void MarkConstructedBeforePublication()
    {
        lock (_gate)
        {
            if (_status != ConstructionStatus.Constructing || !_inFlight) return;
            _status = ConstructionStatus.Constructed;
            _constructPublicationPending = true;
        }
    }

    private static bool WalkStopped(LifecycleHookScope? scope)
        => scope is not null && (scope.Abandoned || scope.Owner.IsDisposed());

    /// <summary>
    /// Stops waiting for a pending child transition without settling this VM.
    /// Disposal calls this before it disposes any child, so a child reaching
    /// Disposed does not roll this VM back before its own Disposed (#755). A
    /// container that disposes its children outside
    /// <see cref="DisposeWithChildren"/> calls it first, while no hook of its
    /// own can run.
    /// </summary>
    private protected void AbandonChildTransition()
    {
        lock (_gate)
        {
            AbandonChildTransitionLocked();
        }
    }

    private void AbandonChildTransitionLocked()
    {
        _childTransitionAbandoned = true;
        // Only a walk whose hook already returned with a deferral is stopped;
        // a hook still running keeps its synchronous walk intact.
        if (_deferredWalkScope is { } scope)
            scope.Abandoned = true;
    }

    /// <summary>The lifecycle hook currently running on this thread, if any.</summary>
    [ThreadStatic]
    private static LifecycleHookScope? t_lifecycleHookScope;

    private sealed class LifecycleHookScope(ComponentVMBase owner)
    {
        internal ComponentVMBase Owner { get; } = owner;
        internal volatile bool Abandoned;
    }

    /// <summary>
    /// Awaitable that resumes the awaiting walk on the owner's foreground
    /// dispatcher. A rejected schedule never escapes the awaiter: the walk resumes
    /// on the pool and faults with the scheduling error.
    /// </summary>
    private sealed class ForegroundResumption(ComponentVMBase owner) : INotifyCompletion
    {
        private ExceptionDispatchInfo? _failure;

        public ForegroundResumption GetAwaiter() => this;

        public bool IsCompleted => false;

        public void OnCompleted(Action continuation)
        {
            try
            {
                owner._dispatcher.Foreground.Schedule(continuation, static (_, resume) =>
                {
                    resume();
                    return Disposable.Empty;
                });
            }
            catch (Exception error)
            {
                _failure = ExceptionDispatchInfo.Capture(error);
                ThreadPool.QueueUserWorkItem(static resume => ((Action)resume!)(), continuation);
            }
        }

        public void GetResult() => _failure?.Throw();
    }

    /// <summary>
    /// Runs one lifecycle hook with a fresh deferral slot. A hook that throws
    /// after deferring completion abandons that deferral: its continuation never
    /// runs and its eventual fault is observed (ADR-0109), so the next transition
    /// starts clean.
    /// </summary>
    private void RunLifecycleHook(Action hook, LifecycleHookLease lease)
    {
        var scope = new LifecycleHookScope(this);
        lock (_gate)
        {
            _deferredLifecycleTask = null;
        }
        var previous = t_lifecycleHookScope;
        t_lifecycleHookScope = scope;
        try
        {
            hook();
        }
        catch
        {
            // Mark the walk abandoned before the hook's lease is released, so a
            // child settling on another thread drives no further child. Observe
            // the abandoned deferral's eventual fault.
            scope.Abandoned = true;
            var abandoned = TakeDeferredLifecycleTask();
            _ = abandoned?.ContinueWith(
                static completed => _ = completed.Exception,
                CancellationToken.None,
                TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously,
                TaskScheduler.Default);
            throw;
        }
        finally
        {
            t_lifecycleHookScope = previous;
            FinishLifecycleHook(lease);
        }

        lock (_gate)
        {
            // The hook returned. A walk it deferred to stops once disposal
            // starts, including a disposal that started while it ran.
            _deferredWalkScope = _deferredLifecycleTask is null ? null : scope;
            if (_deferredWalkScope is not null && _childTransitionAbandoned)
                scope.Abandoned = true;
        }
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
    IComponentVM IComponentVMInternals.OwnershipIdentity => this;
    void IComponentVMInternals.SetParent(IParentCompositeVM? parent) => Parent = parent;
    void IComponentVMInternals.SetIsCurrent(bool value) => IsCurrent = value;
    bool IComponentVMInternals.CommitIsCurrent(bool value) => CommitIsCurrent(value);
    void IComponentVMInternals.PublishIsCurrent() => NotifyPropertyChanged(nameof(IsCurrent));
    Task IComponentVMInternals.ConstructOrJoinAsync() => ConstructOrJoinAsync();
    Task IComponentVMInternals.JoinConstructAsync() => JoinConstructAsync();

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
            if (CommitIsCurrent(value)) NotifyPropertyChanged(nameof(IsCurrent));
        }
    }

    private bool CommitIsCurrent(bool value)
    {
        // Post-dispose guard: spec/02 invariant 3 — Disposed is terminal.
        // A selection change on an already-disposed VM is a silent no-op
        // (no INPC raise, no hub PropertyChangedMessage), mirroring Swift
        // (VMX-006). Reads the terminal state under the same _gate the
        // lifecycle-race guards use.
        if (IsDisposed()) return false;

        // Idempotent-set guard: spec/03-messages.md mandates that a property
        // assignment to the same value MUST NOT emit a PropertyChanged hub
        // message (PROP-002). The guard also avoids redundant INPC raises.
        if (_isCurrent == value) return false;
        _isCurrent = value;
        return true;
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
    /// Initializes the base with an empty <see cref="Hint"/>, the default the
    /// builders use (spec/10 §4).
    /// </summary>
    protected ComponentVMBase(
        string name,
        IMessageHub hub,
        IDispatcher dispatcher,
        Action? onConstruct = null,
        Action? onDestruct = null,
        bool background = false)
        : this(name, string.Empty, hub, dispatcher, onConstruct, onDestruct, background)
    {
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
        !_constructPublicationPending &&
        (_status == ConstructionStatus.Destructed || _status == ConstructionStatus.Constructed);

    /// <inheritdoc/>
    public bool CanDestruct() =>
        !_constructPublicationPending &&
        (_status == ConstructionStatus.Constructed || _status == ConstructionStatus.Destructed);

    /// <inheritdoc/>
    public bool CanReconstruct() =>
        !_constructPublicationPending && _status == ConstructionStatus.Constructed;

    // ── Lifecycle: Construct ────────────────────────────────────────────────
    /// <inheritdoc/>
    public void Construct()
    {
        LifecycleDelivery delivery;
        bool shouldDrain;
        lock (_gate)
        {
            // Idempotent: already Constructed → no-op (no message). A committed
            // Constructed whose publication is pending is still in flight.
            if (_status == ConstructionStatus.Constructed)
            {
                if (_constructPublicationPending)
                    throw new StatusTransitionException(_status, "construct");
                return;
            }

            // Validate the transition (will throw for illegal states like Disposed).
            LifecycleTransitionValidator.Require(_status, "construct");

            // Concurrency guard: cannot re-enter while in-flight.
            if (_inFlight)
                throw new StatusTransitionException(_status, "construct");
            _inFlight = true;

            // Emit Constructing synchronously so subscribers immediately observe the
            // transition starting; then run the actual work on the selected scheduler.
            delivery = QueueStatusDeliveryLocked(
                ConstructionStatus.Constructing,
                out shouldDrain);
        }
        try
        {
            DrainAndThrow(delivery, shouldDrain);
        }
        catch (Exception error)
        {
            RestoreStatusAfterPublicationFailure(ConstructionStatus.Destructed);
            FailInFlight(error);
            throw;
        }

        if (_background)
        {
            try
            {
                _dispatcher.Background.Schedule(Unit.Default, (_, _) =>
                {
                    // Dispose() may have run between scheduling and execution.
                    // Re-check the terminal state under _gate and abort if disposed
                    // (spec/02 invariant 3): no OnConstruct(), no marshalled emission.
                    var hookLease = TryClaimLifecycleHook(ConstructionStatus.Constructing);
                    if (hookLease is null)
                    {
                        ClearInFlight();
                        return Disposable.Empty;
                    }

                    try
                    {
                        RunLifecycleHook(OnConstruct, hookLease);
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
                        ScheduleForegroundLifecycle(() =>
                        {
                            try
                            {
                                SetStatus(ConstructionStatus.Destructed);
                            }
                            finally
                            {
                                FailInFlight(error);
                            }
                        }, ConstructionStatus.Destructed, error);
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
                    ScheduleForegroundLifecycle(() =>
                    {
                        try
                        {
                            SetStatus(ConstructionStatus.Constructed);
                        }
                        finally
                        {
                            ClearInFlight();
                        }
                    }, ConstructionStatus.Destructed);
                    return Disposable.Empty;
                });
            }
            catch (Exception error)
            {
                if (HasInFlightLifecycle())
                {
                    RestoreStatusAfterPublicationFailure(ConstructionStatus.Destructed);
                    FailInFlight(error);
                }
                throw;
            }
            // Return immediately — caller does not wait for background work.
        }
        else
        {
            var completionDeferred = false;
            try
            {
                var hookLease = TryClaimLifecycleHook(ConstructionStatus.Constructing);
                if (hookLease is null)
                    return;
                try
                {
                    RunLifecycleHook(OnConstruct, hookLease);
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
            if (_status == ConstructionStatus.Constructed && !_constructPublicationPending)
                return Task.CompletedTask;
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

    /// <summary>Waits for an in-flight construct without ever starting one.</summary>
    private Task JoinConstructAsync()
    {
        lock (_gate)
        {
            // A container whose Constructed state is committed but not yet
            // published is still in flight (spec/06 §5.1).
            return (_status == ConstructionStatus.Constructing && _inFlight) || _constructPublicationPending
                ? RegisterLifecycleWaiter().Task
                : Task.CompletedTask;
        }
    }

    private Task ConstructOrJoinAsync()
    {
        lock (_gate)
        {
            if (_status == ConstructionStatus.Constructed && !_constructPublicationPending)
                return Task.CompletedTask;
            if ((_status == ConstructionStatus.Constructing && _inFlight) || _constructPublicationPending)
                return RegisterLifecycleWaiter().Task;
        }

        return ConstructAsync();
    }

    // ── Lifecycle: Destruct ─────────────────────────────────────────────────
    /// <inheritdoc/>
    public void Destruct()
    {
        LifecycleDelivery delivery;
        bool shouldDrain;
        lock (_gate)
        {
            if (_status == ConstructionStatus.Destructed) return;

            LifecycleTransitionValidator.Require(_status, "destruct");

            if (_inFlight)
                throw new StatusTransitionException(_status, "destruct");
            _inFlight = true;

            // Emit Destructing synchronously so subscribers see the transition start;
            // the actual OnDestruct runs on the selected scheduler.
            delivery = QueueStatusDeliveryLocked(
                ConstructionStatus.Destructing,
                out shouldDrain);
        }
        try
        {
            DrainAndThrow(delivery, shouldDrain);
        }
        catch (Exception error)
        {
            RestoreStatusAfterPublicationFailure(ConstructionStatus.Constructed);
            FailInFlight(error);
            throw;
        }

        if (_background)
        {
            try
            {
                _dispatcher.Background.Schedule(Unit.Default, (_, _) =>
                {
                    // Dispose() may have run between scheduling and execution.
                    // Re-check the terminal state under _gate and abort if disposed
                    // (spec/02 invariant 3): no OnDestruct(), no marshalled emission.
                    var hookLease = TryClaimLifecycleHook(ConstructionStatus.Destructing);
                    if (hookLease is null)
                    {
                        ClearInFlight();
                        return Disposable.Empty;
                    }

                    try
                    {
                        RunLifecycleHook(OnDestruct, hookLease);
                    }
                    catch (Exception error)
                    {
                        // VMX-007: roll _status back to Constructed (marshalled onto the
                        // foreground per VMX-025; SetStatus re-checks Disposed under
                        // _gate) and clear the in-flight guard so a throwing background
                        // hook leaves the VM recoverable, then re-throw. C# async
                        // lifecycle waiters receive the same error only after that
                        // rollback publication (ADR-0109).
                        ScheduleForegroundLifecycle(() =>
                        {
                            try
                            {
                                SetStatus(ConstructionStatus.Constructed);
                            }
                            finally
                            {
                                FailInFlight(error);
                            }
                        }, ConstructionStatus.Constructed, error);
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
                    ScheduleForegroundLifecycle(() =>
                    {
                        try
                        {
                            SetStatus(ConstructionStatus.Destructed);
                        }
                        finally
                        {
                            ClearInFlight();
                        }
                    }, ConstructionStatus.Constructed);
                    return Disposable.Empty;
                });
            }
            catch (Exception error)
            {
                if (HasInFlightLifecycle())
                {
                    RestoreStatusAfterPublicationFailure(ConstructionStatus.Constructed);
                    FailInFlight(error);
                }
                throw;
            }
        }
        else
        {
            var completionDeferred = false;
            try
            {
                var hookLease = TryClaimLifecycleHook(ConstructionStatus.Destructing);
                if (hookLease is null)
                    return;
                try
                {
                    RunLifecycleHook(OnDestruct, hookLease);
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

    /// <summary>
    /// Joins a destruct already in flight without starting a second one
    /// (#754), or returns null when none is in flight. The check and the
    /// waiter registration are atomic under the lifecycle gate. The join
    /// completes or faults with that destruct, as its own
    /// <see cref="DestructAsync"/> caller observes it. A reconstruct in its
    /// destruct phase is joined too and settles Constructed, which the
    /// container walk reports as a child that did not reach Destructed.
    /// </summary>
    Task? IComponentVMInternals.TryJoinDestructAsync()
    {
        lock (_gate)
        {
            return _status == ConstructionStatus.Destructing && _inFlight
                ? RegisterLifecycleWaiter().Task
                : null;
        }
    }

    // ── Lifecycle: Reconstruct ──────────────────────────────────────────────
    /// <inheritdoc/>
    public void Reconstruct()
    {
        LifecycleDelivery delivery;
        bool shouldDrain;
        lock (_gate)
        {
            LifecycleTransitionValidator.Require(_status, "reconstruct");

            if (_inFlight)
                throw new StatusTransitionException(_status, "reconstruct");
            _inFlight = true;

            delivery = QueueStatusDeliveryLocked(
                ConstructionStatus.Destructing,
                out shouldDrain);
        }
        try
        {
            DrainAndThrow(delivery, shouldDrain);
        }
        catch (Exception error)
        {
            RestoreStatusAfterPublicationFailure(ConstructionStatus.Constructed);
            FailInFlight(error);
            throw;
        }

        var completionDeferred = false;
        try
        {
            var hookLease = TryClaimLifecycleHook(ConstructionStatus.Destructing);
            if (hookLease is null)
                return;
            try
            {
                RunLifecycleHook(OnDestruct, hookLease);
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
        if (IsDisposed())
            return false;
        try
        {
            SetStatus(ConstructionStatus.Constructing);
        }
        catch (Exception error)
        {
            RestoreStatusAfterPublicationFailure(ConstructionStatus.Destructed);
            FailInFlight(error);
            throw;
        }
        var hookLease = TryClaimLifecycleHook(ConstructionStatus.Constructing);
        if (hookLease is null)
            return false;
        try
        {
            RunLifecycleHook(OnConstruct, hookLease);
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
                try
                {
                    ScheduleForegroundLifecycle(() =>
                    {
                        if (IsDisposedOrAbandoned())
                        {
                            ObserveAbandoned(completed);
                            ClearInFlight();
                            return;
                        }

                        if (completed.Status != TaskStatus.RanToCompletion)
                        {
                            var published = true;
                            try { published = TrySetDeferredStatus(ConstructionStatus.Constructed); }
                            finally { FinishDeferredInFlight(completed, published); }
                            return;
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
                    }, ConstructionStatus.Constructed, deferredCompletion: completed);
                }
                catch
                {
                    // ScheduleForegroundLifecycle has already restored state and
                    // completed/faulted the public lifecycle waiter.
                }
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
    public virtual void Dispose() => DisposeAtHookBoundary(cascade: null, resumed: false);

    /// <summary>
    /// Disposes a container: its LIFE-013 child cascade, then this VM, at the
    /// same admitted-hook boundary as <see cref="Dispose()"/> (LIFE-015). With
    /// no foreign hook running, hook admission closes and the children are
    /// disposed before this VM publishes Disposed. A foreign disposal of a VM
    /// whose hook is admitted publishes Disposed, then waits for the hook's
    /// lease (or, when the wait would close a cycle, defers to it) before the
    /// cascade and the remaining cleanup run. The caller must hold no lock
    /// that the hook may need.
    /// </summary>
    private protected void DisposeWithChildren(IEnumerable<IDisposable?> children)
        => DisposeAtHookBoundary(() => DisposeChildren(children), resumed: false);

    /// <param name="cascade">The container's child cascade, if any.</param>
    /// <param name="resumed">
    /// <see langword="true"/> only for the call that publishes Disposed after
    /// this disposal already ran its cascade.
    /// </param>
    private void DisposeAtHookBoundary(Func<ExceptionDispatchInfo?>? cascade, bool resumed)
    {
        ExceptionDispatchInfo? firstError = null;
        bool shouldDrain;
        LifecycleDelivery? delivery;
        LifecycleHookLease? hookLease;
        var cascadeFirst = false;
        lock (_gate)
        {
            if (_status == ConstructionStatus.Disposed) return;
            // While the member cascade runs, a further disposal on any thread
            // is a no-op: the first call disposes the members, then publishes
            // Disposed (spec/02 §7.1).
            if (_memberCascadeRunning && !resumed) return;

            // A pending child walk is abandoned before any child is disposed.
            AbandonChildTransitionLocked();
            // Members follow the container cascade at the same hook boundary:
            // a container's children first, then the members (LIFE-018).
            cascade = WithMemberCascadeLocked(cascade);
            hookLease = _activeHookLease;
            if (cascade is not null &&
                (hookLease is null ||
                 hookLease.OwnerThreadId == Environment.CurrentManagedThreadId))
            {
                // No foreign hook is running, and none may start while the
                // children are disposed: the cascade keeps its depth-first
                // order ahead of this VM's terminal publication.
                _hookAdmissionClosed = true;
                cascadeFirst = true;
                delivery = null;
                shouldDrain = false;
            }
            else
            {
                delivery = BeginTerminalPublicationLocked(out shouldDrain);
            }
        }
        if (cascadeFirst)
        {
            var cascadeError = cascade!();
            try { DisposeAtHookBoundary(cascade: null, resumed: true); }
            catch (Exception error) { cascadeError ??= ExceptionDispatchInfo.Capture(error); }
            cascadeError?.Throw();
            return;
        }

        LifecycleDelivery BeginTerminalPublicationLocked(out bool drain)
        {
            // Terminal publication is best-effort: an observer failure must not
            // prevent the remaining channels or mandatory cleanup from running.
            _status = ConstructionStatus.Disposed;
            _constructPublicationPending = false;
            var notifyTrigger = !_triggerDisposed;
            var statusDelivery = QueueLifecycleDeliveryLocked(() =>
            {
                FirstFailure.Capture(ref firstError, () =>
                    _hub.Send(ConstructionStatusChangedMessage.Create(
                        this, Name, ConstructionStatus.Disposed)));
                FirstFailure.Capture(ref firstError, () =>
                    RaisePropertyChanged(nameof(Status)));
                FirstFailure.Capture(ref firstError, () =>
                    RaisePropertyChanged(nameof(IsConstructed)));
                if (notifyTrigger)
                    FirstFailure.Capture(ref firstError, () =>
                        _statusTrigger.OnNext(Unit.Default));
            }, out drain);

            var waiterDelivery = QueueSettledLifecycleWaitersLocked(out var waiterShouldDrain);
            drain |= waiterShouldDrain;
            return waiterDelivery ?? statusDelivery;
        }

        DrainAndThrow(delivery!, shouldDrain);
        void FinishDisposal()
        {
            // A container reaches its child cascade only after the admitted
            // foreign hook released its lease (LIFE-013 within LIFE-015).
            if (cascade is not null)
                firstError ??= cascade();

            // Subclass cleanup hook, matching Python `_on_dispose` (base.py) and
            // TS `_onDispose` (componentVMBase.ts). Runs immediately after the
            // status reaches Disposed and *before* the status trigger is
            // completed, so a subclass override can still publish a final
            // status value or touch hub-published subjects during cleanup.
            FirstFailure.Capture(ref firstError, OnDispose);
            FirstFailure.Capture(ref firstError, DisposeOwnedResources);

            // Admit trigger teardown under _gate, then invoke Subject observers in
            // lifecycle-delivery order outside it. The terminal OnNext admitted
            // above therefore always precedes OnCompleted, including re-entrant
            // disposal while another lifecycle notification is being drained.
            lock (_gate)
            {
                if (!_triggerDisposed)
                {
                    _triggerDisposed = true;
                    delivery = QueueLifecycleDeliveryLocked(() =>
                    {
                        FirstFailure.Capture(ref firstError, _statusTrigger.OnCompleted);
                        FirstFailure.Capture(ref firstError, _statusTrigger.Dispose);
                    }, out shouldDrain);
                }
                else
                {
                    shouldDrain = false;
                    delivery = null;
                }
            }
            if (delivery is not null)
                DrainAndThrow(delivery, shouldDrain);

            foreach (var command in new IDisposable?[]
                     {
                         _selectCommand as IDisposable,
                         _deselectCommand as IDisposable,
                         _selectNextCommand as IDisposable,
                         _selectPreviousCommand as IDisposable,
                         _reconstructCommand as IDisposable,
                     })
            {
                if (command is not null)
                    FirstFailure.Capture(ref firstError, command.Dispose);
            }

            firstError?.Throw();
        }

        if (hookLease is not null &&
            hookLease.OwnerThreadId != Environment.CurrentManagedThreadId)
        {
            var caller = Environment.CurrentManagedThreadId;
            if (RegisterLifecycleWait(caller, hookLease.OwnerThreadId))
            {
                lock (_gate)
                {
                    if (ReferenceEquals(_activeHookLease, hookLease))
                    {
                        hookLease.DeferredDisposal = FinishDisposal;
                        return;
                    }
                }
            }
            else
            {
                try { hookLease.Completed.Wait(); }
                finally
                {
                    lock (s_lifecycleWaitGraphGate)
                        s_lifecycleWaitGraph.Remove(caller);
                }
            }
        }
        FinishDisposal();
    }

    /// <summary>
    /// Takes the registered members and appends their disposal to
    /// <paramref name="cascade"/>. Returns <paramref name="cascade"/> unchanged
    /// when no member is registered.
    /// </summary>
    private Func<ExceptionDispatchInfo?>? WithMemberCascadeLocked(Func<ExceptionDispatchInfo?>? cascade)
    {
        _membersTaken = true;
        if (_members.Count == 0) return cascade;
        IComponentVM[] members = [.. _members];
        _members.Clear();
        // Set before the first child or member is disposed. It is never
        // cleared: once this disposal publishes Disposed, every later call
        // returns at the terminal check anyway.
        _memberCascadeRunning = true;
        return () =>
        {
            var firstError = cascade?.Invoke();
            var memberError = DisposeChildren(members);
            return firstError ?? memberError;
        };
    }

    // ── Selection predicates ────────────────────────────────────────────────
    /// <inheritdoc/>
    public bool CanSelect() =>
        Parent is not null &&
        Parent.SupportsChildSelection &&
        !ReferenceEquals(Parent.CurrentChild, this) &&
        _status == ConstructionStatus.Constructed;

    /// <inheritdoc/>
    public void Select()
    {
        // A disposed VM's selection calls are silent no-ops (spec/02 §3).
        if (_status == ConstructionStatus.Disposed) return;
        Parent?.SelectChild(this);
    }

    /// <inheritdoc/>
    public bool CanDeselect() =>
        _status != ConstructionStatus.Disposed &&
        Parent is not null &&
        ReferenceEquals(Parent.CurrentChild, this);

    /// <inheritdoc/>
    public void Deselect()
    {
        if (_status == ConstructionStatus.Disposed) return;
        Parent?.DeselectChild(this);
    }

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

    private LifecycleHookLease? TryClaimLifecycleHook(ConstructionStatus expectedStatus)
    {
        lock (_gate)
        {
            if (_status != expectedStatus || _activeHookLease is not null || _hookAdmissionClosed)
                return null;
            return _activeHookLease = new LifecycleHookLease();
        }
    }

    private void FinishLifecycleHook(LifecycleHookLease lease)
    {
        Action? deferredDisposal;
        lock (_gate)
        {
            if (ReferenceEquals(_activeHookLease, lease))
                _activeHookLease = null;
            deferredDisposal = lease.DeferredDisposal;
            lease.DeferredDisposal = null;
        }
        lease.Completed.Set();
        if (deferredDisposal is not null)
        {
            // A cycle-broken Dispose call has no synchronous caller left to
            // receive this deferred failure. Never let it replace an exception
            // already propagating from the admitted hook.
            try { deferredDisposal(); }
            catch (Exception) { }
        }
    }

    private void ClearInFlight()
    {
        bool shouldDrain;
        LifecycleDelivery? delivery;
        lock (_gate)
        {
            _inFlight = false;
            delivery = QueueSettledLifecycleWaitersLocked(out shouldDrain);
        }
        if (delivery is not null) DrainAndThrow(delivery, shouldDrain);
    }

    private void FailInFlight(Exception error)
    {
        bool shouldDrain;
        LifecycleDelivery delivery;
        lock (_gate)
        {
            _inFlight = false;
            var waiters = _lifecycleWaiters.ToArray();
            _lifecycleWaiters.Clear();
            delivery = QueueLifecycleDeliveryLocked(() =>
            {
                foreach (var waiter in waiters)
                    waiter.TrySetException(error);
            }, out shouldDrain);
        }
        DrainAndThrow(delivery, shouldDrain);
    }

    private void FinishInFlightFrom(Task completed)
    {
        if (completed.IsCanceled)
        {
            bool shouldDrain;
            LifecycleDelivery delivery;
            lock (_gate)
            {
                _inFlight = false;
                var waiters = _lifecycleWaiters.ToArray();
                _lifecycleWaiters.Clear();
                delivery = QueueLifecycleDeliveryLocked(() =>
                {
                    foreach (var waiter in waiters)
                        waiter.TrySetCanceled();
                }, out shouldDrain);
            }
            DrainAndThrow(delivery, shouldDrain);
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
                try
                {
                    ScheduleForegroundLifecycle(() =>
                    {
                        var published = true;
                        try
                        {
                            published = TrySetDeferredStatus(completed.Status == TaskStatus.RanToCompletion
                                ? successStatus
                                : rollbackStatus);
                        }
                        finally
                        {
                            FinishDeferredInFlight(completed, published);
                        }
                    }, rollbackStatus, deferredCompletion: completed);
                }
                catch
                {
                    // ScheduleForegroundLifecycle has already restored state and
                    // completed/faulted the public lifecycle waiter.
                }
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
        bool shouldDrain;
        LifecycleDelivery delivery;
        lock (_gate)
        {
            if (_inFlight || !IsSettled(_status)) return;
            _lifecycleWaiters.Remove(waiter);
            delivery = QueueLifecycleDeliveryLocked(
                () => waiter.TrySetResult(true),
                out shouldDrain);
        }
        DrainAndThrow(delivery, shouldDrain);
    }

    private LifecycleDelivery? QueueSettledLifecycleWaitersLocked(
        out bool shouldDrain)
    {
        shouldDrain = false;
        if (!IsSettled(_status) || _lifecycleWaiters.Count == 0) return null;

        var waiters = _lifecycleWaiters.ToArray();
        _lifecycleWaiters.Clear();
        return QueueLifecycleDeliveryLocked(() =>
        {
            foreach (var waiter in waiters)
                waiter.TrySetResult(true);
        }, out shouldDrain);
    }

    private static bool IsSettled(ConstructionStatus status) =>
        status is ConstructionStatus.Constructed or
            ConstructionStatus.Destructed or
            ConstructionStatus.Disposed;

    private void SetStatus(ConstructionStatus newStatus)
    {
        LifecycleDelivery delivery;
        bool shouldDrain;
        lock (_gate)
        {
            if (_status == ConstructionStatus.Disposed) return;
            delivery = QueueStatusDeliveryLocked(newStatus, out shouldDrain);
        }
        DrainAndThrow(delivery, shouldDrain);
    }

    /// <summary>
    /// Publishes the terminal status of a deferred child walk unless disposal
    /// has started: an abandoned walk publishes nothing before Disposed (#755).
    /// Returns false when the status was dropped; the decision is made under
    /// <c>_gate</c>, together with the publication.
    /// </summary>
    private bool TrySetDeferredStatus(ConstructionStatus newStatus)
    {
        LifecycleDelivery delivery;
        bool shouldDrain;
        lock (_gate)
        {
            if (_status == ConstructionStatus.Disposed || _childTransitionAbandoned) return false;
            delivery = QueueStatusDeliveryLocked(newStatus, out shouldDrain);
        }
        DrainAndThrow(delivery, shouldDrain);
        return true;
    }

    private bool IsDisposedOrAbandoned()
    {
        lock (_gate)
        {
            return _status == ConstructionStatus.Disposed || _childTransitionAbandoned;
        }
    }

    /// <summary>
    /// Releases the in-flight guard after a deferred walk settles. A published
    /// status settles the waiters from the walk's outcome. A dropped status
    /// (disposal started) only clears the guard: Dispose completes the waiters
    /// on Disposed, so an abandoned walk's failure never reaches them (#755).
    /// </summary>
    private void FinishDeferredInFlight(Task completed, bool published)
    {
        if (published)
        {
            FinishInFlightFrom(completed);
            return;
        }
        ObserveAbandoned(completed);
        ClearInFlight();
    }

    /// <summary>Observes an abandoned walk's fault so it is never unobserved (ADR-0109).</summary>
    private static void ObserveAbandoned(Task completed) => _ = completed.Exception;

    private void RestoreStatusAfterPublicationFailure(ConstructionStatus status)
    {
        try { SetStatus(status); }
        catch { /* The original transition publication failure remains primary. */ }
    }

    private void ScheduleForegroundLifecycle(
        Action action,
        ConstructionStatus rollback,
        Exception? primaryFailure = null,
        Task? deferredCompletion = null)
    {
        try
        {
            _dispatcher.Foreground.Schedule(Unit.Default, (_, _) =>
            {
                action();
                return Disposable.Empty;
            });
        }
        catch (Exception schedulingFailure)
        {
            if (deferredCompletion is not null && IsDisposedOrAbandoned())
            {
                // An abandoned walk restores no status; Dispose completes the
                // waiters on Disposed (#755).
                ObserveAbandoned(deferredCompletion);
                ClearInFlight();
            }
            else if (HasInFlightLifecycle())
            {
                RestoreStatusAfterPublicationFailure(rollback);
                if (deferredCompletion is not null &&
                    deferredCompletion.Status != TaskStatus.RanToCompletion)
                    FinishInFlightFrom(deferredCompletion);
                else
                    FailInFlight(primaryFailure ?? schedulingFailure);
            }
            if (primaryFailure is not null)
                throw new AggregateException(primaryFailure, schedulingFailure);
            throw;
        }
    }

    private bool HasInFlightLifecycle()
    {
        lock (_gate) return _inFlight;
    }

    /// <summary>
    /// Test-only: whether a transition is still in flight, for example a
    /// container whose Constructed state is committed but not yet published.
    /// </summary>
    internal bool HasInFlightLifecycleForTesting => HasInFlightLifecycle();

    private LifecycleDelivery QueueStatusDeliveryLocked(
        ConstructionStatus newStatus,
        out bool shouldDrain)
    {
        _status = newStatus;
        // The publication starts: a committed Constructed is no longer pending,
        // so subscribers observe a completed transition.
        _constructPublicationPending = false;
        var message = ConstructionStatusChangedMessage.Create(this, Name, newStatus);
        var notifyTrigger = !_triggerDisposed;
        return QueueLifecycleDeliveryLocked(() =>
        {
            _hub.Send(message);

            // Status and IsConstructed are computed/read-only, so they raise INPC only;
            // no PropertyChangedMessage on the hub (spec 03-messages.md restricts hub
            // PropertyChangedMessage to setter-assigned properties).
            RaisePropertyChanged(nameof(Status));
            RaisePropertyChanged(nameof(IsConstructed));

            if (notifyTrigger)
                _statusTrigger.OnNext(Unit.Default);
        }, out shouldDrain);
    }

    private LifecycleDelivery QueueLifecycleDeliveryLocked(
        Action action,
        out bool shouldDrain)
    {
        var delivery = new LifecycleDelivery(action);
        _lifecycleDeliveries.Enqueue(delivery);
        shouldDrain = !_lifecycleDeliveryDraining;
        if (shouldDrain)
        {
            _lifecycleDeliveryDraining = true;
            _lifecycleDeliveryDrainerThreadId = Environment.CurrentManagedThreadId;
        }
        return delivery;
    }

    private void DrainAndThrow(LifecycleDelivery delivery, bool shouldDrain)
    {
        if (shouldDrain)
        {
            DrainIfOwner(true);
        }
        else
        {
            AwaitLifecycleDeliveryUnlessCyclic(delivery);
        }
        if (delivery.Completed.IsSet)
            delivery.Failure?.Throw();
    }

    private void DrainIfOwner(bool shouldDrain)
    {
        if (!shouldDrain) return;

        while (true)
        {
            LifecycleDelivery delivery;
            lock (_gate)
            {
                if (_lifecycleDeliveries.Count == 0)
                {
                    _lifecycleDeliveryDraining = false;
                    _lifecycleDeliveryDrainerThreadId = 0;
                    return;
                }
                delivery = _lifecycleDeliveries.Dequeue();
            }

            try
            {
                delivery.Action();
            }
            catch (Exception error)
            {
                delivery.Failure = ExceptionDispatchInfo.Capture(error);
            }
            finally
            {
                delivery.Completed.Set();
            }
        }
    }

    private void AwaitLifecycleDeliveryUnlessCyclic(LifecycleDelivery delivery)
    {
        if (delivery.Completed.IsSet) return;
        var caller = Environment.CurrentManagedThreadId;
        int owner;
        lock (_gate) owner = _lifecycleDeliveryDrainerThreadId;
        if (owner == 0 || owner == caller) return;
        if (RegisterLifecycleWait(caller, owner)) return;
        try { delivery.Completed.Wait(); }
        finally
        {
            lock (s_lifecycleWaitGraphGate)
                s_lifecycleWaitGraph.Remove(caller);
        }
    }

    private static bool RegisterLifecycleWait(int caller, int owner)
    {
        lock (s_lifecycleWaitGraphGate)
        {
            s_lifecycleWaitGraph[caller] = owner;
            var cursor = owner;
            var visited = new HashSet<int>();
            while (cursor != caller && visited.Add(cursor) &&
                   s_lifecycleWaitGraph.TryGetValue(cursor, out var next))
                cursor = next;
            if (cursor != caller) return false;
            s_lifecycleWaitGraph.Remove(caller);
            return true;
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
        ExceptionDispatchInfo? firstError = null;
        FirstFailure.Capture(
            ref firstError,
            () => _hub.Send(
                PropertyChangedMessage<IComponentVM>.Create(this, Name, propertyName)));
        FirstFailure.Capture(ref firstError, () => RaisePropertyChanged(propertyName));
        firstError?.Throw();
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

    /// <summary>
    /// Registers a member view-model that this VM disposes before it publishes
    /// <see cref="ConstructionStatus.Disposed"/> (spec/02 §7.1, ADR-0162), and
    /// returns it for inline field assignment:
    /// <code>
    /// _chart = OwnMember(new ChartVM(hub, dispatcher));
    /// </code>
    /// <see cref="Dispose()"/> disposes the members in registration order, after a
    /// container's own children, so the cascade stays depth-first. Every member is
    /// attempted. The first failure is rethrown after this VM's mandatory teardown.
    /// While the members are disposed, a further <see cref="Dispose()"/> on any
    /// thread returns at once and does nothing; the first call publishes
    /// <see cref="ConstructionStatus.Disposed"/> after the last member.
    /// A member registered after this VM's disposal started is disposed at once,
    /// and a failure from that disposal is thrown from this call.
    /// A member is not a container child: registration sets no parent link and
    /// does not construct it. Use
    /// <see cref="TransitionChildrenAsync(IEnumerable{IComponentVM}, bool, Action?)"/>
    /// to construct and destruct members.
    /// </summary>
    /// <typeparam name="T">The member's type.</typeparam>
    /// <param name="member">The member view-model.</param>
    /// <returns><paramref name="member"/>.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="member"/> is null.</exception>
    /// <exception cref="InvalidOperationException">
    /// <paramref name="member"/> is this VM or a forwarding decorator of it.
    /// </exception>
    protected T OwnMember<T>(T member) where T : IComponentVM
    {
        ThrowHelper.ThrowIfNull(member, nameof(member));
        if (ReferenceEquals(member.GetOwnershipIdentity(), this))
            throw new InvalidOperationException($"View-model '{Name}' cannot own itself as a member.");

        bool disposeNow;
        lock (_gate)
        {
            disposeNow = _membersTaken;
            if (!disposeNow)
                _members.Add(member);
        }
        if (disposeNow)
            member.Dispose();
        return member;
    }

    /// <summary>Registers a resource for a forwarding decorator of this VM (ADR-0151).</summary>
    internal T OwnForAlias<T>(T resource) where T : IDisposable => Own(resource);

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
