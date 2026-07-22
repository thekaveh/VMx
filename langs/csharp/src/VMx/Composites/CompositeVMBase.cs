using System.Collections;
using System.Collections.Specialized;
using System.Reactive.Disposables;
using VMx.Collections;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Services;

namespace VMx.Composites;

internal static class CompositeCurrentChangeCoordinator
{
    internal static object Gate { get; } = new();
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
    private int _disposeRequested;
    private bool _disposeDeferred;
    private int _activeCurrentPublications;
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
                }
                MaybeAutoConstruct(value);
                lock (_membershipGate) EnsureTransactionCanContinueLocked();
                admissionComplete = true;
                ComponentOwnership.CommitThenPublish(transfer, () =>
                {
                    if (ReferenceEquals(Current, old))
                        ApplyCurrentChange(null, internalTransaction: true);
                    RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                        NotifyCollectionChangedAction.Remove, old, index));
                    RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                        NotifyCollectionChangedAction.Add, value, index));
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
            if (wasCurrent)
                FinishCurrentChange(removed, null, previousFlagChanged, false);
            RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                NotifyCollectionChangedAction.Remove, removed, idx));
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
            if (wasCurrent)
                FinishCurrentChange(item, null, previousFlagChanged, false);
            RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                NotifyCollectionChangedAction.Remove, item, index));
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
            if (previous is not null)
                FinishCurrentChange(previous, null, previousFlagChanged, false);
            RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                NotifyCollectionChangedAction.Reset));
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
        PopulateChildren();
        CompleteLifecycleHookAfter(TransitionChildrenAsync(
            Snapshot().ToArray(),
            construct: true,
            after: () =>
            {
                // The selector runs only after every child settles Constructed.
                if (_currentSelector is null) return;
                var initial = _currentSelector(this);
                if (initial is not null && IndexOfIdentity(initial) >= 0)
                    SetCurrent(initial, async: false);
            }));
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
                    child.Construct();
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
            if (_membershipTransactionActive || _activeCurrentPublications > 0)
            {
                _disposeDeferred = true;
                return;
            }
            _disposeRequested = 1;
            snapshot = _children.ToArray();
        }
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

    private void EndMembershipTransaction(bool propagateDisposeFailure = true)
    {
        bool dispose;
        lock (_membershipGate)
        {
            _membershipTransactionActive = false;
            _membershipTransactionOwnerThreadId = 0;
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
