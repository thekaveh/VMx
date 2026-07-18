//
// GroupVM<Child> — homogeneous peer-child container (no selection slot).
//
// See spec/07-group-vm.md. Coverage: add / remove / iteration / cascading
// lifecycle / batch updates (`batchUpdate()`, GRP-006).
//
import Foundation
import Combine

private struct GroupDisposalAdmissionError: Error {}

public struct GroupVMOptions<Child: ComponentVMBase> {
    public var name: String?
    public var hint: String
    public var hub: MessageHubProtocol?
    public var dispatcher: Dispatcher?
    public var children: (() -> [Child])?
    public var onConstruct: (() -> Void)?
    public var onDestruct: (() -> Void)?
    public var autoConstructOnAdd: Bool

    public init(
        name: String? = nil,
        hint: String = "",
        hub: MessageHubProtocol? = nil,
        dispatcher: Dispatcher? = nil,
        children: (() -> [Child])? = nil,
        onConstruct: (() -> Void)? = nil,
        onDestruct: (() -> Void)? = nil,
        autoConstructOnAdd: Bool = false
    ) {
        self.name = name
        self.hint = hint
        self.hub = hub
        self.dispatcher = dispatcher
        self.children = children
        self.onConstruct = onConstruct
        self.onDestruct = onDestruct
        self.autoConstructOnAdd = autoConstructOnAdd
    }
}

/// Internal parent adaptor — `GroupVM` has no "current child" concept,
/// so `selectChild`/`deselectChild` are deliberate no-ops (spec/07 —
/// children are peers; there is no slot to select into).
private final class GroupParent<Child: ComponentVMBase>: ParentVM, TransactionalOwnershipParentVM {
    weak var group: GroupVM<Child>?

    init(group: GroupVM<Child>) {
        self.group = group
    }

    var supportsChildSelection: Bool { false }
    var currentChild: ComponentVMBase? { nil }
    func selectChild(_ vm: ComponentVMBase) { /* no-op */ }
    func deselectChild(_ vm: ComponentVMBase) { /* no-op */ }

    var ownershipOwner: ComponentVMBase { group! }
    var ownershipOwnerParent: OwnershipParentVM? { group?._ownershipParent }
    func containsIdentity(_ vm: ComponentVMBase) -> Bool {
        group?.containsIdentity(vm) ?? false
    }
    func detachForTransfer(_ vm: ComponentVMBase) throws -> ParentTransfer {
        guard let group else { throw ContainerOwnershipError.inconsistentParent }
        return try group.detachForTransfer(vm)
    }
    func detachForTransfer(
        _ vm: ComponentVMBase,
        transaction: ContainerOwnershipTransaction
    ) throws -> ParentTransfer {
        guard let group else { throw ContainerOwnershipError.inconsistentParent }
        return try group.detachForTransfer(vm, transaction: transaction)
    }
}

open class GroupVM<Child: ComponentVMBase>:
    ComponentVMBase, _Batchable, VMCollection, ObservableMembershipSource {
    private var children: [Child] = []
    private let childrenFactory: (() -> [Child])?
    private var populated = false
    private lazy var groupParent = GroupParent(group: self)
    private let _autoConstructOnAdd: Bool
    private var disposeRequested = false
    private var disposeDeferred = false
    private var membershipTransactionActive = false
    private var membershipTransactionToken: ContainerOwnershipTransaction?
    private var membershipTransactionDepth = 0
    private var membershipTransactionOwner: ObjectIdentifier?
    private var membershipTransactionCompletion: DispatchGroup?
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
        autoConstructOnAdd: Bool = false
    ) {
        self.childrenFactory = childrenFactory
        self._autoConstructOnAdd = autoConstructOnAdd
        super.init(
            name: name, hint: hint,
            hub: hub, dispatcher: dispatcher,
            onConstruct: onConstruct, onDestruct: onDestruct
        )
    }

    open override var type: ViewModelType { .group }

    public var count: Int { membershipGate.withLock { children.count } }

    public func at(_ index: Int) -> Child { membershipGate.withLock { children[index] } }

    public func makeIterator() -> AnyIterator<Child> {
        var iterator = snapshot().makeIterator()
        return AnyIterator { iterator.next() }
    }

    public func snapshot() -> [Child] { membershipGate.withLock { children } }

    public func subscribeMembership(_ callback: @escaping () -> Void) -> AnyCancellable {
        collectionChanged.sink { _ in callback() }
    }

    fileprivate func containsIdentity(_ vm: ComponentVMBase) -> Bool {
        let identity = vm._ownershipIdentity
        return membershipGate.withLock {
            children.contains(where: { $0._ownershipIdentity === identity })
        }
    }

    fileprivate func detachForTransfer(_ vm: ComponentVMBase) throws -> ParentTransfer {
        try detachForTransfer(vm, transaction: ContainerOwnershipTransaction())
    }

    fileprivate func detachForTransfer(
        _ vm: ComponentVMBase,
        transaction: ContainerOwnershipTransaction
    ) throws -> ParentTransfer {
        try joinMembershipTransaction(transaction)
        let detached: (Int, Child)
        do {
            detached = try membershipGate.withLock {
                let identity = vm._ownershipIdentity
                guard let index = children.firstIndex(where: {
                    $0._ownershipIdentity === identity
                }) else {
                    throw ContainerOwnershipError.inconsistentParent
                }
                return (index, children.remove(at: index))
            }
        } catch {
            endMembershipTransaction()
            throw error
        }
        let (index, child) = detached
        return ParentTransfer(
            commit: {
                defer { self.endMembershipTransaction() }
                if child._ownershipParent === self.groupParent {
                    child._parent = nil
                    child._ownershipParent = nil
                }
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
                    child._parent = self.groupParent
                    child._ownershipParent = self.groupParent
                }
            }
        )
    }

    public func add(_ child: Child) {
        if case let .failure(error) = addResult(child) {
            assertionFailure("GroupVM.add failed — \(error)")
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
            transfer = try beginParentTransfer(child, to: groupParent, transaction: transaction)
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
        child._parent = groupParent
        child._ownershipParent = groupParent
        membershipGate.unlock()
        // When autoConstructOnAdd is set and the group is already Constructed,
        // construct the child BEFORE emitting the Add event (GRP-005). `add` is
        // non-throwing per the public API contract; failures surface through
        // assertionFailure in debug/test builds.
        // Divergence from TS (which throws on failure) is recorded in ADR-0060.
        if _autoConstructOnAdd && isConstructed {
            do { try child.construct() } catch {
                membershipGate.withLock {
                    if let attached = children.firstIndex(where: { $0 === child }) {
                        children.remove(at: attached)
                    }
                    if child._ownershipParent === groupParent {
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
                if child._ownershipParent === groupParent {
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
            transfer = try beginParentTransfer(child, to: groupParent, transaction: transaction)
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
        child._parent = groupParent
        child._ownershipParent = groupParent
        membershipGate.unlock()
        if _autoConstructOnAdd && isConstructed {
            do { try child.construct() } catch {
                membershipGate.withLock {
                    if let attached = children.firstIndex(where: { $0 === child }) {
                        children.remove(at: attached)
                    }
                    if child._ownershipParent === groupParent {
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
                if child._ownershipParent === groupParent {
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
        let removed: (Child, Int)? = membershipGate.withLock {
            guard !membershipTransactionActive else { return nil }
            guard let index = children.firstIndex(where: { $0 === child }) else { return nil }
            let item = children.remove(at: index)
            if item._ownershipParent === groupParent {
                item._parent = nil
                item._ownershipParent = nil
            }
            return (item, index)
        }
        guard let (item, index) = removed else { return false }
        // Emit AFTER the child has been removed and parent cleared.
        if _batchLevel > 0 {
            _batchDirty = true
        } else {
            collectionChangedSubject.send(.removed(item, at: index))
        }
        return true
    }

    public func removeAt(_ index: Int) {
        let child: Child? = membershipGate.withLock {
            guard !membershipTransactionActive else { return nil }
            let removed = children.remove(at: index)
            if removed._ownershipParent === groupParent {
                removed._parent = nil
                removed._ownershipParent = nil
            }
            return removed
        }
        guard let child else { return }
        emit(.removed(child, at: index))
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
            transfer = try beginParentTransfer(child, to: groupParent, transaction: transaction)
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
        child._parent = groupParent
        child._ownershipParent = groupParent
        membershipGate.unlock()
        if _autoConstructOnAdd && isConstructed {
            do { try child.construct() } catch {
                membershipGate.withLock {
                    if let attached = children.firstIndex(where: { $0 === child }) {
                        children[attached] = old
                        old._parent = groupParent
                        old._ownershipParent = groupParent
                    }
                    if child._ownershipParent === groupParent {
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
                    old._parent = groupParent
                    old._ownershipParent = groupParent
                }
                if child._ownershipParent === groupParent {
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
        emit(.removed(old, at: index))
        emit(.added(child, at: index))
        return .success(())
    }

    public func clear() {
        let accepted: Bool = membershipGate.withLock {
            guard !membershipTransactionActive else { return false }
            for child in children where child._ownershipParent === groupParent {
                child._parent = nil
                child._ownershipParent = nil
            }
            children.removeAll()
            return true
        }
        guard accepted else { return }
        emit(.reset())
    }

    public func move(from fromIndex: Int, to toIndex: Int) throws {
        let child: Child? = try membershipGate.withLock {
            guard !membershipTransactionActive else {
                throw ContainerOwnershipError.attachmentFailed(GroupMembershipTransactionError())
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

    open override func _onConstruct() throws {
        try super._onConstruct()
        if !populated, let factory = childrenFactory {
            try attachPopulation(factory()).get()
            populated = true
        }
        // A peer's throwing `construct()` (ADR-0053) propagates up the cascade.
        // Snapshot first so the lifecycle iteration is stable; membership
        // mutations from population hooks are rejected until commit/rollback.
        let snapshot = snapshot()
        for child in snapshot { try child.construct() }
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
                        to: groupParent,
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
                    child._parent = groupParent
                    child._ownershipParent = groupParent
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
                if child._ownershipParent === groupParent {
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
            for child in snapshot { child.dispose() }
            super.dispose()
            return
        }
    }

    public static func builder() -> GroupVMBuilder<Child> {
        GroupVMBuilder<Child>()
    }

    public static func create(_ options: GroupVMOptions<Child>) throws -> GroupVM<Child> {
        var b = GroupVM<Child>.builder()
            .hint(options.hint)
            .autoConstructOnAdd(options.autoConstructOnAdd)
        if let name = options.name { b = b.name(name) }
        if let hub = options.hub { b = b._optionHub(hub) }
        if let dispatcher = options.dispatcher { b = b._optionDispatcher(dispatcher) }
        if let children = options.children { b = b.children(children) }
        if let onConstruct = options.onConstruct { b = b.onConstruct(onConstruct) }
        if let onDestruct = options.onDestruct { b = b.onDestruct(onDestruct) }
        return try b.build()
    }

    private func beginMembershipTransactionLocked(
        _ transaction: ContainerOwnershipTransaction,
        allowJoin: Bool
    ) throws {
        guard !disposeRequested && !disposeDeferred else {
            throw ContainerOwnershipError.attachmentFailed(GroupDisposalAdmissionError())
        }
        if membershipTransactionActive {
            guard allowJoin, membershipTransactionToken === transaction else {
                throw ContainerOwnershipError.attachmentFailed(GroupMembershipTransactionError())
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
            throw ContainerOwnershipError.attachmentFailed(GroupDisposalAdmissionError())
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
                shouldDispose = disposeDeferred
                disposeDeferred = false
            }
        }
        completion?.leave()
        if shouldDispose { dispose() }
    }
}

private struct GroupMembershipTransactionError: Error {}
