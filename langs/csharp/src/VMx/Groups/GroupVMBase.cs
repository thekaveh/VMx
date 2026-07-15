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

    // ── INotifyCollectionChanged ──────────────────────────────────────────────
    /// <inheritdoc/>
    public event NotifyCollectionChangedEventHandler? CollectionChanged;

    /// <inheritdoc/>
    public IReadOnlyList<VM> Snapshot() => _children.ToArray();

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
        => _children.Any(child => ReferenceEquals(child, vm));

    ParentTransferToken IParentCompositeVM.DetachForTransfer(IComponentVM vm)
    {
        var index = _children.FindIndex(child => ReferenceEquals(child, vm));
        if (index < 0 || vm is not VM child)
            throw new InvalidOperationException("The recorded parent does not contain the child identity.");

        _children.RemoveAt(index);
        return new ParentTransferToken(
            commit: () => RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                NotifyCollectionChangedAction.Remove, child, index)),
            rollback: () =>
            {
                _children.Insert(index, child);
                child.SetParent(this);
            });
    }

    // ── IList<VM>: count / indexer ────────────────────────────────────────────

    /// <inheritdoc/>
    public int Count => _children.Count;

    /// <inheritdoc/>
    public bool IsReadOnly => false;

    /// <inheritdoc/>
    public VM this[int index]
    {
        get => _children[index];
        set
        {
            var old = _children[index];
            var transfer = ComponentOwnership.BeginTransfer(value, this);
            _children[index] = value;
            old.SetParent(null);
            value.SetParent(this);
            try
            {
                MaybeAutoConstruct(value);
            }
            catch
            {
                _children[index] = old;
                old.SetParent(this);
                value.SetParent(null);
                transfer?.Rollback();
                throw;
            }

            transfer?.Commit();
            RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                NotifyCollectionChangedAction.Remove, old, index));
            RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                NotifyCollectionChangedAction.Add, value, index));
        }
    }

    // ── IList<VM>: mutation ───────────────────────────────────────────────────

    /// <inheritdoc/>
    public void Add(VM item)
    {
        var transfer = ComponentOwnership.BeginTransfer(item, this);
        _children.Add(item);
        item.SetParent(this);
        try
        {
            MaybeAutoConstruct(item);
        }
        catch
        {
            _children.RemoveAt(_children.Count - 1);
            item.SetParent(null);
            transfer?.Rollback();
            throw;
        }

        transfer?.Commit();
        var idx = _children.Count - 1;
        RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Add, item, idx));
    }

    /// <inheritdoc/>
    public bool Remove(VM item)
    {
        var idx = IndexOfIdentity(item);
        if (idx < 0) return false;
        RemoveAt(idx);
        return true;
    }

    /// <inheritdoc/>
    public void Insert(int index, VM item)
    {
        if (index < 0 || index > _children.Count)
            throw new ArgumentOutOfRangeException(nameof(index));
        var transfer = ComponentOwnership.BeginTransfer(item, this);
        _children.Insert(index, item);
        item.SetParent(this);
        try
        {
            MaybeAutoConstruct(item);
        }
        catch
        {
            _children.RemoveAt(index);
            item.SetParent(null);
            transfer?.Rollback();
            throw;
        }

        transfer?.Commit();
        RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Add, item, index));
    }

    /// <inheritdoc/>
    public void Move(int fromIndex, int toIndex)
    {
        ValidateMoveIndex(fromIndex, nameof(fromIndex));
        ValidateMoveIndex(toIndex, nameof(toIndex));
        if (fromIndex == toIndex) return;

        var item = _children[fromIndex];
        _children.RemoveAt(fromIndex);
        _children.Insert(toIndex, item);
        RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Move, item, toIndex, fromIndex));
    }

    /// <inheritdoc/>
    public void RemoveAt(int index)
    {
        var item = _children[index];
        _children.RemoveAt(index);
        if (ReferenceEquals(item.GetParent(), this))
            item.SetParent(null);
        RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Remove, item, index));
    }

    /// <inheritdoc/>
    public void Clear()
    {
        foreach (var child in _children)
            if (ReferenceEquals(child.GetParent(), this))
                child.SetParent(null);
        _children.Clear();
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
    public void CopyTo(VM[] array, int arrayIndex) => _children.CopyTo(array, arrayIndex);

    /// <inheritdoc/>
    public IEnumerator<VM> GetEnumerator() => _children.GetEnumerator();

    /// <inheritdoc/>
    IEnumerator IEnumerable.GetEnumerator() => _children.GetEnumerator();

    private int IndexOfIdentity(VM item) =>
        _children.FindIndex(candidate => ReferenceEquals(candidate, item));

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
            _children.ToArray(),
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
        var start = _children.Count;
        var transfers = new List<ParentTransferToken?>();
        var originalStatuses = new List<ConstructionStatus>();
        try
        {
            foreach (var child in candidates)
            {
                var transfer = ComponentOwnership.BeginTransfer(child, this);
                transfers.Add(transfer);
                originalStatuses.Add(child.Status);
                _children.Add(child);
                child.SetParent(this);
            }

            // Populate the complete snapshot before invoking any child hook.
            // Hooks may inspect or mutate later siblings, and background
            // children must have only one lifecycle transition in flight.
            foreach (var child in candidates)
            {
                if (Status == ConstructionStatus.Constructing)
                    child.Construct();
                else
                    MaybeAutoConstruct(child);
            }
        }
        catch
        {
            while (_children.Count > start)
            {
                var child = _children[_children.Count - 1];
                _children.RemoveAt(_children.Count - 1);
                var originalStatus = originalStatuses[_children.Count - start];
                if (originalStatus == ConstructionStatus.Destructed &&
                    child.Status == ConstructionStatus.Constructed)
                {
                    try { child.DestructAsync().GetAwaiter().GetResult(); }
                    catch { /* Preserve the original population failure. */ }
                }
                if (ReferenceEquals(child.GetParent(), this)) child.SetParent(null);
            }
            for (var index = transfers.Count - 1; index >= 0; index--)
                transfers[index]?.Rollback();
            throw;
        }

        foreach (var transfer in transfers) transfer?.Commit();
        foreach (var child in candidates)
        {
            var index = _children.FindIndex(candidate => ReferenceEquals(candidate, child));
            if (index >= start)
                RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                    NotifyCollectionChangedAction.Add, child, index));
        }
    }

    /// <summary>
    /// Overrides Destruct: destructs all children.
    /// </summary>
    protected override void OnDestruct()
    {
        CompleteLifecycleHookAfter(TransitionChildrenAsync(
            _children.ToArray(),
            construct: false,
            after: () => base.OnDestruct()));
    }

    /// <summary>
    /// Dispose cascade (LIFE-013): recursively dispose each child depth-first, then self.
    /// </summary>
    public override void Dispose()
    {
        // Depth-first: dispose each child before self. Snapshot with ToArray so a
        // child whose Dispose() reentrantly removes a sibling cannot invalidate the
        // enumerator (parity with OnConstruct/OnDestruct and CompositeVMBase.Dispose).
        var firstError = DisposeChildren(_children.ToArray());
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
}
