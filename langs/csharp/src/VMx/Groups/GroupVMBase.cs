using System.Collections;
using System.Collections.Specialized;
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
public abstract class GroupVMBase<VM> : ComponentVMBase, IGroupVM<VM>, IParentCompositeVM
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
    IComponentVM? IParentCompositeVM.CurrentChild => null;
    void IParentCompositeVM.SelectChild(IComponentVM vm) { /* no-op: GroupVM has no selection */ }
    void IParentCompositeVM.DeselectChild(IComponentVM vm) { /* no-op: GroupVM has no selection */ }

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
            _children[index] = value;
            old.SetParent(null);
            value.SetParent(this);
            // Notify replace as Remove then Add (standard INCC pattern). The new
            // child is auto-constructed BETWEEN the two events, matching Python/TS:
            // subscribers observe the remove before the new child's construct
            // messages, and the add after.
            RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                NotifyCollectionChangedAction.Remove, old, index));
            MaybeAutoConstruct(value);
            RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                NotifyCollectionChangedAction.Add, value, index));
        }
    }

    // ── IList<VM>: mutation ───────────────────────────────────────────────────

    /// <inheritdoc/>
    public void Add(VM item)
    {
        _children.Add(item);
        item.SetParent(this);
        MaybeAutoConstruct(item);
        var idx = _children.Count - 1;
        RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Add, item, idx));
    }

    /// <inheritdoc/>
    public bool Remove(VM item)
    {
        var idx = _children.IndexOf(item);
        if (idx < 0) return false;
        RemoveAt(idx);
        return true;
    }

    /// <inheritdoc/>
    public void Insert(int index, VM item)
    {
        _children.Insert(index, item);
        item.SetParent(this);
        MaybeAutoConstruct(item);
        RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Add, item, index));
    }

    /// <inheritdoc/>
    public void RemoveAt(int index)
    {
        var item = _children[index];
        _children.RemoveAt(index);
        item.SetParent(null);
        RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Remove, item, index));
    }

    /// <inheritdoc/>
    public void Clear()
    {
        foreach (var child in _children)
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
    public bool Contains(VM item) => _children.Contains(item);

    /// <inheritdoc/>
    public int IndexOf(VM item) => _children.IndexOf(item);

    /// <inheritdoc/>
    public void CopyTo(VM[] array, int arrayIndex) => _children.CopyTo(array, arrayIndex);

    /// <inheritdoc/>
    public IEnumerator<VM> GetEnumerator() => _children.GetEnumerator();

    /// <inheritdoc/>
    IEnumerator IEnumerable.GetEnumerator() => _children.GetEnumerator();

    // ── Lifecycle overrides ───────────────────────────────────────────────────

    /// <summary>
    /// Overrides Construct to populate + construct every child.
    /// Called by the base Construct() between Constructing → Constructed transitions.
    /// </summary>
    protected override void OnConstruct()
    {
        base.OnConstruct(); // invoke user's onConstruct callback if any
        PopulateChildren();
        foreach (var child in _children.ToArray())
            child.Construct();
    }

    /// <summary>
    /// Called once per Construct() to populate the children collection from
    /// the configured factory. Default: no-op (children were added manually).
    /// Sealed subclasses override to evaluate their factory and Add children.
    /// </summary>
    protected virtual void PopulateChildren() { }

    /// <summary>
    /// Overrides Destruct: destructs all children.
    /// </summary>
    protected override void OnDestruct()
    {
        foreach (var child in _children.ToArray())
            child.Destruct();

        base.OnDestruct(); // invoke user's onDestruct callback if any
    }

    /// <summary>
    /// Dispose cascade (LIFE-013): recursively dispose each child depth-first, then self.
    /// </summary>
    public override void Dispose()
    {
        // Depth-first: dispose each child before self. Snapshot with ToArray so a
        // child whose Dispose() reentrantly removes a sibling cannot invalidate the
        // enumerator (parity with OnConstruct/OnDestruct and CompositeVMBase.Dispose).
        foreach (var child in _children.ToArray())
            child.Dispose();

        base.Dispose();
    }

    // ── IComponentVM.Type ─────────────────────────────────────────────────────

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Group;
}
