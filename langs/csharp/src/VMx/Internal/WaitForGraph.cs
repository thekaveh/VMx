namespace VMx.Internal;

/// <summary>
/// The process-wide wait-for graph (spec/03 §4.1, ADR-0172). It records every
/// blocking wait between VMx-owned resources: container membership
/// transactions (#718), child ownership gates (#1047), message-hub batch,
/// drain and borrowed-scope ownership (spec/03 §4 and §4.2, #1055, #1159),
/// lifecycle deliveries (spec/02 §2.4, ADR-0117), admitted hook leases
/// (ADR-0126, #1156) and form publication scopes (spec/20 §5.5, ADR-0176,
/// #1170). Each wait is recorded before it blocks, so a cycle that
/// crosses any mix of them is visible. The wait that would close a cycle is
/// refused, and the caller takes its own escape instead of waiting. No other
/// C# wait-for graph exists.
/// </summary>
/// <remarks>
/// <para>
/// An edge names the waiting thread and one resource instance, never a VM. A
/// thread has at most one edge.
/// </para>
/// <para>
/// A membership or ownership wait names its resource, a container's
/// membership gate or a child's ownership gate. Its owner is looked up when a
/// cycle is checked, so the edge stops counting as soon as the resource is
/// released, even before the waiter wakes (#736).
/// </para>
/// <para>
/// A hub wait names the hub and the owner thread it waits for: the batch
/// owner, then the drainer, then a borrower other than the caller. Before the
/// hub wakes its waiters, it calls <see cref="ReleaseWaiters"/> with its
/// current owners. Edges to a thread that no longer owns the hub go; edges to
/// a current owner, borrowers included, stay, because that owner still blocks
/// the waiter. Once the hub is disposing, every edge on it goes, because no
/// waiter waits for it again.
/// </para>
/// <para>
/// A lifecycle wait names one lifecycle delivery or one hook lease and the
/// thread that owns it: the VM's publication drainer or the hook's thread.
/// That owner calls <see cref="ReleaseWaiters"/> on the delivery or lease
/// before it sets its completion, so a finished owner's edges never outlive
/// it (#1183).
/// </para>
/// <para>
/// A form publication wait names the form's scope resource and one thread
/// that holds a scope on it. When that thread's outermost scope ends, the form
/// calls <see cref="ReleaseWaiters"/> with the threads that still hold a scope,
/// then wakes its waiters, which record their wait again if they must.
/// </para>
/// <para>
/// Callers may hold container gates, ownership gates, the ownership
/// coordinator, a hub gate, a lifecycle resource's lock, a form's state lock,
/// or no lock at all when they call in. This class never takes another lock,
/// so its lock is always the last one taken.
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
        bool accepted;
        lock (_gate)
        {
            accepted = !(_owners.TryGetValue(resource, out var owner) && Reaches(caller, owner));
            if (accepted) _waitingOn[caller] = new Edge(resource, 0);
        }
        WaitDecidedForTesting?.Invoke(caller, accepted);
        return accepted;
    }

    /// <summary>
    /// Records that <paramref name="caller"/> waits for <paramref name="owner"/>
    /// to free <paramref name="resource"/>: a hub, a lifecycle delivery or a
    /// hook lease. Returns <c>false</c>, and records nothing, when that wait
    /// would close a cycle.
    /// </summary>
    internal bool TryBeginWait(object resource, int owner, int caller)
    {
        bool accepted;
        lock (_gate)
        {
            accepted = !Reaches(caller, owner);
            if (accepted) _waitingOn[caller] = new Edge(resource, owner);
        }
        WaitDecidedForTesting?.Invoke(caller, accepted);
        return accepted;
    }

    /// <summary>Removes the wait that <paramref name="caller"/> recorded.</summary>
    internal void EndWait(int caller)
    {
        lock (_gate) _waitingOn.Remove(caller);
    }

    /// <summary>
    /// Removes the owner-named waits on <paramref name="resource"/> whose owner
    /// is not a current owner: neither <paramref name="owner"/> nor
    /// <paramref name="otherOwner"/> (0 for none) nor a key of
    /// <paramref name="moreOwners"/>. A hub calls this with its batch owner,
    /// drainer and borrowers before it wakes its waiters. A lifecycle delivery
    /// or hook lease calls it with no owner before it sets its completion, so
    /// every wait on it goes.
    /// </summary>
    internal void ReleaseWaiters(
        object resource,
        int owner = 0,
        int otherOwner = 0,
        IReadOnlyDictionary<int, int>? moreOwners = null)
    {
        lock (_gate)
        {
            List<int>? released = null;
            foreach (var entry in _waitingOn)
            {
                var edge = entry.Value;
                if (edge.Owner == 0 || !ReferenceEquals(edge.Resource, resource)) continue;
                if (edge.Owner == owner || edge.Owner == otherOwner) continue;
                if (moreOwners is not null && moreOwners.ContainsKey(edge.Owner)) continue;
                (released ??= []).Add(entry.Key);
            }
            if (released is null) return;
            foreach (var waiter in released) _waitingOn.Remove(waiter);
        }
    }

    /// <summary>
    /// Test-only seam: raised with the caller and the decision after each
    /// <see cref="TryBeginWait(object, int)"/> and
    /// <see cref="TryBeginWait(object, int, int)"/>, accepted or refused, outside
    /// the graph lock (#1472). The graph is process-wide, so a handler sees
    /// every thread's requests and filters by thread. Production code never
    /// subscribes.
    /// </summary>
    internal event Action<int, bool>? WaitDecidedForTesting;

    /// <summary>Test-only: whether <paramref name="thread"/> has a recorded wait.</summary>
    internal bool IsWaitingForTesting(int thread)
    {
        lock (_gate) return _waitingOn.ContainsKey(thread);
    }

    /// <summary>
    /// Test-only: the resource that <paramref name="thread"/> waits for, or
    /// <c>null</c> when it has no recorded wait.
    /// </summary>
    internal object? WaitResourceForTesting(int thread)
    {
        lock (_gate) return _waitingOn.TryGetValue(thread, out var edge) ? edge.Resource : null;
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
