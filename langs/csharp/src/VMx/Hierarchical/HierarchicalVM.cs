#pragma warning disable CA1715 // Spec uses 'TModel' / 'TVM' per ADR-0006 and ADR-0028
using System.Collections.ObjectModel;
using VMx.Components;
using VMx.Messages;
using VMx.Services;

namespace VMx.Hierarchical;

/// <summary>
/// Abstract recursive tree ViewModel. Each node carries a typed
/// <typeparamref name="TModel"/> and may contain children of the same concrete
/// type <typeparamref name="TVM"/>.
///
/// Children are <b>lazy by default</b>: the children factory is not invoked
/// until <see cref="Children"/> is first accessed. Eager materialization can be
/// requested by passing <see langword="true"/> for the <c>eagerChildren</c>
/// constructor parameter — this causes the full subtree to be materialized and
/// each child node constructed during
/// <see cref="ComponentVMBase.OnConstruct"/>, in depth-first order.
///
/// See spec/18-hierarchical-vm.md and ADR-0028.
/// </summary>
/// <typeparam name="TModel">Domain model carried by this node.</typeparam>
/// <typeparam name="TVM">Concrete subclass type (recursive constraint per ADR-0028 §3.2).</typeparam>
public abstract class HierarchicalVM<TModel, TVM> : ComponentVMBase, IEnumerable<IComponentVM>
    where TVM : HierarchicalVM<TModel, TVM>
{
    private readonly Func<TVM, IEnumerable<TVM>> _childrenFactory;
    private readonly bool _eagerChildren;

    private TVM? _hierarchicalParent;
    private List<TVM>? _children;
    private ReadOnlyCollection<TVM>? _pathCache;

    // ── Constructor ─────────────────────────────────────────────────────────

    /// <summary>
    /// Initializes a new node.
    /// </summary>
    /// <param name="model">Domain model for this node.</param>
    /// <param name="childrenFactory">
    /// Factory invoked with this node to produce child instances. Called lazily on
    /// first access to <see cref="Children"/> unless <c>eagerChildren</c> is
    /// <see langword="true"/>.
    /// </param>
    /// <param name="hub">Message hub for pub/sub.</param>
    /// <param name="dispatcher">Dispatcher for async/background work.</param>
    /// <param name="name">Optional VM name (defaults to type name).</param>
    /// <param name="hint">Optional display hint string.</param>
    /// <param name="eagerChildren">
    /// When <see langword="true"/>, materializes the entire subtree at construct
    /// time (depth-first). Default is <see langword="false"/> (lazy).
    /// </param>
    protected HierarchicalVM(
        TModel model,
        Func<TVM, IEnumerable<TVM>> childrenFactory,
        IMessageHub hub,
        IDispatcher dispatcher,
        string? name = null,
        string hint = "",
        bool eagerChildren = false)
        : base(
            name ?? typeof(TVM).Name,
            hint,
            hub,
            dispatcher,
            onConstruct: null,
            onDestruct: null)
    {
        Model = model;
        _childrenFactory = childrenFactory;
        _eagerChildren = eagerChildren;
    }

    // ── Model ────────────────────────────────────────────────────────────────

    /// <summary>The domain model carried by this tree node.</summary>
    public TModel Model { get; }

    // ── Tree identity predicates ─────────────────────────────────────────────

    /// <summary>The parent node; <see langword="null"/> when this node is the root.</summary>
    public TVM? HierarchicalParent => _hierarchicalParent;

    /// <summary><see langword="true"/> when <see cref="HierarchicalParent"/> is <see langword="null"/>.</summary>
    public bool IsRoot => _hierarchicalParent is null;

    /// <summary>Distance from the root. Root is 0; a child of root is 1; etc.</summary>
    public int Depth => _hierarchicalParent is null ? 0 : _hierarchicalParent.Depth + 1;

    /// <summary>
    /// <see langword="true"/> when this node has no children.
    /// Note: accessing this property materializes <see cref="Children"/> if not yet done.
    /// </summary>
    public bool IsLeaf => Children.Count == 0;

    /// <summary>
    /// <see langword="true"/> when this is the first child in its parent's
    /// <see cref="Children"/> list. Always <see langword="false"/> for the root.
    /// </summary>
    public bool IsFirst =>
        _hierarchicalParent is not null &&
        _hierarchicalParent.Children.Count > 0 &&
        ReferenceEquals(_hierarchicalParent.Children[0], this);

    /// <summary>
    /// <see langword="true"/> when this is the last child in its parent's
    /// <see cref="Children"/> list. Always <see langword="false"/> for the root.
    /// </summary>
    public bool IsLast =>
        _hierarchicalParent is not null &&
        _hierarchicalParent.Children.Count > 0 &&
        ReferenceEquals(_hierarchicalParent.Children[_hierarchicalParent.Children.Count - 1], this);

    // ── Children ─────────────────────────────────────────────────────────────

    /// <summary>
    /// The ordered list of child nodes. Lazily materialized on first access
    /// unless <c>eagerChildren</c> was set at construction time.
    /// </summary>
    public IReadOnlyList<TVM> Children => _children ??= MaterializeChildren();

    // ── Path ─────────────────────────────────────────────────────────────────

    /// <summary>
    /// Materialized, cached path from the root to this node (inclusive).
    /// The cache is invalidated when <see cref="HierarchicalParent"/> changes.
    /// </summary>
    public IReadOnlyList<TVM> Path
    {
        get
        {
            if (_pathCache is null)
                _pathCache = BuildPath();
            return _pathCache;
        }
    }

    // ── IEnumerable<IComponentVM> — supports Walk / WalkExpanded ─────────────

    /// <summary>
    /// Iterates the materialized <see cref="Children"/> as <see cref="IComponentVM"/> —
    /// enables <c>Tree.Walk</c> / <c>Tree.WalkExpanded</c> traversal.
    /// </summary>
    public IEnumerator<IComponentVM> GetEnumerator()
    {
        foreach (var child in Children)
            yield return child;
    }

    System.Collections.IEnumerator System.Collections.IEnumerable.GetEnumerator() =>
        GetEnumerator();

    // ── Lifecycle override — eager construction ───────────────────────────────

    /// <inheritdoc/>
    protected override void OnConstruct()
    {
        base.OnConstruct();

        if (_eagerChildren)
        {
            // Depth-first: materialize and construct children before returning.
            // Each child's OnConstruct recurses into its own children first,
            // so the deepest leaf reaches Constructed before the parent.
            foreach (var child in Children)
                child.Construct();
        }
    }

    // ── Structural mutation (add / remove / reparent) ─────────────────────────

    /// <summary>
    /// Adds <paramref name="child"/> to this node's <see cref="Children"/> list,
    /// sets its <see cref="HierarchicalParent"/>, and publishes
    /// <see cref="TreeStructureChangedMessage"/> on the hub.
    /// </summary>
    public void AddChild(TVM child)
    {
#pragma warning disable CA1510 // ThrowIfNull not available on netstandard2.0 target
        if (child is null) throw new ArgumentNullException(nameof(child));
#pragma warning restore CA1510

        EnsureChildrenMaterialized();
        var index = _children!.Count;
        _children.Add(child);

        child.SetHierarchicalParent((TVM)this);

        Hub.Send(new TreeStructureChangedMessage(
            Source: this,
            Change: TreeStructureChange.Added,
            Affected: child,
            Index: index));
    }

    /// <summary>
    /// Removes <paramref name="child"/> from this node's <see cref="Children"/> list
    /// and publishes <see cref="TreeStructureChangedMessage"/> on the hub.
    /// </summary>
    public void RemoveChild(TVM child)
    {
#pragma warning disable CA1510 // ThrowIfNull not available on netstandard2.0 target
        if (child is null) throw new ArgumentNullException(nameof(child));
#pragma warning restore CA1510

        EnsureChildrenMaterialized();
        var index = _children!.IndexOf(child);
        if (index < 0) return;

        _children.RemoveAt(index);
        child.SetHierarchicalParent(null);

        Hub.Send(new TreeStructureChangedMessage(
            Source: this,
            Change: TreeStructureChange.Removed,
            Affected: child,
            Index: index));
    }

    /// <summary>
    /// Moves <paramref name="child"/> from its current parent to this node,
    /// updating parent references and publishing a
    /// <see cref="TreeStructureChange.Reparented"/> message on the hub.
    /// </summary>
    public void ReparentChild(TVM child)
    {
#pragma warning disable CA1510 // ThrowIfNull not available on netstandard2.0 target
        if (child is null) throw new ArgumentNullException(nameof(child));
#pragma warning restore CA1510
        if (ReferenceEquals(child.HierarchicalParent, this)) return;

        // HIER-018: reparenting this node or one of its ancestors under
        // itself would create a parent cycle and corrupt Depth/Path/Walk.
        if (Path.Contains(child))
            throw new InvalidOperationException(
                $"Cannot reparent '{child.Name}' under '{Name}': it is this node or one of its ancestors (HIER-018).");

        // Remove from old parent silently (no message — reparent covers it).
        var oldParent = child._hierarchicalParent;
        if (oldParent is not null)
        {
            oldParent.EnsureChildrenMaterialized();
            oldParent._children!.Remove(child);
        }

        EnsureChildrenMaterialized();
        _children!.Add(child);
        child.SetHierarchicalParent((TVM)this);

        Hub.Send(new TreeStructureChangedMessage(
            Source: this,
            Change: TreeStructureChange.Reparented,
            Affected: child,
            Index: -1));
    }

    // ── Internal helpers ─────────────────────────────────────────────────────

    private List<TVM> MaterializeChildren()
    {
        var list = new List<TVM>(_childrenFactory((TVM)this));
        // Direct-assign during initial factory hydration: parents do not
        // *change* on first materialization, so emitting `HierarchicalParent`
        // PropertyChangedMessage here would publish N spurious events on
        // the first lazy access (or eager construct). Python and TypeScript
        // do the same direct-assign — this keeps the three flavors in sync.
        foreach (var child in list)
            child._hierarchicalParent = (TVM)this;
        return list;
    }

    private void EnsureChildrenMaterialized()
    {
        if (_children is null)
            _children = MaterializeChildren();
    }

    private ReadOnlyCollection<TVM> BuildPath()
    {
        var chain = new List<TVM>();
        TVM? node = (TVM)this;
        while (node is not null)
        {
            chain.Add(node);
            node = node._hierarchicalParent;
        }
        chain.Reverse();
        return chain.AsReadOnly();
    }

    private void SetHierarchicalParent(TVM? parent)
    {
        if (ReferenceEquals(_hierarchicalParent, parent)) return;

        _hierarchicalParent = parent;
        _pathCache = null; // Invalidate path cache on parent change.

        // Invalidate path cache on all descendants as well.
        InvalidatePathCacheDescendants();

        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(
            this, Name, nameof(HierarchicalParent)));
    }

    private void InvalidatePathCacheDescendants()
    {
        if (_children is null) return;
        foreach (var child in _children)
        {
            child._pathCache = null;
            child.InvalidatePathCacheDescendants();
        }
    }
}
#pragma warning restore CA1715
