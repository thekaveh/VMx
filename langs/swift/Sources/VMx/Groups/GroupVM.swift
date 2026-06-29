//
// GroupVM<Child> — homogeneous peer-child container (no selection slot).
//
// See spec/07-group-vm.md. Skeleton coverage: add / remove / iteration /
// cascading lifecycle. Batch updates land in a follow-up PR.
//
import Foundation
import Combine

/// Internal parent adaptor — `GroupVM` has no "current child" concept,
/// so `selectChild`/`deselectChild` are deliberate no-ops (spec/07 —
/// children are peers; there is no slot to select into).
private final class GroupParent: ParentVM {
    var currentChild: ComponentVMBase? { nil }
    func selectChild(_ vm: ComponentVMBase) { /* no-op */ }
    func deselectChild(_ vm: ComponentVMBase) { /* no-op */ }
}

open class GroupVM<Child: ComponentVMBase>: ComponentVMBase {
    private var children: [Child] = []
    private let childrenFactory: (() -> [Child])?
    private var populated = false
    private let groupParent = GroupParent()
    private let _autoConstructOnAdd: Bool

    // ── CollectionChanged publisher ─────────────────────────────────────

    private let collectionChangedSubject = PassthroughSubject<CollectionChangedEvent, Never>()

    /// Emits a `CollectionChangedEvent` after each `add` or `remove` mutation.
    public var collectionChanged: AnyPublisher<CollectionChangedEvent, Never> {
        collectionChangedSubject.eraseToAnyPublisher()
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
        collectionChangedSubject.send(.added(child, at: index))
    }

    public func remove(_ child: Child) -> Bool {
        guard let idx = children.firstIndex(where: { $0 === child }) else {
            return false
        }
        children[idx]._parent = nil
        children.remove(at: idx)
        // Emit AFTER the child has been removed and parent cleared.
        collectionChangedSubject.send(.removed(child, at: idx))
        return true
    }

    open override func _onConstruct() throws {
        try super._onConstruct()
        if !populated, let factory = childrenFactory {
            populated = true
            for c in factory() { add(c) }
        }
        // A peer's throwing `construct()` (ADR-0053) propagates up the cascade.
        for child in children { try child.construct() }
    }

    open override func _onDestruct() throws {
        for child in children { try child.destruct() }
        try super._onDestruct()
    }

    open override func dispose() {
        for child in children { child.dispose() }
        super.dispose()
    }

    public static func builder() -> GroupVMBuilder<Child> {
        GroupVMBuilder<Child>()
    }
}
