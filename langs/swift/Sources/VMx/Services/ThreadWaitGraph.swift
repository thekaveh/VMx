//
// ThreadWaitGraph — the one process-wide wait-for graph for synchronous VMx
// waits that another thread resolves: message-hub drain and batch ownership
// (spec/03, ADR-0119), container membership transactions (#551), and
// lifecycle publication turns and hook leases. Each subsystem registers
// `caller -> owner` before it blocks, so a cycle that crosses subsystems is
// visible (#703). The subsystem that would close the cycle takes its own
// escape instead of waiting.
//
// Each edge names the resource it waits on: a hub, a container, a lifecycle
// publication or a hook lease. The thread that frees a resource calls
// `release(resource:)` before it wakes the waiters, so no woken waiter keeps
// an edge to an owner that no longer blocks it. Edges to the same owner thread
// on other resources stay, because that thread may still hold them. A woken
// waiter that must wait again registers a new edge. A resource can pass to
// another owner while its waiters stay blocked. The thread that passes it then
// calls `redirectWait` for each waiter, so no edge names the old owner.
//
// Lock order: the graph lock is a leaf. A caller may hold a hub gate, a
// container gate or a lifecycle lock when it calls in, but the graph never
// takes another lock or calls out while it holds its own.
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
        let owner: UInt64
        let resource: ObjectIdentifier
    }

    private let lock = NSLock()
    private var waitingOn: [UInt64: Edge] = [:]
    private var waitDecidedHook: ((UInt64, Bool) -> Void)?
    private var membershipWaitWokeHook: (() -> Void)?

    // Test-only seam: called with the caller and the decision after each
    // `beginWait`, outside the graph lock.
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

    /// True when the chain of waits from `start` reaches `target`. Called
    /// under `lock`.
    private func reaches(_ target: UInt64, from start: UInt64) -> Bool {
        var cursor = start
        var visited = Set<UInt64>()
        while cursor != target {
            guard visited.insert(cursor).inserted, let next = waitingOn[cursor] else {
                return false
            }
            cursor = next.owner
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
        guard let edge = waitingOn[caller], edge.resource == resource else { return true }
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
    /// this before it wakes the waiters.
    func release(resource: ObjectIdentifier) {
        lock.lock()
        waitingOn = waitingOn.filter { $0.value.resource != resource }
        lock.unlock()
    }
}
