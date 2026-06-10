//
// GroupVM<Child> — homogeneous peer-child container (no selection slot).
//
// See spec/07-group-vm.md. Skeleton coverage: add / remove / iteration /
// cascading lifecycle. Batch updates + auto-construct-on-add land in a
// follow-up PR.
//
import Foundation

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

    public init(
        name: String,
        hint: String = "",
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        childrenFactory: (() -> [Child])? = nil,
        onConstruct: (() -> Void)? = nil,
        onDestruct: (() -> Void)? = nil
    ) {
        self.childrenFactory = childrenFactory
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
    }

    public func remove(_ child: Child) -> Bool {
        guard let idx = children.firstIndex(where: { $0 === child }) else {
            return false
        }
        children[idx]._parent = nil
        children.remove(at: idx)
        return true
    }

    open override func _onConstruct() {
        super._onConstruct()
        if !populated, let factory = childrenFactory {
            populated = true
            for c in factory() { add(c) }
        }
        for child in children { child.construct() }
    }

    open override func _onDestruct() {
        for child in children { child.destruct() }
        super._onDestruct()
    }

    open override func dispose() {
        for child in children { child.dispose() }
        super.dispose()
    }

    public static func builder() -> GroupVMBuilder<Child> {
        GroupVMBuilder<Child>()
    }
}
