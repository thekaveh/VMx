//
// GroupVM<Child> — homogeneous peer-child container (no selection slot).
//
// See spec/07-group-vm.md. Coverage: add / remove / iteration / cascading
// lifecycle / batch updates (`batchUpdate()`, GRP-006).
//
import Foundation
import Combine

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
private final class GroupParent<Child: ComponentVMBase>: ParentVM, OwnershipParentVM {
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
}

open class GroupVM<Child: ComponentVMBase>:
    ComponentVMBase, _Batchable, VMCollection, ObservableMembershipSource {
    private var children: [Child] = []
    private let childrenFactory: (() -> [Child])?
    private var populated = false
    private lazy var groupParent = GroupParent(group: self)
    private let _autoConstructOnAdd: Bool

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

    public var count: Int { children.count }

    public func at(_ index: Int) -> Child { children[index] }

    public func makeIterator() -> AnyIterator<Child> {
        var iterator = children.makeIterator()
        return AnyIterator { iterator.next() }
    }

    public func snapshot() -> [Child] { children }

    public func subscribeMembership(_ callback: @escaping () -> Void) -> AnyCancellable {
        collectionChanged.sink { _ in callback() }
    }

    fileprivate func containsIdentity(_ vm: ComponentVMBase) -> Bool {
        children.contains(where: { $0 === vm })
    }

    fileprivate func detachForTransfer(_ vm: ComponentVMBase) throws -> ParentTransfer {
        guard let index = children.firstIndex(where: { $0 === vm }) else {
            throw ContainerOwnershipError.inconsistentParent
        }
        let child = children.remove(at: index)
        return ParentTransfer(
            commit: { [weak self, weak child] in
                guard let self, let child else { return }
                self.emit(.removed(child, at: index))
            },
            rollback: { [weak self, weak child] in
                guard let self, let child else { return }
                self.children.insert(child, at: index)
                child._parent = self.groupParent
                child._ownershipParent = self.groupParent
            }
        )
    }

    public func add(_ child: Child) {
        _ = addResult(child)
    }

    @discardableResult
    public func addResult(_ child: Child) -> Result<Void, ContainerOwnershipError> {
        let transfer: ParentTransfer?
        do {
            transfer = try beginParentTransfer(child, to: groupParent)
        } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        children.append(child)
        child._parent = groupParent
        child._ownershipParent = groupParent
        // When autoConstructOnAdd is set and the group is already Constructed,
        // construct the child BEFORE emitting the Add event (GRP-005). `add` is
        // non-throwing per the public API contract; failures surface through
        // assertionFailure in debug/test builds.
        // Divergence from TS (which throws on failure) is recorded in ADR-0060.
        if _autoConstructOnAdd && isConstructed {
            do { try child.construct() } catch {
                children.removeLast()
                child._parent = nil
                child._ownershipParent = nil
                transfer?.rollback()
                return .failure(.attachmentFailed(error))
            }
        }
        transfer?.commit()
        // Emit AFTER the child is appended, parent is wired, and (if
        // autoConstructOnAdd) the child has been constructed.
        let index = children.count - 1
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
        guard index >= 0 && index <= children.count else {
            return .failure(.attachmentFailed(VMCollectionIndexError(index: index, count: children.count)))
        }
        let transfer: ParentTransfer?
        do {
            transfer = try beginParentTransfer(child, to: groupParent)
        } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        children.insert(child, at: index)
        child._parent = groupParent
        child._ownershipParent = groupParent
        if _autoConstructOnAdd && isConstructed {
            do { try child.construct() } catch {
                children.remove(at: index)
                child._parent = nil
                child._ownershipParent = nil
                transfer?.rollback()
                return .failure(.attachmentFailed(error))
            }
        }
        transfer?.commit()
        emit(.added(child, at: index))
        return .success(())
    }

    public func remove(_ child: Child) -> Bool {
        guard let idx = children.firstIndex(where: { $0 === child }) else {
            return false
        }
        let removed = children.remove(at: idx)
        if removed._ownershipParent === groupParent {
            removed._parent = nil
            removed._ownershipParent = nil
        }
        // Emit AFTER the child has been removed and parent cleared.
        if _batchLevel > 0 {
            _batchDirty = true
        } else {
            collectionChangedSubject.send(.removed(child, at: idx))
        }
        return true
    }

    public func removeAt(_ index: Int) {
        let child = children.remove(at: index)
        if child._ownershipParent === groupParent {
            child._parent = nil
            child._ownershipParent = nil
        }
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
        guard index >= 0 && index < children.count else {
            return .failure(.attachmentFailed(VMCollectionIndexError(index: index, count: children.count)))
        }
        let transfer: ParentTransfer?
        do {
            transfer = try beginParentTransfer(child, to: groupParent)
        } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        let old = children[index]
        children[index] = child
        old._parent = nil
        old._ownershipParent = nil
        child._parent = groupParent
        child._ownershipParent = groupParent
        if _autoConstructOnAdd && isConstructed {
            do { try child.construct() } catch {
                children[index] = old
                old._parent = groupParent
                old._ownershipParent = groupParent
                child._parent = nil
                child._ownershipParent = nil
                transfer?.rollback()
                return .failure(.attachmentFailed(error))
            }
        }
        transfer?.commit()
        emit(.removed(old, at: index))
        emit(.added(child, at: index))
        return .success(())
    }

    public func clear() {
        for child in children where child._ownershipParent === groupParent {
            child._parent = nil
            child._ownershipParent = nil
        }
        children.removeAll()
        emit(.reset())
    }

    public func move(from fromIndex: Int, to toIndex: Int) throws {
        try validateMoveIndex(fromIndex)
        try validateMoveIndex(toIndex)
        guard fromIndex != toIndex else { return }
        let child = children.remove(at: fromIndex)
        children.insert(child, at: toIndex)
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
        // Snapshot first so child hooks can mutate the group without perturbing
        // the active lifecycle iteration.
        let snapshot = children
        for child in snapshot { try child.construct() }
    }

    private func attachPopulation(
        _ candidates: [Child]
    ) -> Result<Void, ContainerOwnershipError> {
        let start = children.count
        var transfers: [ParentTransfer?] = []
        var originalStatuses: [ConstructionStatus] = []
        do {
            for child in candidates {
                let transfer = try beginParentTransfer(child, to: groupParent)
                transfers.append(transfer)
                originalStatuses.append(child.status)
                children.append(child)
                child._parent = groupParent
                child._ownershipParent = groupParent
            }
            // Make the entire snapshot visible before any child hook runs.
            for child in candidates {
                if _autoConstructOnAdd && isConstructed { try child.construct() }
                if status == .constructing && child.status != .constructed {
                    try child.construct()
                }
            }
        } catch {
            while children.count > start {
                let child = children.removeLast()
                let originalStatus = originalStatuses[children.count - start]
                if originalStatus == .destructed && child.status == .constructed {
                    try? child.destruct()
                }
                if child._ownershipParent === groupParent {
                    child._parent = nil
                    child._ownershipParent = nil
                }
            }
            for transfer in transfers.reversed() { transfer?.rollback() }
            if let ownershipError = error as? ContainerOwnershipError {
                return .failure(ownershipError)
            }
            return .failure(.attachmentFailed(error))
        }

        for transfer in transfers { transfer?.commit() }
        for child in candidates {
            if let index = children.firstIndex(where: { $0 === child }), index >= start {
                emit(.added(child, at: index))
            }
        }
        return .success(())
    }

    open override func _onDestruct() throws {
        let snapshot = children
        for child in snapshot { try child.destruct() }
        try super._onDestruct()
    }

    open override func dispose() {
        let snapshot = children
        for child in snapshot { child.dispose() }
        super.dispose()
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
}
