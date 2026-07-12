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
private final class GroupParent: ParentVM {
    var supportsChildSelection: Bool { false }
    var currentChild: ComponentVMBase? { nil }
    func selectChild(_ vm: ComponentVMBase) { /* no-op */ }
    func deselectChild(_ vm: ComponentVMBase) { /* no-op */ }
}

open class GroupVM<Child: ComponentVMBase>:
    ComponentVMBase, _Batchable, VMCollection, ObservableMembershipSource {
    private var children: [Child] = []
    private let childrenFactory: (() -> [Child])?
    private var populated = false
    private let groupParent = GroupParent()
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

    public func add(_ child: Child) {
        children.append(child)
        child._parent = groupParent
        // When autoConstructOnAdd is set and the group is already Constructed,
        // construct the child BEFORE emitting the Add event (GRP-005). `add` is
        // non-throwing per the public API contract; failures surface through
        // assertionFailure in debug/test builds.
        // Divergence from TS (which throws on failure) is recorded in ADR-0060.
        if _autoConstructOnAdd && isConstructed {
            do { try child.construct() } catch {
                assertionFailure("autoConstructOnAdd: child construct failed: \(error)")
            }
        }
        // Emit AFTER the child is appended, parent is wired, and (if
        // autoConstructOnAdd) the child has been constructed.
        let index = children.count - 1
        if _batchLevel > 0 {
            _batchDirty = true
        } else {
            collectionChangedSubject.send(.added(child, at: index))
        }
    }

    public func insert(_ child: Child, at index: Int) {
        children.insert(child, at: index)
        child._parent = groupParent
        if _autoConstructOnAdd && isConstructed {
            do { try child.construct() } catch {
                assertionFailure("autoConstructOnAdd: child construct failed: \(error)")
            }
        }
        emit(.added(child, at: index))
    }

    public func remove(_ child: Child) -> Bool {
        guard let idx = children.firstIndex(where: { $0 === child }) else {
            return false
        }
        children[idx]._parent = nil
        children.remove(at: idx)
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
        child._parent = nil
        emit(.removed(child, at: index))
    }

    public func replace(at index: Int, with child: Child) {
        let old = children[index]
        children[index] = child
        old._parent = nil
        child._parent = groupParent
        emit(.removed(old, at: index))
        if _autoConstructOnAdd && isConstructed {
            do { try child.construct() } catch {
                assertionFailure("autoConstructOnAdd: child construct failed: \(error)")
            }
        }
        emit(.added(child, at: index))
    }

    public func clear() {
        for child in children { child._parent = nil }
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
            populated = true
            for c in factory() { add(c) }
        }
        // A peer's throwing `construct()` (ADR-0053) propagates up the cascade.
        // Snapshot first so child hooks can mutate the group without perturbing
        // the active lifecycle iteration.
        let snapshot = children
        for child in snapshot { try child.construct() }
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
        if let hub = options.hub, let dispatcher = options.dispatcher {
            b = b.services(hub: hub, dispatcher: dispatcher)
        }
        if let children = options.children { b = b.children(children) }
        if let onConstruct = options.onConstruct { b = b.onConstruct(onConstruct) }
        if let onDestruct = options.onDestruct { b = b.onDestruct(onDestruct) }
        return try b.build()
    }
}
