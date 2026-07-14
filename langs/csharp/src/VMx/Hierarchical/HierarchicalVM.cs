using System.Collections.ObjectModel;
using VMx.Components;
using VMx.Internal;
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
    private readonly List<TVM> _parkedAttachItems = [];

    private sealed class BatchCandidate<TKey> where TKey : notnull
    {
        public BatchCandidate(
            TVM item,
            TKey key,
            BatchParentKey<TKey> parentKey,
            bool retainIfMissing)
        {
            Item = item;
            Key = key;
            ParentKey = parentKey;
            RetainIfMissing = retainIfMissing;
        }

        public TVM Item { get; }
        public TKey Key { get; }
        public BatchParentKey<TKey> ParentKey { get; }
        public bool RetainIfMissing { get; }
    }

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

    /// <summary>
    /// Distance from the root. Root is 0; a child of root is 1; etc.
    /// Derived from the cached <see cref="Path"/> (root-to-this, inclusive), so it
    /// rides the same cache and invalidation rather than recursing per call.
    /// </summary>
    public int Depth => Path.Count - 1;

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
            CompleteLifecycleHookAfter(TransitionChildrenAsync(
                Children.Cast<IComponentVM>().ToArray(),
                construct: true));
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
        ThrowHelper.ThrowIfNull(child, nameof(child));
        AttachChild(child, explicitReparent: false);
    }

    /// <summary>
    /// Removes <paramref name="child"/> from this node's <see cref="Children"/> list
    /// and publishes <see cref="TreeStructureChangedMessage"/> on the hub.
    /// </summary>
    public void RemoveChild(TVM child)
    {
        ThrowHelper.ThrowIfNull(child, nameof(child));

        EnsureChildrenMaterialized();
        // Match by identity (not Equals) so a TVM overriding Equals cannot
        // cause the wrong sibling to be removed — consistent with the HIER-018
        // cycle check and the reparent detach.
        var index = _children!.FindIndex(c => ReferenceEquals(c, child));
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
        ThrowHelper.ThrowIfNull(child, nameof(child));
        AttachChild(child, explicitReparent: true);
    }

    private void AttachChild(TVM child, bool explicitReparent)
    {
        if (ReferenceEquals(child.HierarchicalParent, this)) return;
        if (Path.Any(p => ReferenceEquals(p, child)))
            throw new InvalidOperationException(
                $"Cannot reparent '{child.Name}' under '{Name}': it is this node or one of its ancestors (HIER-018).");

        // Materialize both collections before mutation so a factory failure
        // cannot leave the child detached from its original parent.
        EnsureChildrenMaterialized();
        var oldParent = child._hierarchicalParent;
        oldParent?.EnsureChildrenMaterialized();
        var oldIndex = oldParent?._children!.FindIndex(c => ReferenceEquals(c, child)) ?? -1;
        var newIndex = _children!.Count;

        if (oldIndex >= 0) oldParent!._children!.RemoveAt(oldIndex);
        try
        {
            _children.Add(child);
            child.SetHierarchicalParent((TVM)this);
        }
        catch
        {
            _children.RemoveAll(candidate => ReferenceEquals(candidate, child));
            if (oldIndex >= 0) oldParent!._children!.Insert(oldIndex, child);
            if (!ReferenceEquals(child._hierarchicalParent, oldParent))
                child.SetHierarchicalParent(oldParent);
            throw;
        }

        var reparented = explicitReparent || oldParent is not null;
        Hub.Send(new TreeStructureChangedMessage(
            Source: this,
            Change: reparented ? TreeStructureChange.Reparented : TreeStructureChange.Added,
            Affected: child,
            Index: reparented ? -1 : newIndex));
    }

    /// <summary>Number of missing-parent items retained on the structural root.</summary>
    public int ParkedAttachCount => GetTreeRoot()._parkedAttachItems.Count;

    /// <summary>
    /// Attaches an out-of-order, consumer-keyed batch beneath this node's
    /// structural root. Ordinary ingestion anomalies are returned as typed
    /// rejections; an existing same-key node is never replaced.
    /// </summary>
    public BatchAttachResult<TVM> AttachMany<TKey>(
        IEnumerable<TVM> items,
        Func<TVM, TKey> keyOf,
        Func<TVM, BatchParentKey<TKey>> parentKeyOf,
        MissingParentPolicy onMissingParent = MissingParentPolicy.Park)
        where TKey : notnull
    {
        ThrowHelper.ThrowIfNull(items, nameof(items));
        ThrowHelper.ThrowIfNull(keyOf, nameof(keyOf));
        ThrowHelper.ThrowIfNull(parentKeyOf, nameof(parentKeyOf));

        var root = GetTreeRoot();
        var incoming = items.ToList();
        var parked = root._parkedAttachItems.ToList();
        root._parkedAttachItems.Clear();
        var added = new List<TVM>();
        var duplicates = new List<TVM>();
        var orphans = new List<TVM>();
        var rejections = new List<BatchAttachRejection<TVM>>();
        var existing = new Dictionary<TKey, TVM>();

        try
        {
            foreach (var node in root.MaterializedSubtree())
            {
                var key = keyOf(node);
                if (key is null) throw new InvalidOperationException("keyOf returned null.");
                if (!existing.TryGetValue(key, out _)) existing.Add(key, node);
            }
        }
        catch (Exception exception)
        {
            root._parkedAttachItems.AddRange(parked);
            rejections.AddRange(parked.Concat(incoming).Select(item => new BatchAttachRejection<TVM>(
                item,
                BatchAttachRejectionReason.SelectorFailed,
                exception.Message)));
            return new BatchAttachResult<TVM>(added, duplicates, orphans, rejections);
        }

        var candidates = new List<BatchCandidate<TKey>>();
        var candidateKeys = new HashSet<TKey>();
        foreach (var entry in parked.Select(item => (Item: item, WasParked: true))
                     .Concat(incoming.Select(item => (Item: item, WasParked: false))))
        {
            TKey key;
            BatchParentKey<TKey> parentKey;
            try
            {
                key = keyOf(entry.Item);
                if (key is null) throw new InvalidOperationException("keyOf returned null.");
                parentKey = parentKeyOf(entry.Item);
            }
            catch (Exception exception)
            {
                if (entry.WasParked) root._parkedAttachItems.Add(entry.Item);
                rejections.Add(new BatchAttachRejection<TVM>(
                    entry.Item,
                    BatchAttachRejectionReason.SelectorFailed,
                    exception.Message));
                continue;
            }

            if (existing.ContainsKey(key))
            {
                duplicates.Add(entry.Item);
                rejections.Add(new BatchAttachRejection<TVM>(
                    entry.Item,
                    BatchAttachRejectionReason.DuplicateExistingKey));
                continue;
            }
            if (candidateKeys.Contains(key))
            {
                duplicates.Add(entry.Item);
                rejections.Add(new BatchAttachRejection<TVM>(
                    entry.Item,
                    BatchAttachRejectionReason.DuplicateBatchKey));
                continue;
            }
            if (entry.Item._hierarchicalParent is not null)
            {
                rejections.Add(new BatchAttachRejection<TVM>(
                    entry.Item,
                    BatchAttachRejectionReason.AlreadyAttached));
                continue;
            }

            candidateKeys.Add(key);

            candidates.Add(new BatchCandidate<TKey>(
                entry.Item,
                key,
                parentKey,
                entry.WasParked || onMissingParent == MissingParentPolicy.Park));
        }

        var unresolved = candidates;
        while (unresolved.Count > 0)
        {
            var next = new List<BatchCandidate<TKey>>();
            var progressed = false;
            foreach (var candidate in unresolved)
            {
                TVM? parent;
                if (candidate.ParentKey.IsRoot)
                    parent = root;
                else
                    existing.TryGetValue(candidate.ParentKey.Key, out parent);
                if (parent is null)
                {
                    next.Add(candidate);
                    continue;
                }

                try
                {
                    parent.AddChild(candidate.Item);
                }
                catch (Exception exception)
                {
                    RollbackBatchAttach(parent, candidate.Item);
                    rejections.Add(new BatchAttachRejection<TVM>(
                        candidate.Item,
                        BatchAttachRejectionReason.AttachmentFailed,
                        exception.Message));
                    continue;
                }

                existing.Add(candidate.Key, candidate.Item);
                added.Add(candidate.Item);
                progressed = true;
            }
            unresolved = next;
            if (!progressed) break;
        }

        var unresolvedByKey = unresolved.ToDictionary(candidate => candidate.Key);
        foreach (var candidate in unresolved)
        {
            var isCycle = BatchParentChainCycles(candidate, unresolvedByKey);
            var reason = isCycle
                ? BatchAttachRejectionReason.Cycle
                : BatchAttachRejectionReason.MissingParent;
            rejections.Add(new BatchAttachRejection<TVM>(candidate.Item, reason));
            if (!isCycle)
            {
                orphans.Add(candidate.Item);
                if (candidate.RetainIfMissing) root._parkedAttachItems.Add(candidate.Item);
            }
        }

        return new BatchAttachResult<TVM>(added, duplicates, orphans, rejections);
    }

    /// <summary>
    /// Drops this node's materialized child cache. The next <see cref="Children"/>
    /// access invokes the children factory again. Invalidating an unmaterialized
    /// node is a no-op.
    /// </summary>
    public void InvalidateChildren()
    {
        if (_children is null) return;
        _children = null;
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(
            this, Name, nameof(Children)));
    }

    /// <summary>
    /// Drops cached children for this node and all materialized descendants.
    /// </summary>
    public void InvalidateSubtree()
    {
        if (_children is null) return;
        foreach (var child in _children.ToArray())
            child.InvalidateSubtree();
        InvalidateChildren();
    }

    /// <inheritdoc/>
    protected override void OnDispose()
    {
        _parkedAttachItems.Clear();
        base.OnDispose();
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

    private TVM GetTreeRoot()
    {
        var node = (TVM)this;
        while (node._hierarchicalParent is not null)
            node = node._hierarchicalParent;
        return node;
    }

    private IEnumerable<TVM> MaterializedSubtree()
    {
        var stack = new Stack<TVM>();
        stack.Push((TVM)this);
        while (stack.Count > 0)
        {
            var node = stack.Pop();
            yield return node;
            if (node._children is null) continue;
            for (var index = node._children.Count - 1; index >= 0; index--)
                stack.Push(node._children[index]);
        }
    }

    private static bool BatchParentChainCycles<TKey>(
        BatchCandidate<TKey> candidate,
        IReadOnlyDictionary<TKey, BatchCandidate<TKey>> unresolved)
        where TKey : notnull
    {
        var seen = new HashSet<TKey>();
        BatchCandidate<TKey>? current = candidate;
        while (current is not null)
        {
            if (!seen.Add(current.Key)) return true;
            if (current.ParentKey.IsRoot) return false;
            unresolved.TryGetValue(current.ParentKey.Key, out current);
        }
        return false;
    }

    private static void RollbackBatchAttach(TVM parent, TVM child)
    {
        if (parent._children is not null)
            parent._children.RemoveAll(item => ReferenceEquals(item, child));
        child._hierarchicalParent = null;
        child._pathCache = null;
        child.InvalidatePathCacheDescendants();
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
