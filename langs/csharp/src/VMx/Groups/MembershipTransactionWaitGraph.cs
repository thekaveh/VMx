namespace VMx.Groups;

/// <summary>
/// Wait-for graph for group membership transactions (#718). A group waits for
/// another thread's open transaction instead of failing, unless the owner of
/// that transaction already waits for the caller, directly or through other
/// threads: then the wait that would close the cycle is refused, so opposing
/// transfers fail instead of deadlocking (as in Swift, #551).
/// </summary>
/// <remarks>
/// A waiter's edge points at the container it waits for, not at the owner
/// thread. The owner is looked up when a cycle is checked, so an edge stops
/// counting as soon as the awaited transaction ends, even before the waiter
/// wakes (#736). Callers hold a container gate when they call in; this class
/// never takes a container gate, so the lock order is always gate, then graph.
/// </remarks>
internal sealed class MembershipTransactionWaitGraph
{
    internal static readonly MembershipTransactionWaitGraph Shared = new();

    private readonly object _gate = new();
    private readonly Dictionary<object, int> _owners = new(ReferenceComparer.Instance);
    private readonly Dictionary<int, object> _waitingOn = new();

    /// <summary>Records that <paramref name="thread"/> owns the transaction of <paramref name="container"/>.</summary>
    internal void Acquire(object container, int thread)
    {
        lock (_gate) _owners[container] = thread;
    }

    /// <summary>Records that the transaction of <paramref name="container"/> has ended.</summary>
    internal void Release(object container)
    {
        lock (_gate) _owners.Remove(container);
    }

    /// <summary>
    /// Records that <paramref name="caller"/> waits for the transaction of
    /// <paramref name="container"/>. Returns <c>false</c>, and records nothing,
    /// when that wait would close a cycle.
    /// </summary>
    internal bool TryBeginWait(object container, int caller)
    {
        lock (_gate)
        {
            var visited = new HashSet<int>();
            object? cursor = container;
            while (cursor is not null && _owners.TryGetValue(cursor, out var owner))
            {
                if (owner == caller) return false;
                if (!visited.Add(owner)) break;
                cursor = _waitingOn.TryGetValue(owner, out var next) ? next : null;
            }
            _waitingOn[caller] = container;
            return true;
        }
    }

    /// <summary>Removes the wait that <paramref name="caller"/> recorded.</summary>
    internal void EndWait(int caller)
    {
        lock (_gate) _waitingOn.Remove(caller);
    }

    private sealed class ReferenceComparer : IEqualityComparer<object>
    {
        internal static readonly ReferenceComparer Instance = new();

        public new bool Equals(object? x, object? y) => ReferenceEquals(x, y);

        public int GetHashCode(object obj)
            => System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
    }
}
