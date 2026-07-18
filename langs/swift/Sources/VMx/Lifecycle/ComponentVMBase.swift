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

private final class LifecycleWaitCoordinator: @unchecked Sendable {
    static let shared = LifecycleWaitCoordinator()

    private let lock = NSLock()
    private var waitingOn: [UInt64: UInt64] = [:]

    func beginWait(caller: UInt64, owner: UInt64) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        waitingOn[caller] = owner
        var cursor = owner
        var visited = Set<UInt64>()
        while visited.insert(cursor).inserted, let next = waitingOn[cursor] {
            if next == caller {
                waitingOn.removeValue(forKey: caller)
                return false
            }
            cursor = next
        }
        return true
    }

    func endWait(caller: UInt64) {
        lock.lock()
        waitingOn.removeValue(forKey: caller)
        lock.unlock()
    }
}

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

func withOwnershipReservationBatch<T>(_ body: () throws -> T) rethrows -> T {
    ownershipTransactionCoordinator.lock()
    defer { ownershipTransactionCoordinator.unlock() }
    return try body()
}

func beginParentTransfer(
    _ child: ComponentVMBase,
    to destination: OwnershipParentVM,
    transaction: ContainerOwnershipTransaction
) throws -> ParentTransfer {
    let identity = child._ownershipIdentity
    ownershipTransactionCoordinator.lock()
    identity.ownershipGate.lock()
    guard !identity.ownershipInProgress else {
        identity.ownershipGate.unlock()
        ownershipTransactionCoordinator.unlock()
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
        ownershipTransactionCoordinator.unlock()
        throw error
    }

    // The coordinator orders reservation acquisition only. The canonical
    // identity remains reserved, but consumer callbacks during finalization
    // must be able to start unrelated transfers.
    ownershipTransactionCoordinator.unlock()

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

/// View-model kind tag. Mirrors `ViewModelType`.
public enum ViewModelType: String, Sendable {
    case component = "Component"
    case readOnlyComponent = "ReadOnlyComponent"
    case composite = "Composite"
    case group = "Group"
    case aggregate = "Aggregate"
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

    private let propertyChangedSubject = PassthroughSubject<String, Never>()
    private let statusTriggerSubject = PassthroughSubject<Void, Never>()
    private var triggersDisposed = false
    private var activePropertyNotifications = 0
    private var propertyNotificationTeardownPending = false
    private var ownedCleanups: [() throws -> Void] = []

    private final class LifecyclePublication {
        let status: ConstructionStatus
        let generation: UInt64?
        let isDisposal: Bool
        let ownerThread: UInt64
        var mayBeAdopted: Bool
        let afterDelivery: () -> Void
        let ready = DispatchSemaphore(value: 0)
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
        return !disposalRequested &&
            (_status == .destructed || _status == .constructed)
    }

    public func canDestruct() -> Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        return !disposalRequested &&
            (_status == .constructed || _status == .destructed)
    }

    public func canReconstruct() -> Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        return !disposalRequested && _status == .constructed
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
                guard let self else { return }
                guard let lease = self._claimHook(
                    generation,
                    status: .constructing
                ) else { return }
                let terminal: ConstructionStatus
                do {
                    try self._onConstruct()
                    terminal = .constructed
                } catch {
                    terminal = current
                }
                self._finishHook(lease)
                self.dispatcher.scheduleForeground { [weak self] in
                    guard let self else { return }
                    _ = self._commitStatus(terminal, generation: generation)
                    self._clearInFlight(generation)
                }
            }
        } else {
            guard let lease = _claimHook(
                generation,
                status: .constructing
            ) else { return }
            do {
                try _onConstruct()
            } catch {
                _finishHook(lease)
                _ = _commitStatus(current, generation: generation)
                _clearInFlight(generation)
                throw error
            }
            _finishHook(lease)
            _ = _commitStatus(.constructed, generation: generation)
            _clearInFlight(generation)
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
                guard let self else { return }
                guard let lease = self._claimHook(
                    generation,
                    status: .destructing
                ) else { return }
                let terminal: ConstructionStatus
                do {
                    try self._onDestruct()
                    terminal = .destructed
                } catch {
                    terminal = current
                }
                self._finishHook(lease)
                self.dispatcher.scheduleForeground { [weak self] in
                    guard let self else { return }
                    _ = self._commitStatus(terminal, generation: generation)
                    self._clearInFlight(generation)
                }
            }
        } else {
            guard let lease = _claimHook(
                generation,
                status: .destructing
            ) else { return }
            do {
                try _onDestruct()
            } catch {
                _finishHook(lease)
                _ = _commitStatus(current, generation: generation)
                _clearInFlight(generation)
                throw error
            }
            _finishHook(lease)
            _ = _commitStatus(.destructed, generation: generation)
            _clearInFlight(generation)
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
            _finishHook(destructLease)
            _ = _commitStatus(.constructed, generation: generation)
            _clearInFlight(generation)
            throw error
        }
        _finishHook(destructLease)
        guard _commitStatus(.destructed, generation: generation) else { return }
        guard _commitStatus(.constructing, generation: generation) else { return }

        guard let constructLease = _claimHook(
            generation,
            status: .constructing
        ) else { return }
        do {
            try _onConstruct()
        } catch {
            _finishHook(constructLease)
            _ = _commitStatus(.destructed, generation: generation)
            _clearInFlight(generation)
            throw error
        }
        _finishHook(constructLease)
        _ = _commitStatus(.constructed, generation: generation)
        _clearInFlight(generation)
    }

    /// Idempotent terminal transition. From any non-Disposed state,
    /// transitions to `.disposed` and invokes `_onDispose()`. Subclasses
    /// override `_onDispose()` (and may override `dispose()` itself to
    /// cascade to children).
    open func dispose() {
        lifecycleLock.lock()
        if disposalRequested || _status == .disposed {
            lifecycleLock.unlock()
            return
        }
        disposalRequested = true
        transitionGeneration &+= 1
        inFlight = false
        let hookLease = activeHookLease
        let publication = _enqueueStatusLocked(
            .disposed,
            isDisposal: true,
            afterDelivery: { [weak self] in
                self?._scheduleDisposalFinish(waitingFor: hookLease)
            }
        )
        lifecycleLock.unlock()
        _publishLifecycle(publication)
    }

    // ── Selection ───────────────────────────────────────────────────────

    public func canSelect() -> Bool {
        // spec/05 §5 + spec/07: parent non-nil, parent owns a selection slot,
        // not already current, constructed.
        guard !_isDisposalRequested() else { return false }
        guard let parent = _parent else { return false }
        return parent.supportsChildSelection &&
            parent.currentChild !== self &&
            _statusSnapshot() == .constructed
    }

    public func select() {
        guard !_isDisposalRequested() else { return }
        _parent?.selectChild(self)
    }

    public func canDeselect() -> Bool {
        guard !_isDisposalRequested() else { return false }
        guard let parent = _parent else { return false }
        return parent.currentChild === self
    }

    public func deselect() {
        guard !_isDisposalRequested() else { return }
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
        shouldDeliverInline: Bool,
        awaitedOwner: UInt64
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

    private func _clearInFlight(_ generation: UInt64) {
        lifecycleLock.lock()
        if transitionGeneration == generation { inFlight = false }
        lifecycleLock.unlock()
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
            return (publication, false, false, true, 0)
        }
        lifecyclePublications.append(publication)
        if lifecycleDrainerThread == 0 {
            lifecycleDrainerThread = caller
            _applyLifecyclePublicationLocked(publication)
            return (publication, true, false, false, 0)
        }
        let shouldAwaitTurn = lifecycleDrainerThread != caller && !mayBeAdopted
        return (publication, false, shouldAwaitTurn, false, lifecycleDrainerThread)
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
            if !LifecycleWaitCoordinator.shared.beginWait(
                caller: caller,
                owner: plan.awaitedOwner
            ) {
                lifecycleLock.lock()
                plan.publication.mayBeAdopted = true
                lifecycleLock.unlock()
                return
            }
            defer { LifecycleWaitCoordinator.shared.endWait(caller: caller) }
            plan.publication.ready.wait()
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
                lease.completed.wait()
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
        UInt64(pthread_mach_thread_np(pthread_self()))
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
