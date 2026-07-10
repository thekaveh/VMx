using System.Collections;
using System.Collections.Specialized;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Services;

namespace VMx.Composites;

/// <summary>
/// Abstract base for all CompositeVM variants.  Implements <see cref="ICompositeVM{VM}"/>
/// on top of <see cref="ComponentVMBase"/>: ordered child collection with
/// <see cref="INotifyCollectionChanged"/> events, <see cref="Current"/> selection,
/// and coordinated Construct / Destruct / Dispose for the child hierarchy.
///
/// See spec/06-composite-vm.md.
/// </summary>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public abstract class CompositeVMBase<VM> : ComponentVMBase, ICompositeVM<VM>, IParentCompositeVM
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

    // ── INotifyCollectionChanged ──────────────────────────────────────────────
    /// <inheritdoc/>
    public event NotifyCollectionChangedEventHandler? CollectionChanged;

    // ── ICompositeVM: Current ─────────────────────────────────────────────────

    /// <inheritdoc/>
    public VM? Current
    {
        get => _current;
        set => SetCurrent(value, async: _asyncSelection);
    }

    bool IParentCompositeVM.SupportsChildSelection => true;

    // ── IList<VM> ─────────────────────────────────────────────────────────────

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
            // Mirror RemoveAt: if the slot we just replaced held the current
            // selection, drop Current to null before subscribers see any
            // CollectionChanged event for this replace.
            if (ReferenceEquals(_current, old))
                SetCurrent(null, async: false);
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

    IComponentVM? IParentCompositeVM.CurrentChild => _current;

    void IParentCompositeVM.SelectChild(IComponentVM vm)
    {
        if (vm is VM typed) SelectComponent(typed);
    }

    void IParentCompositeVM.DeselectChild(IComponentVM vm)
    {
        if (vm is VM typed) DeselectComponent(typed);
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
        if (!ReferenceEquals(_current, vm))
            throw new InvalidOperationException(
                $"Cannot deselect '{vm.Name}': it is not the current selection.");
        Current = null;
    }

    /// <inheritdoc/>
    public bool CanSelectComponent(VM vm)
        => _children.Contains(vm) && vm.Status == ConstructionStatus.Constructed;

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
        if (ReferenceEquals(_current, item))
            SetCurrent(null, async: false);
        RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Remove, item, index));
    }

    /// <inheritdoc/>
    public void Clear()
    {
        foreach (var child in _children)
            child.SetParent(null);
        _children.Clear();
        SetCurrent(null, async: false);
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
    /// Overrides Construct to populate + construct every child sequentially
    /// (see spec/06 §5 and ADR-0020). Called by the base Construct() between
    /// Constructing → Constructed transitions.
    /// </summary>
    protected override void OnConstruct()
    {
        base.OnConstruct(); // invoke user's onConstruct callback if any
        // Populate children from factory (lazy: only on first construct).
        PopulateChildren();
        // Construct all children.
        ConstructChildren();
        // Apply the optional initial-current selector (spec/06 §3.2, ADR-0042).
        // The composite is still in Constructing here; every child is Constructed.
        // Selector returning null or an out-of-set value leaves Current at its
        // prior value and emits no notification (matches SelectComponent semantics).
        if (_currentSelector is not null)
        {
            var initial = _currentSelector(this);
            if (initial is not null && _children.Contains(initial))
                SetCurrent(initial, async: false);
        }
    }

    /// <summary>Constructs all current children sequentially.</summary>
    protected void ConstructChildren()
    {
        foreach (var child in _children.ToArray())
            child.Construct();
    }

    /// <summary>
    /// Called once per Construct() to populate the children collection from
    /// the configured factory.  Default: no-op (children were added manually).
    /// Sealed subclasses override to evaluate their factory and Add children.
    /// </summary>
    protected virtual void PopulateChildren() { }

    /// <summary>
    /// Overrides Destruct: sets Current = null first, then destructs all children.
    /// </summary>
    protected override void OnDestruct()
    {
        if (_current is not null)
            SetCurrent(null, async: false);

        foreach (var child in _children.ToArray())
            child.Destruct();

        base.OnDestruct(); // invoke user's onDestruct callback if any
    }

    /// <summary>
    /// Dispose cascade (LIFE-013): recursively dispose each child depth-first, then self.
    /// </summary>
    public override void Dispose()
    {
        // Depth-first: dispose each child before self.
        foreach (var child in _children.ToArray())
            child.Dispose();

        base.Dispose();
    }

    // ── IComponentVM.Type ─────────────────────────────────────────────────────

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Composite;

    // ── Private helpers ───────────────────────────────────────────────────────

    private void SetCurrent(VM? value, bool async)
    {
        if (value is not null && !_children.Contains(value))
            throw new InvalidOperationException(
                $"Cannot set Current to '{value.Name}': it is not a member of this composite.");

        if (async)
        {
            _dispatcher.Foreground.Schedule(value, (sched, v) => { ApplyCurrentChange(v); return System.Reactive.Disposables.Disposable.Empty; });
        }
        else
        {
            ApplyCurrentChange(value);
        }
    }

    private void ApplyCurrentChange(VM? value)
    {
        // Async TOCTOU guard: with AsyncSelection the child may have been removed
        // between SetCurrent's membership check and this deferred foreground
        // delivery. Dropping silently upholds the spec/06 §3 invariant that a
        // non-null Current is always a member of the children collection.
        if (value is not null && !_children.Contains(value)) return;
        if (ReferenceEquals(_current, value)) return;

        var previous = _current;
        _current = value;

        // Update IsCurrent on affected children.
        if (previous is not null)
            previous.SetIsCurrent(false);
        if (value is not null)
            value.SetIsCurrent(true);

        // Emit PropertyChangedMessage for "Current" on the hub.
        NotifyPropertyChanged(nameof(Current));

        // Invoke the optional builder-registered OnCurrentChanged callback
        // AFTER state update + hub publish + PropertyChanged so all observers
        // see the new value consistently (spec/06 §3.2, ADR-0042 §5.2).
        _onCurrentChanged?.Invoke(value);
    }
}
