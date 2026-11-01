//
// AggregateVM6<C1..C6> — arity-6 aggregate viewmodel.
//
// See spec/08-aggregate-vm.md (AGG-006 added in spec v2.2).
//
import Foundation

open class AggregateVM6<
    C1: ComponentVMBase, C2: ComponentVMBase,
    C3: ComponentVMBase, C4: ComponentVMBase,
    C5: ComponentVMBase, C6: ComponentVMBase
>: ComponentVMBase {
    private lazy var aggregateParent = AggregateParent(owner: self) { [unowned self] in
        self.childComponents
    }
    private let factory1: () -> C1
    private let factory2: () -> C2
    private let factory3: () -> C3
    private let factory4: () -> C4
    private let factory5: () -> C5
    private let factory6: () -> C6
    public private(set) var component1: C1?
    public private(set) var component2: C2?
    public private(set) var component3: C3?
    public private(set) var component4: C4?
    public private(set) var component5: C5?
    public private(set) var component6: C6?

    public init(
        name: String, hint: String = "",
        hub: MessageHubProtocol, dispatcher: Dispatcher,
        factory1: @escaping () -> C1,
        factory2: @escaping () -> C2,
        factory3: @escaping () -> C3,
        factory4: @escaping () -> C4,
        factory5: @escaping () -> C5,
        factory6: @escaping () -> C6
    ) {
        self.factory1 = factory1; self.factory2 = factory2
        self.factory3 = factory3; self.factory4 = factory4
        self.factory5 = factory5; self.factory6 = factory6
        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)
    }

    open override var type: ViewModelType { .aggregate }

    open override func _onConstruct() throws {
        try aggregateParent.withTransaction {
        try super._onConstruct()
        let c1 = factory1(); let c2 = factory2(); let c3 = factory3()
        let c4 = factory4(); let c5 = factory5(); let c6 = factory6()
        let previous: [ComponentVMBase?] = [
            component1, component2, component3, component4, component5, component6
        ]
        guard try replaceAggregateSlots(
            parent: aggregateParent, previous: previous,
            next: [c1, c2, c3, c4, c5, c6], assign: {
            component1 = c1; component2 = c2; component3 = c3
            component4 = c4; component5 = c5; component6 = c6
        }) else { return }
        _notifyPropertyChanged("component1")
        _notifyPropertyChanged("component2")
        _notifyPropertyChanged("component3")
        _notifyPropertyChanged("component4")
        _notifyPropertyChanged("component5")
        _notifyPropertyChanged("component6")

        // Background components defer Constructed until each is (spec/02 §6).
        try _transitionContainerChildren([c1, c2, c3, c4, c5, c6] as [ComponentVMBase], construct: true)
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

    public static func builder() -> AggregateVM6Builder<C1, C2, C3, C4, C5, C6> {
        AggregateVM6Builder<C1, C2, C3, C4, C5, C6>()
    }
}
