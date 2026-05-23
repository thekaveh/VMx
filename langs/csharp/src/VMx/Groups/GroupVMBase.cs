#pragma warning disable CA1715 // Spec uses 'VM' for child VM type parameter per ADR-0006
using System.Collections;
using System.Collections.Specialized;
using VMx.Components;
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
    // ── Children backing store ────────────────────────────────────────────────
    private readonly List<VM> _children = new();

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
        Action? onConstruct,
        Action? onDestruct)
        : base(name, hint, hub, dispatcher, onConstruct, onDestruct)
    {
    }

    // ── IParentCompositeVM (non-generic; children may call Select/Deselect) ────
    // GroupVM has no selection concept; these are deliberate no-ops.

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
            // Notify replace as Remove then Add (standard INCC pattern).
            CollectionChanged?.Invoke(this, new NotifyCollectionChangedEventArgs(
                NotifyCollectionChangedAction.Remove, old, index));
            CollectionChanged?.Invoke(this, new NotifyCollectionChangedEventArgs(
                NotifyCollectionChangedAction.Add, value, index));
            old.SetParent(null);
            value.SetParent(this);
        }
    }

    // ── IList<VM>: mutation ───────────────────────────────────────────────────

    /// <inheritdoc/>
    public void Add(VM item)
    {
        _children.Add(item);
        item.SetParent(this);
        var idx = _children.Count - 1;
        CollectionChanged?.Invoke(this, new NotifyCollectionChangedEventArgs(
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
        CollectionChanged?.Invoke(this, new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Add, item, index));
    }

    /// <inheritdoc/>
    public void RemoveAt(int index)
    {
        var item = _children[index];
        _children.RemoveAt(index);
        item.SetParent(null);
        CollectionChanged?.Invoke(this, new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Remove, item, index));
    }

    /// <inheritdoc/>
    public void Clear()
    {
        foreach (var child in _children)
            child.SetParent(null);
        _children.Clear();
        CollectionChanged?.Invoke(this, new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Reset));
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
        foreach (var child in _children)
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
        foreach (var child in _children)
            child.Destruct();

        base.OnDestruct(); // invoke user's onDestruct callback if any
    }

    /// <summary>
    /// Dispose cascade (LIFE-013): recursively dispose each child depth-first, then self.
    /// </summary>
    public override void Dispose()
    {
        // Depth-first: dispose each child before self.
        foreach (var child in _children)
            child.Dispose();

        base.Dispose();
        GC.SuppressFinalize(this);
    }

    // ── IComponentVM.Type ─────────────────────────────────────────────────────

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Group;
}
#pragma warning restore CA1715
