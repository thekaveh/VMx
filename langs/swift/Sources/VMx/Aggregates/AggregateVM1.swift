//
// AggregateVM1<C1> — arity-1 aggregate viewmodel.
//
// See spec/08-aggregate-vm.md and ADR-0007.
//
import Foundation

open class AggregateVM1<C1: ComponentVMBase>: ComponentVMBase {
    private lazy var aggregateParent = AggregateParent(owner: self) { [unowned self] in
        [self.component1 as ComponentVMBase?].compactMap { $0 }
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
        try super._onConstruct()
        let c1 = factory1()
        try validateAggregateSlots(parent: aggregateParent, children: [c1])
        let previous: [ComponentVMBase?] = [component1]
        component1?.dispose()
        component1 = c1
        commitAggregateSlots(parent: aggregateParent, previous: previous, next: [c1])
        _notifyPropertyChanged("component1")
        try c1.construct()
    }

    open override func _onDestruct() throws {
        try component1?.destruct()
        try super._onDestruct()
    }

    open override func dispose() {
        component1?.dispose()
        super.dispose()
    }

    public static func builder() -> AggregateVM1Builder<C1> {
        AggregateVM1Builder<C1>()
    }
}
