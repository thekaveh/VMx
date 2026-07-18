//
// CompositeVM<VM> — homogeneous-child container with a `current`
// selection slot.
//
// See spec/06-composite-vm.md. The Swift flavor is at full library parity as
// of v3.1.0; this type covers child mutation, selection, lifecycle cascade,
// batch updates, async selection, and CollectionChanged events.
//
import Foundation
import Combine

private struct ContainerDisposalAdmissionError: Error {}
private let compositeCurrentChangeCoordinator = NSRecursiveLock()

public struct CompositeVMOptions<Child: ComponentVMBase> {
    public var name: String?
    public var hint: String
    public var hub: MessageHubProtocol?
    public var dispatcher: Dispatcher?
    public var children: (() -> [Child])?
    public var current: (([Child]) -> Child?)?
    public var onCurrentChanged: ((Child?) -> Void)?
    public var onConstruct: (() -> Void)?
    public var onDestruct: (() -> Void)?
    public var autoConstructOnAdd: Bool
    public var asyncSelection: Bool

    public init(
        name: String? = nil,
        hint: String = "",
        hub: MessageHubProtocol? = nil,
        dispatcher: Dispatcher? = nil,
        children: (() -> [Child])? = nil,
        current: (([Child]) -> Child?)? = nil,
        onCurrentChanged: ((Child?) -> Void)? = nil,
        onConstruct: (() -> Void)? = nil,
        onDestruct: (() -> Void)? = nil,
        autoConstructOnAdd: Bool = false,
        asyncSelection: Bool = false
    ) {
        self.name = name
        self.hint = hint
        self.hub = hub
        self.dispatcher = dispatcher
        self.children = children
        self.current = current
        self.onCurrentChanged = onCurrentChanged
        self.onConstruct = onConstruct
        self.onDestruct = onDestruct
        self.autoConstructOnAdd = autoConstructOnAdd
        self.asyncSelection = asyncSelection
    }
}

open class CompositeVM<Child: ComponentVMBase>:
    ComponentVMBase, ParentVM, TransactionalOwnershipParentVM, _Batchable, SelectableVMCollection,
    ObservableMembershipSource {
    private var children: [Child] = []
    private var _current: Child?
    private let childrenFactory: (() -> [Child])?
    private let currentSelector: (([Child]) -> Child?)?
    private let onCurrentChanged: ((Child?) -> Void)?
    private var populated = false
    private let _autoConstructOnAdd: Bool
    private let _asyncSelection: Bool
    private var disposeRequested = false
    private var disposeDeferred = false
    private var membershipTransactionActive = false
    private var membershipTransactionToken: ContainerOwnershipTransaction?
    private var membershipTransactionDepth = 0
    private var membershipTransactionOwner: ObjectIdentifier?
    private var membershipTransactionCompletion: DispatchGroup?
    private var activeCurrentPublications = 0
    private let membershipGate = NSRecursiveLock()

    // ── Batch-update state ──────────────────────────────────────────────

    private var _batchLevel = 0
    private var _batchDirty = false

    // ── CollectionChanged publisher ─────────────────────────────────────

    private let collectionChangedSubject = PassthroughSubject<CollectionChangedEvent, Never>()

    /// Emits a `CollectionChangedEvent` after each `add` or `remove` mutation.
    /// During a batch, granular events are suppressed; `dispose()` on the
    /// returned `BatchUpdateHandle` emits a single `.reset` (if dirty).
    public var collectionChanged: AnyPublisher<CollectionChangedEvent, Never> {
        collectionChangedSubject.eraseToAnyPublisher()
    }

    /// Begin a batch update. Per-mutation `CollectionChanged` events are
    /// suppressed until `dispose()` is called on the returned handle, at which
    /// point a single `.reset` event is emitted (only if a mutation occurred).
    /// Nested `batchUpdate()` calls are supported via a reference counter; the
    /// reset fires only when the outermost batch ends.
    public func batchUpdate() -> BatchUpdateHandle {
        _batchLevel += 1
        return BatchUpdateHandle(owner: self)
    }

    /// Called by `BatchUpdateHandle.dispose()` — do not call directly.
    func _exitBatch() {
        guard _batchLevel > 0 else { return }
        _batchLevel -= 1
        if _batchLevel == 0 && _batchDirty {
            _batchDirty = false
            collectionChangedSubject.send(.reset())
        }
    }

    public init(
        name: String,
        hint: String = "",
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        childrenFactory: (() -> [Child])? = nil,
        onConstruct: (() -> Void)? = nil,
        onDestruct: (() -> Void)? = nil,
        currentSelector: (([Child]) -> Child?)? = nil,
        onCurrentChanged: ((Child?) -> Void)? = nil,
        autoConstructOnAdd: Bool = false,
        asyncSelection: Bool = false
    ) {
        self.childrenFactory = childrenFactory
        self.currentSelector = currentSelector
        self.onCurrentChanged = onCurrentChanged
        self._autoConstructOnAdd = autoConstructOnAdd
        self._asyncSelection = asyncSelection
        super.init(
            name: name, hint: hint,
            hub: hub, dispatcher: dispatcher,
            onConstruct: onConstruct, onDestruct: onDestruct
        )
    }

    open override var type: ViewModelType { .composite }

    // ── ParentVM ────────────────────────────────────────────────────────

    public var supportsChildSelection: Bool { true }

    public var currentChild: ComponentVMBase? { membershipGate.withLock { _current } }

    public func selectChild(_ vm: ComponentVMBase) {
        // Mirror C# `CanSelectComponent`: the target must be a member *and*
        // Constructed. C# throws on a violation; Swift keeps the existing
        // no-op rather than introducing an (uncatchable) trap — the
        // trap-vs-throw recoverability gap is tracked separately (ADR-0037).
        guard vm.status == .constructed else { return }
        membershipGate.lock()
        guard !membershipTransactionActive,
              let child = children.first(where: { $0 === vm }) else {
            membershipGate.unlock()
            return
        }
        membershipGate.unlock()
        _requestCurrentChange(child, requireConstructed: true)
    }

    public func deselectChild(_ vm: ComponentVMBase) {
        membershipGate.lock()
        let child = !membershipTransactionActive ? _current : nil
        membershipGate.unlock()
        if let child, child === vm { _requestDeselect(child) }
    }

    var ownershipOwner: ComponentVMBase { self }
    var ownershipOwnerParent: OwnershipParentVM? { _ownershipParent }

    func containsIdentity(_ vm: ComponentVMBase) -> Bool {
        let identity = vm._ownershipIdentity
        return membershipGate.withLock {
            children.contains(where: { $0._ownershipIdentity === identity })
        }
    }

    func detachForTransfer(_ vm: ComponentVMBase) throws -> ParentTransfer {
        try detachForTransfer(vm, transaction: ContainerOwnershipTransaction())
    }

    func detachForTransfer(
        _ vm: ComponentVMBase,
        transaction: ContainerOwnershipTransaction
    ) throws -> ParentTransfer {
        try joinMembershipTransaction(transaction)
        let detached: (Int, Child, Bool)
        do {
            detached = try membershipGate.withLock {
                let identity = vm._ownershipIdentity
                guard let index = children.firstIndex(where: {
                    $0._ownershipIdentity === identity
                }) else {
                    throw ContainerOwnershipError.inconsistentParent
                }
                let child = children.remove(at: index)
                return (index, child, _current === child)
            }
        } catch {
            endMembershipTransaction()
            throw error
        }
        let (index, child, wasCurrent) = detached
        return ParentTransfer(
            commit: {
                defer { self.endMembershipTransaction() }
                if child._ownershipParent === self {
                    child._parent = nil
                    child._ownershipParent = nil
                }
                if wasCurrent { self._applyCurrentChange(nil, internalTransaction: true) }
                self.emit(.removed(child, at: index))
            },
            rollback: {
                defer { self.endMembershipTransaction() }
                self.membershipGate.withLock {
                    guard !self.disposeRequested else {
                        child._parent = nil
                        child._ownershipParent = nil
                        return
                    }
                    self.children.insert(child, at: Swift.min(index, self.children.count))
                    child._parent = self
                    child._ownershipParent = self
                }
            }
        )
    }

    // ── Public collection surface ───────────────────────────────────────

    public var count: Int { membershipGate.withLock { children.count } }

    public func at(_ index: Int) -> Child {
        membershipGate.withLock { children[index] }
    }

    public func makeIterator() -> AnyIterator<Child> {
        var iterator = snapshot().makeIterator()
        return AnyIterator { iterator.next() }
    }

    public func snapshot() -> [Child] { membershipGate.withLock { children } }

    public func subscribeMembership(_ callback: @escaping () -> Void) -> AnyCancellable {
        collectionChanged.sink { _ in callback() }
    }

    /// The selected child, or `nil`.
    ///
    /// The **setter traps** (`preconditionFailure`) if assigned a value that is
    /// not a member of this composite (spec/06 §3.1 — `Current` must be a
    /// member). Swift property setters cannot be `throws`, so the recoverable
    /// path is `setCurrent(_:)` / `canSetCurrent(_:)` (VMX-026 / ADR-0053): they
    /// validate membership and throw a catchable `CompositeMembershipError`,
    /// mirroring the C#/Python/TypeScript catchable throw. The trapping setter
    /// is retained (not deprecated) for ergonomic binding of an already-validated
    /// member — assigning a known child or `nil` is the common case and never
    /// traps.
    public var current: Child? {
        get { membershipGate.withLock { _current } }
        set { _setCurrent(newValue) }
    }

    /// Pre-flight predicate for `setCurrent(_:)` / the `current` setter: returns
    /// `true` iff `value` is `nil` or a member of this composite. Mirrors C#
    /// `CanSelectComponent` membership gating for the `Current` slot (spec/06
    /// §3.1).
    public func canSetCurrent(_ value: Child?) -> Bool {
        membershipGate.withLock {
            guard !membershipTransactionActive else { return false }
            guard let value else { return true }
            return children.contains(where: { $0 === value })
        }
    }

    /// Throwing, catchable alternative to the `current` property setter
    /// (VMX-026 / ADR-0053). Validates membership and throws
    /// `CompositeMembershipError` on a non-child, instead of trapping. A `nil`
    /// or member assignment behaves exactly like `current = value`.
    public func setCurrent(_ value: Child?) throws {
        membershipGate.lock()
        guard !membershipTransactionActive,
              value == nil || children.contains(where: { $0 === value }) else {
            membershipGate.unlock()
            throw CompositeMembershipError(
                memberName: value?.name ?? "<nil>", compositeName: name
            )
        }
        membershipGate.unlock()
        _requestCurrentChange(value)
    }

    /// Pre-flight predicate for `selectComponent(_:)`: returns `true` iff `vm`
    /// is a member of this composite **and** `vm.status == .constructed`.
    ///
    /// This is distinct from `canSetCurrent(_:)`, which checks membership only
    /// without the Constructed gate (spec/06 §3.1). Swift throws catchably
    /// (ADR-0053) where C# surfaces `InvalidOperationException`.
    public func canSelectComponent(_ vm: Child) -> Bool {
        guard vm.status == .constructed else { return false }
        return membershipGate.withLock {
            !membershipTransactionActive
                && children.contains(where: { $0 === vm })
        }
    }

    /// Selects `vm` as the current child, throwing `CompositeMembershipError`
    /// if `canSelectComponent(vm)` returns `false` (non-member or not yet
    /// constructed — spec/06 §3.1 / COMP-008).
    ///
    /// Swift convergence of the C#/TypeScript `selectComponent` throwing path
    /// (ADR-0053): catchable throw rather than a trap, unlike the `current`
    /// property setter which cannot be `throws` in Swift.
    public func selectComponent(_ vm: Child) throws {
        guard vm.status == .constructed else {
            throw CompositeMembershipError(memberName: vm.name, compositeName: name)
        }
        membershipGate.lock()
        guard !membershipTransactionActive,
              children.contains(where: { $0 === vm }) else {
            membershipGate.unlock()
            throw CompositeMembershipError(memberName: vm.name, compositeName: name)
        }
        membershipGate.unlock()
        _requestCurrentChange(vm, requireConstructed: true)
    }

    /// Deselects `vm`, clearing the current slot, throwing
    /// `CompositeMembershipError` if `vm` is not the current selection
    /// (spec/06 §3.1 / COMP-011).
    ///
    /// Swift convergence of the C#/TypeScript `deselectComponent` throwing path
    /// (ADR-0053): catchable throw rather than a trap.
    public func deselectComponent(_ vm: Child) throws {
        membershipGate.lock()
        guard !membershipTransactionActive, _current === vm else {
            membershipGate.unlock()
            throw CompositeMembershipError(memberName: vm.name, compositeName: name)
        }
        membershipGate.unlock()
        _requestDeselect(vm)
    }

    public func add(_ child: Child) {
        if case let .failure(error) = addResult(child) {
            assertionFailure("CompositeVM.add failed — \(error)")
        }
    }

    @discardableResult
    public func addResult(_ child: Child) -> Result<Void, ContainerOwnershipError> {
        let transaction: ContainerOwnershipTransaction
        do { transaction = try beginMembershipTransaction() } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        defer { endMembershipTransaction() }
        let originalStatus = child.status
        let transfer: ParentTransfer?
        do {
            transfer = try beginParentTransfer(child, to: self, transaction: transaction)
        } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        membershipGate.lock()
        do {
            try requireTransactionCanContinueLocked()
        } catch {
            membershipGate.unlock()
            transfer?.rollback()
            return .failure(.attachmentFailed(error))
        }
        children.append(child)
        child._parent = self
        child._ownershipParent = self
        membershipGate.unlock()
        // When autoConstructOnAdd is set and the composite is already
        // Constructed, construct the child BEFORE emitting the Add event
        // (COMP-012). `add` is non-throwing per the public API contract;
        // failures surface through assertionFailure in debug/test builds.
        // Divergence from TS (which throws on failure) is recorded in ADR-0060.
        if _autoConstructOnAdd && isConstructed {
            do { try child.construct() } catch {
                membershipGate.withLock {
                    if let attached = children.firstIndex(where: { $0 === child }) {
                        children.remove(at: attached)
                    }
                    if child._ownershipParent === self {
                        child._parent = nil
                        child._ownershipParent = nil
                    }
                }
                transfer?.rollback()
                return .failure(.attachmentFailed(error))
            }
        }
        do {
            try membershipGate.withLock { try requireTransactionCanContinueLocked() }
        } catch {
            membershipGate.withLock {
                if let attached = children.firstIndex(where: { $0 === child }) {
                    children.remove(at: attached)
                }
                if child._ownershipParent === self {
                    child._parent = nil
                    child._ownershipParent = nil
                }
            }
            var compensationError: Error?
            if originalStatus == .destructed && child.status == .constructed {
                do { try child.destruct() } catch { compensationError = error }
            }
            transfer?.rollback()
            if let compensationError {
                return .failure(.attachmentFailed(compensationError))
            }
            return .failure(.attachmentFailed(error))
        }
        // Commit the old-parent removal before publishing the destination add.
        transfer?.commit()
        // Emit AFTER the child is appended, parent is wired, and (if
        // autoConstructOnAdd) the child has been constructed.
        let index = membershipGate.withLock {
            children.firstIndex(where: { $0 === child }) ?? Swift.max(children.count - 1, 0)
        }
        if _batchLevel > 0 {
            _batchDirty = true
        } else {
            collectionChangedSubject.send(.added(child, at: index))
        }
        return .success(())
    }

    public func insert(_ child: Child, at index: Int) {
        _ = insertResult(child, at: index)
    }

    @discardableResult
    public func insertResult(
        _ child: Child,
        at index: Int
    ) -> Result<Void, ContainerOwnershipError> {
        let transaction: ContainerOwnershipTransaction
        do { transaction = try beginMembershipTransaction() } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        defer { endMembershipTransaction() }
        let originalStatus = child.status
        let childCount = membershipGate.withLock { children.count }
        guard index >= 0 && index <= childCount else {
            return .failure(.attachmentFailed(VMCollectionIndexError(index: index, count: childCount)))
        }
        let transfer: ParentTransfer?
        do {
            transfer = try beginParentTransfer(child, to: self, transaction: transaction)
        } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        membershipGate.lock()
        do {
            try requireTransactionCanContinueLocked()
        } catch {
            membershipGate.unlock()
            transfer?.rollback()
            return .failure(.attachmentFailed(error))
        }
        children.insert(child, at: index)
        child._parent = self
        child._ownershipParent = self
        membershipGate.unlock()
        if _autoConstructOnAdd && isConstructed {
            do { try child.construct() } catch {
                membershipGate.withLock {
                    if let attached = children.firstIndex(where: { $0 === child }) {
                        children.remove(at: attached)
                    }
                    if child._ownershipParent === self {
                        child._parent = nil
                        child._ownershipParent = nil
                    }
                }
                transfer?.rollback()
                return .failure(.attachmentFailed(error))
            }
        }
        do {
            try membershipGate.withLock { try requireTransactionCanContinueLocked() }
        } catch {
            membershipGate.withLock {
                if let attached = children.firstIndex(where: { $0 === child }) {
                    children.remove(at: attached)
                }
                if child._ownershipParent === self {
                    child._parent = nil
                    child._ownershipParent = nil
                }
            }
            var compensationError: Error?
            if originalStatus == .destructed && child.status == .constructed {
                do { try child.destruct() } catch { compensationError = error }
            }
            transfer?.rollback()
            if let compensationError {
                return .failure(.attachmentFailed(compensationError))
            }
            return .failure(.attachmentFailed(error))
        }
        transfer?.commit()
        emit(.added(child, at: index))
        return .success(())
    }

    public func remove(_ child: Child) -> Bool {
        guard (try? beginMembershipTransaction()) != nil else { return false }
        defer { endMembershipTransaction() }
        let removed: (Child, Int, Bool)? = membershipGate.withLock {
            guard let index = children.firstIndex(where: { $0 === child }) else { return nil }
            let item = children.remove(at: index)
            if item._ownershipParent === self {
                item._parent = nil
                item._ownershipParent = nil
            }
            let wasCurrent = _current === item
            return (item, index, wasCurrent)
        }
        guard let (item, index, wasCurrent) = removed else { return false }
        if wasCurrent { _applyCurrentChange(nil, internalTransaction: true) }
        emit(.removed(item, at: index))
        return true
    }

    public func removeAt(_ index: Int) {
        guard (try? beginMembershipTransaction()) != nil else { return }
        defer { endMembershipTransaction() }
        let removal: (Child, Bool)? = membershipGate.withLock {
            let removed = children.remove(at: index)
            if removed._ownershipParent === self {
                removed._parent = nil
                removed._ownershipParent = nil
            }
            let wasCurrent = _current === removed
            return (removed, wasCurrent)
        }
        guard let (item, wasCurrent) = removal else { return }
        if wasCurrent { _applyCurrentChange(nil, internalTransaction: true) }
        // Emit AFTER the child has been removed and parent cleared.
        emit(.removed(item, at: index))
    }

    public func replace(at index: Int, with child: Child) {
        _ = replaceResult(at: index, with: child)
    }

    @discardableResult
    public func replaceResult(
        at index: Int,
        with child: Child
    ) -> Result<Void, ContainerOwnershipError> {
        let transaction: ContainerOwnershipTransaction
        do { transaction = try beginMembershipTransaction() } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        defer { endMembershipTransaction() }
        let originalStatus = child.status
        let childCount = membershipGate.withLock { children.count }
        guard index >= 0 && index < childCount else {
            return .failure(.attachmentFailed(VMCollectionIndexError(index: index, count: childCount)))
        }
        let transfer: ParentTransfer?
        do {
            transfer = try beginParentTransfer(child, to: self, transaction: transaction)
        } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        membershipGate.lock()
        do {
            try requireTransactionCanContinueLocked()
        } catch {
            membershipGate.unlock()
            transfer?.rollback()
            return .failure(.attachmentFailed(error))
        }
        let old = children[index]
        children[index] = child
        old._parent = nil
        old._ownershipParent = nil
        child._parent = self
        child._ownershipParent = self
        membershipGate.unlock()
        if _autoConstructOnAdd && isConstructed {
            do { try child.construct() } catch {
                membershipGate.withLock {
                    if let attached = children.firstIndex(where: { $0 === child }) {
                        children[attached] = old
                        old._parent = self
                        old._ownershipParent = self
                    }
                    if child._ownershipParent === self {
                        child._parent = nil
                        child._ownershipParent = nil
                    }
                }
                transfer?.rollback()
                return .failure(.attachmentFailed(error))
            }
        }
        do {
            try membershipGate.withLock { try requireTransactionCanContinueLocked() }
        } catch {
            membershipGate.withLock {
                if let attached = children.firstIndex(where: { $0 === child }) {
                    children[attached] = old
                    old._parent = self
                    old._ownershipParent = self
                }
                if child._ownershipParent === self {
                    child._parent = nil
                    child._ownershipParent = nil
                }
            }
            var compensationError: Error?
            if originalStatus == .destructed && child.status == .constructed {
                do { try child.destruct() } catch { compensationError = error }
            }
            transfer?.rollback()
            if let compensationError {
                return .failure(.attachmentFailed(compensationError))
            }
            return .failure(.attachmentFailed(error))
        }
        transfer?.commit()
        if current === old { _applyCurrentChange(nil, internalTransaction: true) }
        emit(.removed(old, at: index))
        emit(.added(child, at: index))
        return .success(())
    }

    public func clear() {
        guard (try? beginMembershipTransaction()) != nil else { return }
        defer { endMembershipTransaction() }
        let result: (Bool, Child?) = membershipGate.withLock {
            let previous = _current
            for child in children where child._ownershipParent === self {
                child._parent = nil
                child._ownershipParent = nil
            }
            children.removeAll()
            return (true, previous)
        }
        guard result.0 else { return }
        if result.1 != nil { _applyCurrentChange(nil, internalTransaction: true) }
        emit(.reset())
    }

    public func move(from fromIndex: Int, to toIndex: Int) throws {
        let child: Child? = try membershipGate.withLock {
            guard !membershipTransactionActive else {
                throw ContainerOwnershipError.attachmentFailed(ContainerMembershipTransactionError())
            }
            try validateMoveIndex(fromIndex)
            try validateMoveIndex(toIndex)
            guard fromIndex != toIndex else { return nil }
            let item = children.remove(at: fromIndex)
            children.insert(item, at: toIndex)
            return item
        }
        guard let child else { return }
        emit(.moved(child, from: fromIndex, to: toIndex))
    }

    private func validateMoveIndex(_ index: Int) throws {
        guard index >= 0 && index < children.count else {
            throw VMCollectionIndexError(index: index, count: children.count)
        }
    }

    private func emit(_ event: CollectionChangedEvent) {
        if _batchLevel > 0 {
            _batchDirty = true
        } else {
            collectionChangedSubject.send(event)
        }
    }

    // ── Lifecycle overrides ─────────────────────────────────────────────

    open override func _onConstruct() throws {
        try super._onConstruct()
        if !populated {
            if let factory = childrenFactory {
                try attachPopulation(factory()).get()
            }
            populated = true
        }
        // A child's throwing `construct()` (ADR-0053) propagates up through this
        // hook to the composite's originating `construct()` call. Snapshot first
        // so the lifecycle iteration is stable; membership mutations attempted
        // from population hooks are rejected until the transaction completes.
        let snapshot = snapshot()
        for child in snapshot { try child.construct() }
        if let selector = currentSelector,
           let initial = selector(snapshot),
           snapshot.contains(where: { $0 === initial }) {
            // Non-raising validated assignment (spec/06 §3.1 / COMP-025): the
            // membership is already checked above, so the internal setter never
            // hits its non-child trap here.
            _setCurrent(initial)
        }
    }

    private func attachPopulation(
        _ candidates: [Child]
    ) -> Result<Void, ContainerOwnershipError> {
        var identities = Set<ObjectIdentifier>()
        guard candidates.allSatisfy({
            identities.insert(ObjectIdentifier($0._ownershipIdentity)).inserted
        }) else {
            return .failure(.duplicate)
        }
        let transaction: ContainerOwnershipTransaction
        do {
            transaction = try beginMembershipTransaction()
        } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        defer { endMembershipTransaction() }
        let start = membershipGate.withLock { children.count }

        var transfers: [ParentTransfer] = []
        var originalStatuses: [ConstructionStatus] = []
        do {
            try withOwnershipReservationBatch(candidates) {
                for child in candidates {
                    let transfer = try beginParentTransfer(
                        child,
                        to: self,
                        transaction: transaction
                    )
                    transfers.append(transfer)
                    originalStatuses.append(child.status)
                }
            }
            try membershipGate.withLock {
                try requireTransactionCanContinueLocked()
                for child in candidates {
                    children.append(child)
                    child._parent = self
                    child._ownershipParent = self
                }
            }
            // Make the entire snapshot visible before any child hook runs.
            for child in candidates {
                if _autoConstructOnAdd && isConstructed { try child.construct() }
                if status == .constructing && child.status != .constructed {
                    try child.construct()
                }
            }
            try membershipGate.withLock { try requireTransactionCanContinueLocked() }
        } catch let attachmentError {
            var compensationError: Error?
            for (offset, child) in candidates.enumerated().reversed() {
                guard offset < originalStatuses.count else { continue }
                membershipGate.withLock {
                    if let attached = children.firstIndex(where: { $0 === child }) {
                        children.remove(at: attached)
                    }
                }
                let originalStatus = originalStatuses[offset]
                if originalStatus == .destructed && child.status == .constructed {
                    do { try child.destruct() } catch {
                        if compensationError == nil { compensationError = error }
                    }
                }
                if child._ownershipParent === self {
                    child._parent = nil
                    child._ownershipParent = nil
                }
            }
            for transfer in transfers.reversed() { transfer.rollback() }
            if let compensationError {
                return .failure(.attachmentFailed(compensationError))
            }
            if let ownershipError = attachmentError as? ContainerOwnershipError {
                return .failure(ownershipError)
            }
            return .failure(.attachmentFailed(attachmentError))
        }

        for transfer in transfers { transfer.commit() }
        for child in candidates {
            if let index = membershipGate.withLock({
                children.firstIndex(where: { $0 === child })
            }), index >= start {
                emit(.added(child, at: index))
            }
        }
        return .success(())
    }

    open override func _onDestruct() throws {
        // Bypass asyncSelection for teardown: destruct is synchronous and must
        // clear the current slot before children are destructed.
        if membershipGate.withLock({ _current != nil }) { _applyCurrentChange(nil) }
        let snapshot = snapshot()
        for child in snapshot { try child.destruct() }
        try super._onDestruct()
    }

    open override func dispose() {
        while true {
            var waitForTransaction: DispatchGroup?
            var snapshot: [Child]?
            let shouldReturn: Bool = membershipGate.withLock {
                if disposeRequested { return true }
                if membershipTransactionActive {
                    if membershipTransactionOwner == ObjectIdentifier(Thread.current) {
                        disposeDeferred = true
                        return true
                    }
                    waitForTransaction = membershipTransactionCompletion
                    return false
                }
                if activeCurrentPublications > 0 {
                    disposeDeferred = true
                    return true
                }
                disposeRequested = true
                snapshot = children
                return false
            }
            if shouldReturn { return }
            if let waitForTransaction {
                waitForTransaction.wait()
                continue
            }
            guard let snapshot else { return }
            // LIFE-013: depth-first dispose children, then self.
            for child in snapshot { child.dispose() }
            super.dispose()
            return
        }
    }

    // ── Builder entrypoint ──────────────────────────────────────────────

    public static func builder() -> CompositeVMBuilder<Child> {
        CompositeVMBuilder<Child>()
    }

    public static func create(_ options: CompositeVMOptions<Child>) throws -> CompositeVM<Child> {
        var b = CompositeVM<Child>.builder()
            .hint(options.hint)
            .autoConstructOnAdd(options.autoConstructOnAdd)
            .asyncSelection(options.asyncSelection)
        if let name = options.name { b = b.name(name) }
        if let hub = options.hub { b = b._optionHub(hub) }
        if let dispatcher = options.dispatcher { b = b._optionDispatcher(dispatcher) }
        if let children = options.children { b = b.children(children) }
        if let current = options.current { b = b.current(current) }
        if let onCurrentChanged = options.onCurrentChanged { b = b.onCurrentChanged(onCurrentChanged) }
        if let onConstruct = options.onConstruct { b = b.onConstruct(onConstruct) }
        if let onDestruct = options.onDestruct { b = b.onDestruct(onDestruct) }
        return try b.build()
    }

    // ── Internal ────────────────────────────────────────────────────────

    private func beginMembershipTransactionLocked(
        _ transaction: ContainerOwnershipTransaction,
        allowJoin: Bool
    ) throws {
        guard !disposeRequested && !disposeDeferred else {
            throw ContainerOwnershipError.attachmentFailed(ContainerDisposalAdmissionError())
        }
        if membershipTransactionActive {
            guard allowJoin, membershipTransactionToken === transaction else {
                throw ContainerOwnershipError.attachmentFailed(ContainerMembershipTransactionError())
            }
            membershipTransactionDepth += 1
            return
        }
        membershipTransactionActive = true
        membershipTransactionToken = transaction
        membershipTransactionDepth = 1
        membershipTransactionOwner = ObjectIdentifier(Thread.current)
        let completion = DispatchGroup()
        completion.enter()
        membershipTransactionCompletion = completion
    }

    private func beginMembershipTransaction() throws -> ContainerOwnershipTransaction {
        let transaction = ContainerOwnershipTransaction()
        try membershipGate.withLock {
            try beginMembershipTransactionLocked(transaction, allowJoin: false)
        }
        return transaction
    }

    private func joinMembershipTransaction(
        _ transaction: ContainerOwnershipTransaction
    ) throws {
        try membershipGate.withLock {
            try beginMembershipTransactionLocked(transaction, allowJoin: true)
        }
    }

    private func requireTransactionCanContinueLocked() throws {
        guard !disposeRequested && !disposeDeferred else {
            throw ContainerOwnershipError.attachmentFailed(ContainerDisposalAdmissionError())
        }
    }

    private func endMembershipTransaction() {
        var completion: DispatchGroup?
        var shouldDispose = false
        membershipGate.withLock {
            precondition(membershipTransactionDepth > 0)
            membershipTransactionDepth -= 1
            if membershipTransactionDepth == 0 {
                membershipTransactionActive = false
                membershipTransactionToken = nil
                membershipTransactionOwner = nil
                completion = membershipTransactionCompletion
                membershipTransactionCompletion = nil
                shouldDispose = disposeDeferred && activeCurrentPublications == 0
                if shouldDispose { disposeDeferred = false }
            }
        }
        completion?.leave()
        if shouldDispose { dispose() }
    }

    private func _setCurrent(_ value: Child?) {
        // Non-child assignment is a programmer error reachable only via the
        // (non-throwing) `current` property setter; `setCurrent(_:)` pre-validates
        // via `canSetCurrent(_:)` and throws `CompositeMembershipError` before
        // reaching here (VMX-026 / ADR-0053). The trap remains for the property
        // setter, which Swift cannot make `throws`.
        let allowed = membershipGate.withLock {
            !membershipTransactionActive
                && (value == nil || children.contains(where: { $0 === value }))
        }
        if !allowed {
            preconditionFailure(
                "Cannot set current to '\(value?.name ?? "<nil>")': not an available child of this composite. "
                + "Use setCurrent(_:)/canSetCurrent(_:) for a catchable check."
            )
        }
        _requestCurrentChange(value)
    }

    private func _requestCurrentChange(
        _ value: Child?,
        requireConstructed: Bool = false
    ) {
        if _asyncSelection {
            // COMP-010: defer the full current-change to the foreground dispatcher.
            // A TOCTOU re-check in `_applyCurrentChange` drops the deferred selection
            // if the child was removed between schedule and flush, upholding the
            // spec/06 §3 invariant that a non-null current is always a member.
            let captured = value
            dispatcher.scheduleForeground { [weak self] in
                self?._applyCurrentChange(captured, requireConstructed: requireConstructed)
            }
        } else {
            _applyCurrentChange(value, requireConstructed: requireConstructed)
        }
    }

    private func _requestDeselect(_ expected: Child) {
        let apply = { [weak self, weak expected] in
            guard let self, let expected else { return }
            self._applyCurrentChange(
                nil,
                expectedCurrent: expected,
                requireExpectedCurrent: true
            )
        }
        if _asyncSelection {
            dispatcher.scheduleForeground(apply)
        } else {
            apply()
        }
    }

    private func _applyCurrentChange(
        _ value: Child?,
        internalTransaction: Bool = false,
        requireConstructed: Bool = false,
        expectedCurrent: Child? = nil,
        requireExpectedCurrent: Bool = false
    ) {
        // TOCTOU guard (COMP-010): re-validate membership after a foreground-
        // dispatched selection — the child may have been removed before the
        // deferred closure ran.
        if let value, requireConstructed, value.status != .constructed { return }
        compositeCurrentChangeCoordinator.lock()
        var ownsTransaction = false
        if !internalTransaction {
            do {
                _ = try beginMembershipTransaction()
                ownsTransaction = true
            } catch {
                compositeCurrentChangeCoordinator.unlock()
                return
            }
        }
        let committed: (Child?, Bool, Bool)? = membershipGate.withLock {
            if let value, !children.contains(where: { $0 === value }) { return nil }
            if requireExpectedCurrent && _current !== expectedCurrent { return nil }
            if _current === value { return nil }
            let previous = _current
            _current = value
            let previousChanged = previous?._commitIsCurrent(false) ?? false
            let valueChanged = value?._commitIsCurrent(true) ?? false
            activeCurrentPublications += 1
            return (previous, previousChanged, valueChanged)
        }
        if ownsTransaction { endMembershipTransaction() }
        compositeCurrentChangeCoordinator.unlock()
        guard let committed else { return }
        _finishCurrentChange(
            from: committed.0,
            to: value,
            previousFlagChanged: committed.1,
            valueFlagChanged: committed.2
        )
    }

    private func _finishCurrentChange(
        from previous: Child?,
        to value: Child?,
        previousFlagChanged: Bool,
        valueFlagChanged: Bool
    ) {
        defer { _endCurrentPublication() }

        // COMP-006: the flag is committed atomically with the current slot, but
        // its admitted notification remains foreground-dispatched.
        if let prev = previous, previousFlagChanged {
            dispatcher.scheduleForeground { [weak prev] in
                guard let prev else { return }
                prev._publishIsCurrent()
            }
        }
        if valueFlagChanged { value?._publishIsCurrent() }

        _notifyPropertyChanged("current")
        onCurrentChanged?(value)
    }

    private func _endCurrentPublication() {
        var shouldDispose = false
        membershipGate.withLock {
            precondition(activeCurrentPublications > 0)
            activeCurrentPublications -= 1
            shouldDispose = activeCurrentPublications == 0
                && !membershipTransactionActive
                && disposeDeferred
            if shouldDispose { disposeDeferred = false }
        }
        if shouldDispose { dispose() }
    }
}

private struct ContainerMembershipTransactionError: Error {}

/// Thrown by `CompositeVM.setCurrent(_:)` when the argument is not a member of
/// the composite's children (spec/06 §3.1 — `Current` must be a member; cf.
/// `COMP-009`). This is the Swift convergence (ADR-0053, VMX-026) of the
/// non-child `Current` assignment that C# surfaces as `InvalidOperationException`
/// and Python/TypeScript as a thrown error. The non-throwing `current` property
/// setter traps instead, because Swift setters cannot be `throws`.
public struct CompositeMembershipError: Error, CustomStringConvertible {
    public let memberName: String
    public let compositeName: String

    public init(memberName: String, compositeName: String) {
        self.memberName = memberName
        self.compositeName = compositeName
    }

    public var description: String {
        "Cannot set current to '\(memberName)': "
        + "not a child of composite '\(compositeName)'."
    }
}
