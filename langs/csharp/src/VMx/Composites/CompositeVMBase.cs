using System.Collections;
using System.Collections.Specialized;
using System.Reactive.Disposables;
using VMx.Collections;
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

    // ── ICompositeVM: Current ─────────────────────────────────────────────────

    /// <inheritdoc/>
    public VM? Current
    {
        get => _current;
        set => SetCurrent(value, async: _asyncSelection);
    }

    bool IParentCompositeVM.SupportsChildSelection => true;
    IComponentVM IParentCompositeVM.Owner => this;
    IParentCompositeVM? IParentCompositeVM.OwnerParent => Parent;

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
            if (ReferenceEquals(_current, old))
                SetCurrent(null, async: false);
            RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                NotifyCollectionChangedAction.Remove, old, index));
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

    bool IParentCompositeVM.ContainsChild(IComponentVM vm)
        => _children.Any(child => ReferenceEquals(child, vm));

    ParentTransferToken IParentCompositeVM.DetachForTransfer(IComponentVM vm)
    {
        var index = _children.FindIndex(child => ReferenceEquals(child, vm));
        if (index < 0 || vm is not VM child)
            throw new InvalidOperationException("The recorded parent does not contain the child identity.");

        var wasCurrent = ReferenceEquals(_current, child);
        _children.RemoveAt(index);
        return new ParentTransferToken(
            commit: () =>
            {
                if (wasCurrent && ReferenceEquals(_current, child))
                    SetCurrent(null, async: false);
                RaiseCollectionChanged(new NotifyCollectionChangedEventArgs(
                    NotifyCollectionChangedAction.Remove, child, index));
            },
            rollback: () =>
            {
                _children.Insert(index, child);
                child.SetParent(this);
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
        var idx = _children.IndexOf(item);
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
        if (ReferenceEquals(_current, item))
            SetCurrent(null, async: false);
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
        CompleteLifecycleHookAfter(TransitionChildrenAsync(
            _children.ToArray(),
            construct: true,
            after: () =>
            {
                // The selector runs only after every child settles Constructed.
                if (_currentSelector is null) return;
                var initial = _currentSelector(this);
                if (initial is not null && _children.Contains(initial))
                    SetCurrent(initial, async: false);
            }));
    }

    /// <summary>Constructs all current children sequentially.</summary>
    protected void ConstructChildren()
    {
        CompleteLifecycleHookAfter(TransitionChildrenAsync(
            _children.ToArray(),
            construct: true));
    }

    /// <summary>
    /// Called once per Construct() to populate the children collection from
    /// the configured factory.  Default: no-op (children were added manually).
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
    /// Overrides Destruct: sets Current = null first, then waits for every child.
    /// </summary>
    protected override void OnDestruct()
    {
        if (_current is not null)
            SetCurrent(null, async: false);

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
