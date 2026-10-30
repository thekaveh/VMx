namespace VMx.Groups;

/// <summary>
/// Wait-for graph for container membership transactions (#718) and child
/// ownership gates (#1047). A caller waits for another thread's open
/// transaction or held ownership gate instead of failing, unless that owner
/// already waits for the caller, directly or through other threads: then the
/// wait that would close the cycle is refused, so opposing transfers fail
/// instead of deadlocking. Swift refuses opposing container transactions the
/// same way (#551).
/// </summary>
/// <remarks>
/// A resource is a container's membership gate or a child's ownership gate. A
/// waiter's edge points at the resource it waits for, not at the owner thread.
/// The owner is looked up when a cycle is checked, so an edge stops counting as
/// soon as the resource is released, even before the waiter wakes (#736).
/// Callers may hold container gates, ownership gates, the ownership
/// coordinator, or no lock at all when they call in. This class never takes
/// another lock, so its lock is always the last one taken.
/// </remarks>
internal sealed class MembershipTransactionWaitGraph
{
    internal static readonly MembershipTransactionWaitGraph Shared = new();

    private readonly object _gate = new();
    private readonly Dictionary<object, int> _owners = new(ReferenceComparer.Instance);
    private readonly Dictionary<int, object> _waitingOn = new();

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
            var visited = new HashSet<int>();
            object? cursor = resource;
            while (cursor is not null && _owners.TryGetValue(cursor, out var owner))
            {
                if (owner == caller) return false;
                if (!visited.Add(owner)) break;
                cursor = _waitingOn.TryGetValue(owner, out var next) ? next : null;
            }
            _waitingOn[caller] = resource;
            return true;
        }
    }

    /// <summary>Removes the wait that <paramref name="caller"/> recorded.</summary>
    internal void EndWait(int caller)
    {
        lock (_gate) _waitingOn.Remove(caller);
    }

    /// <summary>Test-only: whether <paramref name="thread"/> has a recorded wait.</summary>
    internal bool IsWaitingForTesting(int thread)
    {
        lock (_gate) return _waitingOn.ContainsKey(thread);
    }

    private sealed class ReferenceComparer : IEqualityComparer<object>
    {
        internal static readonly ReferenceComparer Instance = new();

        public new bool Equals(object? x, object? y) => ReferenceEquals(x, y);

        public int GetHashCode(object obj)
            => System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
    }
}
