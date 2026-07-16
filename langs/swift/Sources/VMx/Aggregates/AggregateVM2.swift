//
// AggregateVM2<C1, C2> — arity-2 aggregate viewmodel.
//
// See spec/08-aggregate-vm.md.
//
import Foundation

open class AggregateVM2<C1: ComponentVMBase, C2: ComponentVMBase>: ComponentVMBase {
    private lazy var aggregateParent = AggregateParent(owner: self) { [unowned self] in
        [
            self.component1 as ComponentVMBase?,
            self.component2 as ComponentVMBase?
        ].compactMap { $0 }
    }
    private let factory1: () -> C1
    private let factory2: () -> C2
    public private(set) var component1: C1?
    public private(set) var component2: C2?

    public init(
        name: String, hint: String = "",
        hub: MessageHubProtocol, dispatcher: Dispatcher,
        factory1: @escaping () -> C1,
        factory2: @escaping () -> C2
    ) {
        self.factory1 = factory1
        self.factory2 = factory2
        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)
    }

    open override var type: ViewModelType { .aggregate }

    open override func _onConstruct() throws {
        try super._onConstruct()
        let c1 = factory1()
        let c2 = factory2()
        try validateAggregateSlots(parent: aggregateParent, children: [c1, c2])
        let previous: [ComponentVMBase?] = [component1, component2]
        component1?.dispose()
        component2?.dispose()

        component1 = c1
        _notifyPropertyChanged("component1")

        component2 = c2
        commitAggregateSlots(parent: aggregateParent, previous: previous, next: [c1, c2])
        _notifyPropertyChanged("component2")

        try c1.construct(); try c2.construct()
    }

    open override func _onDestruct() throws {
        try component1?.destruct(); try component2?.destruct()
        try super._onDestruct()
    }

    open override func dispose() {
        component1?.dispose(); component2?.dispose()
        super.dispose()
    }

    public static func builder() -> AggregateVM2Builder<C1, C2> {
        AggregateVM2Builder<C1, C2>()
    }
}
