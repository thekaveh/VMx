namespace VMx.Internal;

/// <summary>
/// The process-wide wait-for graph for container membership transactions
/// (#718), child ownership gates (#1047) and message-hub drain and batch
/// ownership (spec/03, #1055). Each of these waits is recorded before it
/// blocks, so a cycle that crosses them is visible. The wait that would close
/// a cycle is refused, and the caller takes its own escape instead of waiting.
/// Lifecycle delivery waits still use the separate graph in
/// <c>ComponentVMBase</c>. Swift's graph covers those waits too (#703).
/// </summary>
/// <remarks>
/// <para>
/// A membership or ownership wait names its resource, a container's
/// membership gate or a child's ownership gate. Its owner is looked up when a
/// cycle is checked, so the edge stops counting as soon as the resource is
/// released, even before the waiter wakes (#736).
/// </para>
/// <para>
/// A hub wait names the hub and the owner thread it waits for. Before the hub
/// wakes its waiters, it calls <see cref="ReleaseWaiters"/> with its current
/// owners. Edges to a thread that no longer owns the hub go; edges to a current
/// owner stay, because that owner still blocks the waiter. Once the hub is
/// disposing, every edge on it goes, because no waiter waits for it again.
/// </para>
/// <para>
/// Callers may hold container gates, ownership gates, the ownership
/// coordinator, a hub gate, or no lock at all when they call in. This class
/// never takes another lock, so its lock is always the last one taken.
/// </para>
/// </remarks>
internal sealed class WaitForGraph
{
    internal static readonly WaitForGraph Shared = new();

    private readonly object _gate = new();
    private readonly Dictionary<object, int> _owners = new(ReferenceComparer.Instance);
    private readonly Dictionary<int, Edge> _waitingOn = new();

    // A waiter's edge: the resource it waits for and, for a hub wait, the owner
    // thread named when the wait began (0 when the owner is looked up).
    private readonly record struct Edge(object Resource, int Owner);

    /// <summary>Records that <paramref name="thread"/> holds <paramref name="resource"/>.</summary>
    internal void Acquire(object resource, int thread)
    {
        lock (_gate) _owners[resource] = thread;
    }

    /// <summary>Records that <paramref name="resource"/> has been released.</summary>
    internal void Release(object resource)
    {
        lock (_gate) _owners.Remove(resource);
    }

    /// <summary>
    /// Records that <paramref name="caller"/> waits for <paramref name="resource"/>.
    /// Returns <c>false</c>, and records nothing, when that wait would close a
    /// cycle.
    /// </summary>
    internal bool TryBeginWait(object resource, int caller)
    {
        lock (_gate)
        {
            if (_owners.TryGetValue(resource, out var owner) && Reaches(caller, owner)) return false;
            _waitingOn[caller] = new Edge(resource, 0);
            return true;
        }
    }

    /// <summary>
    /// Records that <paramref name="caller"/> waits for <paramref name="owner"/>
    /// to free <paramref name="resource"/>, a hub. Returns <c>false</c>, and
    /// records nothing, when that wait would close a cycle.
    /// </summary>
    internal bool TryBeginWait(object resource, int owner, int caller)
    {
        lock (_gate)
        {
            if (Reaches(caller, owner)) return false;
            _waitingOn[caller] = new Edge(resource, owner);
            return true;
        }
    }

    /// <summary>Removes the wait that <paramref name="caller"/> recorded.</summary>
    internal void EndWait(int caller)
    {
        lock (_gate) _waitingOn.Remove(caller);
    }

    /// <summary>
    /// Removes the hub waits on <paramref name="resource"/> whose owner is
    /// neither <paramref name="owner"/> nor <paramref name="otherOwner"/>, the
    /// hub's current owners (0 for none). The hub calls this before it wakes
    /// its waiters.
    /// </summary>
    internal void ReleaseWaiters(object resource, int owner = 0, int otherOwner = 0)
    {
        lock (_gate)
        {
            List<int>? released = null;
            foreach (var entry in _waitingOn)
            {
                var edge = entry.Value;
                if (edge.Owner == 0 || !ReferenceEquals(edge.Resource, resource)) continue;
                if (edge.Owner == owner || edge.Owner == otherOwner) continue;
                (released ??= []).Add(entry.Key);
            }
            if (released is null) return;
            foreach (var waiter in released) _waitingOn.Remove(waiter);
        }
    }

    /// <summary>Test-only: whether <paramref name="thread"/> has a recorded wait.</summary>
    internal bool IsWaitingForTesting(int thread)
    {
        lock (_gate) return _waitingOn.ContainsKey(thread);
    }

    // True when the chain of waits from start reaches target. Call under _gate.
    private bool Reaches(int target, int start)
    {
        var visited = new HashSet<int>();
        var cursor = start;
        while (cursor != target)
        {
            if (!visited.Add(cursor) || !_waitingOn.TryGetValue(cursor, out var edge)) return false;
            if (edge.Owner != 0) cursor = edge.Owner;
            else if (!_owners.TryGetValue(edge.Resource, out cursor)) return false;
        }
        return true;
    }

    private sealed class ReferenceComparer : IEqualityComparer<object>
    {
        internal static readonly ReferenceComparer Instance = new();

        public new bool Equals(object? x, object? y) => ReferenceEquals(x, y);

        public int GetHashCode(object obj)
            => System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
    }
}
