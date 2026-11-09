using System.Collections;
using System.Collections.Specialized;
using System.Reactive.Disposables;
using System.Runtime.ExceptionServices;
using VMx.Collections;
using VMx.Components;
using VMx.Internal;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;

namespace VMx.Composites;

internal static class CompositeCurrentChangeCoordinator
{
    internal static object Gate { get; } = new();
}

/// <summary>
/// The construct walk shared by composites and groups: the membership
/// snapshot, then (with auto-construct-on-add) each child added while the walk
/// runs (spec/02 §6, spec/06 §5.1).
/// </summary>
internal static class ContainerConstructWalk
{
    /// <summary>
    /// Enumerates lazily, so the walk sees children added while it waits on a
    /// background child. The walk never starts a late child. A late child
    /// whose add registered a start record in this <paramref name="walk"/> is
    /// added to <paramref name="joined"/>: the walk waits for the add's start
    /// attempt, then joins it, so one whose own construction failed rolls the
    /// container back. A late child without a record was not started by an
    /// add, so the walk skips it. The scope stays open after the last scan:
    /// <see cref="SealOrNextLate"/> joins a child added after it, and
    /// commits the Constructed state under the membership gate.
    /// </summary>
    internal static IEnumerable<IComponentVM> Enumerate<VM>(
        Func<VM[]> snapshot,
        bool includeLate,
        ISet<IComponentVM> joined,
        ISet<IComponentVM> visited,
        LateChildStarts.Walk walk)
        where VM : class, IComponentVM
    {
        var initial = snapshot();
        visited.UnionWith(initial);
        foreach (var child in initial) yield return child;
        if (!includeLate) yield break;
        while (true)
        {
            var late = snapshot().FirstOrDefault(child => !visited.Contains(child));
            if (late is null) yield break;
            visited.Add(late);
            if (!walk.Take(late)) continue;
            joined.Add(late);
            yield return late;
        }
    }

    /// <summary>
    /// The construct walk's commit step. Under <paramref name="gate"/>, the
    /// membership gate, it returns the next unvisited member that an add
    /// started (it has a start record in <paramref name="walk"/>), which the
    /// walk then joins. Without one, it commits the Constructed state through
    /// <paramref name="commit"/> in the same gated section, so an add reads
    /// either Constructing (and is joined) or Constructed, then ends the walk's
    /// scope and returns null (spec/02 §6, spec/06 §5.1).
    /// </summary>
    internal static IComponentVM? SealOrNextLate<VM>(
        object gate,
        IEnumerable<VM> members,
        ISet<IComponentVM> joined,
        ISet<IComponentVM> visited,
        LateChildStarts.Walk walk,
        Action commit)
        where VM : class, IComponentVM
    {
        lock (gate)
        {
            foreach (var child in members)
            {
                if (!visited.Add(child)) continue;
                if (!walk.Take(child)) continue;
                joined.Add(child);
                return child;
            }
            commit();
        }
        walk.End();
        return null;
    }
}

/// <summary>
/// The collection-change delivery, auto-construct-on-add, and late-child start
/// steps shared by composites and groups (spec/01 §1.4, spec/06 §5.1). Each
/// container member only forwards here with its own event, flags, start
/// records, and disposal check.
/// </summary>
internal static class ContainerMembership
{
    /// <summary>
    /// Raises the local event through <paramref name="handler"/>, then
    /// publishes one equivalent <see cref="CollectionChangedMessage{T}"/> sent
    /// by <paramref name="container"/> through the hub's ordinary <c>Send</c>
    /// (spec/01 §1.4, ADR-0142). <paramref name="canPublish"/> runs after the
    /// local handlers, so a container they dispose publishes nothing.
    /// </summary>
    internal static void DeliverCollectionChanged<TContainer, VM>(
        TContainer container,
        NotifyCollectionChangedEventHandler? handler,
        NotifyCollectionChangedEventArgs args,
        Func<TContainer, bool> canPublish)
        where TContainer : ComponentVMBase
        where VM : class, IComponentVM
    {
        // A throwing local handler must not suppress the hub message for the
        // committed change (spec/01 §1.4, #723): send it, then rethrow.
        // The first failure wins, as in NotifyPropertyChanged and Python.
        ExceptionDispatchInfo? firstFailure = null;
        try { handler?.Invoke(container, args); }
        catch (Exception error) { firstFailure = ExceptionDispatchInfo.Capture(error); }
        if (canPublish(container))
        {
            try { container.Hub.Send(CollectionChangedMessage<VM>.From(container, args)); }
            catch (Exception error) { firstFailure ??= ExceptionDispatchInfo.Capture(error); }
        }
        firstFailure?.Throw();
    }

    /// <summary>
    /// Constructs <paramref name="item"/> on add when
    /// <paramref name="autoConstructOnAdd"/> is set, the
    /// <paramref name="container"/> is Constructed, and the item is not.
    /// </summary>
    internal static void MaybeAutoConstruct<VM>(
        ComponentVMBase container,
        bool autoConstructOnAdd,
        VM item)
        where VM : class, IComponentVM
    {
        if (!autoConstructOnAdd) return;
        // While Constructing, only an add with a start record starts its
        // child; any other child is in the construct walk's snapshot.
        var status = container.Status;
        if (status != ConstructionStatus.Constructed) return;
        if (item.Status == ConstructionStatus.Constructed) return;
        item.Construct();
    }

    /// <summary>
    /// Called under the gate as an add attaches <paramref name="item"/>: an
    /// add that will auto-start the child while the
    /// <paramref name="container"/> is Constructing registers a start record
    /// the construct walk waits on.
    /// </summary>
    internal static LateChildStarts.Record? AttachLateStartLocked<VM>(
        ComponentVMBase container,
        LateChildStarts lateStarts,
        bool autoConstructOnAdd,
        VM item)
        where VM : class, IComponentVM
        => lateStarts.AttachLocked(
            item, autoConstructOnAdd && container.Status == ConstructionStatus.Constructing);

    /// <summary>The add's auto-construct of a child it attached with <paramref name="record"/>.</summary>
    internal static void AutoConstructAttached<VM>(
        ComponentVMBase container,
        LateChildStarts lateStarts,
        bool autoConstructOnAdd,
        VM item,
        LateChildStarts.Record? record)
        where VM : class, IComponentVM
    {
        if (record is null)
        {
            MaybeAutoConstruct(container, autoConstructOnAdd, item);
            return;
        }
        // The construct walk never starts a late child; it waits for this
        // attempt, then joins the child (spec/06 §5.1). The record is done
        // before this add publishes or ends its transaction.
        try
        {
            lateStarts.Probe(item, LateChildStage.Attached);
            if (item.Status == ConstructionStatus.Destructed) item.Construct();
        }
        finally
        {
            record.MarkDone();
            if (container.Status != ConstructionStatus.Constructing) lateStarts.Remove(item, record);
        }
    }
}

/// <summary>
/// The ref-counted collection-change batch shared by composites and groups
/// (spec v1.1). A change inside an open batch only marks it dirty; the
/// outermost close delivers one <c>Reset</c> if any change occurred.
/// </summary>
internal sealed class ContainerBatch
{
    private readonly Action<NotifyCollectionChangedEventArgs> _deliver;
    private int _depth;
    private bool _dirty;

    /// <param name="deliver">The container's local-event and hub delivery.</param>
    internal ContainerBatch(Action<NotifyCollectionChangedEventArgs> deliver) => _deliver = deliver;

    /// <summary>Opens one batch level; disposing the handle closes it once.</summary>
    internal IDisposable Enter()
    {
        _depth++;
        return new Handle(this);
    }

    /// <summary>Delivers <paramref name="args"/> now, or marks an open batch dirty.</summary>
    internal void Raise(NotifyCollectionChangedEventArgs args)
    {
        if (_depth > 0)
        {
            _dirty = true;
            return;
        }
        _deliver(args);
    }

    private void Exit()
    {
        _depth--;
        if (_depth == 0 && _dirty)
        {
            _dirty = false;
            _deliver(new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Reset));
        }
    }

    /// <summary>The handle <see cref="Enter"/> returns.</summary>
    private sealed class Handle : IDisposable
    {
        private readonly ContainerBatch _owner;
        private bool _disposed;

        internal Handle(ContainerBatch owner) => _owner = owner;

        /// <summary>Closes the batch and emits a Reset event if mutations occurred.</summary>
        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            _owner.Exit();
        }
    }
}

/// <summary>Test-only probe points of <see cref="LateChildStarts"/>.</summary>
internal enum LateChildStage
{
    /// <summary>An add attached the child with a start record and has not started it.</summary>
    Attached,

    /// <summary>The walk waits for an add to finish its start attempt.</summary>
    WalkWaitingOnAdd,

    /// <summary>A construct walk ended its scope (the probe's child is the container).</summary>
    WalkEnded,
}

/// <summary>
/// Start records of the children that an auto-construct-on-add attaches
/// while the container is Constructing (spec/06 §5.1). The add attaches the
/// child under the membership gate and starts it only after it releases the
/// gate, so the construct walk can pull the child first. The add registers a
/// record in the current walk's scope as it attaches the child, and marks it
/// done right after its construct attempt. The walk never starts a late
/// child: it waits for that attempt, then joins the child. Each walk owns its
/// scope, so a stale walk (abandoned, failed, or no longer current) never
/// takes or clears another walk's records, and a scope's records go with it.
/// </summary>
internal sealed class LateChildStarts
{
    private readonly object _gate = new();
    private Walk? _current;

    /// <summary>
    /// Test-only seam: runs at each <see cref="LateChildStage"/>. Production
    /// code never sets it.
    /// </summary>
    internal Action<IComponentVM, LateChildStage>? ProbeForTesting { get; set; }

    /// <summary>One add's start attempt of its child.</summary>
    internal sealed class Record
    {
        private readonly TaskCompletionSource<bool> _attempted =
            new(TaskCreationOptions.RunContinuationsAsynchronously);

        /// <summary>The walk scope the record was registered in, if any.</summary>
        internal Walk? Scope { get; init; }

        /// <summary>Completes once the add's construct attempt returned or threw.</summary>
        internal Task Attempted => _attempted.Task;

        internal void MarkDone() => _attempted.TrySetResult(true);
    }

    /// <summary>One construct walk's scope of start records.</summary>
    internal sealed class Walk
    {
        private readonly LateChildStarts _owner;
        private readonly IComponentVM _container;
        private readonly Dictionary<IComponentVM, Record> _records =
            new(ComponentVMBase.ChildReferenceComparer.Instance);
        // The records this walk took; only the sequential walk reads it.
        private readonly Dictionary<IComponentVM, Record> _taken =
            new(ComponentVMBase.ChildReferenceComparer.Instance);
        private bool _ended;

        internal Walk(LateChildStarts owner, IComponentVM container)
        {
            _owner = owner;
            _container = container;
        }

        /// <summary>Under the owner's lock: registers or drops a child's record.</summary>
        internal void SetLocked(IComponentVM child, Record? record)
        {
            if (_ended) return;
            if (record is null) _records.Remove(child);
            else _records[child] = record;
        }

        /// <summary>Under the owner's lock: removes a record if it is still the child's.</summary>
        internal void RemoveLocked(IComponentVM child, Record record)
        {
            if (_records.TryGetValue(child, out var registered) && ReferenceEquals(registered, record))
                _records.Remove(child);
        }

        /// <summary>Takes the record of a late child this walk visits.</summary>
        internal bool Take(IComponentVM child)
        {
            Record? record;
            lock (_owner._gate)
            {
                if (!_records.TryGetValue(child, out record)) return false;
                _records.Remove(child);
            }
            _taken[child] = record;
            return true;
        }

        /// <summary>Ends this walk's scope; another walk's scope is never touched.</summary>
        internal void End()
        {
            lock (_owner._gate)
            {
                if (_ended) return;
                _ended = true;
                _records.Clear();
                if (ReferenceEquals(_owner._current, this)) _owner._current = null;
            }
            _owner.Probe(_container, LateChildStage.WalkEnded);
        }

        /// <summary>
        /// The walk's join of a joined child: a late child is joined after its
        /// add's start attempt; a population child is joined at once.
        /// </summary>
        internal Task Join(IComponentVM child)
            => _taken.TryGetValue(child, out var record)
                ? JoinAfterAttemptAsync(child, record)
                : child.JoinConstructAsync();

        private Task JoinAfterAttemptAsync(IComponentVM child, Record record)
        {
            if (record.Attempted.IsCompleted) return child.JoinConstructAsync();
            _owner.Probe(child, LateChildStage.WalkWaitingOnAdd);
            return JoinAfterPendingAttemptAsync(child, record);
        }

        private static async Task JoinAfterPendingAttemptAsync(IComponentVM child, Record record)
        {
            await record.Attempted.ConfigureAwait(false);
            await child.JoinConstructAsync().ConfigureAwait(false);
        }
    }

    /// <summary>
    /// Starts a construct walk's scope; call it before the walk's initial
    /// snapshot. An older walk's scope stops being current.
    /// </summary>
    internal Walk BeginWalk(IComponentVM container)
    {
        var walk = new Walk(this, container);
        lock (_gate) _current = walk;
        return walk;
    }

    /// <summary>
    /// Called under the membership gate as an add attaches
    /// <paramref name="child"/>. When the add will start the child
    /// (auto-construct-on-add while Constructing), returns its record and
    /// registers it in the current walk's scope, if any; otherwise drops any
    /// earlier record of that child from that scope.
    /// </summary>
    internal Record? AttachLocked(IComponentVM child, bool willStart)
    {
        lock (_gate)
        {
            var scope = _current;
            var record = willStart ? new Record { Scope = scope } : null;
            scope?.SetLocked(child, record);
            return record;
        }
    }

    /// <summary>Removes <paramref name="record"/> from its scope if it is still <paramref name="child"/>'s.</summary>
    internal void Remove(IComponentVM child, Record? record)
    {
        if (record?.Scope is not { } scope) return;
        lock (_gate) scope.RemoveLocked(child, record);
    }

    internal void Probe(IComponentVM child, LateChildStage stage)
        => ProbeForTesting?.Invoke(child, stage);
}

/// <summary>
/// Abstract base for all CompositeVM variants.  Implements <see cref="ICompositeVM{VM}"/>
/// on top of <see cref="ComponentVMBase"/>: ordered child collection with
/// <see cref="INotifyCollectionChanged"/> events, <see cref="Current"/> selection,
/// and coordinated Construct / Destruct / Dispose for the child hierarchy.
///
/// See spec/06-composite-vm.md.
/// </summary>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public abstract class CompositeVMBase<VM> : ComponentVMBase, ICompositeVM<VM>,
    IParentCompositeVM, IObservableMembershipSource<VM>
    where VM : class, IComponentVM
{
    private readonly bool _asyncSelection;
    private readonly bool _autoConstructOnAdd;
    private readonly ChildOrder _destructOrder;
    private readonly Func<IEnumerable<VM>, VM?>? _currentSelector;
    private readonly Action<VM?>? _onCurrentChanged;

    // ── Children backing store ────────────────────────────────────────────────
    private readonly List<VM> _children = new();

    // ── Current selection ─────────────────────────────────────────────────────
    private VM? _current;

    // ── Batch-update state (spec v1.1) ────────────────────────────────────────
    private readonly ContainerBatch _batch;

    // Collects the children population started constructing (see OnConstruct).
    private HashSet<IComponentVM>? _populationJoined;
    private int _disposeRequested;
    private bool _disposeDeferred;
    private int _activeCurrentPublications;
    // The threads that publish a current change under the lease above. A
    // Dispose from one of them defers to the lease: waiting there for another
    // thread's transaction could deadlock the selection (spec/06 §3.2, #1064).
    private readonly List<int> _currentPublicationThreads = new();
    private bool _membershipTransactionActive;
    private int _membershipTransactionOwnerThreadId;
    // The child an in-flight Add, Insert or replacement attached and has not
    // admitted yet; its rollback may still remove it (#1064). Such a child is
    // not a member for selection (spec/06 §4.3 rule 2, ADR-0173).
    private VM? _pendingAdmission;
    // The children an in-flight AttachPopulation attached and has not
    // committed yet; like _pendingAdmission, not members for selection (#1148).
    private VM[]? _stagedPopulation;
    // Set while the open membership transaction is uncommitted: its rollback
    // could still undo a staged attach, population or transfer detach. The
    // owner thread's selection calls are refused in that window (spec/06 §4.3
    // rule 4, ADR-0173). Cleared at the commit and when the transaction ends.
    private bool _transactionStaged;
    private readonly object _membershipGate = new();
    // Start records of the children an auto-construct add attaches while
    // Constructing; the construct walk waits on them (spec/06 §5.1).
    private readonly LateChildStarts _lateStarts = new();

    /// <summary>Test-only access to the late-child start claims.</summary>
    internal LateChildStarts LateStartsForTesting => _lateStarts;

    /// <summary>Whether a thread holds this container's membership transaction.</summary>
    internal bool MembershipTransactionActiveForTesting
    {
        get { lock (_membershipGate) return _membershipTransactionActive; }
    }

    // ── INotifyCollectionChanged ──────────────────────────────────────────────
    /// <inheritdoc/>
    public event NotifyCollectionChangedEventHandler? CollectionChanged;

    /// <inheritdoc/>
    public IReadOnlyList<VM> Snapshot()
    {
        lock (_membershipGate) return _children.ToArray();
    }

    /// <inheritdoc/>
    public IDisposable SubscribeMembership(Action callback)
    {
#if NET8_0_OR_GREATER
        ArgumentNullException.ThrowIfNull(callback);
#else
        if (callback is null) throw new ArgumentNullException(nameof(callback));
#endif
        NotifyCollectionChangedEventHandler handler = (_, _) => callback();
        CollectionChanged += handler;
        return Disposable.Create(() => CollectionChanged -= handler);
    }

    // ── ICompositeVM: Current ─────────────────────────────────────────────────

    /// <inheritdoc/>
    public VM? Current
    {
        get { lock (_membershipGate) return _current; }
        set => SetCurrent(value, async: _asyncSelection);
    }

    bool IParentCompositeVM.SupportsChildSelection => true;
    IComponentVM IParentCompositeVM.Owner => this;
    IParentCompositeVM? IParentCompositeVM.OwnerParent => Parent;

    // ── IList<VM> ─────────────────────────────────────────────────────────────

    /// <inheritdoc/>
    public int Count { get { lock (_membershipGate) return _children.Count; } }

    /// <inheritdoc/>
    public bool IsReadOnly => false;

    /// <inheritdoc/>
    public VM this[int index]
    {
        get { lock (_membershipGate) return _children[index]; }
        set
        {
            ThrowHelper.ThrowIfNull(value, nameof(value));
            BeginMembershipTransaction();
            ParentTransferToken? transfer = null;
            VM? old = null;
            LateChildStarts.Record? record = null;
            var admissionComplete = false;
            var propagateDisposeFailure = true;
            var originalStatus = value.Status;
            try
            {
                transfer = ComponentOwnership.BeginTransfer(value, this);
                lock (_membershipGate)
                {
                    EnsureTransactionCanContinueLocked();
                    // old keeps this composite as its parent until the commit,
                    // which frees it and clears Current in one locked section.
                    // No other container can adopt it while it is still
                    // current here (COMP-006), and a rollback can always put
                    // it back (#1219).
                    old = _children[index];
                    _children[index] = value;
                    value.SetParent(this);
                    StageAdmissionLocked(value);
                    record = AttachLateStartLocked(value);
                }
                AutoConstructAttached(value, record);
                lock (_membershipGate) EnsureTransactionCanContinueLocked();
                admissionComplete = true;
                ComponentOwnership.CommitThenPublish(transfer, () =>
                {
                    // Admitted after the old parent's detach commit (COMP-006).
                    AdmitAfterTransferCommit();
                    PublishEvery(
                        // Frees old, and clears Current only while it is still
                        // the replaced child, in one locked section.
                        () => DetachClearingCurrent(old),
                        () => RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                            NotifyCollectionChangedAction.Remove, old, index)),
                        () => RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                            NotifyCollectionChangedAction.Add, value, index)));
                });
            }
            catch (Exception originalError) when (!admissionComplete)
            {
                propagateDisposeFailure = false;
                var rollbackFailures = new List<Exception>();
                lock (_membershipGate)
                {
                    if (old is not null && _children.Any(child => ReferenceEquals(child, value)))
                    {
                        var actualIndex = _children.FindIndex(
                            child => ReferenceEquals(child, value));
                        _children[actualIndex] = old;
                        value.SetParent(null);
                    }
                    _pendingAdmission = null;
                    _lateStarts.Remove(value, record);
                }
                if (originalStatus == ConstructionStatus.Destructed &&
                    value.Status == ConstructionStatus.Constructed)
                {
                    try { value.DestructAsync().GetAwaiter().GetResult(); }
                    catch (Exception error) { rollbackFailures.Add(error); }
                }
                try { transfer?.Rollback(); }
                catch (Exception error) { rollbackFailures.Add(error); }
                if (rollbackFailures.Count > 0)
                    throw new AggregateException(
                        "Container replacement failed and rollback could not restore lifecycle state.",
                        new[] { originalError }.Concat(rollbackFailures));
                throw;
            }
            catch
            {
                propagateDisposeFailure = false;
                throw;
            }
            finally { EndMembershipTransaction(propagateDisposeFailure); }
        }
    }

    // ── Constructor ───────────────────────────────────────────────────────────

    /// <summary>
    /// Initializes the composite base.
    /// </summary>
    protected CompositeVMBase(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        bool asyncSelection,
        bool autoConstructOnAdd,
        Action? onConstruct,
        Action? onDestruct,
        Func<IEnumerable<VM>, VM?>? currentSelector,
        Action<VM?>? onCurrentChanged)
        : this(name, hint, hub, dispatcher, asyncSelection, autoConstructOnAdd,
            onConstruct, onDestruct, currentSelector, onCurrentChanged, ChildOrder.Insertion)
    {
    }

    /// <summary>
    /// Initializes the composite base with an explicit child destruct order
    /// (ADR-0161). <paramref name="destructOrder"/> sets the order in which
    /// destruct and dispose walk the children; construct order is unchanged.
    /// </summary>
    protected CompositeVMBase(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        bool asyncSelection,
        bool autoConstructOnAdd,
        Action? onConstruct,
        Action? onDestruct,
        Func<IEnumerable<VM>, VM?>? currentSelector,
        Action<VM?>? onCurrentChanged,
        ChildOrder destructOrder)
        : base(name, hint, hub, dispatcher, onConstruct, onDestruct)
    {
        _batch = new ContainerBatch(DeliverCollectionChanged);
        _asyncSelection = asyncSelection;
        _autoConstructOnAdd = autoConstructOnAdd;
        _destructOrder = destructOrder;
        _currentSelector = currentSelector;
        _onCurrentChanged = onCurrentChanged;
    }

    /// <summary>
    /// Initializes the composite base with an empty <c>Hint</c>, the default
    /// the builders use (spec/10 §4).
    /// </summary>
    protected CompositeVMBase(
        string name,
        IMessageHub hub,
        IDispatcher dispatcher,
        bool asyncSelection = false,
        bool autoConstructOnAdd = false,
        Action? onConstruct = null,
        Action? onDestruct = null,
        Func<IEnumerable<VM>, VM?>? currentSelector = null,
        Action<VM?>? onCurrentChanged = null)
        : this(
            name,
            string.Empty,
            hub,
            dispatcher,
            asyncSelection,
            autoConstructOnAdd,
            onConstruct,
            onDestruct,
            currentSelector,
            onCurrentChanged)
    {
    }

    // ── IParentCompositeVM (non-generic, used by ComponentVMBase for selection) ─

    IComponentVM? IParentCompositeVM.CurrentChild
    {
        get { lock (_membershipGate) return _current; }
    }

    // The child Select() and Deselect() paths run the checks of
    // SelectComponent and DeselectComponent, but a refusal changes nothing
    // and raises nothing (spec/05 §6, spec/06 §3.1, ADR-0188).
    void IParentCompositeVM.SelectChild(IComponentVM vm)
    {
        if (vm is not VM typed || !CanSelectComponentIgnoringDestructing(typed)) return;
        SetCurrent(typed, _asyncSelection, requireConstructed: true, silent: true);
    }

    void IParentCompositeVM.DeselectChild(IComponentVM vm)
    {
        if (vm is not VM typed) return;
        lock (_membershipGate)
        {
            if (CallerOwnsUncommittedTransactionLocked() || !ReferenceEquals(_current, typed)) return;
        }
        SetCurrent(null, _asyncSelection, silent: true);
    }

    // The dispose clear (spec/06 §4.3 rule 9, ADR-0189): a child that
    // published Disposed from its own disposal is cleared as Current, only
    // while it is still current. The composite's own dispose cascade skips it.
    void IParentCompositeVM.ChildDisposed(IComponentVM vm)
    {
        var identity = vm.GetOwnershipIdentity();
        VM? current;
        lock (_membershipGate)
        {
            if (DisposalPendingLocked()) return;
            current = _current;
        }
        if (current is null || !ReferenceEquals(current.GetOwnershipIdentity(), identity)) return;
        ApplyCurrentChange(null, CurrentChange.DisposeClear, onlyReplacing: current);
    }

    bool IParentCompositeVM.ContainsChild(IComponentVM vm)
    {
        var identity = vm.GetOwnershipIdentity();
        lock (_membershipGate)
            return _children.Any(child =>
                ReferenceEquals(child.GetOwnershipIdentity(), identity));
    }

    ParentTransferToken IParentCompositeVM.DetachForTransfer(IComponentVM vm)
    {
        int index;
        VM child;
        bool wasCurrent;
        lock (_membershipGate)
        {
            BeginMembershipTransactionLocked();
            index = _children.FindIndex(candidate => ReferenceEquals(candidate, vm));
            if (index < 0 || vm is not VM typed)
            {
                _membershipTransactionActive = false;
                _membershipTransactionOwnerThreadId = 0;
                WaitForGraph.Shared.Release(_membershipGate);
                Monitor.PulseAll(_membershipGate);
                throw new InvalidOperationException("The recorded parent does not contain the child identity.");
            }
            child = typed;
            wasCurrent = ReferenceEquals(_current, child);
            _children.RemoveAt(index);
            // The detach is staged until the transfer commits or rolls back
            // (spec/06 §4.3 rule 4).
            _transactionStaged = true;
        }
        return new ParentTransferToken(
            commit: () =>
            {
                System.Runtime.ExceptionServices.ExceptionDispatchInfo? firstError = null;
                lock (_membershipGate) _transactionStaged = false;
                try
                {
                    if (wasCurrent)
                        ApplyCurrentChange(null, CurrentChange.Clear, onlyReplacing: child);
                }
                catch (Exception error)
                {
                    firstError = System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(error);
                }
                try
                {
                    RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                        NotifyCollectionChangedAction.Remove, child, index));
                }
                catch (Exception error)
                {
                    firstError ??= System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(error);
                }
                try
                {
                    EndMembershipTransaction(propagateDisposeFailure: firstError is null);
                }
                catch (Exception error)
                {
                    firstError ??= System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(error);
                }
                firstError?.Throw();
            },
            rollback: () =>
            {
                try
                {
                    lock (_membershipGate)
                    {
                        if (_disposeRequested != 0)
                        {
                            child.SetParent(null);
                            return;
                        }
                        _children.Insert(Math.Min(index, _children.Count), child);
                        child.SetParent(this);
                    }
                }
                finally { EndMembershipTransaction(propagateDisposeFailure: false); }
            });
    }

    // ── ICompositeVM: selection ───────────────────────────────────────────────

    /// <inheritdoc/>
    public void SelectComponent(VM vm)
    {
        // A call that only the Destructing rule refuses changes nothing and
        // raises nothing; the commit drops it (spec/06 §3.1, ADR-0188).
        if (!CanSelectComponentIgnoringDestructing(vm)) throw CannotSelect(vm);
        // The commit checks Constructed again under its locks, so a destruct
        // on another thread after this check cannot pass it (#1220).
        SetCurrent(vm, _asyncSelection, requireConstructed: true);
    }

    private static InvalidOperationException CannotSelect(VM vm)
        => new($"Cannot select '{vm.Name}': can_select_component returned false.");

    /// <inheritdoc/>
    public void DeselectComponent(VM vm)
    {
        lock (_membershipGate)
        {
            // Every selection call fails inside the caller's own uncommitted
            // transaction (spec/06 §4.3 rule 4).
            if (CallerOwnsUncommittedTransactionLocked()) throw TransactionInProgress();
            if (!ReferenceEquals(_current, vm))
                throw new InvalidOperationException(
                    $"Cannot deselect '{vm.Name}': it is not the current selection.");
        }
        Current = null;
    }

    /// <summary>
    /// Returns whether <see cref="SelectComponent"/> would succeed now:
    /// <paramref name="vm"/> is an admitted member and Constructed, no disposal
    /// of this composite is pending, this composite is not Destructing, and
    /// the caller is not inside its own uncommitted membership transaction
    /// (spec/06 §3.1, ADR-0173, ADR-0188).
    /// </summary>
    public bool CanSelectComponent(VM vm)
    {
        if (!CanSelectComponentIgnoringDestructing(vm)) return false;
        lock (_membershipGate) return !DestructingLocked();
    }

    /// <summary>The <see cref="CanSelectComponent"/> checks except the Destructing rule.</summary>
    private bool CanSelectComponentIgnoringDestructing(VM vm)
    {
        if (vm.Status != ConstructionStatus.Constructed) return false;
        lock (_membershipGate)
            return !CallerOwnsUncommittedTransactionLocked() &&
                !DisposalPendingLocked() &&
                IsCommittedMemberLocked(vm);
    }

    // ── IList<VM>: mutation ───────────────────────────────────────────────────

    /// <inheritdoc/>
    public void Add(VM item)
    {
        ThrowHelper.ThrowIfNull(item, nameof(item));
        BeginMembershipTransaction();
        ParentTransferToken? transfer = null;
        var attached = false;
        var originalStatus = item.Status;
        LateChildStarts.Record? record = null;
        int idx;
        try
        {
            transfer = ComponentOwnership.BeginTransfer(item, this);
            lock (_membershipGate)
            {
                EnsureTransactionCanContinueLocked();
                _children.Add(item);
                item.SetParent(this);
                idx = _children.Count - 1;
                attached = true;
                StageAdmissionLocked(item);
                record = AttachLateStartLocked(item);
            }
            AutoConstructAttached(item, record);
            lock (_membershipGate) EnsureTransactionCanContinueLocked();
        }
        catch (Exception originalError)
        {
            var rollbackFailures = new List<Exception>();
            lock (_membershipGate)
            {
                var attachedIndex = attached
                    ? _children.FindIndex(child => ReferenceEquals(child, item))
                    : -1;
                if (attachedIndex >= 0)
                {
                    _children.RemoveAt(attachedIndex);
                    item.SetParent(null);
                }
                _pendingAdmission = null;
                _lateStarts.Remove(item, record);
            }
            if (originalStatus == ConstructionStatus.Destructed &&
                item.Status == ConstructionStatus.Constructed)
            {
                try { item.DestructAsync().GetAwaiter().GetResult(); }
                catch (Exception error) { rollbackFailures.Add(error); }
            }
            try { transfer?.Rollback(); }
            catch (Exception error) { rollbackFailures.Add(error); }
            EndMembershipTransaction(propagateDisposeFailure: false);
            if (rollbackFailures.Count > 0)
                throw new AggregateException(
                    "Container attachment failed and rollback could not restore lifecycle state.",
                    new[] { originalError }.Concat(rollbackFailures));
            throw;
        }
        try
        {
            ComponentOwnership.CommitThenPublish(transfer, () =>
            {
                // Admitted after the old parent's detach commit (COMP-006).
                AdmitAfterTransferCommit();
                RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                    NotifyCollectionChangedAction.Add, item, idx));
            });
        }
        catch
        {
            EndMembershipTransaction(propagateDisposeFailure: false);
            throw;
        }
        EndMembershipTransaction();
    }

    /// <inheritdoc/>
    public bool Remove(VM item)
    {
        BeginMembershipTransaction();
        bool found;
        try
        {
            int idx;
            VM removed = default!;
            var wasCurrent = false;
            var previousFlagChanged = false;
            lock (CompositeCurrentChangeCoordinator.Gate)
            {
                lock (_membershipGate)
                {
                    idx = _children.FindIndex(candidate => ReferenceEquals(candidate, item));
                    found = idx >= 0;
                    if (found) (removed, wasCurrent) = RemoveAtLocked(idx);
                }
                if (wasCurrent) previousFlagChanged = removed.CommitIsCurrent(false);
            }
            // A non-child ends the transaction below, after the lane is
            // released: ending it can run a deferred disposal, whose cascade
            // must not hold the shared lane (spec/06 §4.2, #1147).
            if (found)
                PublishEvery(
                    () =>
                    {
                        if (wasCurrent)
                            FinishCurrentChange(removed, null, previousFlagChanged, false);
                    },
                    () => RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                        NotifyCollectionChangedAction.Remove, removed, idx)));
        }
        catch
        {
            EndMembershipTransaction(propagateDisposeFailure: false);
            throw;
        }
        EndMembershipTransaction();
        return found;
    }

    /// <inheritdoc/>
    public void Insert(int index, VM item)
    {
        ThrowHelper.ThrowIfNull(item, nameof(item));
        BeginMembershipTransaction();
        ParentTransferToken? transfer = null;
        var attached = false;
        var originalStatus = item.Status;
        LateChildStarts.Record? record = null;
        try
        {
            transfer = ComponentOwnership.BeginTransfer(item, this);
            lock (_membershipGate)
            {
                EnsureTransactionCanContinueLocked();
                if (index < 0 || index > _children.Count)
                    throw new ArgumentOutOfRangeException(nameof(index));
                _children.Insert(index, item);
                item.SetParent(this);
                attached = true;
                StageAdmissionLocked(item);
                record = AttachLateStartLocked(item);
            }
            AutoConstructAttached(item, record);
            lock (_membershipGate) EnsureTransactionCanContinueLocked();
        }
        catch (Exception originalError)
        {
            var rollbackFailures = new List<Exception>();
            lock (_membershipGate)
            {
                var attachedIndex = attached
                    ? _children.FindIndex(child => ReferenceEquals(child, item))
                    : -1;
                if (attachedIndex >= 0)
                {
                    _children.RemoveAt(attachedIndex);
                    item.SetParent(null);
                }
                _pendingAdmission = null;
                _lateStarts.Remove(item, record);
            }
            if (originalStatus == ConstructionStatus.Destructed &&
                item.Status == ConstructionStatus.Constructed)
            {
                try { item.DestructAsync().GetAwaiter().GetResult(); }
                catch (Exception error) { rollbackFailures.Add(error); }
            }
            try { transfer?.Rollback(); }
            catch (Exception error) { rollbackFailures.Add(error); }
            EndMembershipTransaction(propagateDisposeFailure: false);
            if (rollbackFailures.Count > 0)
                throw new AggregateException(
                    "Container attachment failed and rollback could not restore lifecycle state.",
                    new[] { originalError }.Concat(rollbackFailures));
            throw;
        }
        try
        {
            ComponentOwnership.CommitThenPublish(transfer, () =>
            {
                // Admitted after the old parent's detach commit (COMP-006).
                AdmitAfterTransferCommit();
                RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                    NotifyCollectionChangedAction.Add, item, index));
            });
        }
        catch
        {
            EndMembershipTransaction(propagateDisposeFailure: false);
            throw;
        }
        EndMembershipTransaction();
    }

    /// <inheritdoc/>
    public void Move(int fromIndex, int toIndex)
    {
        VM item;
        lock (_membershipGate)
        {
            EnsureChildAdmission();
            ValidateMoveIndex(fromIndex, nameof(fromIndex));
            ValidateMoveIndex(toIndex, nameof(toIndex));
            if (fromIndex == toIndex) return;
            item = _children[fromIndex];
            _children.RemoveAt(fromIndex);
            _children.Insert(toIndex, item);
        }
        RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Move, item, toIndex, fromIndex));
    }

    /// <summary>
    /// Publishes a committed membership change. Every step runs even when an
    /// earlier one throws (for example a throwing <c>OnCurrentChanged</c>), so
    /// the collection event is never lost; the first failure is rethrown.
    /// </summary>
    private static void PublishEvery(params Action[] steps)
    {
        ExceptionDispatchInfo? firstError = null;
        foreach (var step in steps)
            FirstFailure.Capture(ref firstError, step);
        firstError?.Throw();
    }

    /// <inheritdoc/>
    public void RemoveAt(int index)
    {
        BeginMembershipTransaction();
        try
        {
            VM item;
            bool wasCurrent;
            var previousFlagChanged = false;
            lock (CompositeCurrentChangeCoordinator.Gate)
            {
                lock (_membershipGate)
                    (item, wasCurrent) = RemoveAtLocked(index);
                if (wasCurrent) previousFlagChanged = item.CommitIsCurrent(false);
            }
            PublishEvery(
                () =>
                {
                    if (wasCurrent)
                        FinishCurrentChange(item, null, previousFlagChanged, false);
                },
                () => RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                    NotifyCollectionChangedAction.Remove, item, index)));
        }
        catch
        {
            EndMembershipTransaction(propagateDisposeFailure: false);
            throw;
        }
        EndMembershipTransaction();
    }

    /// <inheritdoc/>
    public void Clear()
    {
        BeginMembershipTransaction();
        try
        {
            VM? previous;
            var previousFlagChanged = false;
            lock (CompositeCurrentChangeCoordinator.Gate)
            {
                lock (_membershipGate)
                {
                    previous = _current;
                    _current = null;
                    foreach (var child in _children)
                        if (ReferenceEquals(child.GetParent(), this))
                            child.SetParent(null);
                    _children.Clear();
                }
                if (previous is not null)
                    previousFlagChanged = previous.CommitIsCurrent(false);
            }
            PublishEvery(
                () =>
                {
                    if (previous is not null)
                        FinishCurrentChange(previous, null, previousFlagChanged, false);
                },
                () => RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                    NotifyCollectionChangedAction.Reset)));
        }
        catch
        {
            EndMembershipTransaction(propagateDisposeFailure: false);
            throw;
        }
        EndMembershipTransaction();
    }

    /// <summary>
    /// Opens a ref-counted batch window. Mutations inside suppress individual
    /// <see cref="CollectionChanged"/> events and hub messages. The outermost
    /// dispose fires a single <c>Reset</c> event, followed by one hub
    /// <see cref="CollectionChangedMessage{T}"/> Reset, iff any mutation
    /// occurred during the batch.
    /// </summary>
    public IDisposable BatchUpdate() => _batch.Enter();

    private void RaiseCollectionChanged(NotifyCollectionChangedEventArgs args) => _batch.Raise(args);

    /// <summary>
    /// Raises the local event, then publishes one equivalent
    /// <see cref="CollectionChangedMessage{T}"/> sent by this composite through the
    /// hub's ordinary <c>Send</c> (spec/01 §1.4, ADR-0142). Callers run outside
    /// the membership gate and the shared coordination lane, so hub subscribers
    /// hold neither. A disposed composite publishes nothing.
    /// </summary>
    private void DeliverCollectionChanged(NotifyCollectionChangedEventArgs args)
        => ContainerMembership.DeliverCollectionChanged<CompositeVMBase<VM>, VM>(
            this, CollectionChanged, args,
            static composite => Volatile.Read(ref composite._disposeRequested) == 0
                && !composite.IsDisposed());

    private LateChildStarts.Record? AttachLateStartLocked(VM item)
        => ContainerMembership.AttachLateStartLocked(this, _lateStarts, _autoConstructOnAdd, item);

    private void AutoConstructAttached(VM item, LateChildStarts.Record? record)
        => ContainerMembership.AutoConstructAttached(this, _lateStarts, _autoConstructOnAdd, item, record);

    private void MaybeAutoConstruct(VM item)
        => ContainerMembership.MaybeAutoConstruct(this, _autoConstructOnAdd, item);

    private void ValidateMoveIndex(int index, string parameterName)
    {
        if (index < 0 || index >= _children.Count)
            throw new ArgumentOutOfRangeException(parameterName, index,
                $"Move index must be in [0, {_children.Count}).");
    }

    // ── IList<VM>: query ──────────────────────────────────────────────────────

    /// <inheritdoc/>
    public bool Contains(VM item) => IndexOfIdentity(item) >= 0;

    /// <inheritdoc/>
    public int IndexOf(VM item) => IndexOfIdentity(item);

    /// <inheritdoc/>
    public void CopyTo(VM[] array, int arrayIndex)
    {
        lock (_membershipGate) _children.CopyTo(array, arrayIndex);
    }

    /// <inheritdoc/>
    public IEnumerator<VM> GetEnumerator() => Snapshot().GetEnumerator();

    /// <inheritdoc/>
    IEnumerator IEnumerable.GetEnumerator() => Snapshot().GetEnumerator();

    // ── Lifecycle overrides ───────────────────────────────────────────────────

    /// <summary>
    /// Overrides Construct to populate + construct every child sequentially
    /// (see spec/06 §5 and ADR-0020). Called by the base Construct() between
    /// Constructing → Constructed transitions.
    /// </summary>
    protected override void OnConstruct()
    {
        base.OnConstruct(); // invoke user's onConstruct callback if any
        // Populate children from factory (lazy: only on first construct).
        // Children whose construct population started are joined, not restarted.
        var joined = new HashSet<IComponentVM>(ComponentVMBase.ChildReferenceComparer.Instance);
        _populationJoined = joined;

        try { PopulateChildren(); }
        finally { _populationJoined = null; }
        // This walk's scope of start records; begun before its snapshot. It
        // stays open until the commit step, which ends it.
        var lateWalk = _lateStarts.BeginWalk(this);
        var visited = new HashSet<IComponentVM>(ComponentVMBase.ChildReferenceComparer.Instance);
        var walk = TransitionChildrenAsync(
            ContainerConstructWalk.Enumerate(
                () => Snapshot().ToArray(), _autoConstructOnAdd, joined, visited, lateWalk),
            construct: true,
            after: () =>
            {
                // The selector runs only after every child settles Constructed.
                if (_currentSelector is null) return;
                var initial = _currentSelector(this);
                if (initial is not null) ApplySelectorResult(initial);
            },
            joined: joined,
            join: lateWalk.Join,
            seal: _autoConstructOnAdd ? () => SealOrNextLate(joined, visited, lateWalk) : null);
        // A failed or abandoned walk ends its own scope; a committed one already did.
        _ = walk.ContinueWith(
            _ => lateWalk.End(),
            CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
        CompleteLifecycleHookAfter(walk);
    }

    private IComponentVM? SealOrNextLate(
        ISet<IComponentVM> joined, ISet<IComponentVM> visited, LateChildStarts.Walk lateWalk)
        => ContainerConstructWalk.SealOrNextLate(
            _membershipGate, _children, joined, visited, lateWalk, MarkConstructedBeforePublication);

    /// <summary>Constructs all current children sequentially.</summary>
    protected void ConstructChildren()
    {
        CompleteLifecycleHookAfter(TransitionChildrenAsync(
            Snapshot().ToArray(),
            construct: true));
    }

    /// <summary>
    /// Called once per Construct() to populate the children collection from
    /// the configured factory.  Default: no-op (children were added manually).
    /// Sealed subclasses override to evaluate their factory and Add children.
    /// </summary>
    protected virtual void PopulateChildren() { }

    /// <summary>
    /// Attaches one factory population as an all-or-nothing transaction. A
    /// subclass may call it from <see cref="PopulateChildren"/> or at any other
    /// time. Until the population commits, its candidates are not members for
    /// selection: the <c>Current</c> setter raises the non-member error and the
    /// construct walk's assignment ignores them (spec/06 §4.3, ADR-0173).
    /// </summary>
    protected void AttachPopulation(IEnumerable<VM> children, Action? onCommitted = null)
    {
        var candidates = children.ToArray();
        if (candidates.Where((candidate, index) =>
                candidates.Take(index).Any(previous => ReferenceEquals(
                    previous.GetOwnershipIdentity(), candidate.GetOwnershipIdentity()))).Any())
            throw new InvalidOperationException(
                "Factory population contains a duplicate child identity " +
                "(duplicate canonical child identity).");
        BeginMembershipTransaction();
        var transfers = new List<ParentTransferToken?>();
        var originalStatuses = new List<ConstructionStatus>();
        try
        {
            using (ComponentOwnership.BeginReservationBatch(candidates))
            {
                foreach (var child in candidates)
                {
                    var transfer = ComponentOwnership.BeginTransfer(child, this);
                    transfers.Add(transfer);
                    originalStatuses.Add(child.Status);
                }
            }
            lock (_membershipGate)
            {
                EnsureTransactionCanContinueLocked();
                foreach (var child in candidates)
                {
                    _children.Add(child);
                    child.SetParent(this);
                }
                _stagedPopulation = candidates;
                _transactionStaged = true;
            }

            // Populate the complete snapshot before invoking hooks, but never
            // execute user lifecycle code while holding the membership gate.
            foreach (var child in candidates)
            {
                if (Status == ConstructionStatus.Constructing)
                {
                    child.Construct();
                    // A child population left pending is joined, never restarted.
                    if (child.Status is not ConstructionStatus.Constructed
                        and not ConstructionStatus.Disposed)
                        _populationJoined?.Add(child);
                }
                else
                    MaybeAutoConstruct(child);
            }
            lock (_membershipGate) EnsureTransactionCanContinueLocked();
        }
        catch (Exception originalError)
        {
            var rollbackFailures = new List<Exception>();
            for (var candidateIndex = candidates.Length - 1; candidateIndex >= 0; candidateIndex--)
            {
                if (candidateIndex >= originalStatuses.Count) continue;
                var child = candidates[candidateIndex];
                lock (_membershipGate)
                {
                    var attached = _children.FindIndex(item => ReferenceEquals(item, child));
                    if (attached >= 0) _children.RemoveAt(attached);
                }
                var originalStatus = originalStatuses[candidateIndex];
                if (originalStatus == ConstructionStatus.Destructed &&
                    child.Status == ConstructionStatus.Constructed)
                {
                    try { child.DestructAsync().GetAwaiter().GetResult(); }
                    catch (Exception error) { rollbackFailures.Add(error); }
                }
                if (ReferenceEquals(child.GetParent(), this)) child.SetParent(null);
            }
            // Every candidate is detached: none is left to select (spec/06 §4.3 rule 2).
            lock (_membershipGate) _stagedPopulation = null;
            try
            {
                for (var index = transfers.Count - 1; index >= 0; index--)
                {
                    try { transfers[index]?.Rollback(); }
                    catch (Exception error) { rollbackFailures.Add(error); }
                }
            }
            finally { EndMembershipTransaction(propagateDisposeFailure: false); }
            if (rollbackFailures.Count > 0)
                throw new AggregateException(
                    "Container population failed and rollback could not restore lifecycle state.",
                    new[] { originalError }.Concat(rollbackFailures));
            throw;
        }
        try
        {
            ComponentOwnership.CommitThenPublish(transfers, () =>
            {
                // Admitted after the old parents' detach commits (COMP-006).
                AdmitAfterTransferCommit();
                onCommitted?.Invoke();
                foreach (var child in candidates)
                {
                    var index = Snapshot().ToList().FindIndex(
                        candidate => ReferenceEquals(candidate, child));
                    if (index >= 0)
                        RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                            NotifyCollectionChangedAction.Add, child, index));
                }
            });
        }
        catch
        {
            EndMembershipTransaction(propagateDisposeFailure: false);
            throw;
        }
        EndMembershipTransaction();
    }

    /// <summary>
    /// Overrides Destruct: sets Current = null first, then waits for every child,
    /// walking the children in the configured destruct order (ADR-0161). The
    /// clear opens no membership transaction and is never refused, so it also
    /// runs while another thread holds a transaction, inside this composite's
    /// own transaction and while disposal is deferred (spec/06 §5, ADR-0173).
    /// </summary>
    protected override void OnDestruct()
    {
        ApplyCurrentChange(null, CurrentChange.Clear);

        CompleteLifecycleHookAfter(TransitionChildrenAsync(
            Snapshot().ToArray().InDestructOrder(_destructOrder),
            construct: false,
            after: () => base.OnDestruct()));
    }

    /// <summary>
    /// Dispose cascade (LIFE-013): recursively dispose each child depth-first, then self.
    /// </summary>
#pragma warning disable CA2215 // DisposeWithChildren runs the base disposal at its hook-lease boundary (LIFE-015).
    public override void Dispose()
#pragma warning restore CA2215
    {
        VM[] snapshot;
        lock (_membershipGate)
        {
            if (_disposeRequested != 0) return;
            if (_currentPublicationThreads.Contains(Environment.CurrentManagedThreadId))
            {
                _disposeDeferred = true;
                return;
            }
            if (!WaitForForeignTransactionLocked()) return;
            if (_membershipTransactionActive || _activeCurrentPublications > 0)
            {
                _disposeDeferred = true;
                return;
            }
            _disposeRequested = 1;
            // Depth-first, in the configured destruct order (ADR-0161).
            snapshot = _children.ToArray().InDestructOrder(_destructOrder);
        }
        // The cascade runs at the base's admitted-hook boundary (LIFE-015): a
        // foreign disposal cleans no child while this container's hook runs.
        // No lock is held here, so the hook can finish while this call waits.
        DisposeWithChildren(snapshot);
    }

    // ── IComponentVM.Type ─────────────────────────────────────────────────────

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Composite;

    private void EnsureChildAdmission()
    {
        if (Volatile.Read(ref _disposeRequested) != 0 || _disposeDeferred)
            throw new ObjectDisposedException(GetType().Name,
                "Cannot attach a child while the container is disposing.");
        if (_membershipTransactionActive)
            throw new InvalidOperationException(
                "A container membership transaction is already in progress.");
    }

    /// <summary>
    /// Waits, under <c>_membershipGate</c>, until no other thread holds this
    /// container's membership transaction (ADR-0122). A wait that would close a
    /// wait-for cycle records the disposal for the transaction owner instead,
    /// which disposes this container when its transaction ends (#717). Returns
    /// <c>false</c> when the caller has nothing left to do.
    /// </summary>
    private bool WaitForForeignTransactionLocked()
    {
        var caller = Environment.CurrentManagedThreadId;
        var waits = WaitForGraph.Shared;
        while (_membershipTransactionActive && _membershipTransactionOwnerThreadId != caller)
        {
            if (!waits.TryBeginWait(_membershipGate, caller))
            {
                _disposeDeferred = true;
                return false;
            }
            try { Monitor.Wait(_membershipGate); }
            finally { waits.EndWait(caller); }
            if (_disposeRequested != 0) return false;
        }
        return true;
    }

    private void BeginMembershipTransactionLocked()
    {
        EnsureChildAdmission();
        _membershipTransactionActive = true;
        _membershipTransactionOwnerThreadId = Environment.CurrentManagedThreadId;
        // Recorded so a group transfer or a disposal that waits for this
        // transaction can see a wait-for cycle (#717).
        WaitForGraph.Shared.Acquire(_membershipGate, _membershipTransactionOwnerThreadId);
    }

    private void BeginMembershipTransaction()
    {
        lock (_membershipGate) BeginMembershipTransactionLocked();
    }

    private void EnsureTransactionCanContinueLocked()
    {
        if (_disposeRequested != 0 || _disposeDeferred)
            throw new ObjectDisposedException(GetType().Name,
                "Cannot attach a child while the container is disposing.");
    }

    private void EndMembershipTransaction(bool propagateDisposeFailure = true)
    {
        bool dispose;
        lock (_membershipGate)
        {
            _membershipTransactionActive = false;
            _membershipTransactionOwnerThreadId = 0;
            _transactionStaged = false;
            WaitForGraph.Shared.Release(_membershipGate);
            // The deferral stays set until Dispose admits it, so no transaction
            // or selection starts between this release and Dispose (#1064).
            dispose = _disposeDeferred && _activeCurrentPublications == 0;
            Monitor.PulseAll(_membershipGate);
        }
        if (dispose)
        {
            try { Dispose(); }
            catch when (!propagateDisposeFailure) { }
        }
    }

    private void EndCurrentPublication(bool propagateDisposeFailure)
    {
        bool dispose;
        lock (_membershipGate)
        {
            _activeCurrentPublications--;
            _currentPublicationThreads.Remove(Environment.CurrentManagedThreadId);
            // The deferral stays set until Dispose admits it (#1064).
            dispose = _activeCurrentPublications == 0 &&
                !_membershipTransactionActive && _disposeDeferred;
            Monitor.PulseAll(_membershipGate);
        }
        if (dispose)
        {
            try { Dispose(); }
            catch when (!propagateDisposeFailure) { }
        }
    }

    // ── Private helpers ───────────────────────────────────────────────────────

    /// <summary>The kinds of <see cref="ApplyCurrentChange"/> (spec/06 §4.3).</summary>
    private enum CurrentChange
    {
        /// <summary>A selection call: a refusal raises.</summary>
        Call,

        /// <summary>
        /// An asynchronous delivery, the construct walk's assignment or a
        /// child Select() or Deselect(): the same checks as a call, but a
        /// refusal is a silent no-op (ADR-0188).
        /// </summary>
        Delivery,

        /// <summary>
        /// The destruct clear (§5) or a detach clear (rule 6): never refused.
        /// </summary>
        Clear,

        /// <summary>
        /// The clear that a child's own dispose commits (rule 9): like
        /// <see cref="Clear"/>, but skipped while disposal of this composite is
        /// requested or deferred, or after it is Disposed.
        /// </summary>
        DisposeClear,
    }

    private static InvalidOperationException TransactionInProgress()
        => new("A container membership transaction is already in progress.");

    /// <summary>Marks <paramref name="item"/> attached but not admitted (rules 2 and 4).</summary>
    private void StageAdmissionLocked(VM item)
    {
        _pendingAdmission = item;
        _transactionStaged = true;
    }

    /// <summary>
    /// The admission: the staged child or population becomes a member for
    /// selection, before CollectionChanged publishes, and the owner thread may
    /// select again (spec/06 §4.3 rules 2 and 4).
    /// </summary>
    private void AdmitLocked()
    {
        _pendingAdmission = null;
        _stagedPopulation = null;
        _transactionStaged = false;
    }

    /// <summary>
    /// Admits the staged child or population after the old parents' detach
    /// commits and before CollectionChanged (spec/06 §4.3 rule 2). An earlier
    /// admission would let another thread select a moved child here while the
    /// old parent's detach clear can still reset its IsCurrent flag (COMP-006).
    /// </summary>
    private void AdmitAfterTransferCommit()
    {
        lock (_membershipGate) AdmitLocked();
    }

    private bool DisposalPendingLocked()
        => Volatile.Read(ref _disposeRequested) != 0 || _disposeDeferred;

    /// <summary>
    /// Contained, not Disposed, and not staged by an add or population
    /// (rule 2, ADR-0189).
    /// </summary>
    private bool IsCommittedMemberLocked(VM value)
        => value.Status != ConstructionStatus.Disposed &&
            !ReferenceEquals(value, _pendingAdmission) &&
            (_stagedPopulation is not { } staged || !Array.Exists(staged, child => ReferenceEquals(child, value))) &&
            _children.Any(child => ReferenceEquals(child, value));

    /// <summary>The caller owns this composite's uncommitted transaction (rule 4).</summary>
    private bool CallerOwnsUncommittedTransactionLocked()
        => _transactionStaged && _membershipTransactionActive &&
            _membershipTransactionOwnerThreadId == Environment.CurrentManagedThreadId;

    /// <summary>
    /// The refusal of a selection of <paramref name="value"/>, or null
    /// (spec/06 §4.3 rules 2-4). <paramref name="disposed"/> keeps the
    /// post-dispose behavior: a null clear that would change a disposed
    /// composite raises, as it always has (chapter 01 §4). After Disposed,
    /// re-assigning the child that is already current changes nothing and
    /// stays the no-op it always was; while disposal is only requested or
    /// deferred, it is refused like any non-null selection (rule 3).
    /// </summary>
    /// <remarks>
    /// <paramref name="requireConstructed"/> (<see cref="SelectComponent"/>)
    /// also refuses a child that is not Constructed now, with the predicate
    /// error (spec/06 §3.1). The check runs at the commit, so a destruct after
    /// the entry check cannot pass it (#1220).
    /// </remarks>
    private Exception? SelectionRefusalLocked(VM? value, bool disposed, bool requireConstructed = false)
    {
        if (CallerOwnsUncommittedTransactionLocked()) return TransactionInProgress();
        if (value is null)
            return disposed && _current is not null ? SelectionWhileDisposing() : null;
        if (DisposalPendingLocked())
            return disposed && ReferenceEquals(value, _current) ? null : SelectionWhileDisposing();
        if (!IsCommittedMemberLocked(value))
            return new InvalidOperationException(
                $"Cannot set Current to '{value.Name}': it is not a member of this composite.");
        if (requireConstructed && value.Status != ConstructionStatus.Constructed) return CannotSelect(value);
        return null;
    }

    /// <summary>
    /// This composite is Destructing (spec/06 §4.3 rule 8, ADR-0188). The
    /// status is Destructing before the destruct clear takes the membership
    /// gate, so a commit that reads it under the gate cannot follow the clear.
    /// </summary>
    private bool DestructingLocked() => Status == ConstructionStatus.Destructing;

    private ObjectDisposedException SelectionWhileDisposing()
        => new(GetType().Name, "Cannot select a child while the container is disposing.");

    /// <param name="value">The new Current.</param>
    /// <param name="async">Schedules the commit on the foreground dispatcher.</param>
    /// <param name="requireConstructed">Refuses a child that is not Constructed (spec/06 §3.1).</param>
    /// <param name="silent">
    /// A child Select() or Deselect(): a refusal changes nothing and raises
    /// nothing (ADR-0188).
    /// </param>
    private void SetCurrent(VM? value, bool async, bool requireConstructed = false, bool silent = false)
    {
        if (!async)
        {
            ApplyCurrentChange(
                value, silent ? CurrentChange.Delivery : CurrentChange.Call,
                requireConstructed: requireConstructed);
            return;
        }
        // The call validates now and raises as the synchronous setter does;
        // the delivery validates again (spec/06 §4.3 rule 7). A selection that
        // only the Destructing rule refuses schedules nothing (rule 8).
        var disposed = IsDisposed();
        lock (_membershipGate)
        {
            if (SelectionRefusalLocked(value, disposed, requireConstructed) is { } refusal)
            {
                if (silent) return;
                throw refusal;
            }
            if (value is not null && DestructingLocked()) return;
        }
        _dispatcher.Foreground.Schedule(value, (sched, v) =>
        {
            ApplyCurrentChange(v, CurrentChange.Delivery, requireConstructed: requireConstructed);
            return System.Reactive.Disposables.Disposable.Empty;
        });
    }

    /// <summary>
    /// Changes <c>Current</c> without a membership transaction (spec/06 §4.3,
    /// ADR-0173). Validation and the commit of <c>Current</c> and both
    /// <c>IsCurrent</c> flags run under the coordination lane and the
    /// membership gate; another thread's transaction neither fails nor delays
    /// it. The publication runs after both are released, under the
    /// current-publication lease, so a disposal from the callbacks is deferred
    /// until they return. With <paramref name="onlyReplacing"/>, the change
    /// applies only while that child is still current: a transaction clears
    /// the child it detached, never a selection made after the detach (#1064).
    /// </summary>
    private void ApplyCurrentChange(
        VM? value, CurrentChange kind, VM? onlyReplacing = null, bool requireConstructed = false)
    {
        var clear = kind is CurrentChange.Clear or CurrentChange.DisposeClear;
        if (clear)
        {
            // A clear with nothing to clear skips the global lane.
            lock (_membershipGate)
                if (_current is null) return;
        }
        var disposed = !clear && IsDisposed();
        VM? previous;
        bool previousFlagChanged;
        bool valueFlagChanged;
        lock (CompositeCurrentChangeCoordinator.Gate)
        {
            lock (_membershipGate)
            {
                if (!clear &&
                    SelectionRefusalLocked(value, disposed, requireConstructed) is { } refusal)
                {
                    if (kind == CurrentChange.Call) throw refusal;
                    return;
                }
                // Rule 8: while Destructing, a non-null selection that rules
                // 2-4 admit changes nothing and raises nothing (ADR-0188).
                if (!clear && value is not null && DestructingLocked()) return;
                // Rule 9: the dispose clear is skipped while disposal of this
                // composite is requested or deferred, or after Disposed.
                if (kind == CurrentChange.DisposeClear && DisposalPendingLocked()) return;
                previous = _current;
                if (ReferenceEquals(previous, value) ||
                    (onlyReplacing is not null && !ReferenceEquals(previous, onlyReplacing)))
                    return;
                _current = value;
                previousFlagChanged = previous?.CommitIsCurrent(false) ?? false;
                valueFlagChanged = value?.CommitIsCurrent(true) ?? false;
                _activeCurrentPublications++;
                _currentPublicationThreads.Add(Environment.CurrentManagedThreadId);
            }
        }
        try
        {
            FinishCurrentChange(previous, value, previousFlagChanged, valueFlagChanged);
        }
        catch
        {
            EndCurrentPublication(propagateDisposeFailure: false);
            throw;
        }
        EndCurrentPublication(propagateDisposeFailure: true);
    }

    /// <summary>
    /// Assigns the <c>Current(selector)</c> result of a construct walk: the
    /// non-raising validated assignment of spec/06 §3.2 (ADR-0165, ADR-0173).
    /// It is a silent no-op while this composite is disposing, when
    /// <paramref name="value"/> is not a committed member (not contained, or
    /// staged by an add or population whose rollback could still remove it),
    /// and on a thread that owns this composite's uncommitted transaction.
    /// </summary>
    private void ApplySelectorResult(VM value) => ApplyCurrentChange(value, CurrentChange.Delivery);

    /// <summary>
    /// Frees <paramref name="detached"/> and clears it as Current in one locked
    /// section (#1219). Under the coordination lane and the membership gate,
    /// the child loses this composite as its parent and, while it is still
    /// current, the same section clears Current and its flag (spec/06 §4.3
    /// rule 6). No other composite can adopt and select the child in between,
    /// so the clear never resets the flag of a selection elsewhere (COMP-006).
    /// The publication runs after both locks are released, under the
    /// current-publication lease, as in <see cref="ApplyCurrentChange"/>.
    /// </summary>
    private void DetachClearingCurrent(VM detached)
    {
        bool previousFlagChanged;
        lock (CompositeCurrentChangeCoordinator.Gate)
        {
            lock (_membershipGate)
            {
                if (ReferenceEquals(detached.GetParent(), this)) detached.SetParent(null);
                if (!ReferenceEquals(_current, detached)) return;
                _current = null;
                previousFlagChanged = detached.CommitIsCurrent(false);
                _activeCurrentPublications++;
                _currentPublicationThreads.Add(Environment.CurrentManagedThreadId);
            }
        }
        try
        {
            FinishCurrentChange(detached, null, previousFlagChanged, false);
        }
        catch
        {
            EndCurrentPublication(propagateDisposeFailure: false);
            throw;
        }
        EndCurrentPublication(propagateDisposeFailure: true);
    }

    private void FinishCurrentChange(
        VM? previous,
        VM? value,
        bool previousFlagChanged,
        bool valueFlagChanged)
    {

        // Update IsCurrent on affected children.
        if (previous is not null && previousFlagChanged)
            previous.PublishIsCurrent();
        if (value is not null && valueFlagChanged)
            value.PublishIsCurrent();

        // Emit PropertyChangedMessage for "Current" on the hub.
        NotifyPropertyChanged(nameof(Current));

        // Invoke the optional builder-registered OnCurrentChanged callback
        // AFTER state update + hub publish + PropertyChanged so all observers
        // see the new value consistently (spec/06 §3.2, ADR-0042 §5.2).
        _onCurrentChanged?.Invoke(value);
    }

    private int IndexOfIdentity(VM item)
    {
        lock (_membershipGate)
            return _children.FindIndex(candidate => ReferenceEquals(candidate, item));
    }

    private (VM Item, bool WasCurrent) RemoveAtLocked(int index)
    {
        var item = _children[index];
        _children.RemoveAt(index);
        if (ReferenceEquals(item.GetParent(), this)) item.SetParent(null);
        var wasCurrent = ReferenceEquals(_current, item);
        if (wasCurrent) _current = null;
        return (item, wasCurrent);
    }
}
