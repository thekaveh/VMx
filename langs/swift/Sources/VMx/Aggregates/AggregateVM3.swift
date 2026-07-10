//
// AggregateVM3<C1, C2, C3> — arity-3 aggregate viewmodel.
//
// See spec/08-aggregate-vm.md.
//
import Foundation

open class AggregateVM3<
    C1: ComponentVMBase, C2: ComponentVMBase, C3: ComponentVMBase
>: ComponentVMBase {
    private let factory1: () -> C1
    private let factory2: () -> C2
    private let factory3: () -> C3
    public private(set) var component1: C1?
    public private(set) var component2: C2?
    public private(set) var component3: C3?

    public init(
        name: String, hint: String = "",
        hub: MessageHubProtocol, dispatcher: Dispatcher,
        factory1: @escaping () -> C1,
        factory2: @escaping () -> C2,
        factory3: @escaping () -> C3
    ) {
        self.factory1 = factory1
        self.factory2 = factory2
        self.factory3 = factory3
        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)
    }

    open override var type: ViewModelType { .aggregate }

    open override func _onConstruct() throws {
        try super._onConstruct()
        component1?.dispose(); component2?.dispose(); component3?.dispose()
        let c1 = factory1(); component1 = c1
        _notifyPropertyChanged("component1")
        let c2 = factory2(); component2 = c2
        _notifyPropertyChanged("component2")
        let c3 = factory3(); component3 = c3
        _notifyPropertyChanged("component3")
        try c1.construct(); try c2.construct(); try c3.construct()
    }

    open override func _onDestruct() throws {
        try component1?.destruct(); try component2?.destruct(); try component3?.destruct()
        try super._onDestruct()
    }

    open override func dispose() {
        component1?.dispose(); component2?.dispose(); component3?.dispose()
        super.dispose()
    }

    public static func builder() -> AggregateVM3Builder<C1, C2, C3> {
        AggregateVM3Builder<C1, C2, C3>()
    }
}
