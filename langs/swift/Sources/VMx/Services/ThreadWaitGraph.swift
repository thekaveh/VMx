//
// ThreadWaitGraph — the one process-wide wait-for graph for synchronous VMx
// waits that another thread resolves (spec/03 §4.1, ADR-0172): message-hub
// drain, batch and borrowed-scope ownership (spec/03, ADR-0119), container
// membership transactions (#551), lifecycle publication turns and hook
// leases, child ownership gates (#1154), and `FormVM` publication scopes
// (spec/20 §5.5, ADR-0176). Each subsystem records its wait
// before it blocks, so a cycle that crosses subsystems is visible (#703). The
// subsystem whose wait would close the cycle takes its own escape instead of
// waiting. No subsystem keeps a second graph.
//
// Each edge names the resource it waits on: a hub, a container, a lifecycle
// publication, a hook lease, an ownership gate or a form's publication scope.
// A waiting thread has at most one edge. There are two edge kinds:
//
// - An owner-named edge (`beginWait`) names the owner thread when the wait
//   starts. The thread that frees the resource calls `release(resource:)`
//   before it wakes the waiters, so no woken waiter keeps an edge to an owner
//   that no longer blocks it. Edges to the same owner thread on other
//   resources stay, because that thread may still hold them. A woken waiter
//   that must wait again records a new edge. A resource can pass to another
//   owner while its waiters stay blocked. The thread that passes it then calls
//   `redirectWait` for each waiter, so no edge names the old owner.
// - A resource-named edge (`beginResourceWait`) names no owner. The cycle
//   check finds the resource's current holder, recorded by `acquire`, at the
//   time of the check. The holder calls `releaseHolder(resource:)` before it
//   frees the resource, so a released resource ends every chain through it at
//   once. A gate waiter blocks in the lock itself and cannot record its wait
//   again, so `release(resource:)` is not used for these edges.
//
// Lock order: the graph lock is a leaf. A caller may hold a hub gate, a
// container gate, an ownership gate or a lifecycle lock when it calls in, but
// the graph never takes another lock or calls out while it holds its own.
//
import Foundation
import Darwin

final class ThreadWaitGraph: @unchecked Sendable {
    static let shared = ThreadWaitGraph()

    /// The key of the calling thread in every edge.
    static var currentThread: UInt64 {
        UInt64(pthread_mach_thread_np(pthread_self()))
    }

    private struct Edge {
        /// The owner thread of an owner-named edge; `nil` for a
        /// resource-named edge, whose owner is `holders[resource]`.
        let owner: UInt64?
        let resource: ObjectIdentifier
    }

    private let lock = NSLock()
    private var waitingOn: [UInt64: Edge] = [:]
    // The holder thread of each resource that resource-named edges wait on.
    private var holders: [ObjectIdentifier: UInt64] = [:]
    private var waitDecidedHook: ((UInt64, Bool) -> Void)?
    private var membershipWaitWokeHook: (() -> Void)?

    // Test-only seam: called with the caller and the decision after each
    // `beginWait` and `beginResourceWait`, outside the graph lock.
    var onWaitDecidedForTesting: ((UInt64, Bool) -> Void)? {
        get { lock.withLock { waitDecidedHook } }
        set { lock.withLock { waitDecidedHook = newValue } }
    }

    // Test-only seam: called on a woken membership waiter before it ends its
    // own edge, so a test can hold the interval between wake and `endWait`.
    var onMembershipWaitWokeForTesting: (() -> Void)? {
        get { lock.withLock { membershipWaitWokeHook } }
        set { lock.withLock { membershipWaitWokeHook = newValue } }
    }

    /// Records that `caller` waits for `owner` to free `resource`. Returns
    /// `false`, and records nothing, when the edge would close a cycle.
    func beginWait(caller: UInt64, owner: UInt64, resource: ObjectIdentifier) -> Bool {
        lock.lock()
        let accepted = !reaches(caller, from: owner)
        if accepted { waitingOn[caller] = Edge(owner: owner, resource: resource) }
        let hook = waitDecidedHook
        lock.unlock()
        hook?(caller, accepted)
        return accepted
    }

    /// Records that `caller` waits for the current holder of `resource`, a
    /// resource that `acquire(resource:thread:)` records. Returns `false`, and
    /// records nothing, when the holder's chain of waits reaches `caller`.
    /// With no recorded holder the wait is accepted: the holder is freeing the
    /// resource, so the wait ends without a cycle.
    func beginResourceWait(caller: UInt64, resource: ObjectIdentifier) -> Bool {
        lock.lock()
        let accepted = holders[resource].map { !reaches(caller, from: $0) } ?? true
        if accepted { waitingOn[caller] = Edge(owner: nil, resource: resource) }
        let hook = waitDecidedHook
        lock.unlock()
        hook?(caller, accepted)
        return accepted
    }

    /// Records `thread` as the holder of `resource`. The holder calls this
    /// once it holds the resource, before any other thread can wait for it
    /// with `beginResourceWait`.
    func acquire(resource: ObjectIdentifier, thread: UInt64) {
        lock.lock()
        holders[resource] = thread
        lock.unlock()
    }

    /// Removes the holder of `resource`. The holder calls this before it frees
    /// the resource, so no chain passes through a freed resource.
    func releaseHolder(resource: ObjectIdentifier) {
        lock.lock()
        holders.removeValue(forKey: resource)
        lock.unlock()
    }

    /// True when the chain of waits from `start` reaches `target`. A chain
    /// ends at a thread that does not wait, or at a resource-named edge whose
    /// resource has no holder. Called under `lock`.
    private func reaches(_ target: UInt64, from start: UInt64) -> Bool {
        var cursor = start
        var visited = Set<UInt64>()
        while cursor != target {
            guard visited.insert(cursor).inserted,
                  let next = waitingOn[cursor],
                  let owner = next.owner ?? holders[next.resource] else {
                return false
            }
            cursor = owner
        }
        return true
    }

    /// Points the edge of `caller` on `resource` at `newOwner`. Returns
    /// `false`, and removes the edge, when the new edge would close a cycle.
    /// Returns `true`, and records nothing, when `caller` has no edge on
    /// `resource`.
    func redirectWait(caller: UInt64, resource: ObjectIdentifier, to newOwner: UInt64) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard let edge = waitingOn[caller], edge.resource == resource, edge.owner != nil else {
            return true
        }
        waitingOn.removeValue(forKey: caller)
        guard !reaches(caller, from: newOwner) else { return false }
        waitingOn[caller] = Edge(owner: newOwner, resource: resource)
        return true
    }

    /// Removes the edge of `caller`, if any.
    func endWait(caller: UInt64) {
        lock.lock()
        waitingOn.removeValue(forKey: caller)
        lock.unlock()
    }

    /// Removes every edge that waits on `resource`. The freeing thread calls
    /// this before it wakes the waiters. Used for owner-named edges only.
    func release(resource: ObjectIdentifier) {
        lock.lock()
        waitingOn = waitingOn.filter { $0.value.resource != resource }
        lock.unlock()
    }

    /// Removes every edge that waits on `resource` and names `owner`. A
    /// resource that several threads hold at once, such as a form's
    /// publication scope, uses this: edges to the other holders stay, because
    /// those holders still block their waiters. Used for owner-named edges
    /// only.
    func release(resource: ObjectIdentifier, owner: UInt64) {
        lock.lock()
        waitingOn = waitingOn.filter { $0.value.resource != resource || $0.value.owner != owner }
        lock.unlock()
    }
}
