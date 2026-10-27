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

/// Typed failure for exclusive container ownership operations.
public enum ContainerOwnershipError: Error {
    case duplicate
    case cycle
    case inconsistentParent
    case attachmentFailed(Error)
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

private func acquireOwnershipIdentities(_ children: [ComponentVMBase]) -> [ComponentVMBase] {
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
            if identity.ownershipGate.try() {
                acquired.append(identity)
            } else {
                blocked = identity
                break
            }
        }
        if blocked == nil {
            ownershipTransactionCoordinator.unlock()
            return identities
        }
        for identity in acquired.reversed() { identity.ownershipGate.unlock() }
        ownershipTransactionCoordinator.unlock()

        // Never retain the coordinator or another child while waiting. Once
        // this blocker moves, retry the complete identity set atomically.
        blocked!.ownershipGate.lock()
        blocked!.ownershipGate.unlock()
    }
}

func withOwnershipReservationBatch<T>(
    _ children: [ComponentVMBase],
    _ body: () throws -> T
) rethrows -> T {
    let identities = acquireOwnershipIdentities(children)
    defer {
        for identity in identities.reversed() { identity.ownershipGate.unlock() }
    }
    return try body()
}

func withExclusiveOwnershipReservationBatch<T>(
    _ children: [ComponentVMBase],
    _ body: () throws -> T
) throws -> T {
    let identities = acquireOwnershipIdentities(children)
    guard !identities.contains(where: { $0.ownershipInProgress }) else {
        for identity in identities.reversed() { identity.ownershipGate.unlock() }
        throw ContainerOwnershipTransactionError()
    }
    for identity in identities { identity.ownershipInProgress = true }
    defer {
        for identity in identities { identity.ownershipInProgress = false }
        for identity in identities.reversed() { identity.ownershipGate.unlock() }
    }
    return try body()
}

func beginParentTransfer(
    _ child: ComponentVMBase,
    to destination: OwnershipParentVM,
    transaction: ContainerOwnershipTransaction
) throws -> ParentTransfer {
    let identity = child._ownershipIdentity
    _ = acquireOwnershipIdentities([identity])
    guard !identity.ownershipInProgress else {
        identity.ownershipGate.unlock()
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
        identity.ownershipGate.unlock()
        throw error
    }

    func finish(commit: Bool) {
        defer {
            identity.ownershipInProgress = false
            identity.ownershipGate.unlock()
        }
        if commit { staged?.commit() } else { staged?.rollback() }
    }
    return ParentTransfer(commit: { finish(commit: true) }, rollback: { finish(commit: false) })
}

private struct ContainerOwnershipTransactionError: Error {}

/// Records, under `container`'s gate, that the caller waits for `owner`'s open
/// membership transaction. A container serializes another thread's open
/// transaction unless that thread already waits for this one, directly or
/// through others, including through a hub drain (#551, #703). Returns
/// `false`, and records nothing, in that case. A C# group also waits; a C#
/// composite, Python and Rust reject the transaction instead (#756).
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
/// on the per-VM `propertyChangedSubject`.
private final class VMxConcurrentSubject<Output, Failure: Error>: Subject {
    private final class TokenSubscription: Subscription {
        private weak var parent: VMxConcurrentSubject<Output, Failure>?
        private let token: UUID
        private var cancelled = false
        init(parent: VMxConcurrentSubject<Output, Failure>, token: UUID) {
            self.parent = parent
            self.token = token
        }
        func request(_ demand: Subscribers.Demand) {
            // Unlimited demand — mirrors PassthroughSubject's event-driven
            // (non-backpressured) semantics for VMx property-change notifications.
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
        var cancelled: Bool = false
        init(
            receiveValue: @escaping (Output) -> Subscribers.Demand,
            receiveCompletion: @escaping (Subscribers.Completion<Failure>) -> Void
        ) {
            self.receiveValue = receiveValue
            self.receiveCompletion = receiveCompletion
        }
    }

    private let lock = NSLock()
    private var entries: [UUID: Entry] = [:]
    private var finished = false

    public func send(_ value: Output) {
        lock.lock()
        let snapshot = Array(entries.values)
        let isFinished = finished
        lock.unlock()
        if isFinished { return }
        for entry in snapshot where !entry.cancelled {
            _ = entry.receiveValue(value)
        }
    }

    public func send(completion: Subscribers.Completion<Failure>) {
        lock.lock()
        if finished {
            lock.unlock()
            return
        }
        if case .finished = completion { finished = true }
        let snapshot = Array(entries.values)
        if case .finished = completion { entries.removeAll() }
        lock.unlock()
        for entry in snapshot where !entry.cancelled {
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
            entries[token] = entry
        }
        lock.unlock()
        subscriber.receive(subscription: TokenSubscription(parent: self, token: token))
        if alreadyFinished {
            subscriber.receive(completion: .finished)
        }
    }

    fileprivate func removeSubscriber(token: UUID) {
        lock.lock()
        let removed = entries.removeValue(forKey: token)
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
    /// gate, the next late child with a start record, or `nil` once none is
    /// left — then, in the same gate section, the container's state is
    /// flipped to `.constructed` (unpublished) and the scope ends, so a later
    /// add reads `.constructed` and follows the add-after-Constructed rule.
    let seal: () -> (child: ComponentVMBase, record: LateChildStarts.Record)?
    /// Test-only: runs as the commit-time seal starts each pull, before it
    /// checks for cancellation.
    var willSeal: (() -> Void)? = nil
}

/// The outcome of a construct walk's commit-time seal.
enum ChildWalkSeal {
    /// No late child is left; the container's state is flipped to `.constructed`.
    case sealed
    /// A late child is joined first; the walk settles `deferral` afterwards.
    case pending(LifecycleDeferral)
    /// A late child did not reach `.constructed`, or the walk failed.
    case failed
    /// An abandon or a disposal cancelled the walk. Like develop's abandon
    /// path, the seal publishes no rollback: a walk that already finished
    /// commits as it would have without the seal, and a cancelled join never
    /// settles.
    case abandoned
}

/// Walks a parent's children through one transition, waiting on each child
/// left in its transient status (spec/02 §6). Cancellation never settles the
/// deferral, so a disposed parent publishes nothing further.
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
    private let target: ConstructionStatus
    private let transient: ConstructionStatus
    private var currentDeferral = LifecycleDeferral()
    /// Settled when the walk finishes; a seal that joins another late child
    /// replaces it with a fresh one (`seal()`).
    var deferral: LifecycleDeferral { lock.withLock { currentDeferral } }

    init(
        children: [ComponentVMBase],
        construct: Bool,
        after: (() throws -> Void)?,
        joined: [ComponentVMBase] = [],
        lateChild: LateChildSource? = nil
    ) {
        self.children = children
        self.after = after
        self.joined = Set(joined.map(ObjectIdentifier.init))
        self.lateChild = lateChild
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
            lateChild.willSeal?()
            lock.lock()
            if cancelled {
                lock.unlock()
                return .abandoned
            }
            lock.unlock()
            guard let (late, record) = lateChild.seal() else { return .sealed }
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
                if try advance() { return .pending(fresh) }
            } catch {
                endLate()
                return .failed
            }
        }
    }

    private func advance() throws -> Bool {
        while true {
            lock.lock()
            guard !cancelled else {
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
            if status != target && status != transient
                && !joined.contains(ObjectIdentifier(child)) {
                if target == .constructed { try child.construct() } else { try child.destruct() }
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
            guard child.status == target else {
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

    /// A late child's add finished its start attempt: resume the walk,
    /// which now joins that child.
    private func startAttempted(_ child: ComponentVMBase) {
        lock.lock()
        guard !cancelled, let waitingStart, waitingStart === child else {
            lock.unlock()
            return
        }
        self.waitingStart = nil
        lock.unlock()
        do {
            if try advance() { return }
            settle(true)
        } catch {
            // A deferred failure has no caller to rethrow to: roll back.
            settle(false)
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
        // The child rolled back or was disposed: roll the parent back.
        guard child.status == target else {
            settle(false)
            return
        }
        lock.lock()
        index += 1
        lock.unlock()
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
    /// Set under `lifecycleLock` when disposal starts: at a container's
    /// `dispose()` entry (`_enterDispose()`), before its child cascade, or at
    /// this base `dispose()` entry. From then on `ownMember` disposes a new
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
    func _commitIsCurrent(_ value: Bool) -> Bool {
        lifecycleLock.lock()
        guard !disposalRequested,
              _status != .disposed,
              _isCurrent != value else {
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
            _completeTransitionAfterChildren(
                success: .constructed,
                rollback: current,
                generation: generation
            )
        }
    }

    public func destruct() throws {
        lifecycleLock.lock()
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
            _completeTransitionAfterChildren(
                success: .destructed,
                rollback: current,
                generation: generation
            )
        }
    }

    public func reconstruct() throws {
        lifecycleLock.lock()
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
                // The walk had finished; commit as develop's abandon path does.
                // A disposal that already began makes the commit a no-op.
                break
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

    /// A container's seal (call under its membership gate): flips the state
    /// of the in-flight construct to `.constructed` without publishing it.
    /// The transition's commit publishes `.constructed` once.
    func _flipConstructedForSeal() {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        guard inFlight, !disposalRequested, _status == .constructing else { return }
        _status = .constructed
        commitPending = true
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
    /// - It skips a child that is already at the target status. It joins a
    ///   child that is already `.constructing` (construct) or `.destructing`
    ///   (destruct) and does not start it again.
    /// - A child that stays in its transient status (a background child)
    ///   defers this VM's terminal status. This VM stays `.constructing` or
    ///   `.destructing` until the child settles, and then the walk continues.
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
    /// done, then joins the child (`LateChildStarts`, spec/06 §5.1).
    func _transitionContainerChildren(
        _ children: [ComponentVMBase],
        construct: Bool,
        joined: [ComponentVMBase] = [],
        lateChild: LateChildSource? = nil,
        after: (() throws -> Void)? = nil
    ) throws {
        let walker = ChildTransitionWalker(
            children: children,
            construct: construct,
            after: after,
            joined: joined,
            lateChild: lateChild
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

    /// A container's `dispose()` override calls this at entry, before its
    /// child cascade, under `lifecycleLock`. It marks disposal as started so
    /// `ownMember` disposes a new member at once, and returns `false` when
    /// disposal already started (a re-entrant or concurrent call, which then
    /// returns at once without waiting, spec/02 §7.1).
    func _enterDispose() -> Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        guard !disposeEntered, !disposalRequested, _status != .disposed else {
            return false
        }
        disposeEntered = true
        return true
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
    /// the members are being disposed returns at once.
    open func dispose() {
        lifecycleLock.lock()
        if baseDisposeStarted || disposalRequested || _status == .disposed {
            lifecycleLock.unlock()
            return
        }
        // A leaf enters disposal here; a container already entered through
        // `_enterDispose()` before its child cascade and reaches this body
        // once, through `super.dispose()`.
        baseDisposeStarted = true
        disposeEntered = true
        let members = ownedMembers
        ownedMembers.removeAll()
        lifecycleLock.unlock()
        if !members.isEmpty {
            // A member reaching Disposed must not roll this VM back ahead of
            // its own disposal (as the containers' child cascade, LIFE-013).
            _abandonChildTransition()
            // Depth-first, before this VM publishes Disposed. Swift dispose
            // does not throw, so every member is attempted.
            for member in members { member.dispose() }
        }

        lifecycleLock.lock()
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
        lifecycleLock.unlock()
        walker?.cancel()
        sealing?.cancel()
        _publishLifecycle(publication)
        // A parent waiting on this VM observes Disposed and rolls back.
        for waiter in waiters { waiter.callback() }
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
    /// children first. Every member is attempted. Swift disposal does not
    /// throw, so a member's failing cleanup is not reported (the flavors with
    /// a throwing disposal surface report the first failure).
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

    private func _isDisposalRequested() -> Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        return disposalRequested || _status == .disposed
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
              activeHookLease == nil else { return nil }
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
        guard transitionGeneration == generation,
              !disposalRequested,
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
            _drainLifecyclePublications()
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
            next.ready.signal()
            lifecycleLock.unlock()
            return
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
        lifecycleLock.unlock()

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
