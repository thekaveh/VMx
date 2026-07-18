using System.Collections;
using System.Collections.Specialized;
using System.Reactive.Disposables;
using VMx.Collections;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Services;

namespace VMx.Groups;

/// <summary>
/// Abstract base for all GroupVM variants. Implements <see cref="IGroupVM{VM}"/>
/// on top of <see cref="ComponentVMBase"/>: ordered peer-child collection with
/// <see cref="INotifyCollectionChanged"/> events, and coordinated Construct /
/// Destruct / Dispose for the child hierarchy.
///
/// GroupVM differs from CompositeVMBase by having no <c>Current</c> selection slot
/// and no child-navigation commands. Children are peers, not navigable.
///
/// See spec/07-group-vm.md.
/// </summary>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public abstract class GroupVMBase<VM> : ComponentVMBase, IGroupVM<VM>,
    IParentCompositeVM, IObservableMembershipSource<VM>
    where VM : class, IComponentVM
{
    private readonly bool _autoConstructOnAdd;

    // ── Children backing store ────────────────────────────────────────────────
    private readonly List<VM> _children = new();

    // ── Batch-update state (spec v1.1) ────────────────────────────────────────
    private int _batchDepth;
    private bool _batchDirty;
    private int _disposeRequested;
    private bool _disposeDeferred;
    private bool _membershipTransactionActive;
    private int _membershipTransactionOwnerThreadId;
    private readonly object _membershipGate = new();

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

    // ── Constructor ───────────────────────────────────────────────────────────

    /// <summary>
    /// Initializes the group base.
    /// </summary>
    protected GroupVMBase(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        bool autoConstructOnAdd,
        Action? onConstruct,
        Action? onDestruct)
        : base(name, hint, hub, dispatcher, onConstruct, onDestruct)
    {
        _autoConstructOnAdd = autoConstructOnAdd;
    }

    // ── IParentCompositeVM (non-generic; children may call Select/Deselect) ────
    // GroupVM has no selection concept; these are deliberate no-ops.

    bool IParentCompositeVM.SupportsChildSelection => false;
    IComponentVM IParentCompositeVM.Owner => this;
    IParentCompositeVM? IParentCompositeVM.OwnerParent => Parent;
    IComponentVM? IParentCompositeVM.CurrentChild => null;
    void IParentCompositeVM.SelectChild(IComponentVM vm) { /* no-op: GroupVM has no selection */ }
    void IParentCompositeVM.DeselectChild(IComponentVM vm) { /* no-op: GroupVM has no selection */ }
    bool IParentCompositeVM.ContainsChild(IComponentVM vm)
    {
        lock (_membershipGate)
            return _children.Any(child => ReferenceEquals(child, vm));
    }

    ParentTransferToken IParentCompositeVM.DetachForTransfer(IComponentVM vm)
    {
        int index;
        VM child;
        lock (_membershipGate)
        {
            BeginMembershipTransactionLocked();
            index = _children.FindIndex(candidate => ReferenceEquals(candidate, vm));
            if (index < 0 || vm is not VM typed)
            {
                _membershipTransactionActive = false;
                _membershipTransactionOwnerThreadId = 0;
                Monitor.PulseAll(_membershipGate);
                throw new InvalidOperationException("The recorded parent does not contain the child identity.");
            }
            child = typed;
            _children.RemoveAt(index);
        }
        return new ParentTransferToken(
            commit: () =>
            {
                try
                {
                    RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                        NotifyCollectionChangedAction.Remove, child, index));
                }
                finally { EndMembershipTransaction(); }
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
                finally { EndMembershipTransaction(); }
            });
    }

    // ── IList<VM>: count / indexer ────────────────────────────────────────────

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
                }
                MaybeAutoConstruct(value);
                lock (_membershipGate) EnsureTransactionCanContinueLocked();
            }
            catch
            {
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
                }
                try { transfer?.Rollback(); }
                finally { EndMembershipTransaction(); }
                throw;
            }
            try
            {
                transfer?.Commit();
                RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                    NotifyCollectionChangedAction.Remove, old, index));
                RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                    NotifyCollectionChangedAction.Add, value, index));
            }
            finally { EndMembershipTransaction(); }
        }
    }

    // ── IList<VM>: mutation ───────────────────────────────────────────────────

    /// <inheritdoc/>
    public void Add(VM item)
    {
        BeginMembershipTransaction();
        ParentTransferToken? transfer = null;
        var attached = false;
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
            }
            MaybeAutoConstruct(item);
            lock (_membershipGate) EnsureTransactionCanContinueLocked();
        }
        catch
        {
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
            }
            try { transfer?.Rollback(); }
            finally { EndMembershipTransaction(); }
            throw;
        }
        try
        {
            transfer?.Commit();
            RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                NotifyCollectionChangedAction.Add, item, idx));
        }
        finally { EndMembershipTransaction(); }
    }

    /// <inheritdoc/>
    public bool Remove(VM item)
    {
        VM removed;
        int idx;
        lock (_membershipGate)
        {
            EnsureChildAdmission();
            idx = _children.FindIndex(candidate => ReferenceEquals(candidate, item));
            if (idx < 0) return false;
            removed = RemoveAtLocked(idx);
        }
        RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Remove, removed, idx));
        return true;
    }

    /// <inheritdoc/>
    public void Insert(int index, VM item)
    {
        BeginMembershipTransaction();
        ParentTransferToken? transfer = null;
        var attached = false;
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
            }
            MaybeAutoConstruct(item);
            lock (_membershipGate) EnsureTransactionCanContinueLocked();
        }
        catch
        {
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
            }
            try { transfer?.Rollback(); }
            finally { EndMembershipTransaction(); }
            throw;
        }
        try
        {
            transfer?.Commit();
            RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                NotifyCollectionChangedAction.Add, item, index));
        }
        finally { EndMembershipTransaction(); }
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

    /// <inheritdoc/>
    public void RemoveAt(int index)
    {
        VM item;
        lock (_membershipGate)
        {
            EnsureChildAdmission();
            item = RemoveAtLocked(index);
        }
        RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Remove, item, index));
    }

    /// <inheritdoc/>
    public void Clear()
    {
        lock (_membershipGate)
        {
            EnsureChildAdmission();
            foreach (var child in _children)
                if (ReferenceEquals(child.GetParent(), this))
                    child.SetParent(null);
            _children.Clear();
        }
        RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Reset));
    }

    /// <summary>
    /// Opens a ref-counted batch window. Mutations inside suppress individual
    /// <see cref="CollectionChanged"/> events. The outermost dispose fires a
    /// single <c>Reset</c> event iff any mutation occurred during the batch.
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
            CollectionChanged?.Invoke(this, new NotifyCollectionChangedEventArgs(
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
        CollectionChanged?.Invoke(this, args);
    }

    private void MaybeAutoConstruct(VM item)
    {
        if (!_autoConstructOnAdd) return;
        if (Status != ConstructionStatus.Constructed) return;
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
    /// Decrement the group's batch depth on dispose.
    /// </summary>
    private sealed class CollectionBatch : IDisposable
    {
        private readonly GroupVMBase<VM> _owner;
        private bool _disposed;

        internal CollectionBatch(GroupVMBase<VM> owner) => _owner = owner;

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

    private int IndexOfIdentity(VM item)
    {
        lock (_membershipGate)
            return _children.FindIndex(candidate => ReferenceEquals(candidate, item));
    }

    // ── Lifecycle overrides ───────────────────────────────────────────────────

    /// <summary>
    /// Overrides Construct to populate + construct every child.
    /// Called by the base Construct() between Constructing → Constructed transitions.
    /// </summary>
    protected override void OnConstruct()
    {
        base.OnConstruct(); // invoke user's onConstruct callback if any
        PopulateChildren();
        CompleteLifecycleHookAfter(TransitionChildrenAsync(
            Snapshot().ToArray(),
            construct: true));
    }

    /// <summary>
    /// Called once per Construct() to populate the children collection from
    /// the configured factory. Default: no-op (children were added manually).
    /// Sealed subclasses override to evaluate their factory and Add children.
    /// </summary>
    protected virtual void PopulateChildren() { }

    /// <summary>Attaches one factory population as an all-or-nothing transaction.</summary>
    protected void AttachPopulation(IEnumerable<VM> children)
    {
        var candidates = children.ToArray();
        if (candidates.Where((candidate, index) =>
                candidates.Take(index).Any(previous => ReferenceEquals(previous, candidate))).Any())
            throw new InvalidOperationException(
                "Factory population contains a duplicate child identity.");
        BeginMembershipTransaction();
        var transfers = new List<ParentTransferToken?>();
        var originalStatuses = new List<ConstructionStatus>();
        try
        {
            foreach (var child in candidates)
            {
                var transfer = ComponentOwnership.BeginTransfer(child, this);
                transfers.Add(transfer);
                originalStatuses.Add(child.Status);
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

            foreach (var child in candidates)
            {
                if (Status == ConstructionStatus.Constructing)
                    child.Construct();
                else
                    MaybeAutoConstruct(child);
            }
        }
        catch (Exception originalError)
        {
            var rollbackFailures = new List<Exception>();
            for (var candidateIndex = candidates.Length - 1; candidateIndex >= 0; candidateIndex--)
            {
                var child = candidates[candidateIndex];
                lock (_membershipGate)
                {
                    var attached = _children.FindIndex(item => ReferenceEquals(item, child));
                    if (attached >= 0) _children.RemoveAt(attached);
                }
                if (candidateIndex >= originalStatuses.Count) continue;
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
            finally { EndMembershipTransaction(); }
            if (rollbackFailures.Count > 0)
                throw new AggregateException(
                    "Group population failed and rollback could not restore lifecycle state.",
                    new[] { originalError }.Concat(rollbackFailures));
            throw;
        }
        try
        {
            foreach (var transfer in transfers) transfer?.Commit();
            foreach (var child in candidates)
            {
                var index = Snapshot().ToList().FindIndex(
                    candidate => ReferenceEquals(candidate, child));
                if (index >= 0)
                    RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                        NotifyCollectionChangedAction.Add, child, index));
            }
        }
        finally { EndMembershipTransaction(); }
    }

    /// <summary>
    /// Overrides Destruct: destructs all children.
    /// </summary>
    protected override void OnDestruct()
    {
        CompleteLifecycleHookAfter(TransitionChildrenAsync(
            Snapshot().ToArray(),
            construct: false,
            after: () => base.OnDestruct()));
    }

    /// <summary>
    /// Dispose cascade (LIFE-013): recursively dispose each child depth-first, then self.
    /// </summary>
    public override void Dispose()
    {
        VM[] snapshot;
        lock (_membershipGate)
        {
            if (_disposeRequested != 0) return;
            while (_membershipTransactionActive
                   && _membershipTransactionOwnerThreadId != Environment.CurrentManagedThreadId)
            {
                Monitor.Wait(_membershipGate);
                if (_disposeRequested != 0) return;
            }
            if (_membershipTransactionActive)
            {
                _disposeDeferred = true;
                return;
            }
            _disposeRequested = 1;
            snapshot = _children.ToArray();
        }
        // Depth-first: dispose each child before self. Snapshot with ToArray so a
        // child whose Dispose() reentrantly removes a sibling cannot invalidate the
        // enumerator (parity with OnConstruct/OnDestruct and CompositeVMBase.Dispose).
        var firstError = DisposeChildren(snapshot);
        try
        {
            base.Dispose();
        }
        catch (Exception error)
        {
            firstError ??= System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(error);
        }
        firstError?.Throw();
    }

    // ── IComponentVM.Type ─────────────────────────────────────────────────────

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Group;

    private void EnsureChildAdmission()
    {
        if (Volatile.Read(ref _disposeRequested) != 0 || _disposeDeferred)
            throw new ObjectDisposedException(GetType().Name,
                "Cannot attach a child while the container is disposing.");
        if (_membershipTransactionActive)
            throw new InvalidOperationException(
                "A container membership transaction is already in progress.");
    }

    private void BeginMembershipTransactionLocked()
    {
        EnsureChildAdmission();
        _membershipTransactionActive = true;
        _membershipTransactionOwnerThreadId = Environment.CurrentManagedThreadId;
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

    private void EndMembershipTransaction()
    {
        bool dispose;
        lock (_membershipGate)
        {
            _membershipTransactionActive = false;
            _membershipTransactionOwnerThreadId = 0;
            dispose = _disposeDeferred;
            _disposeDeferred = false;
            Monitor.PulseAll(_membershipGate);
        }
        if (dispose) Dispose();
    }

    private VM RemoveAtLocked(int index)
    {
        var item = _children[index];
        _children.RemoveAt(index);
        if (ReferenceEquals(item.GetParent(), this)) item.SetParent(null);
        return item;
    }
}
