//
// AggregateVM1<C1> — arity-1 aggregate viewmodel.
//
// See spec/08-aggregate-vm.md and ADR-0007.
//
import Foundation

open class AggregateVM1<C1: ComponentVMBase>: ComponentVMBase {
    private lazy var aggregateParent = AggregateParent(owner: self) { [unowned self] in
        self.childComponents
    }
    private let factory1: () -> C1
    public private(set) var component1: C1?

    public init(
        name: String, hint: String = "",
        hub: MessageHubProtocol, dispatcher: Dispatcher,
        factory1: @escaping () -> C1
    ) {
        self.factory1 = factory1
        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)
    }

    open override var type: ViewModelType { .aggregate }

    open override func _onConstruct() throws {
        try aggregateParent.withTransaction {
        try super._onConstruct()
        let c1 = factory1()
        let previous: [ComponentVMBase?] = [component1]
        guard try replaceAggregateSlots(parent: aggregateParent, previous: previous, next: [c1], assign: {
            component1 = c1
        }) else { return }
        _notifyPropertyChanged("component1")
        // Background components defer Constructed until each is (spec/02 §6).
        try _transitionContainerChildren([c1] as [ComponentVMBase], construct: true)
        }
    }

    open override func _onDestruct() throws {
        let components = childComponents
        try _transitionContainerChildren(components, construct: false) {
            try super._onDestruct()
        }
    }

    open override func dispose() {
        // LIFE-013 at the base's admitted-hook boundary (LIFE-015): a foreign
        // disposal disposes no slot while this aggregate's hook runs. The
        // slots are read when the cascade starts, so the snapshot waits for an
        // active slot replacement (spec/08 §4). A re-entrant or concurrent
        // dispose returns at once (spec/02 §7.1).
        _disposeWithChildren(snapshot: { [unowned self] in
            aggregateParent.slotSnapshot()
        })
    }

    public static func builder() -> AggregateVM1Builder<C1> {
        AggregateVM1Builder<C1>()
    }
}
