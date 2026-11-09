//
// ComponentVMBase — open base class for every VMx viewmodel.
//
// Manages:
// - The five-state lifecycle (`construct`, `destruct`, `reconstruct`,
//   `dispose`) with transition validation matching the
//   `lifecycle-transitions.json` fixture.
// - Hub publishing (`ConstructionStatusChangedMessage`,
//   `PropertyChangedMessage`).
// - The five built-in commands (`select`, `deselect`, `selectNext`,
//   `selectPrevious`, `reconstruct`).
// - Parent/child selection delegation hooks.
//
// See spec/05-component-vm.md and spec/02-lifecycle.md.
//
import Foundation
import Combine

/// Minimal parent interface used by a child for selection delegation.
/// Mirrors `IParentVM` in the other flavors.
public protocol ParentVM: AnyObject {
    var supportsChildSelection: Bool { get }
    var currentChild: ComponentVMBase? { get }
    func selectChild(_ vm: ComponentVMBase)
    func deselectChild(_ vm: ComponentVMBase)
}

/// A parent that reacts when a child publishes Disposed from its own
/// `dispose()`. `CompositeVM` clears `current` for it (spec/06 §4.3 rule 9,
/// ADR-0189).
protocol ChildDisposalObserver: AnyObject {
    func childDisposed(_ vm: ComponentVMBase)
}

/// Typed failure for exclusive container ownership operations.
public enum ContainerOwnershipError: Error {
    case duplicate
    case cycle
    case inconsistentParent
    case attachmentFailed(Error)
}

/// The inner error of `ContainerOwnershipError.attachmentFailed` when a
/// failed add, insert, index replacement or population also fails its
/// lifecycle compensation (spec/06 §4.2, ADR-0218). It keeps both failures.
public struct ContainerRollbackError: Error, CustomStringConvertible {
    /// The failure that started the rollback.
    public let originalError: Error
    /// The first failure of the lifecycle compensation.
    public let compensationError: Error

    public var description: String {
        "container change failed: \(originalError); "
            + "lifecycle compensation also failed: \(compensationError)"
    }
}

/// Internal ownership surface kept separate from public selection delegation.
protocol OwnershipParentVM: AnyObject {
    var ownershipOwner: ComponentVMBase { get }
    var ownershipOwnerParent: OwnershipParentVM? { get }
    func containsIdentity(_ vm: ComponentVMBase) -> Bool
    func detachForTransfer(_ vm: ComponentVMBase) throws -> ParentTransfer
}

/// Transaction-aware ownership surface used by containers that can stage
/// several children from the same old parent as one atomic population.
protocol TransactionalOwnershipParentVM: OwnershipParentVM {
    func detachForTransfer(
        _ vm: ComponentVMBase,
        transaction: ContainerOwnershipTransaction
    ) throws -> ParentTransfer
}

final class ContainerOwnershipTransaction {}

/// One-shot staged removal from an old parent.
final class ParentTransfer {
    private let commitAction: () -> Void
    private let rollbackAction: () -> Void
    private var finished = false

    init(commit: @escaping () -> Void, rollback: @escaping () -> Void) {
        commitAction = commit
        rollbackAction = rollback
    }

    func commit() {
        precondition(!finished, "parent transfer is already finished")
        finished = true
        commitAction()
    }

    func rollback() {
        precondition(!finished, "parent transfer is already finished")
        finished = true
        rollbackAction()
    }
}

private let ownershipTransactionCoordinator = NSRecursiveLock()

/// Takes `identity`'s ownership gate without blocking. The first hold of the
/// calling thread records it as the gate's holder in `ThreadWaitGraph`, so a
/// thread that waits for the gate can see the cycle (spec/03 §4.1, #1154).
private func tryHoldOwnershipGate(_ identity: ComponentVMBase) -> Bool {
    guard identity.ownershipGate.try() else { return false }
    identity.ownershipGateHolds += 1
    if identity.ownershipGateHolds == 1 {
        ThreadWaitGraph.shared.acquire(
            resource: ObjectIdentifier(identity.ownershipGate),
            thread: ThreadWaitGraph.currentThread
        )
    }
    return true
}

/// Releases one hold of `identity`'s ownership gate. The last hold removes the
/// holder from `ThreadWaitGraph` before the gate unlocks (release before wake).
private func releaseOwnershipGate(_ identity: ComponentVMBase) {
    identity.ownershipGateHolds -= 1
    if identity.ownershipGateHolds == 0 {
        ThreadWaitGraph.shared.releaseHolder(resource: ObjectIdentifier(identity.ownershipGate))
    }
    identity.ownershipGate.unlock()
}

private func acquireOwnershipIdentities(_ children: [ComponentVMBase]) throws -> [ComponentVMBase] {
    var seen = Set<ObjectIdentifier>()
    let identities = children.compactMap { child -> ComponentVMBase? in
        let identity = child._ownershipIdentity
        return seen.insert(ObjectIdentifier(identity)).inserted ? identity : nil
    }
    while true {
        var acquired: [ComponentVMBase] = []
        var blocked: ComponentVMBase?
        ownershipTransactionCoordinator.lock()
        for identity in identities {
            if tryHoldOwnershipGate(identity) {
                acquired.append(identity)
            } else {
                blocked = identity
                break
            }
        }
        guard let blocked else {
            ownershipTransactionCoordinator.unlock()
            return identities
        }
        for identity in acquired.reversed() { releaseOwnershipGate(identity) }
        ownershipTransactionCoordinator.unlock()

        // Never retain the coordinator or another child while waiting. A wait
        // that would close a wait-for cycle fails before any mutation: the
        // gate's holder already waits, directly or through other threads, for
        // this one (spec/03 §4.1). Once this blocker moves, retry the complete
        // identity set atomically.
        let caller = ThreadWaitGraph.currentThread
        guard ThreadWaitGraph.shared.beginResourceWait(
            caller: caller,
            resource: ObjectIdentifier(blocked.ownershipGate)
        ) else {
            throw ContainerOwnershipTransactionError()
        }
        blocked.ownershipGate.lock()
        // End the edge while this thread holds the gate, so no later holder
        // inherits it.
        ThreadWaitGraph.shared.endWait(caller: caller)
        blocked.ownershipGate.unlock()
    }
}

func withOwnershipReservationBatch<T>(
    _ children: [ComponentVMBase],
    _ body: () throws -> T
) throws -> T {
    let identities = try acquireOwnershipIdentities(children)
    defer {
        for identity in identities.reversed() { releaseOwnershipGate(identity) }
    }
    return try body()
}

func withExclusiveOwnershipReservationBatch<T>(
    _ children: [ComponentVMBase],
    _ body: () throws -> T
) throws -> T {
    let identities = try acquireOwnershipIdentities(children)
    guard !identities.contains(where: { $0.ownershipInProgress }) else {
        for identity in identities.reversed() { releaseOwnershipGate(identity) }
        throw ContainerOwnershipTransactionError()
    }
    for identity in identities { identity.ownershipInProgress = true }
    defer {
        for identity in identities { identity.ownershipInProgress = false }
        for identity in identities.reversed() { releaseOwnershipGate(identity) }
    }
    return try body()
}

/// True while an ownership transaction holds `child`'s identity. Never
/// waits: a gate that another thread holds counts as in progress.
func isOwnershipTransactionInProgress(_ child: ComponentVMBase) -> Bool {
    let identity = child._ownershipIdentity
    guard tryHoldOwnershipGate(identity) else { return true }
    defer { releaseOwnershipGate(identity) }
    return identity.ownershipInProgress
}

func beginParentTransfer(
    _ child: ComponentVMBase,
    to destination: OwnershipParentVM,
    transaction: ContainerOwnershipTransaction
) throws -> ParentTransfer {
    let identity = child._ownershipIdentity
    _ = try acquireOwnershipIdentities([identity])
    guard !identity.ownershipInProgress else {
        releaseOwnershipGate(identity)
        throw ContainerOwnershipTransactionError()
    }
    identity.ownershipInProgress = true

    let staged: ParentTransfer?
    do {
        guard !destination.containsIdentity(child) else {
            throw ContainerOwnershipError.duplicate
        }

        var cursor: OwnershipParentVM? = destination
        while let current = cursor {
            guard current.ownershipOwner._ownershipIdentity !== identity else {
                throw ContainerOwnershipError.cycle
            }
            cursor = current.ownershipOwnerParent
        }

        if let parent = child._transferOwnershipParent as? TransactionalOwnershipParentVM {
            staged = try parent.detachForTransfer(child, transaction: transaction)
        } else {
            staged = try child._transferOwnershipParent?.detachForTransfer(child)
        }
    } catch {
        identity.ownershipInProgress = false
        releaseOwnershipGate(identity)
        throw error
    }

    func finish(commit: Bool) {
        defer {
            identity.ownershipInProgress = false
            releaseOwnershipGate(identity)
        }
        if commit { staged?.commit() } else { staged?.rollback() }
    }
    return ParentTransfer(commit: { finish(commit: true) }, rollback: { finish(commit: false) })
}

private struct ContainerOwnershipTransactionError: Error {}

/// Records, under `container`'s gate, that a disposal waits for `owner`'s open
/// membership transaction (ADR-0122, ADR-0153). Returns `false`, and records
/// nothing, when `owner` already waits for the caller, directly or through
/// others, including through a hub drain (#551, #703). A membership change
/// never waits: it fails at once (ADR-0187).
func beginMembershipWait(owner: UInt64, container: AnyObject) -> Bool {
    ThreadWaitGraph.shared.beginWait(
        caller: ThreadWaitGraph.currentThread,
        owner: owner,
        resource: ObjectIdentifier(container)
    )
}

/// Waits for a transaction recorded by `beginMembershipWait` to end.
func awaitMembershipTransaction(_ completion: DispatchGroup) {
    completion.wait()
    ThreadWaitGraph.shared.onMembershipWaitWokeForTesting?()
    ThreadWaitGraph.shared.endWait(caller: ThreadWaitGraph.currentThread)
}

/// Ends every membership wait on `container`. The transaction owner calls it
/// under the container's gate, before it wakes the waiters.
func releaseMembershipWaiters(of container: AnyObject) {
    ThreadWaitGraph.shared.release(resource: ObjectIdentifier(container))
}

/// A `Subject` whose `send(_:)` snapshots subscribers under a brief lock and
/// invokes them OUTSIDE the lock, so a slow consumer parked in one
/// subscriber's closure cannot block a concurrent `send(_:)` on the same
/// subject from another thread.
///
/// Combine's `PassthroughSubject` serializes `send(_:)` invocations — a parked
/// subscriber blocks every subsequent `send(_:)` on the same subject until the
/// in-progress call returns. That breaks the cross-language contract
/// (spec/06 §3.2 / COMP-006): a slow consumer on one child must not block the
/// publication of another child's `isCurrent` change. C#/Python/TypeScript use
/// delegate invocations or reactivex/rxjs Subjects that invoke subscribers
/// without holding a per-subject send lock; this custom Subject mirrors that
/// concurrency contract in Swift. Drop-in replacement for `PassthroughSubject`
/// on the per-VM `propertyChangedSubject` and on every `FormVM` channel
/// (ADR-0174). One `send(_:)` delivers to subscribers in subscription order;
/// two concurrent `send(_:)` calls are not ordered. Like `PassthroughSubject`,
/// it honors each subscriber's demand: a value that arrives while a
/// subscriber has no outstanding demand is dropped for that subscriber.
final class VMxConcurrentSubject<Output, Failure: Error>: Subject {
    private final class TokenSubscription: Subscription {
        private weak var parent: VMxConcurrentSubject<Output, Failure>?
        private let token: UUID
        private var cancelled = false
        init(parent: VMxConcurrentSubject<Output, Failure>, token: UUID) {
            self.parent = parent
            self.token = token
        }
        func request(_ demand: Subscribers.Demand) {
            parent?.addDemand(demand, token: token)
        }
        func cancel() {
            guard !cancelled else { return }
            cancelled = true
            parent?.removeSubscriber(token: token)
        }
    }

    private final class Entry {
        let receiveValue: (Output) -> Subscribers.Demand
        let receiveCompletion: (Subscribers.Completion<Failure>) -> Void
        // Both are guarded by the subject's `lock`.
        var cancelled: Bool = false
        var demand: Subscribers.Demand = .none
        init(
            receiveValue: @escaping (Output) -> Subscribers.Demand,
            receiveCompletion: @escaping (Subscribers.Completion<Failure>) -> Void
        ) {
            self.receiveValue = receiveValue
            self.receiveCompletion = receiveCompletion
        }
    }

    private let lock = NSLock()
    // Kept in subscription order, so one sender delivers in that order.
    private var entries: [(token: UUID, entry: Entry)] = []
    private var finished = false

    public func send(_ value: Output) {
        lock.lock()
        let snapshot = entries.map(\.entry)
        let isFinished = finished
        lock.unlock()
        if isFinished { return }
        for entry in snapshot where claimDemand(entry) {
            // No lock is held while the subscriber runs.
            let more = entry.receiveValue(value)
            if more > .none {
                lock.lock()
                if !entry.cancelled { entry.demand += more }
                lock.unlock()
            }
        }
    }

    /// Takes one unit of demand from a live entry under `lock`. Returns
    /// `false`, so the value is dropped for that entry, when it was cancelled
    /// or has no outstanding demand, as `PassthroughSubject` does.
    private func claimDemand(_ entry: Entry) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard !entry.cancelled, entry.demand > .none else { return false }
        if entry.demand != .unlimited { entry.demand -= 1 }
        return true
    }

    /// Reads `cancelled` under `lock`; `removeSubscriber` sets it there.
    private func isLive(_ entry: Entry) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        return !entry.cancelled
    }

    /// Adds demand that a subscriber requested through its subscription.
    fileprivate func addDemand(_ demand: Subscribers.Demand, token: UUID) {
        guard demand > .none else { return }
        lock.lock()
        if let entry = entries.first(where: { $0.token == token })?.entry {
            entry.demand += demand
        }
        lock.unlock()
    }

    public func send(completion: Subscribers.Completion<Failure>) {
        lock.lock()
        if finished {
            lock.unlock()
            return
        }
        if case .finished = completion { finished = true }
        let snapshot = entries.map(\.entry)
        if case .finished = completion { entries.removeAll() }
        lock.unlock()
        for entry in snapshot where isLive(entry) {
            entry.receiveCompletion(completion)
        }
    }

    public func send(subscription: any Subscription) {
        // VMx publishes via send(_:), not via subscription handshake; this
        // exists only to satisfy the Subject protocol.
    }

    public func receive<S>(subscriber: S) where S: Subscriber, S.Failure == Failure, S.Input == Output {
        let token = UUID()
        // Capture subscriber strongly in the closures. `entries` holds the
        // Entry which holds the closures; removeSubscriber releases both.
        let entry = Entry(
            receiveValue: { value in subscriber.receive(value) },
            receiveCompletion: { completion in subscriber.receive(completion: completion) }
        )
        lock.lock()
        let alreadyFinished = finished
        if !alreadyFinished {
            entries.append((token: token, entry: entry))
        }
        lock.unlock()
        subscriber.receive(subscription: TokenSubscription(parent: self, token: token))
        if alreadyFinished {
            subscriber.receive(completion: .finished)
        }
    }

    fileprivate func removeSubscriber(token: UUID) {
        lock.lock()
        let index = entries.firstIndex { $0.token == token }
        let removed = index.map { entries.remove(at: $0).entry }
        removed?.cancelled = true
        lock.unlock()
        // The entry owns the subscriber; release it after `lock` (non-recursive)
        // so a subscriber deinit can subscribe to or send on this subject.
        withExtendedLifetime(removed) {}
    }
}

/// View-model kind tag. Mirrors `ViewModelType`.
public enum ViewModelType: String, Sendable {
    case component = "Component"
    case readOnlyComponent = "ReadOnlyComponent"
    case composite = "Composite"
    case group = "Group"
    case aggregate = "Aggregate"
}

/// One-shot completion of a lifecycle hook deferred by `_transitionChildren`.
final class LifecycleDeferral {
    private let lock = NSLock()
    private var result: Bool?
    private var callback: ((Bool) -> Void)?

    func settle(_ succeeded: Bool) {
        lock.lock()
        guard result == nil else {
            lock.unlock()
            return
        }
        result = succeeded
        let callback = self.callback
        self.callback = nil
        lock.unlock()
        callback?(succeeded)
    }

    func onSettle(_ callback: @escaping (Bool) -> Void) {
        lock.lock()
        if let result {
            lock.unlock()
            callback(result)
            return
        }
        self.callback = callback
        lock.unlock()
    }
}

/// A child walk failed or was misused (spec/02 §6.1).
///
/// ``ComponentVMBase/_transitionChildren(_:construct:after:)`` throws it when
/// a child does not reach the status the parent's transition requires, when
/// the helper is called outside the parent's own construct or destruct hook,
/// and when a hook defers its completion twice. `childName` names the child
/// that failed, or the parent for a usage error.
public struct ChildTransitionError: Error, CustomStringConvertible {
    /// The name of the child that failed, or of the parent for a usage error.
    public let childName: String
    /// Why the walk failed.
    public let reason: String
    public var description: String { "Child '\(childName)' \(reason)" }
}

/// Supplies a child walk with children added while it runs (see
/// `_transitionContainerChildren`). A struct, not a bare closure, so trailing-closure
/// matching of `after` stays unambiguous.
struct LateChildSource {
    /// The start records of the adds that attached late children
    /// (spec/06 §5.1).
    let starts: LateChildStarts
    /// This walk's records; the walk ends only this scope.
    let scope: LateChildStarts.Scope
    /// The next late child and the start record of the add that starts it,
    /// or `nil` when none is left. A late child that no add starts is
    /// skipped here, never returned. The walk's scope stays open.
    let next: () -> (child: ComponentVMBase, record: LateChildStarts.Record)?
    /// The commit-time pull (spec/06 §5.1): under the container's membership
    /// gate, the next late child with a start record. Once none is left, the
    /// same gate section is the commit step: it writes `.constructed`
    /// (unpublished) and ends the scope, so a later add reads `.constructed`
    /// and follows the add-after-Constructed rule. A walk that was abandoned
    /// or stopped commits nothing (ADR-0186).
    let seal: () -> LateChildSeal
    /// Test-only: runs as the commit-time seal starts each pull, after its
    /// cancellation check and before it takes the membership gate.
    var willSeal: (() -> Void)? = nil
}

/// Tells a construct walk whether a child is still a member of its container
/// (spec/06 §5.1, ADR-0186). A struct, not a bare closure, so trailing-closure
/// matching of `after` stays unambiguous.
struct ChildMembership {
    /// Whether `child` is a member of the container now.
    let contains: (ComponentVMBase) -> Bool
}

/// One commit-time pull of a `LateChildSource`.
enum LateChildSeal {
    /// A late child to join before the commit step.
    case late(ComponentVMBase, LateChildStarts.Record)
    /// The commit step wrote `.constructed`.
    case sealed
    /// The walk was abandoned or stopped: the commit step wrote nothing.
    case abandoned
}

/// The outcome of a construct walk's commit-time seal.
enum ChildWalkSeal {
    /// No late child is left; the container's state is flipped to `.constructed`.
    case sealed
    /// A late child is joined first; the walk settles `deferral` afterwards.
    case pending(LifecycleDeferral)
    /// A late child did not reach `.constructed`, or the walk failed.
    case failed
    /// An abandon or a disposal cancelled the walk. The seal commits
    /// nothing and publishes no rollback; the abandoner settles the
    /// transition (ADR-0186). A cancelled join never settles.
    case abandoned
}

/// Walks a parent's children through one transition, waiting on each child
/// left in its transient status (spec/02 §6). A walk that waited continues
/// through `resume`, on the parent's foreground dispatcher (ADR-0218 rule 3).
/// Cancellation never settles the deferral, so a disposed parent publishes
/// nothing further.
final class ChildTransitionWalker {
    private let lock = NSLock()
    private var children: [ComponentVMBase]
    private var after: (() throws -> Void)?
    private var index = 0
    private var cancelled = false
    private var waiting: (child: ComponentVMBase, id: UInt64)?
    /// A late child whose add has not finished its start attempt yet.
    private var waitingStart: ComponentVMBase?
    /// Children that already started this transition (factory population or
    /// a late auto-constructed child): joined, never restarted. Only the
    /// sequential walk itself reads or extends it.
    private var joined: Set<ObjectIdentifier>
    /// The start records of the late children among `joined`. Only the
    /// sequential walk reads or extends it.
    private var lateRecords: [ObjectIdentifier: LateChildStarts.Record] = [:]
    /// Supplies children added while the walk runs; each is joined, never
    /// started by the walk.
    private let lateChild: LateChildSource?
    /// True once the walk's owner is disposed: the walk starts no further child.
    private let superseded: () -> Bool
    /// Whether a child is still a member of the walk's container (spec/06
    /// §5.1, ADR-0186). The walk skips a child that is not, and ignores how
    /// such a child settles. `nil` counts every child.
    private let membership: ChildMembership?
    private let target: ConstructionStatus
    private let transient: ConstructionStatus
    /// Test-only: runs after the walk read a child's status and before it
    /// starts the child.
    private let beforeStart: (ComponentVMBase) -> Void
    /// Runs a resumed walk on the walking VM's foreground dispatcher
    /// (spec/02 §6, ADR-0218 rule 3).
    private let resume: (@escaping () -> Void) -> Void
    private var currentDeferral = LifecycleDeferral()
    /// Settled when the walk finishes; a seal that joins another late child
    /// replaces it with a fresh one (`seal()`).
    var deferral: LifecycleDeferral { lock.withLock { currentDeferral } }

    init(
        children: [ComponentVMBase],
        construct: Bool,
        after: (() throws -> Void)?,
        joined: [ComponentVMBase] = [],
        lateChild: LateChildSource? = nil,
        superseded: @escaping () -> Bool = { false },
        membership: ChildMembership? = nil,
        beforeStart: @escaping (ComponentVMBase) -> Void = { _ in },
        resume: @escaping (@escaping () -> Void) -> Void = { $0() }
    ) {
        self.beforeStart = beforeStart
        self.resume = resume
        self.children = children
        self.after = after
        self.joined = Set(joined.map(ObjectIdentifier.init))
        self.lateChild = lateChild
        self.superseded = superseded
        self.membership = membership
        self.target = construct ? .constructed : .destructed
        self.transient = construct ? .constructing : .destructing
    }

    /// Returns `true` while a child is pending; the walk then resumes when
    /// that child settles and finally settles `deferral`.
    func start() throws -> Bool {
        do {
            return try advance()
        } catch {
            endLate()
            throw error
        }
    }

    func cancel() {
        lock.lock()
        cancelled = true
        let waiting = self.waiting
        self.waiting = nil
        waitingStart = nil
        children = []
        after = nil
        lock.unlock()
        endLate()
        if let waiting { waiting.child._cancelSettleWait(waiting.id) }
    }

    /// The walk pulls no further late children: drop its own start records.
    private func endLate() {
        guard let lateChild else { return }
        lateChild.starts.endWalk(lateChild.scope)
    }

    /// Settles a deferred walk; a failed one pulls no further late children.
    private func settle(_ succeeded: Bool) {
        if !succeeded { endLate() }
        deferral.settle(succeeded)
    }

    /// The commit-time step of a construct walk with a late source: pulls
    /// each late child an add attached since the last pull and joins it (the
    /// selector, `after`, never runs again), until the container seals.
    /// Called by the owner with no lock held.
    func seal() -> ChildWalkSeal {
        guard let lateChild else { return .sealed }
        while true {
            // A disposed owner joins no further late child (LIFE-015).
            // Defensive check (#1410): only `_disposeAtHookBoundary` requests
            // disposal, and it cancels this walk at once: before the request
            // when it runs the cascade inline, and right after the request
            // otherwise. So `stopped` decides only inside that short window
            // on another thread, and no test can hold it open. Without the check
            // the outcome is the same: `_flipConstructedForSeal()` does not
            // flip a container whose disposal is requested, `advance()` stops
            // on `superseded()`, and `_commitStatus` drops the commit of the
            // superseded generation.
            let stopped = superseded()
            lock.lock()
            if cancelled || stopped {
                lock.unlock()
                return .abandoned
            }
            lock.unlock()
            lateChild.willSeal?()
            let late: ComponentVMBase
            let record: LateChildStarts.Record
            switch lateChild.seal() {
            case .sealed: return .sealed
            case .abandoned: return .abandoned
            case .late(let child, let start):
                late = child
                record = start
            }
            let fresh = LifecycleDeferral()
            lock.lock()
            if cancelled {
                lock.unlock()
                return .abandoned
            }
            joined.insert(ObjectIdentifier(late))
            lateRecords[ObjectIdentifier(late)] = record
            // The finished walk dropped its children; join this one next.
            children = [late]
            index = 0
            currentDeferral = fresh
            lock.unlock()
            do {
                // A walk stopped by disposal never settles `fresh`.
                // Defensive check (#1410): `superseded()` is true here only
                // when a disposal landed during this pull, and that disposal
                // also cancels this walk, so `fresh` never settles. Then
                // `.pending(fresh)` publishes nothing, and `.abandoned`
                // reaches `_commitStatus`, which drops the commit of the
                // superseded generation. The outcome is the same either way,
                // so no test can observe this check.
                if try advance() { return superseded() ? .abandoned : .pending(fresh) }
            } catch {
                endLate()
                return .failed
            }
        }
    }

    private func advance() throws -> Bool {
        while true {
            // A disposed owner starts no further child and no `after` (LIFE-015).
            let stopped = superseded()
            lock.lock()
            guard !cancelled, !stopped else {
                lock.unlock()
                return true
            }
            if index >= children.count, let lateChild {
                // Pull a late child outside `lock`: the source takes the
                // container's membership gate.
                lock.unlock()
                guard let (late, record) = lateChild.next() else {
                    lock.lock()
                    if cancelled {
                        lock.unlock()
                        return true
                    }
                    let after = self.after
                    self.after = nil
                    children = []
                    lock.unlock()
                    try after?()
                    return false
                }
                lock.lock()
                if !cancelled {
                    joined.insert(ObjectIdentifier(late))
                    lateRecords[ObjectIdentifier(late)] = record
                    children.append(late)
                }
                lock.unlock()
                continue
            }
            guard index < children.count else {
                let after = self.after
                self.after = nil
                children = []
                lock.unlock()
                try after?()
                return false
            }
            let child = children[index]
            lock.unlock()

            // A child that left the container is skipped: it neither starts
            // nor joins, and it does not change the container (ADR-0186).
            if !counts(child) {
                lock.lock()
                index += 1
                lock.unlock()
                continue
            }

            // A late child is never started here: wait until its add's start
            // attempt is done, then join the child (spec/06 §5.1).
            if let record = lateRecords[ObjectIdentifier(child)], !record.isDone {
                lateChild?.starts.probe(child, .walkWaitingOnAdd)
                lock.lock()
                if cancelled {
                    lock.unlock()
                    return true
                }
                // Register under `lock` so an add finishing on another thread
                // observes `waitingStart` before it resumes the walk.
                if record.whenDone({ [self] in self.startAttempted(child) }) {
                    waitingStart = child
                    lock.unlock()
                    return true
                }
                lock.unlock()
            }

            let status = child.status
            // A Disposed child does not count: skip it, and call no lifecycle
            // operation on it (spec/02 §6, ADR-0189).
            if Self.isDisposed(child) {
                lock.lock()
                index += 1
                lock.unlock()
                continue
            }
            if status != target && status != transient
                && !joined.contains(ObjectIdentifier(child)) {
                beforeStart(child)
                do {
                    if target == .constructed { try child.construct() } else { try child.destruct() }
                } catch let error as StatusTransitionError {
                    // Another thread started the same transition after the
                    // status read: join it instead (ADR-0218 rule 6).
                    guard child._isInTransition(transient) || child.status == target else {
                        throw error
                    }
                }
            }
            // A child container whose state is already flipped but whose
            // commit is still in flight is waited for like a transient one.
            if child._isInTransition(transient) {
                lock.lock()
                if cancelled {
                    lock.unlock()
                    return true
                }
                // Register under `lock` so a settle racing in from another
                // thread observes `waiting` before it resumes the walk.
                if let id = child._awaitSettle(from: transient, { [self] in
                    self.childSettled(child)
                }) {
                    waiting = (child, id)
                    lock.unlock()
                    return true
                }
                lock.unlock()
            }
            guard child.status == target || Self.isDisposed(child) || !counts(child) else {
                throw ChildTransitionError(
                    childName: child.name,
                    reason: "did not reach \(target)"
                )
            }
            lock.lock()
            index += 1
            lock.unlock()
        }
    }

    /// Whether `child` still counts for this walk: it is a member of the
    /// container, or the walk has no membership predicate.
    private func counts(_ child: ComponentVMBase) -> Bool {
        membership?.contains(child) ?? true
    }

    /// Whether the walk treats `child` as Disposed: its status is Disposed, or
    /// its disposal is committed (a forwarding decorator answers for the VM
    /// it wraps). Swift commits a disposal under `lifecycleLock` but can apply
    /// the queued `.disposed` status later, while another thread drains the
    /// child's lifecycle publications. During the inline dispose cascade
    /// neither holds, so the walk does not skip the child, and a walk call on
    /// it fails under LIFE-021, as in the other flavors.
    private static func isDisposed(_ child: ComponentVMBase) -> Bool {
        child.status == .disposed || child._ownershipIdentity._isDisposalRequested()
    }

    /// A late child's add finished its start attempt: resume the walk on the
    /// owner's foreground, where it joins that child (ADR-0218 rule 3).
    private func startAttempted(_ child: ComponentVMBase) {
        lock.lock()
        guard !cancelled, let waitingStart, waitingStart === child else {
            lock.unlock()
            return
        }
        self.waitingStart = nil
        lock.unlock()
        resume { [self] in
            guard !self.isCancelled else { return }
            self.continueWalk()
        }
    }

    private func childSettled(_ child: ComponentVMBase) {
        lock.lock()
        guard !cancelled, let waiting, waiting.child === child else {
            lock.unlock()
            return
        }
        self.waiting = nil
        lock.unlock()
        // The child rolled back: roll the parent back, unless it left the
        // container meanwhile (ADR-0186). A child that reached Disposed during
        // the wait ends the wait as a success (ADR-0189).
        let reached = child.status == target || Self.isDisposed(child) || !counts(child)
        // The rest of the walk, its rollback included, runs on the owner's
        // foreground (ADR-0218 rule 3).
        resume { [self] in
            guard !self.isCancelled else { return }
            guard reached else {
                self.settle(false)
                return
            }
            self.lock.lock()
            self.index += 1
            self.lock.unlock()
            self.continueWalk()
        }
    }

    private var isCancelled: Bool { lock.withLock { cancelled } }

    /// Continues a walk that waited, and settles it when it ends.
    private func continueWalk() {
        do {
            if try advance() { return }
            settle(true)
        } catch {
            // A deferred failure has no caller to rethrow to: roll back.
            settle(false)
        }
    }
}

open class ComponentVMBase {
    // ── Identity ────────────────────────────────────────────────────────

    public let name: String
    public let hint: String

    /// Subclasses override to declare their kind. Defaults to `.component`.
    open var type: ViewModelType { .component }

    // ── Services ────────────────────────────────────────────────────────

    /// Injected hub. `public` (read-only) so subclasses — including consumer
    /// subclasses in another module — can publish messages on it. Swift has no
    /// `protected`; `internal` would not cross the module boundary, so the
    /// cross-module-subclassing surface (hub / dispatcher / raise) is `public`.
    public let hub: MessageHubProtocol
    /// Injected dispatcher (read-only `public` for the same cross-module reason).
    public let dispatcher: Dispatcher

    private let onConstructCb: (() throws -> Void)?
    private let onDestructCb: (() throws -> Void)?
    private let background: Bool

    // ── State ───────────────────────────────────────────────────────────

    private var _status: ConstructionStatus = .destructed
    private var inFlight = false
    private var transitionGeneration: UInt64 = 0
    private var disposalRequested = false
    private var _isCurrent = false

    /// Protects lifecycle state, transition admission, publication ordering,
    /// property-publication leases, selection state, and owned resources. User
    /// callbacks are never invoked while this lock is held. Status mutations
    /// enqueue immutable records under the lock; an ordered handoff lane then
    /// publishes each committed record in full.
    private let lifecycleLock = NSRecursiveLock()

    /// Parent backpointer — set by `CompositeVM` / `GroupVM` when this VM
    /// is added as a child. `internal` so containers in the module can
    /// flip it.
    weak var _parent: ParentVM?
    weak var _ownershipParent: OwnershipParentVM? {
        didSet { _ownershipParentDidChange() }
    }
    weak var _forwardingOwner: ComponentVMBase?

    var _ownershipIdentity: ComponentVMBase { self }

    var _transferOwnershipParent: OwnershipParentVM? {
        if let direct = _ownershipParent { return direct }
        if let forwardingOwner = _forwardingOwner, forwardingOwner !== self {
            return forwardingOwner._ownershipParent
        }
        return nil
    }

    func _ownershipParentDidChange() {}
    fileprivate let ownershipGate = NSRecursiveLock()
    // The calling thread's recursive holds of `ownershipGate`; guarded by it.
    fileprivate var ownershipGateHolds = 0
    fileprivate var ownershipInProgress = false

    // ── Reactive primitives ─────────────────────────────────────────────

    private let propertyChangedSubject = VMxConcurrentSubject<String, Never>()
    private let statusTriggerSubject = PassthroughSubject<Void, Never>()
    private var triggersDisposed = false
    private var activePropertyNotifications = 0
    private var propertyNotificationTeardownPending = false
    private var ownedCleanups: [() throws -> Void] = []
    /// Member VMs registered through `ownMember`, in registration order.
    private var ownedMembers: [ComponentVMBase] = []
    /// Set under `lifecycleLock` when disposal starts, at the entry of
    /// `_disposeAtHookBoundary(children:)`, before the child cascade. Every
    /// `dispose()` path reaches it. From then on `ownMember` disposes a new
    /// member at once (spec/02 §7.1).
    private var disposeEntered = false
    /// Set when this base `dispose()` body starts, before the member
    /// cascade, so a re-entrant or concurrent `dispose()` returns at once.
    private var baseDisposeStarted = false

    private final class LifecyclePublication {
        let status: ConstructionStatus
        let generation: UInt64?
        let isDisposal: Bool
        let ownerThread: UInt64
        var mayBeAdopted: Bool
        let afterDelivery: () -> Void
        let ready = DispatchSemaphore(value: 0)
        /// Set under `lifecycleLock` when a wait edge names this publication.
        var waitRegistered = false
        var applied = false
        var succeeded = false

        init(
            status: ConstructionStatus,
            generation: UInt64?,
            isDisposal: Bool,
            ownerThread: UInt64,
            mayBeAdopted: Bool,
            afterDelivery: @escaping () -> Void = {}
        ) {
            self.status = status
            self.generation = generation
            self.isDisposal = isDisposal
            self.ownerThread = ownerThread
            self.mayBeAdopted = mayBeAdopted
            self.afterDelivery = afterDelivery
        }
    }

    private final class LifecycleHookLease {
        let threadID: UInt64
        let completed = DispatchSemaphore(value: 0)
        /// Set under `lifecycleLock` when a wait edge names this lease.
        var waitRegistered = false

        init(threadID: UInt64) {
            self.threadID = threadID
        }
    }

    private var lifecyclePublications: [LifecyclePublication] = []
    private var lifecyclePublicationHead = 0
    private var lifecycleDrainerThread: UInt64 = 0
    private var activeHookLease: LifecycleHookLease?
    private var disposalCleanupPendingForHook = false
    private var disposalFinished = false
    /// Set when an inline dispose cascade starts, ahead of this VM's
    /// terminal transition, and never cleared. From then on no lifecycle hook
    /// is admitted (LIFE-015), a lifecycle call fails with the `.disposed`
    /// error, and no status other than `.disposed` commits (spec/02 §7.2,
    /// LIFE-021).
    private var hookAdmissionClosed = false
    /// The child and member cascade of a disposal that found a foreign hook
    /// admitted; `_finishDisposalNow` runs it after the lease (LIFE-015).
    private var deferredDisposalCascade: (() -> [ComponentVMBase])?
    /// Test-only seam (#1167); see `afterHookReleaseForTesting`.
    private var _afterHookReleaseForTesting: (() -> Void)?
    /// Test-only seam (#1370); see `childStartProbeForTesting`.
    private var _childStartProbeForTesting: ((ComponentVMBase) -> Void)?

    // ── Deferred child transitions (spec/02 §6, LIFE-014) ───────────────

    /// Callbacks resumed once the in-flight transition settles (or the VM is
    /// disposed). A parent waiting on this VM registers here.
    private var settleWaiters: [(id: UInt64, callback: () -> Void)] = []
    private var nextSettleWaiterID: UInt64 = 0
    /// Set by `_transitionChildren` while a hook defers its terminal status.
    private var pendingLifecycleDeferral: LifecycleDeferral?
    /// The walker waiting on a pending child; cancelled on dispose.
    private var activeChildWalker: ChildTransitionWalker?
    /// The construct walk whose late children are sealed at commit time
    /// (spec/06 §5.1), and its transition generation.
    private var sealWalker: (walker: ChildTransitionWalker, generation: UInt64)?
    /// The state is flipped to `.constructed` by a container's seal while
    /// the commit that publishes it is still in flight.
    private var commitPending = false

    // ── Built-in commands ───────────────────────────────────────────────

    public private(set) var selectCommand: RelayCommand
    public private(set) var deselectCommand: RelayCommand
    public private(set) var selectNextCommand: RelayCommand
    public private(set) var selectPreviousCommand: RelayCommand
    public private(set) var reconstructCommand: RelayCommand

    // ── Construction ────────────────────────────────────────────────────

    public init(
        name: String,
        hint: String = "",
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        onConstruct: (() throws -> Void)? = nil,
        onDestruct: (() throws -> Void)? = nil,
        background: Bool = false
    ) {
        self.name = name
        self.hint = hint
        self.hub = hub
        self.dispatcher = dispatcher
        self.onConstructCb = onConstruct
        self.onDestructCb = onDestruct
        self.background = background

        // Capture the trigger publisher up front so it doesn't depend on
        // `self` capture order during init.
        let trigger = statusTriggerSubject.eraseToAnyPublisher()

        // Placeholders so phase-1 initialization completes; the real
        // self-capturing commands are assigned immediately below.
        self.selectCommand = RelayCommand(task: nil, predicate: nil, triggers: [])
        self.deselectCommand = RelayCommand(task: nil, predicate: nil, triggers: [])
        self.selectNextCommand = RelayCommand(
            task: nil, predicate: { false }, triggers: []
        )
        self.selectPreviousCommand = RelayCommand(
            task: nil, predicate: { false }, triggers: []
        )
        self.reconstructCommand = RelayCommand(task: nil, predicate: nil, triggers: [])

        _rewireBuiltinCommands(trigger: trigger)
    }

    /// Replaces the placeholder commands with real ones wired to the
    /// selection/lifecycle predicates and tasks per spec/05 §5, with the
    /// status trigger driving `canExecuteChanged`. `selectNext` /
    /// `selectPrevious` keep permanently-false predicates — canonical
    /// parity with the other flavors, which expose them without parent
    /// enumeration in the baseline surface.
    private func _rewireBuiltinCommands(trigger: AnyPublisher<Void, Never>) {
        selectCommand = RelayCommand(
            task: { [weak self] in self?.select() },
            predicate: { [weak self] in self?.canSelect() ?? false },
            triggers: [trigger]
        )
        deselectCommand = RelayCommand(
            task: { [weak self] in self?.deselect() },
            predicate: { [weak self] in self?.canDeselect() ?? false },
            triggers: [trigger]
        )
        selectNextCommand = RelayCommand(
            task: nil, predicate: { false }, triggers: [trigger]
        )
        selectPreviousCommand = RelayCommand(
            task: nil, predicate: { false }, triggers: [trigger]
        )
        reconstructCommand = RelayCommand(
            // `reconstruct()` is throwing (ADR-0053); the command is gated by
            // `canReconstruct()` so it never throws when fired, and a command
            // task has no error channel, so swallow with `try?`.
            task: { [weak self] in try? self?.reconstruct() },
            predicate: { [weak self] in self?.canReconstruct() ?? false },
            triggers: [trigger]
        )
    }

    // ── Status ──────────────────────────────────────────────────────────

    public var status: ConstructionStatus { _statusSnapshot() }

    public var isConstructed: Bool { _statusSnapshot() == .constructed }

    // ── isCurrent ───────────────────────────────────────────────────────

    public var isCurrent: Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        return _isCurrent
    }

    /// Internal setter used by containers to flip the flag.
    func _setIsCurrent(_ value: Bool) {
        if _commitIsCurrent(value) { _publishIsCurrent() }
    }

    /// Commits the flag and reserves its paired notification without invoking
    /// consumer code. Composite selection uses this phase for atomic state.
    /// Once disposal is requested, a commit to `false` still clears the flag
    /// and reports no change to publish, and a commit to `true` changes
    /// nothing (spec/02 §3 invariant 3, ADR-0189).
    func _commitIsCurrent(_ value: Bool) -> Bool {
        lifecycleLock.lock()
        if disposalRequested || _status == .disposed {
            if !value { _isCurrent = false }
            lifecycleLock.unlock()
            return false
        }
        guard _isCurrent != value else {
            lifecycleLock.unlock()
            return false
        }
        _isCurrent = value
        activePropertyNotifications += 1
        lifecycleLock.unlock()
        return true
    }

    /// Delivers one notification reserved by `_commitIsCurrent`.
    func _publishIsCurrent() {
        _publishAdmittedPropertyChanged("isCurrent")
    }

    // ── propertyChanged publisher ───────────────────────────────────────

    public var propertyChanged: AnyPublisher<String, Never> {
        propertyChangedSubject.eraseToAnyPublisher()
    }

    /// Publishes only on the in-process property-changed surface. Subclasses
    /// normally call `_notifyPropertyChanged` for assigned mutable state.
    /// `public` so consumer subclasses in another module can fire it (Swift has
    /// no `protected`; this is the cross-module analogue of C#'s
    /// `protected RaisePropertyChanged`).
    public func _raisePropertyChanged(_ propertyName: String) {
        guard _beginPropertyPublication() else { return }
        defer { _endPropertyPublication() }
        propertyChangedSubject.send(propertyName)
    }

    /// Publishes one hub message followed by one VM-local property change for
    /// state that a subclass has already equality-gated and assigned.
    public func _notifyPropertyChanged(_ propertyName: String) {
        lifecycleLock.lock()
        guard !disposalRequested,
              _status != .disposed,
              !triggersDisposed else {
            lifecycleLock.unlock()
            return
        }
        activePropertyNotifications += 1
        lifecycleLock.unlock()

        _publishAdmittedPropertyChanged(propertyName)
    }

    private func _publishAdmittedPropertyChanged(_ propertyName: String) {
        defer {
            _endPropertyPublication()
        }

        hub.send(PropertyChangedMessage(
            sender: self, senderName: name, propertyName: propertyName
        ))
        // Complete the admitted pair even when a hub observer disposes this VM.
        propertyChangedSubject.send(propertyName)
    }

    private func _beginPropertyPublication(allowDisposed: Bool = false) -> Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        guard (allowDisposed || (!disposalRequested && _status != .disposed)),
              !triggersDisposed else {
            return false
        }
        activePropertyNotifications += 1
        return true
    }

    private func _endPropertyPublication() {
        lifecycleLock.lock()
        activePropertyNotifications -= 1
        let shouldComplete = activePropertyNotifications == 0 &&
            propertyNotificationTeardownPending
        if shouldComplete { propertyNotificationTeardownPending = false }
        lifecycleLock.unlock()
        if shouldComplete {
            propertyChangedSubject.send(completion: .finished)
        }
    }

    // ── Lifecycle predicates ────────────────────────────────────────────

    public func canConstruct() -> Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        return !disposalRequested && !commitPending &&
            (_status == .destructed || _status == .constructed)
    }

    public func canDestruct() -> Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        return !disposalRequested && !commitPending &&
            (_status == .constructed || _status == .destructed)
    }

    public func canReconstruct() -> Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        return !disposalRequested && !commitPending && _status == .constructed
    }

    // ── Lifecycle operations ────────────────────────────────────────────

    public func construct() throws {
        lifecycleLock.lock()
        // During the inline dispose cascade the call fails as it fails from
        // `.disposed`, before the idempotent, legality and in-flight checks
        // (spec/02 §7.2, LIFE-021).
        if hookAdmissionClosed {
            lifecycleLock.unlock()
            throw StatusTransitionError(
                currentStatus: .disposed, attemptedOperation: "construct"
            )
        }
        let current = _status
        if disposalRequested || inFlight {
            lifecycleLock.unlock()
            throw StatusTransitionError(
                currentStatus: current, attemptedOperation: "construct"
            )
        }
        if current == .constructed {
            lifecycleLock.unlock()
            return
        }
        guard _isLegalTransition(from: current, operation: "construct") else {
            lifecycleLock.unlock()
            throw StatusTransitionError(
                currentStatus: current, attemptedOperation: "construct"
            )
        }
        inFlight = true
        transitionGeneration &+= 1
        let generation = transitionGeneration
        let publication = _enqueueStatusLocked(
            .constructing,
            generation: generation
        )
        lifecycleLock.unlock()
        _publishLifecycle(publication)

        if background {
            dispatcher.scheduleBackground { [weak self] in
                self?._runBackgroundHook(
                    generation: generation,
                    status: .constructing,
                    success: .constructed,
                    rollback: current
                ) { try $0._onConstruct() }
            }
        } else {
            guard let lease = _claimHook(
                generation,
                status: .constructing
            ) else { return }
            do {
                try _onConstruct()
            } catch {
                _abandonChildTransition()
                _finishHook(lease)
                _completeTransition(current, generation: generation)
                throw error
            }
            _finishHook(lease)
            _runAfterHookReleaseForTesting()
            _completeTransitionAfterChildren(
                success: .constructed,
                rollback: current,
                generation: generation
            )
        }
    }

    public func destruct() throws {
        lifecycleLock.lock()
        // During the inline dispose cascade the call fails as it fails from
        // `.disposed`, before the idempotent, legality and in-flight checks
        // (spec/02 §7.2, LIFE-021).
        if hookAdmissionClosed {
            lifecycleLock.unlock()
            throw StatusTransitionError(
                currentStatus: .disposed, attemptedOperation: "destruct"
            )
        }
        let current = _status
        if disposalRequested || inFlight {
            lifecycleLock.unlock()
            throw StatusTransitionError(
                currentStatus: current, attemptedOperation: "destruct"
            )
        }
        if current == .destructed {
            lifecycleLock.unlock()
            return
        }
        guard _isLegalTransition(from: current, operation: "destruct") else {
            lifecycleLock.unlock()
            throw StatusTransitionError(
                currentStatus: current, attemptedOperation: "destruct"
            )
        }
        inFlight = true
        transitionGeneration &+= 1
        let generation = transitionGeneration
        let publication = _enqueueStatusLocked(
            .destructing,
            generation: generation
        )
        lifecycleLock.unlock()
        _publishLifecycle(publication)

        if background {
            dispatcher.scheduleBackground { [weak self] in
                self?._runBackgroundHook(
                    generation: generation,
                    status: .destructing,
                    success: .destructed,
                    rollback: current
                ) { try $0._onDestruct() }
            }
        } else {
            guard let lease = _claimHook(
                generation,
                status: .destructing
            ) else { return }
            do {
                try _onDestruct()
            } catch {
                _abandonChildTransition()
                _finishHook(lease)
                _completeTransition(current, generation: generation)
                throw error
            }
            _finishHook(lease)
            _runAfterHookReleaseForTesting()
            _completeTransitionAfterChildren(
                success: .destructed,
                rollback: current,
                generation: generation
            )
        }
    }

    public func reconstruct() throws {
        lifecycleLock.lock()
        // During the inline dispose cascade the call fails as it fails from
        // `.disposed`, before the idempotent, legality and in-flight checks
        // (spec/02 §7.2, LIFE-021).
        if hookAdmissionClosed {
            lifecycleLock.unlock()
            throw StatusTransitionError(
                currentStatus: .disposed, attemptedOperation: "reconstruct"
            )
        }
        let current = _status
        if disposalRequested || inFlight {
            lifecycleLock.unlock()
            throw StatusTransitionError(
                currentStatus: current, attemptedOperation: "reconstruct"
            )
        }
        guard _isLegalTransition(from: current, operation: "reconstruct") else {
            lifecycleLock.unlock()
            throw StatusTransitionError(
                currentStatus: current, attemptedOperation: "reconstruct"
            )
        }
        inFlight = true
        transitionGeneration &+= 1
        let generation = transitionGeneration
        let publication = _enqueueStatusLocked(
            .destructing,
            generation: generation
        )
        lifecycleLock.unlock()
        _publishLifecycle(publication)

        guard let destructLease = _claimHook(
            generation,
            status: .destructing
        ) else { return }
        do {
            try _onDestruct()
        } catch {
            _abandonChildTransition()
            _finishHook(destructLease)
            _completeTransition(.constructed, generation: generation)
            throw error
        }
        _finishHook(destructLease)
        if let deferral = _takeLifecycleDeferral() {
            // A background child is still destructing: run the construct
            // phase only once every child has reached Destructed (spec/02 §6).
            deferral.onSettle { [weak self] succeeded in
                guard let self else { return }
                guard succeeded else {
                    self._completeTransition(.constructed, generation: generation)
                    return
                }
                // A deferred construct-phase failure has already rolled back;
                // there is no caller left to rethrow to.
                try? self._reconstructConstructPhase(generation: generation)
            }
            return
        }
        try _reconstructConstructPhase(generation: generation)
    }

    /// The Destructed → Constructing → Constructed half of `reconstruct()`.
    private func _reconstructConstructPhase(generation: UInt64) throws {
        guard _commitStatus(.destructed, generation: generation) else { return }
        guard _commitStatus(.constructing, generation: generation) else { return }

        guard let constructLease = _claimHook(
            generation,
            status: .constructing
        ) else { return }
        do {
            try _onConstruct()
        } catch {
            _abandonChildTransition()
            _finishHook(constructLease)
            _completeTransition(.destructed, generation: generation)
            throw error
        }
        _finishHook(constructLease)
        _completeTransitionAfterChildren(
            success: .constructed,
            rollback: .destructed,
            generation: generation
        )
    }

    /// Runs a background lifecycle hook and marshals its terminal status
    /// (deferred until pending children settle) back to the foreground.
    private func _runBackgroundHook(
        generation: UInt64,
        status: ConstructionStatus,
        success: ConstructionStatus,
        rollback: ConstructionStatus,
        _ hook: (ComponentVMBase) throws -> Void
    ) {
        guard let lease = _claimHook(generation, status: status) else { return }
        var failed = false
        do {
            try hook(self)
        } catch {
            _abandonChildTransition()
            failed = true
        }
        _finishHook(lease)
        let finish: (ConstructionStatus) -> Void = { [weak self] terminal in
            self?.dispatcher.scheduleForeground { [weak self] in
                self?._completeTransition(terminal, generation: generation)
            }
        }
        if !failed, let deferral = _takeLifecycleDeferral() {
            deferral.onSettle { succeeded in finish(succeeded ? success : rollback) }
        } else {
            finish(failed ? rollback : success)
        }
    }

    /// Commits `success` now, or — when the hook deferred through
    /// `_transitionChildren` — once every pending child settles (`rollback` if
    /// one did not reach its target). The in-flight guard is held meanwhile.
    private func _completeTransitionAfterChildren(
        success: ConstructionStatus,
        rollback: ConstructionStatus,
        generation: UInt64
    ) {
        guard let deferral = _takeLifecycleDeferral() else {
            _completeTransition(success, generation: generation)
            return
        }
        deferral.onSettle { [weak self] succeeded in
            self?._completeTransition(
                succeeded ? success : rollback,
                generation: generation
            )
        }
    }

    /// Publishes the terminal status, then releases the in-flight guard, then
    /// resumes any parent waiting on this transition — so a resumed parent
    /// observes the fully published status and may start the next transition.
    private func _completeTransition(
        _ status: ConstructionStatus,
        generation: UInt64
    ) {
        if status == .constructed, let walker = _sealWalker(generation) {
            // Commit or keep walking (spec/06 §5.1): the seal joins each late
            // child an add attached since the walk's last pull, then flips the
            // state under the membership gate; only then is it published.
            switch walker.seal() {
            case .sealed:
                break
            case .pending(let deferral):
                deferral.onSettle { [weak self] succeeded in
                    self?._completeTransition(
                        succeeded ? .constructed : .destructed,
                        generation: generation
                    )
                }
                return
            case .failed:
                _clearSealWalker(walker)
                _completeTransition(.destructed, generation: generation)
                return
            case .abandoned:
                // A stopped or abandoned walk commits nothing (ADR-0186): the
                // disposal or the raising hook settles the transition.
                return
            }
            _clearSealWalker(walker)
        }
        lifecycleLock.lock()
        if transitionGeneration == generation {
            activeChildWalker = nil
            sealWalker = nil
        }
        lifecycleLock.unlock()
        _ = _commitStatus(status, generation: generation)
        lifecycleLock.lock()
        var waiters: [(id: UInt64, callback: () -> Void)] = []
        if transitionGeneration == generation {
            inFlight = false
            commitPending = false
            waiters = settleWaiters
            settleWaiters.removeAll()
        }
        lifecycleLock.unlock()
        for waiter in waiters { waiter.callback() }
    }

    // ── Child transitions (spec/02 §6) ──────────────────────────────────

    /// Registers `callback` to run once this VM's in-flight `transient`
    /// transition settles or the VM is disposed. Returns `nil` without
    /// registering when no such transition is in flight.
    func _awaitSettle(
        from transient: ConstructionStatus,
        _ callback: @escaping () -> Void
    ) -> UInt64? {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        guard _isInTransitionLocked(transient) else { return nil }
        nextSettleWaiterID &+= 1
        settleWaiters.append((nextSettleWaiterID, callback))
        return nextSettleWaiterID
    }

    /// Whether this VM's `transient` transition is in flight: its status is
    /// `transient`, or a container seal already flipped it to `.constructed`
    /// while the commit is still in flight.
    func _isInTransition(_ transient: ConstructionStatus) -> Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        return _isInTransitionLocked(transient)
    }

    private func _isInTransitionLocked(_ transient: ConstructionStatus) -> Bool {
        inFlight && !disposalRequested
            && (_status == transient || (transient == .constructing && commitPending))
    }

    /// A container's commit step (call under its membership gate): writes
    /// `.constructed` for the in-flight construct and reserves its
    /// publication. The transition's commit publishes `.constructed` once.
    /// Returns `false`, and writes nothing, when the walk was abandoned or
    /// disposal stopped it. The check runs under `lifecycleLock`, the lock of
    /// the status write, and an abandon takes the seal walker under the same
    /// lock (ADR-0186).
    func _flipConstructedForSeal() -> Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        guard inFlight, !disposalRequested, !hookAdmissionClosed,
              _status == .constructing,
              let sealWalker, sealWalker.generation == transitionGeneration else { return false }
        _status = .constructed
        commitPending = true
        return true
    }

    private func _sealWalker(_ generation: UInt64) -> ChildTransitionWalker? {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        guard let sealWalker, sealWalker.generation == generation,
              transitionGeneration == generation else { return nil }
        return sealWalker.walker
    }

    private func _clearSealWalker(_ walker: ChildTransitionWalker) {
        lifecycleLock.lock()
        if sealWalker?.walker === walker { sealWalker = nil }
        lifecycleLock.unlock()
    }

    private func _takeSealWalkerLocked() -> ChildTransitionWalker? {
        let walker = sealWalker?.walker
        sealWalker = nil
        return walker
    }

    func _cancelSettleWait(_ id: UInt64) {
        lifecycleLock.lock()
        settleWaiters.removeAll { $0.id == id }
        lifecycleLock.unlock()
    }

    /// Constructs or destructs `children` one at a time as part of this VM's
    /// own transition, then runs `after` (spec/02 §6.1, ADR-0162).
    ///
    /// Call it only from this VM's `_onConstruct()` or `_onDestruct()`
    /// override, including the two phases of `reconstruct()` and a hook that
    /// runs on the background dispatcher. A leaf VM that keeps child VMs in
    /// fields uses it instead of a hand-written loop:
    ///
    /// ```swift
    /// open override func _onConstruct() throws {
    ///     try _transitionChildren([chart, table], construct: true)
    /// }
    /// open override func _onDestruct() throws {
    ///     try _transitionChildren([table, chart], construct: false)
    /// }
    /// ```
    ///
    /// The walk follows these rules:
    /// - It walks `children` in the given order and starts a child only after
    ///   the previous child settled. For reverse-order destruct, pass the
    ///   reversed list.
    /// - It skips a child that is already at the target status, and a child
    ///   that is `.disposed`. It joins a child that is already `.constructing`
    ///   (construct) or `.destructing` (destruct) and does not start it again.
    /// - A child that stays in its transient status (a background child)
    ///   defers this VM's terminal status. This VM stays `.constructing` or
    ///   `.destructing` until the child settles, and then the walk continues
    ///   on this VM's foreground dispatcher. A walk that never waits runs on
    ///   the calling thread to its end (ADR-0218 rule 3).
    /// - A child whose same transition another thread started after the walk
    ///   read its status is joined, not started again (ADR-0218 rule 6).
    /// - A child that reaches `.disposed` while the walk waits for it ends
    ///   the wait as a success (spec/02 §6, ADR-0189).
    /// - A child that settles at any other status fails the walk. This VM
    ///   rolls back to its prior settled status. A synchronous failure is
    ///   thrown from this call and then from `construct()`, `destruct()` or
    ///   `reconstruct()`. Siblings that already reached the target are not
    ///   undone.
    /// - `after` runs once, after every child settled at the target and before
    ///   this VM publishes its terminal status. A throwing `after` rolls this
    ///   VM back like a failing child.
    ///
    /// Outside this VM's own construct or destruct hook the call throws
    /// ``ChildTransitionError`` and starts no child. The method is `public`
    /// and not `open`: a subclass in another module calls it, and no subclass
    /// replaces it (ADR-0066).
    ///
    /// - Parameters:
    ///   - children: The children to transition, in walk order.
    ///   - construct: `true` to construct the children, `false` to destruct
    ///     them.
    ///   - after: Runs once after every child settled at the target.
    /// - Throws: ``ChildTransitionError`` for a usage error or a child that
    ///   did not reach the target; any error a child's `construct()` or
    ///   `destruct()` or `after` throws.
    public func _transitionChildren(
        _ children: [ComponentVMBase],
        construct: Bool,
        after: (() throws -> Void)? = nil
    ) throws {
        lifecycleLock.lock()
        let inOwnHook = activeHookLease?.threadID == Self.currentThreadID
        lifecycleLock.unlock()
        guard inOwnHook else {
            throw ChildTransitionError(
                childName: name,
                reason: "_transitionChildren was called outside this VM's construct or destruct hook"
            )
        }
        try _transitionContainerChildren(children, construct: construct, after: after)
    }

    /// The container form of `_transitionChildren` (no usage guard).
    /// Transitions `children` sequentially to Constructed (`construct`) or
    /// Destructed, then runs `after`. Call only from `_onConstruct` /
    /// `_onDestruct`. Children that settle synchronously keep the hook fully
    /// synchronous. A child left in its transient status (a background child)
    /// defers this VM's terminal status until it settles; a child that settles
    /// anywhere else rolls this VM back (LIFE-014). A child already in its
    /// transient status is joined, not restarted. A child in `joined` already
    /// started this transition (factory population): it is joined and its
    /// settled status is final, so it is never restarted. After `children`,
    /// the walk pulls each child `lateChild` returns (a child added while the
    /// walk runs) and joins it, until `lateChild` returns `nil`. The walk
    /// never starts a late child: it waits until the add's start attempt is
    /// done, then joins the child (`LateChildStarts`, spec/06 §5.1). A
    /// construct walk with `membership` counts members only (ADR-0186): it
    /// checks membership before it starts or joins a child and again after
    /// the child settles, and a child that left the container does not
    /// change this VM.
    func _transitionContainerChildren(
        _ children: [ComponentVMBase],
        construct: Bool,
        joined: [ComponentVMBase] = [],
        lateChild: LateChildSource? = nil,
        membership: ChildMembership? = nil,
        after: (() throws -> Void)? = nil
    ) throws {
        let walker = ChildTransitionWalker(
            children: children,
            construct: construct,
            after: after,
            joined: joined,
            lateChild: lateChild,
            superseded: { [weak self] in self?._isDisposalRequested() ?? true },
            membership: construct ? membership : nil,
            beforeStart: { [weak self] child in self?.childStartProbeForTesting?(child) },
            resume: { [weak self] work in self?.dispatcher.scheduleForeground(work) }
        )
        if construct, lateChild != nil {
            // Late children are sealed at commit time (spec/06 §5.1).
            lifecycleLock.lock()
            let stale = _takeSealWalkerLocked()
            sealWalker = (walker, transitionGeneration)
            lifecycleLock.unlock()
            stale?.cancel()
        }
        guard try walker.start() else { return }
        lifecycleLock.lock()
        if disposalRequested || _status == .disposed {
            // Disposed mid-hook: a disposed VM never settles.
            lifecycleLock.unlock()
            walker.cancel()
            return
        }
        guard pendingLifecycleDeferral == nil else {
            lifecycleLock.unlock()
            walker.cancel()
            throw ChildTransitionError(
                childName: name,
                reason: "a lifecycle hook already deferred completion"
            )
        }
        pendingLifecycleDeferral = walker.deferral
        activeChildWalker = walker
        lifecycleLock.unlock()
    }

    /// Stops waiting for a pending child transition without settling this
    /// VM. Containers call this before disposing their children so a child
    /// reaching Disposed cannot roll this VM back ahead of its own disposal.
    func _abandonChildTransition() {
        lifecycleLock.lock()
        let walker = activeChildWalker
        activeChildWalker = nil
        pendingLifecycleDeferral = nil
        let sealing = _takeSealWalkerLocked()
        lifecycleLock.unlock()
        walker?.cancel()
        sealing?.cancel()
    }

    private func _takeLifecycleDeferral() -> LifecycleDeferral? {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        let deferral = pendingLifecycleDeferral
        pendingLifecycleDeferral = nil
        return deferral
    }

    /// Idempotent terminal transition. From any non-Disposed state,
    /// transitions to `.disposed` and invokes `_onDispose()`. Subclasses
    /// override `_onDispose()` (and may override `dispose()` itself to
    /// cascade to children).
    ///
    /// Before this VM publishes `.disposed`, it stops waiting for a pending
    /// child walk and disposes every member registered through
    /// ``ownMember(_:)``, in registration order (spec/02 §7.1). A container
    /// disposes its own children first. A `dispose()` call that arrives while
    /// the members are being disposed returns at once. While a construct or
    /// destruct hook of this VM runs on another thread, this VM publishes
    /// `.disposed` first. It disposes no child or member until that hook
    /// returns (LIFE-015). Otherwise the children and members are disposed
    /// inline, before `.disposed`. A `construct()`, `destruct()` or
    /// `reconstruct()` call that starts during that inline cascade throws
    /// ``StatusTransitionError`` for `.disposed`, and a transition that
    /// started earlier commits no status other than `.disposed`
    /// (spec/02 §7.2, LIFE-021).
    open func dispose() { _disposeAtHookBoundary(children: nil) }

    /// A container's `dispose()` calls this, holding no lock, instead of
    /// disposing `children` and then calling `super.dispose()` (LIFE-013).
    /// The cascade runs at the same admitted-hook boundary as `dispose()`
    /// (LIFE-015).
    final func _disposeWithChildren(_ children: [ComponentVMBase]) {
        _disposeAtHookBoundary(children: children.isEmpty ? nil : { children })
    }

    /// Like `_disposeWithChildren(_:)`, but `snapshot` is read only when the
    /// cascade starts. A fixed aggregate reads its slots under its own lock
    /// then, so the cascade disposes the slots an admitted hook committed.
    final func _disposeWithChildren(snapshot: @escaping () -> [ComponentVMBase]) {
        _disposeAtHookBoundary(children: snapshot)
    }

    /// The cascade is `children`, then the members registered with
    /// `ownMember`. With no hook admitted, or one admitted on this thread,
    /// hook admission closes and the cascade runs before this VM publishes
    /// Disposed. With a hook admitted on another thread, this VM publishes
    /// Disposed now. The cascade then runs in `_finishDisposalNow` when that
    /// hook's lease is released, also on a wait cycle.
    private func _disposeAtHookBoundary(children: (() -> [ComponentVMBase])?) {
        lifecycleLock.lock()
        if baseDisposeStarted || disposalRequested || _status == .disposed {
            lifecycleLock.unlock()
            return
        }
        baseDisposeStarted = true
        disposeEntered = true
        // A container's children first, then the members (spec/02 §7.1).
        let members = ownedMembers
        ownedMembers.removeAll()
        let cascade: (() -> [ComponentVMBase])? = children == nil && members.isEmpty
            ? nil
            : { (children?() ?? []) + members }
        let lease = activeHookLease
        if let cascade,
           lease == nil || lease?.threadID == Self.currentThreadID {
            hookAdmissionClosed = true
            lifecycleLock.unlock()
            // A child reaching Disposed must not roll this VM back ahead of
            // its own disposal (LIFE-013).
            _abandonChildTransition()
            // Depth-first, before this VM publishes Disposed. Swift dispose
            // does not throw, so every child and member is attempted.
            for vm in cascade() { vm.dispose() }
            lifecycleLock.lock()
        } else {
            deferredDisposalCascade = cascade
        }

        if disposalRequested || _status == .disposed {
            lifecycleLock.unlock()
            return
        }
        disposalRequested = true
        transitionGeneration &+= 1
        inFlight = false
        commitPending = false
        let hookLease = activeHookLease
        // A transition waiting on a child never settles once Disposed.
        let walker = activeChildWalker
        activeChildWalker = nil
        pendingLifecycleDeferral = nil
        let sealing = _takeSealWalkerLocked()
        let waiters = settleWaiters
        settleWaiters.removeAll()
        let publication = _enqueueStatusLocked(
            .disposed,
            isDisposal: true,
            afterDelivery: { [weak self] in
                self?._scheduleDisposalFinish(waitingFor: hookLease)
            }
        )
        // The parent that holds this VM: its own, or, for a VM wrapped by a
        // parented forwarding decorator, the decorator's (FWD-001).
        let holder: ParentVM? = _parent
            ?? (_forwardingOwner !== self ? _forwardingOwner?._parent : nil)
        lifecycleLock.unlock()
        walker?.cancel()
        sealing?.cancel()
        _publishLifecycle(publication)
        // A parent walk waiting on this VM observes Disposed and stops
        // waiting for it (spec/02 §6, ADR-0189).
        for waiter in waiters { waiter.callback() }
        // The dispose clear runs after Disposed, in both disposal orders, and
        // before `dispose()` returns (spec/06 §4.3 rule 9, ADR-0189).
        (holder as? ChildDisposalObserver)?.childDisposed(self)
    }

    // ── Selection ───────────────────────────────────────────────────────

    /// spec/09 §1 (FWD-001): when this VM is wrapped by a forwarding
    /// decorator that is itself some container's child, the decorator is the
    /// child the parent holds. The wrapped VM's own selection API then routes
    /// through that decorator, so selection stays transparent to the wrapped
    /// component (the other flavors install a parent adapter on the wrapped
    /// VM). Only an owner that is parented is returned, so an unparented
    /// decorator chain never recurses back here.
    private var _forwardingSelectionOwner: ComponentVMBase? {
        guard _parent == nil,
              let owner = _forwardingOwner,
              owner !== self,
              owner._parent != nil else { return nil }
        return owner
    }

    public func canSelect() -> Bool {
        // spec/05 §5 + spec/07: parent non-nil, parent owns a selection slot,
        // not already current, constructed.
        guard !_isDisposalRequested() else { return false }
        if let owner = _forwardingSelectionOwner { return owner.canSelect() }
        guard let parent = _parent else { return false }
        return parent.supportsChildSelection &&
            parent.currentChild !== self &&
            _statusSnapshot() == .constructed
    }

    public func select() {
        guard !_isDisposalRequested() else { return }
        if let owner = _forwardingSelectionOwner { owner.select(); return }
        _parent?.selectChild(self)
    }

    public func canDeselect() -> Bool {
        guard !_isDisposalRequested() else { return false }
        if let owner = _forwardingSelectionOwner { return owner.canDeselect() }
        guard let parent = _parent else { return false }
        return parent.currentChild === self
    }

    public func deselect() {
        guard !_isDisposalRequested() else { return }
        if let owner = _forwardingSelectionOwner { owner.deselect(); return }
        _parent?.deselectChild(self)
    }

    // ── Overridable lifecycle hooks ─────────────────────────────────────

    /// Default: invoke the closure injected via the builder.
    ///
    /// Declared `throws` (ADR-0053) so container overrides can propagate a
    /// child's throwing `construct()` up to the originating `construct()` call —
    /// parity with the C#/Python/TypeScript cascade. The default body does not
    /// itself throw.
    open func _onConstruct() throws {
        try onConstructCb?()
    }

    /// Default: invoke the closure injected via the builder. Declared `throws`
    /// for symmetry with `_onConstruct()` (ADR-0053); the default body does not
    /// itself throw.
    open func _onDestruct() throws {
        try onDestructCb?()
    }

    /// Subclasses override for resource cleanup on terminal dispose.
    open func _onDispose() {}

    /// Register a throwing cleanup closure for terminal VM disposal.
    open func own(_ cleanup: @escaping () throws -> Void) {
        lifecycleLock.lock()
        let disposeNow = disposalRequested || _status == .disposed
        if !disposeNow {
            ownedCleanups.append(cleanup)
        }
        lifecycleLock.unlock()
        if disposeNow {
            try? cleanup()
        }
    }

    /// Register a Combine cancellable for terminal VM disposal.
    open func own(_ cancellable: any Cancellable) {
        own { cancellable.cancel() }
    }

    /// Registers `member` for depth-first disposal and returns it
    /// (spec/02 §7.1, ADR-0162).
    ///
    /// `dispose()` disposes the registered members in registration order,
    /// before this VM publishes `.disposed`. A container disposes its own
    /// children first. While a construct or destruct hook of this VM runs on
    /// another thread, this VM publishes `.disposed` first. It disposes the
    /// members after that hook returns (LIFE-015). Every member is attempted. Swift
    /// disposal does not throw, so a member's failing cleanup is not reported
    /// (the flavors with a throwing disposal surface report the first failure).
    ///
    /// ```swift
    /// let chart: ChartVM
    ///
    /// init(hub: MessageHubProtocol, dispatcher: Dispatcher) {
    ///     chart = ChartVM(hub: hub, dispatcher: dispatcher)
    ///     super.init(name: "panel", hub: hub, dispatcher: dispatcher)
    ///     ownMember(chart)
    /// }
    /// ```
    ///
    /// A member is not a container child. It gets no parent link and no
    /// selection, and registration does not construct it. Use
    /// ``_transitionChildren(_:construct:after:)`` in the lifecycle hooks to
    /// construct and destruct it. A member registered after this VM's
    /// `dispose()` started is disposed at once. Registering a member twice
    /// is harmless, because `dispose()` is idempotent. A forwarding decorator
    /// registers the member on the component it wraps, as `own` does
    /// (ADR-0151).
    ///
    /// Registering this VM itself (or a forwarding decorator of it) is a
    /// programming error and traps, because the method does not throw
    /// (ADR-0009).
    @discardableResult
    public func ownMember<T: ComponentVMBase>(_ member: T) -> T {
        let owner = _ownershipIdentity
        precondition(
            member._ownershipIdentity !== owner,
            "ownMember: a view-model cannot register itself as its own member"
        )
        if owner !== self {
            owner.ownMember(member)
            return member
        }
        lifecycleLock.lock()
        let disposeNow = disposeEntered || disposalRequested || _status == .disposed
        if !disposeNow {
            ownedMembers.append(member)
        }
        lifecycleLock.unlock()
        if disposeNow {
            member.dispose()
        }
        return member
    }

    private func disposeOwnedResources() {
        lifecycleLock.lock()
        let resources = Array(ownedCleanups.reversed())
        ownedCleanups.removeAll()
        lifecycleLock.unlock()
        for cleanup in resources {
            try? cleanup()
        }
    }

    // ── Internal helpers ────────────────────────────────────────────────

    /// Reads `_status` under `lifecycleLock` so every read has a memory
    /// barrier (Swift has no `volatile`). Reentrant — safe to call while a
    /// lifecycle method already holds the lock.
    private func _statusSnapshot() -> ConstructionStatus {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        return _status
    }

    /// True once this VM's terminal disposal is requested.
    func _isDisposalRequested() -> Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        return disposalRequested || _status == .disposed
    }

    /// Runs `commit` and returns `true`, unless this VM's terminal disposal is
    /// requested. The check and `commit` run under `lifecycleLock`, so no
    /// disposal request lands between them. `commit` must only store values.
    func _commitUnlessDisposalRequested(_ commit: () -> Void) -> Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        guard !disposalRequested, _status != .disposed else { return false }
        commit()
        return true
    }

    private typealias LifecyclePublicationPlan = (
        publication: LifecyclePublication,
        shouldDrain: Bool,
        shouldAwaitTurn: Bool,
        shouldDeliverInline: Bool
    )

    private func _claimHook(
        _ generation: UInt64,
        status: ConstructionStatus
    ) -> LifecycleHookLease? {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        guard transitionGeneration == generation,
              _status == status,
              activeHookLease == nil,
              !hookAdmissionClosed else { return nil }
        let lease = LifecycleHookLease(threadID: Self.currentThreadID)
        activeHookLease = lease
        return lease
    }

    private func _finishHook(_ lease: LifecycleHookLease) {
        lifecycleLock.lock()
        if activeHookLease === lease {
            activeHookLease = nil
        }
        if lease.waitRegistered {
            ThreadWaitGraph.shared.release(resource: ObjectIdentifier(lease))
        }
        let shouldFinishDisposal = disposalCleanupPendingForHook
        if shouldFinishDisposal {
            disposalCleanupPendingForHook = false
        }
        lifecycleLock.unlock()

        lease.completed.signal()
        if shouldFinishDisposal {
            _finishDisposalNow()
        }
    }

    @discardableResult
    private func _commitStatus(
        _ status: ConstructionStatus,
        generation: UInt64
    ) -> Bool {
        lifecycleLock.lock()
        // Once the inline dispose cascade has started, the next and last
        // status is `.disposed`: a settled commit, a rollback, a queued
        // background commit and the reconstruct construct phase are dropped
        // and publish nothing (spec/02 §7.2, LIFE-021).
        guard transitionGeneration == generation,
              !disposalRequested,
              !hookAdmissionClosed,
              _status != .disposed else {
            lifecycleLock.unlock()
            return false
        }
        // The sealed commit's publication starts: subscribers see a completed
        // transition, as without the seal.
        commitPending = false
        let publication = _enqueueStatusLocked(
            status,
            generation: generation
        )
        lifecycleLock.unlock()
        _publishLifecycle(publication)
        lifecycleLock.lock()
        let succeeded = publication.publication.succeeded
        lifecycleLock.unlock()
        return succeeded
    }

    /// Test-only seam (#1167): runs on the calling thread after a synchronous
    /// `construct()` or `destruct()` hook released its lease and before the
    /// transition commits, so a test can start a disposal in that window.
    var afterHookReleaseForTesting: (() -> Void)? {
        get {
            lifecycleLock.lock()
            defer { lifecycleLock.unlock() }
            return _afterHookReleaseForTesting
        }
        set {
            lifecycleLock.lock()
            _afterHookReleaseForTesting = newValue
            lifecycleLock.unlock()
        }
    }

    /// Test-only seam (#1370, #1375): runs in this VM's child walk after it
    /// read a child's status and before it starts that child, so a test can
    /// start the same child on another thread in that window.
    var childStartProbeForTesting: ((ComponentVMBase) -> Void)? {
        get {
            lifecycleLock.lock()
            defer { lifecycleLock.unlock() }
            return _childStartProbeForTesting
        }
        set {
            lifecycleLock.lock()
            _childStartProbeForTesting = newValue
            lifecycleLock.unlock()
        }
    }

    private func _runAfterHookReleaseForTesting() {
        lifecycleLock.lock()
        let seam = _afterHookReleaseForTesting
        lifecycleLock.unlock()
        seam?()
    }

    /// Test-only seam (#1056): commits `status` for the transition in flight,
    /// on the calling thread, as a foreground completion does. Two threads
    /// that call it while a third drains this VM queue two foreign waiters,
    /// which the in-flight guard keeps the public API from doing.
    @discardableResult
    func commitInFlightStatusForTesting(_ status: ConstructionStatus) -> Bool {
        lifecycleLock.lock()
        let generation = transitionGeneration
        lifecycleLock.unlock()
        return _commitStatus(status, generation: generation)
    }

    /// Mutate status and enqueue its immutable publication record while
    /// `lifecycleLock` is held. Callbacks are drained only after unlocking.
    private func _enqueueStatusLocked(
        _ status: ConstructionStatus,
        generation: UInt64? = nil,
        isDisposal: Bool = false,
        afterDelivery: @escaping () -> Void = {}
    ) -> LifecyclePublicationPlan {
        let caller = Self.currentThreadID
        let mayBeAdopted = lifecycleDrainerThread == caller
        let publication = LifecyclePublication(
            status: status,
            generation: generation,
            isDisposal: isDisposal,
            ownerThread: caller,
            mayBeAdopted: mayBeAdopted,
            afterDelivery: afterDelivery
        )
        if isDisposal && lifecycleDrainerThread == caller {
            _applyLifecyclePublicationLocked(publication)
            return (publication, false, false, true)
        }
        lifecyclePublications.append(publication)
        if lifecycleDrainerThread == 0 {
            lifecycleDrainerThread = caller
            _applyLifecyclePublicationLocked(publication)
            return (publication, true, false, false)
        }
        let shouldAwaitTurn = lifecycleDrainerThread != caller && !mayBeAdopted
        return (publication, false, shouldAwaitTurn, false)
    }

    private func _applyLifecyclePublicationLocked(
        _ publication: LifecyclePublication
    ) {
        guard !publication.applied else { return }
        publication.applied = true
        if publication.isDisposal {
            guard disposalRequested, _status != .disposed else { return }
        } else {
            guard let generation = publication.generation,
                  transitionGeneration == generation,
                  !disposalRequested,
                  !hookAdmissionClosed,
                  _status != .disposed else { return }
        }
        _status = publication.status
        publication.succeeded = true
    }

    private func _publishLifecycle(_ plan: LifecyclePublicationPlan) {
        if plan.shouldDeliverInline {
            _deliverLifecyclePublication(plan.publication)
        } else if plan.shouldDrain {
            _drainLifecyclePublications()
        } else if plan.shouldAwaitTurn {
            let caller = Self.currentThreadID
            // Recorded under `lifecycleLock`, which orders it against the
            // hand-off that releases it. A turn already handed over needs no edge.
            lifecycleLock.lock()
            if lifecycleDrainerThread != caller {
                guard ThreadWaitGraph.shared.beginWait(
                    caller: caller,
                    owner: lifecycleDrainerThread,
                    resource: ObjectIdentifier(plan.publication)
                ) else {
                    plan.publication.mayBeAdopted = true
                    lifecycleLock.unlock()
                    return
                }
                plan.publication.waitRegistered = true
            }
            lifecycleLock.unlock()
            plan.publication.ready.wait()
            // The edge ends before this thread drains or delivers.
            ThreadWaitGraph.shared.endWait(caller: caller)
            lifecycleLock.lock()
            let adopted = plan.publication.mayBeAdopted
            lifecycleLock.unlock()
            // A hand-off that adopted this publication woke this thread
            // without the turn; the drainer delivers it.
            if !adopted { _drainLifecyclePublications() }
        }
    }

    private func _drainLifecyclePublications() {
        let caller = Self.currentThreadID
        while true {
            lifecycleLock.lock()
            guard lifecyclePublicationHead < lifecyclePublications.count else {
                lifecyclePublications.removeAll(keepingCapacity: true)
                lifecyclePublicationHead = 0
                lifecycleDrainerThread = 0
                lifecycleLock.unlock()
                return
            }
            let publication = lifecyclePublications[lifecyclePublicationHead]
            _applyLifecyclePublicationLocked(publication)
            let shouldDeliver = publication.succeeded
            lifecycleLock.unlock()

            if shouldDeliver { _deliverLifecyclePublication(publication) }

            lifecycleLock.lock()
            lifecyclePublicationHead += 1
            if lifecyclePublicationHead >= lifecyclePublications.count {
                lifecyclePublications.removeAll(keepingCapacity: true)
                lifecyclePublicationHead = 0
                lifecycleDrainerThread = 0
                lifecycleLock.unlock()
                return
            }
            let next = lifecyclePublications[lifecyclePublicationHead]
            if next.ownerThread == caller || next.mayBeAdopted {
                lifecycleDrainerThread = caller
                lifecycleLock.unlock()
                continue
            }
            lifecycleDrainerThread = next.ownerThread
            if next.waitRegistered {
                ThreadWaitGraph.shared.release(resource: ObjectIdentifier(next))
            }
            _redirectQueuedWaitsLocked(to: next.ownerThread)
            next.ready.signal()
            lifecycleLock.unlock()
            return
        }
    }

    /// Points the wait edge of each publication queued behind the handed-over
    /// turn at the new drainer (#1056). After that, no edge names a thread
    /// that no longer drains this VM. A waiter whose new edge would close a
    /// cycle is woken without the turn. Its publication becomes adoptable,
    /// and the drainer that reaches it delivers it in FIFO order. A wait
    /// refused at registration works the same way. Called under
    /// `lifecycleLock`.
    private func _redirectQueuedWaitsLocked(to drainer: UInt64) {
        var index = lifecyclePublicationHead + 1
        while index < lifecyclePublications.count {
            let queued = lifecyclePublications[index]
            index += 1
            guard queued.waitRegistered else { continue }
            if ThreadWaitGraph.shared.redirectWait(
                caller: queued.ownerThread,
                resource: ObjectIdentifier(queued),
                to: drainer
            ) { continue }
            queued.waitRegistered = false
            queued.mayBeAdopted = true
            queued.ready.signal()
        }
    }

    private func _deliverLifecyclePublication(
        _ publication: LifecyclePublication
    ) {
        hub.send(ConstructionStatusChangedMessage(
            sender: self,
            senderName: name,
            status: publication.status
        ))
        guard _publicationIsCurrent(publication) else { return }
        _publishStatusProperty("status")
        guard _publicationIsCurrent(publication) else { return }
        _publishStatusProperty("isConstructed")
        guard _publicationIsCurrent(publication) else { return }
        statusTriggerSubject.send(())
        guard _publicationIsCurrent(publication) else { return }
        publication.afterDelivery()
    }

    private func _publicationIsCurrent(
        _ publication: LifecyclePublication
    ) -> Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        if publication.isDisposal {
            return publication.succeeded && disposalRequested && _status == .disposed
        }
        return publication.succeeded &&
            !disposalRequested &&
            transitionGeneration == publication.generation &&
            _status == publication.status
    }

    private func _publishStatusProperty(_ propertyName: String) {
        guard _beginPropertyPublication(allowDisposed: true) else { return }
        defer { _endPropertyPublication() }
        propertyChangedSubject.send(propertyName)
    }

    private func _scheduleDisposalFinish(
        waitingFor lease: LifecycleHookLease?
    ) {
        if let lease {
            if lease.threadID == Self.currentThreadID {
                lifecycleLock.lock()
                if activeHookLease === lease {
                    disposalCleanupPendingForHook = true
                    lifecycleLock.unlock()
                    return
                }
                lifecycleLock.unlock()
            } else {
                let caller = Self.currentThreadID
                // Recorded under `lifecycleLock`, which orders it against
                // `_finishHook` releasing it.
                lifecycleLock.lock()
                if activeHookLease === lease {
                    guard ThreadWaitGraph.shared.beginWait(
                        caller: caller,
                        owner: lease.threadID,
                        resource: ObjectIdentifier(lease)
                    ) else {
                        disposalCleanupPendingForHook = true
                        lifecycleLock.unlock()
                        return
                    }
                    lease.waitRegistered = true
                }
                lifecycleLock.unlock()
                lease.completed.wait()
                ThreadWaitGraph.shared.endWait(caller: caller)
            }
        }
        _finishDisposalNow()
    }

    private func _finishDisposalNow() {
        lifecycleLock.lock()
        guard !disposalFinished else {
            lifecycleLock.unlock()
            return
        }
        disposalFinished = true
        let cascade = deferredDisposalCascade
        deferredDisposalCascade = nil
        lifecycleLock.unlock()

        // A cascade deferred behind an admitted foreign hook runs only now.
        for vm in cascade?() ?? [] { vm.dispose() }
        _onDispose()
        disposeOwnedResources()

        lifecycleLock.lock()
        let shouldComplete = !triggersDisposed
        var shouldCompleteProperties = false
        if shouldComplete {
            triggersDisposed = true
            if activePropertyNotifications == 0 {
                shouldCompleteProperties = true
            } else {
                propertyNotificationTeardownPending = true
            }
        }
        lifecycleLock.unlock()

        if shouldComplete {
            statusTriggerSubject.send(completion: .finished)
            if shouldCompleteProperties {
                propertyChangedSubject.send(completion: .finished)
            }
        }

        selectCommand.dispose()
        deselectCommand.dispose()
        selectNextCommand.dispose()
        selectPreviousCommand.dispose()
        reconstructCommand.dispose()
    }

    private static var currentThreadID: UInt64 {
        ThreadWaitGraph.currentThread
    }

    // ── Transition table (fixture-driven, LIFE-011) ─────────────────────
    //
    // Delegates to `LifecycleTransitionTable`, which decodes the bundled
    // `lifecycle-transitions.json` fixture — the cross-flavor source of truth.
    // The hand-rolled switch is replaced so Swift cannot drift from the
    // canonical table the way C#/Python/TypeScript cannot.

    private func _isLegalTransition(
        from current: ConstructionStatus,
        operation: String
    ) -> Bool {
        LifecycleTransitionTable.shared.isLegal(from: current, operation: operation)
    }
}
