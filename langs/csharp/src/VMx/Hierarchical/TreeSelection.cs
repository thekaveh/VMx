using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Runtime.ExceptionServices;
using VMx.Internal;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;

namespace VMx.Hierarchical;

/// <summary>
/// Opt-in helper that holds one current node of a hierarchical tree. It is
/// composed on a tree node, its <b>root</b>, and accepts only nodes of the
/// root's materialized tree. See spec/18-hierarchical-vm.md §10 and ADR-0164.
/// </summary>
/// <remarks>
/// <para>
/// The helper adds no <see cref="HierarchicalVM{TModel,TVM}"/> member and
/// implements no capability on the nodes. It never takes ownership of the
/// root, never disposes, constructs, materializes, expands or moves a node,
/// never changes a node's <c>IsCurrent</c>, and publishes nothing to a
/// message hub (spec/18 §10.4).
/// </para>
/// <para>
/// While a node is current, the helper subscribes to the hub of every node on
/// the path from the current node to the root (one subscription per distinct
/// hub). On any message whose sender is a node of that path, it repeats the
/// <see cref="CanSelect"/> check. It clears the selection when the check
/// fails and watches the new path when the check passes (spec/18 §10.2).
/// Inside a hub transaction the clear happens when the hub delivers the
/// message.
/// </para>
/// <para>
/// The helper follows the threading model of its tree: like
/// <see cref="HierarchicalVM{TModel,TVM}"/>, it holds no lock and must be used
/// from one thread.
/// </para>
/// <para>
/// The VM that owns the helper forwards <see cref="CurrentChanged"/> to its
/// own property-change notification (spec/14 rule 6) and disposes the helper.
/// </para>
/// </remarks>
/// <typeparam name="TModel">Domain model carried by each tree node.</typeparam>
/// <typeparam name="TVM">Concrete tree node type.</typeparam>
public sealed class TreeSelection<TModel, TVM> : IDisposable
    where TVM : HierarchicalVM<TModel, TVM>
{
    private readonly TVM _root;
    private readonly Subject<TVM?> _changes = new();

    // The watched path, from the current node to the root (inclusive), and
    // one hub subscription per distinct hub of that path.
    private List<TVM> _path = [];
    private List<HubWatch> _watches = [];
    private TVM? _current;
    private bool _disposed;

    // Changes made while a value is being delivered wait here, so every
    // subscriber sees the changes in order (spec/18 §10.3).
    private readonly Queue<TVM?> _pending = new();
    private bool _emitting;

    /// <summary>
    /// Creates a selection on <paramref name="root"/> with no current node.
    /// </summary>
    /// <param name="root">
    /// The node whose materialized tree is selectable. It need not be a
    /// structural root. The helper never takes ownership of it.
    /// </param>
    /// <exception cref="ArgumentNullException"><paramref name="root"/> is null.</exception>
    public TreeSelection(TVM root)
    {
        ThrowHelper.ThrowIfNull(root, nameof(root));
        _root = root;
    }

    /// <summary>
    /// The current node, or <see langword="null"/> when nothing is selected.
    /// </summary>
    public TVM? Current => _current;

    /// <summary>
    /// Emits the new <see cref="Current"/> value, or <see langword="null"/>,
    /// once for every effective change. The stream is hot and does not replay
    /// a value to a new subscriber. It emits after the state is updated, so a
    /// subscriber may call <see cref="Select"/> or <see cref="Clear"/>.
    /// <see cref="Dispose"/> completes it without emitting.
    /// </summary>
    public IObservable<TVM?> CurrentChanged => _changes.AsObservable();

    /// <summary>
    /// Returns <see langword="true"/> when <paramref name="node"/> may become
    /// current: the helper is not disposed, walking
    /// <see cref="HierarchicalVM{TModel,TVM}.HierarchicalParent"/> links from
    /// <paramref name="node"/> reaches the root (the root itself qualifies),
    /// and no node on that path is <see cref="ConstructionStatus.Disposed"/>.
    /// </summary>
    /// <remarks>
    /// The check reads only parent links and status. It never reads
    /// <see cref="HierarchicalVM{TModel,TVM}.Children"/> and never invokes a
    /// children factory (spec/18 §10.1).
    /// </remarks>
    /// <param name="node">The candidate node; <see langword="null"/> is rejected.</param>
    public bool CanSelect(TVM? node)
    {
        if (_disposed || node is null) return false;
        for (var cursor = node; cursor is not null; cursor = cursor.HierarchicalParent)
        {
            if (cursor.Status == ConstructionStatus.Disposed) return false;
            if (ReferenceEquals(cursor, _root)) return true;
        }
        return false;
    }

    /// <summary>
    /// Makes <paramref name="node"/> current and emits it on
    /// <see cref="CurrentChanged"/>. Selecting the current node again does
    /// nothing. After <see cref="Dispose"/> the call does nothing.
    /// </summary>
    /// <param name="node">A node that <see cref="CanSelect"/> accepts.</param>
    /// <exception cref="ArgumentNullException"><paramref name="node"/> is null.</exception>
    /// <exception cref="InvalidOperationException">
    /// <see cref="CanSelect"/> rejects <paramref name="node"/>.
    /// <see cref="Current"/> keeps its value and nothing is emitted.
    /// </exception>
    public void Select(TVM node)
    {
        if (_disposed) return;
        ThrowHelper.ThrowIfNull(node, nameof(node));
        if (!CanSelect(node))
            throw new InvalidOperationException(
                $"Cannot select '{node.Name}': it is not a live member of the materialized tree of '{_root.Name}'.");
        if (ReferenceEquals(node, _current)) return;

        // Watch first: a failed subscription leaves the previous state intact.
        Watch(node);
        _current = node;
        Emit(node);
    }

    /// <summary>
    /// Sets <see cref="Current"/> to <see langword="null"/> and emits
    /// <see langword="null"/> on <see cref="CurrentChanged"/>. Does nothing
    /// when nothing is selected or after <see cref="Dispose"/>.
    /// </summary>
    public void Clear()
    {
        if (_disposed || _current is null) return;
        _current = null;
        Unwatch();
        Emit(null);
    }

    /// <summary>
    /// Releases the hub subscriptions, sets <see cref="Current"/> to
    /// <see langword="null"/> without emitting, and completes
    /// <see cref="CurrentChanged"/>. Every step runs, and the first failure is
    /// rethrown. A second call does nothing. Disposing the helper never
    /// disposes or detaches a node.
    /// </summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _current = null;
        _path = [];
        _pending.Clear();

        // A throwing step must not skip a later one. Run every step, then
        // rethrow the first failure (#768).
        ExceptionDispatchInfo? firstError = null;
        var watches = _watches;
        _watches = [];
        foreach (var watch in watches)
            FirstFailure.Capture(ref firstError, watch.Subscription.Dispose);
        FirstFailure.Capture(ref firstError, _changes.OnCompleted);
        FirstFailure.Capture(ref firstError, _changes.Dispose);
        firstError?.Throw();
    }

    // Delivers value after the changes already being delivered. A subscriber
    // that selects or clears re-entrantly queues its change behind this one.
    // A throwing subscriber does not drop later changes; the first failure is
    // rethrown once the queue is drained.
    private void Emit(TVM? value)
    {
        _pending.Enqueue(value);
        if (_emitting) return;
        _emitting = true;
        ExceptionDispatchInfo? firstError = null;
        try
        {
            while (_pending.Count > 0 && !_disposed)
            {
                var next = _pending.Dequeue();
                FirstFailure.Capture(ref firstError, () => _changes.OnNext(next));
            }
        }
        finally
        {
            _emitting = false;
            if (_disposed) _pending.Clear();
        }

        firstError?.Throw();
    }

    // ── Watching ────────────────────────────────────────────────────────────

    private void OnMessage(IMessage message)
    {
        var current = _current;
        if (_disposed || current is null) return;
        if (!PathContains(message.SenderObject)) return;

        if (CanSelect(current))
        {
            // A move inside the tree keeps the selection, but it can change
            // the ancestors, so watch the new path.
            Watch(current);
            return;
        }

        _current = null;
        Unwatch();
        Emit(null);
    }

    private bool PathContains(object sender)
    {
        foreach (var node in _path)
        {
            if (ReferenceEquals(node, sender)) return true;
        }
        return false;
    }

    /// <summary>
    /// Watches the path from <paramref name="node"/> to the root. Keeps the
    /// subscriptions of hubs that stay on the path, subscribes to new hubs,
    /// and releases the rest. A failed subscription leaves the previous watch
    /// in place.
    /// </summary>
    private void Watch(TVM node)
    {
        var path = new List<TVM>();
        for (TVM? cursor = node; cursor is not null; cursor = cursor.HierarchicalParent)
        {
            path.Add(cursor);
            if (ReferenceEquals(cursor, _root)) break;
        }

        var kept = new List<HubWatch>();
        var added = new List<HubWatch>();
        try
        {
            foreach (var pathNode in path)
            {
                var hub = pathNode.Hub;
                if (Find(kept, hub) is not null || Find(added, hub) is not null) continue;
                var existing = Find(_watches, hub);
                if (existing is not null)
                {
                    kept.Add(existing);
                    continue;
                }
                added.Add(new HubWatch(hub, hub.Messages.Subscribe(OnMessage, static _ => { })));
            }
        }
        catch
        {
            foreach (var watch in added)
                watch.Subscription.Dispose();
            throw;
        }

        var released = _watches.Where(watch => !kept.Contains(watch)).ToList();
        kept.AddRange(added);
        _watches = kept;
        _path = path;
        foreach (var watch in released)
            watch.Subscription.Dispose();
    }

    private void Unwatch()
    {
        var watches = _watches;
        _watches = [];
        _path = [];
        foreach (var watch in watches)
            watch.Subscription.Dispose();
    }

    private static HubWatch? Find(List<HubWatch> watches, IMessageHub hub)
    {
        foreach (var watch in watches)
        {
            if (ReferenceEquals(watch.Hub, hub)) return watch;
        }
        return null;
    }

    private sealed class HubWatch(IMessageHub hub, IDisposable subscription)
    {
        public IMessageHub Hub { get; } = hub;
        public IDisposable Subscription { get; } = subscription;
    }
}
