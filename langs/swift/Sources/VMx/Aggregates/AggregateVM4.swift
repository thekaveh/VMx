//
// AggregateVM4<C1..C4> — arity-4 aggregate viewmodel.
//
// See spec/08-aggregate-vm.md.
//
import Foundation

open class AggregateVM4<
    C1: ComponentVMBase, C2: ComponentVMBase,
    C3: ComponentVMBase, C4: ComponentVMBase
>: ComponentVMBase {
    private let factory1: () -> C1
    private let factory2: () -> C2
    private let factory3: () -> C3
    private let factory4: () -> C4
    public private(set) var component1: C1?
    public private(set) var component2: C2?
    public private(set) var component3: C3?
    public private(set) var component4: C4?

    public init(
        name: String, hint: String = "",
        hub: MessageHubProtocol, dispatcher: Dispatcher,
        factory1: @escaping () -> C1,
        factory2: @escaping () -> C2,
        factory3: @escaping () -> C3,
        factory4: @escaping () -> C4
    ) {
        self.factory1 = factory1; self.factory2 = factory2
        self.factory3 = factory3; self.factory4 = factory4
        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)
    }

    open override var type: ViewModelType { .aggregate }

    open override func _onConstruct() throws {
        try super._onConstruct()
        component1?.dispose(); component2?.dispose()
        component3?.dispose(); component4?.dispose()
        let c1 = factory1(); component1 = c1
        _notifyPropertyChanged("component1")
        let c2 = factory2(); component2 = c2
        _notifyPropertyChanged("component2")
        let c3 = factory3(); component3 = c3
        _notifyPropertyChanged("component3")
        let c4 = factory4(); component4 = c4
        _notifyPropertyChanged("component4")
        try c1.construct(); try c2.construct(); try c3.construct(); try c4.construct()
    }

    open override func _onDestruct() throws {
        try component1?.destruct(); try component2?.destruct()
        try component3?.destruct(); try component4?.destruct()
        try super._onDestruct()
    }

    open override func dispose() {
        component1?.dispose(); component2?.dispose()
        component3?.dispose(); component4?.dispose()
        super.dispose()
    }

    public static func builder() -> AggregateVM4Builder<C1, C2, C3, C4> {
        AggregateVM4Builder<C1, C2, C3, C4>()
    }
}
