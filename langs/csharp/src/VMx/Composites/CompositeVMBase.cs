using System.Collections;
using System.Collections.Specialized;
using System.Reactive.Disposables;
using System.Runtime.ExceptionServices;
using VMx.Collections;
using VMx.Components;
using VMx.Groups;
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
    /// <see cref="SealOrNextLateLocked"/> joins a child added after it, and
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
    /// The construct walk's commit step; call it under the membership gate.
    /// Returns the next unvisited member that an add started (it has a start
    /// record in <paramref name="walk"/>), which the walk then joins. Without
    /// one, it commits the Constructed state through <paramref name="commit"/>
    /// in the same gated section and returns null, so an add reads either
    /// Constructing (and is joined) or Constructed (spec/02 §6, spec/06 §5.1).
    /// </summary>
    internal static IComponentVM? SealOrNextLateLocked<VM>(
        IEnumerable<VM> members,
        ISet<IComponentVM> joined,
        ISet<IComponentVM> visited,
        LateChildStarts.Walk walk,
        Action commit)
        where VM : class, IComponentVM
    {
        foreach (var child in members)
        {
            if (!visited.Add(child)) continue;
            if (!walk.Take(child)) continue;
            joined.Add(child);
            return child;
        }
        commit();
        return null;
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
    private readonly Func<IEnumerable<VM>, VM?>? _currentSelector;
    private readonly Action<VM?>? _onCurrentChanged;

    // ── Children backing store ────────────────────────────────────────────────
    private readonly List<VM> _children = new();

    // ── Current selection ─────────────────────────────────────────────────────
    private VM? _current;

    // ── Batch-update state (spec v1.1) ────────────────────────────────────────
    private int _batchDepth;
    private bool _batchDirty;

    // Collects the children population started constructing (see OnConstruct).
    private HashSet<IComponentVM>? _populationJoined;
    private int _disposeRequested;
    private bool _disposeDeferred;
    private int _activeCurrentPublications;
    private bool _membershipTransactionActive;
    private int _membershipTransactionOwnerThreadId;
    private readonly object _membershipGate = new();
    // Start records of the children an auto-construct add attaches while
    // Constructing; the construct walk waits on them (spec/06 §5.1).
    private readonly LateChildStarts _lateStarts = new();

    /// <summary>Test-only access to the late-child start claims.</summary>
    internal LateChildStarts LateStartsForTesting => _lateStarts;

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
                    old = _children[index];
                    _children[index] = value;
                    old.SetParent(null);
                    value.SetParent(this);
                    record = AttachLateStartLocked(value);
                }
                AutoConstructAttached(value, record);
                lock (_membershipGate) EnsureTransactionCanContinueLocked();
                admissionComplete = true;
                ComponentOwnership.CommitThenPublish(transfer, () =>
                {
                    var wasCurrent = ReferenceEquals(Current, old);
                    PublishEvery(
                        () =>
                        {
                            if (wasCurrent)
                                ApplyCurrentChange(null, internalTransaction: true);
                        },
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
                        old.SetParent(this);
                        value.SetParent(null);
                    }
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
        : base(name, hint, hub, dispatcher, onConstruct, onDestruct)
    {
        _asyncSelection = asyncSelection;
        _autoConstructOnAdd = autoConstructOnAdd;
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

    void IParentCompositeVM.SelectChild(IComponentVM vm)
    {
        if (vm is VM typed) SelectComponent(typed);
    }

    void IParentCompositeVM.DeselectChild(IComponentVM vm)
    {
        if (vm is VM typed) DeselectComponent(typed);
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
                MembershipTransactionWaitGraph.Shared.Release(_membershipGate);
                Monitor.PulseAll(_membershipGate);
                throw new InvalidOperationException("The recorded parent does not contain the child identity.");
            }
            child = typed;
            wasCurrent = ReferenceEquals(_current, child);
            _children.RemoveAt(index);
        }
        return new ParentTransferToken(
            commit: () =>
            {
                System.Runtime.ExceptionServices.ExceptionDispatchInfo? firstError = null;
                try
                {
                    if (wasCurrent)
                        ApplyCurrentChange(null, internalTransaction: true);
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
        if (!CanSelectComponent(vm))
            throw new InvalidOperationException(
                $"Cannot select '{vm.Name}': can_select_component returned false.");
        Current = vm;
    }

    /// <inheritdoc/>
    public void DeselectComponent(VM vm)
    {
        if (!ReferenceEquals(Current, vm))
            throw new InvalidOperationException(
                $"Cannot deselect '{vm.Name}': it is not the current selection.");
        Current = null;
    }

    /// <inheritdoc/>
    public bool CanSelectComponent(VM vm)
        => IndexOfIdentity(vm) >= 0 && vm.Status == ConstructionStatus.Constructed;

    // ── IList<VM>: mutation ───────────────────────────────────────────────────

    /// <inheritdoc/>
    public void Add(VM item)
    {
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
                RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                    NotifyCollectionChangedAction.Add, item, idx)));
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
        try
        {
            int idx;
            VM removed;
            bool wasCurrent;
            var previousFlagChanged = false;
            lock (CompositeCurrentChangeCoordinator.Gate)
            {
                lock (_membershipGate)
                    idx = _children.FindIndex(candidate => ReferenceEquals(candidate, item));
                if (idx < 0)
                {
                    EndMembershipTransaction();
                    return false;
                }
                lock (_membershipGate)
                    (removed, wasCurrent) = RemoveAtLocked(idx);
                if (wasCurrent) previousFlagChanged = removed.CommitIsCurrent(false);
            }
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
        return true;
    }

    /// <inheritdoc/>
    public void Insert(int index, VM item)
    {
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
                RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                    NotifyCollectionChangedAction.Add, item, index)));
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
        System.Runtime.ExceptionServices.ExceptionDispatchInfo? firstError = null;
        foreach (var step in steps)
        {
            try { step(); }
            catch (Exception error)
            {
                firstError ??= System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(error);
            }
        }
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
    public IDisposable BatchUpdate()
    {
        _batchDepth++;
        return new CollectionBatch(this);
    }

    private void ExitBatch()
    {
        _batchDepth--;
        if (_batchDepth == 0 && _batchDirty)
        {
            _batchDirty = false;
            DeliverCollectionChanged(new NotifyCollectionChangedEventArgs(
                NotifyCollectionChangedAction.Reset));
        }
    }

    private void RaiseCollectionChanged(NotifyCollectionChangedEventArgs args)
    {
        if (_batchDepth > 0)
        {
            _batchDirty = true;
            return;
        }
        DeliverCollectionChanged(args);
    }

    /// <summary>
    /// Raises the local event, then publishes one equivalent
    /// <see cref="CollectionChangedMessage{T}"/> sent by this composite through the
    /// hub's ordinary <c>Send</c> (spec/01 §1.4, ADR-0142). Callers run outside
    /// the membership gate and the shared coordination lane, so hub subscribers
    /// hold neither. A disposed composite publishes nothing.
    /// </summary>
    private void DeliverCollectionChanged(NotifyCollectionChangedEventArgs args)
    {
        // A throwing local handler must not suppress the hub message for the
        // committed change (spec/01 §1.4, #723): send it, then rethrow.
        // The first failure wins, as in NotifyPropertyChanged and Python.
        ExceptionDispatchInfo? firstFailure = null;
        try { CollectionChanged?.Invoke(this, args); }
        catch (Exception error) { firstFailure = ExceptionDispatchInfo.Capture(error); }
        if (Volatile.Read(ref _disposeRequested) == 0 && !IsDisposed())
        {
            try { Hub.Send(CollectionChangedMessage<VM>.From(this, args)); }
            catch (Exception error) { firstFailure ??= ExceptionDispatchInfo.Capture(error); }
        }
        firstFailure?.Throw();
    }

    /// <summary>
    /// Called under the gate as an add attaches <paramref name="item"/>: an
    /// add that will auto-start the child while this container is
    /// Constructing registers a start record the construct walk waits on.
    /// </summary>
    private LateChildStarts.Record? AttachLateStartLocked(VM item)
        => _lateStarts.AttachLocked(
            item, _autoConstructOnAdd && Status == ConstructionStatus.Constructing);

    /// <summary>The add's auto-construct of a child it attached with <paramref name="record"/>.</summary>
    private void AutoConstructAttached(VM item, LateChildStarts.Record? record)
    {
        if (record is null)
        {
            MaybeAutoConstruct(item);
            return;
        }
        // The construct walk never starts a late child; it waits for this
        // attempt, then joins the child (spec/06 §5.1). The record is done
        // before this add publishes or ends its transaction.
        try
        {
            _lateStarts.Probe(item, LateChildStage.Attached);
            if (item.Status == ConstructionStatus.Destructed) item.Construct();
        }
        finally
        {
            record.MarkDone();
            if (Status != ConstructionStatus.Constructing) _lateStarts.Remove(item, record);
        }
    }

    private void MaybeAutoConstruct(VM item)
    {
        if (!_autoConstructOnAdd) return;
        // While Constructing, only an add with a start record starts its
        // child; any other child is in the construct walk's snapshot.
        var status = Status;
        if (status != ConstructionStatus.Constructed) return;
        if (item.Status == ConstructionStatus.Constructed) return;
        item.Construct();
    }

    private void ValidateMoveIndex(int index, string parameterName)
    {
        if (index < 0 || index >= _children.Count)
            throw new ArgumentOutOfRangeException(parameterName, index,
                $"Move index must be in [0, {_children.Count}).");
    }

    /// <summary>
    /// Disposable batch handle returned by <see cref="BatchUpdate"/>.
    /// Decrement the composite's batch depth on dispose.
    /// </summary>
    private sealed class CollectionBatch : IDisposable
    {
        private readonly CompositeVMBase<VM> _owner;
        private bool _disposed;

        internal CollectionBatch(CompositeVMBase<VM> owner) => _owner = owner;

        /// <summary>Closes the batch and emits a Reset event if mutations occurred.</summary>
        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            _owner.ExitBatch();
        }
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
                if (initial is not null && IndexOfIdentity(initial) >= 0)
                    SetCurrent(initial, async: false);
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

    /// <summary>
    /// The commit step of this container's construct walk (spec/06 §5.1):
    /// joins a child an add started after the last scan, or commits Constructed
    /// and ends the walk's scope.
    /// </summary>
    private IComponentVM? SealOrNextLate(
        ISet<IComponentVM> joined, ISet<IComponentVM> visited, LateChildStarts.Walk lateWalk)
    {
        IComponentVM? late;
        lock (_membershipGate)
        {
            late = ContainerConstructWalk.SealOrNextLateLocked(
                _children, joined, visited, lateWalk, MarkConstructedBeforePublication);
        }
        if (late is null) lateWalk.End();
        return late;
    }

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

    /// <summary>Attaches one factory population as an all-or-nothing transaction.</summary>
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
    /// Overrides Destruct: sets Current = null first, then waits for every child.
    /// </summary>
    protected override void OnDestruct()
    {
        if (Current is not null)
            SetCurrent(null, async: false);

        CompleteLifecycleHookAfter(TransitionChildrenAsync(
            Snapshot().ToArray(),
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
            if (!WaitForForeignTransactionLocked()) return;
            if (_membershipTransactionActive || _activeCurrentPublications > 0)
            {
                _disposeDeferred = true;
                return;
            }
            _disposeRequested = 1;
            snapshot = _children.ToArray();
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
        var waits = MembershipTransactionWaitGraph.Shared;
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
        MembershipTransactionWaitGraph.Shared.Acquire(_membershipGate, _membershipTransactionOwnerThreadId);
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
            MembershipTransactionWaitGraph.Shared.Release(_membershipGate);
            dispose = _disposeDeferred && _activeCurrentPublications == 0;
            if (dispose) _disposeDeferred = false;
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
            dispose = _activeCurrentPublications == 0 &&
                !_membershipTransactionActive && _disposeDeferred;
            if (dispose) _disposeDeferred = false;
            Monitor.PulseAll(_membershipGate);
        }
        if (dispose)
        {
            try { Dispose(); }
            catch when (!propagateDisposeFailure) { }
        }
    }

    // ── Private helpers ───────────────────────────────────────────────────────

    private void SetCurrent(VM? value, bool async)
    {
        if (async)
        {
            lock (_membershipGate)
            {
                EnsureChildAdmission();
                if (value is not null &&
                    !_children.Any(child => ReferenceEquals(child, value)))
                    throw new InvalidOperationException(
                        $"Cannot set Current to '{value.Name}': it is not a member of this composite.");
            }
            _dispatcher.Foreground.Schedule(value, (sched, v) =>
            {
                ApplyCurrentChange(v, strict: false);
                return System.Reactive.Disposables.Disposable.Empty;
            });
        }
        else
        {
            ApplyCurrentChange(value);
        }
    }

    private void ApplyCurrentChange(
        VM? value,
        bool internalTransaction = false,
        bool strict = true)
    {
        // Async TOCTOU guard: with AsyncSelection the child may have been removed
        // between SetCurrent's membership check and this deferred foreground
        // delivery. Dropping silently upholds the spec/06 §3 invariant that a
        // non-null Current is always a member of the children collection.
        lock (_membershipGate)
        {
            if (ReferenceEquals(_current, value)) return;
        }
        var ownsTransaction = false;
        var publicationActive = false;
        try
        {
            VM? previous = null;
            var changed = false;
            var previousFlagChanged = false;
            var valueFlagChanged = false;
            lock (CompositeCurrentChangeCoordinator.Gate)
            {
                bool inheritedTransaction;
                lock (_membershipGate)
                    inheritedTransaction = _membershipTransactionActive &&
                        _membershipTransactionOwnerThreadId == Environment.CurrentManagedThreadId;
                if (!internalTransaction && !inheritedTransaction)
                {
                    try { BeginMembershipTransaction(); }
                    catch when (!strict) { return; }
                    ownsTransaction = true;
                }
                lock (_membershipGate)
                {
                    if (value is not null &&
                        !_children.Any(child => ReferenceEquals(child, value)))
                    {
                        if (strict)
                            throw new InvalidOperationException(
                                $"Cannot set Current to '{value.Name}': it is not a member of this composite.");
                    }
                    else if (!ReferenceEquals(_current, value))
                    {
                        previous = _current;
                        _current = value;
                        changed = true;
                        previousFlagChanged = previous?.CommitIsCurrent(false) ?? false;
                        valueFlagChanged = value?.CommitIsCurrent(true) ?? false;
                        if (ownsTransaction)
                        {
                            _activeCurrentPublications++;
                            publicationActive = true;
                        }
                    }
                }
            }
            if (ownsTransaction)
            {
                ownsTransaction = false;
                EndMembershipTransaction();
            }
            if (changed)
                FinishCurrentChange(
                    previous, value, previousFlagChanged, valueFlagChanged);
        }
        catch
        {
            if (ownsTransaction)
                EndMembershipTransaction(propagateDisposeFailure: false);
            if (publicationActive)
                EndCurrentPublication(propagateDisposeFailure: false);
            throw;
        }
        if (publicationActive) EndCurrentPublication(propagateDisposeFailure: true);
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
