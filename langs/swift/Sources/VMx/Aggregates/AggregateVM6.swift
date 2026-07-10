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
        try super._onConstruct()
        component1?.dispose(); component2?.dispose()
        component3?.dispose(); component4?.dispose()
        component5?.dispose(); component6?.dispose()

        let c1 = factory1(); component1 = c1
        _notifyPropertyChanged("component1")
        let c2 = factory2(); component2 = c2
        _notifyPropertyChanged("component2")
        let c3 = factory3(); component3 = c3
        _notifyPropertyChanged("component3")
        let c4 = factory4(); component4 = c4
        _notifyPropertyChanged("component4")
        let c5 = factory5(); component5 = c5
        _notifyPropertyChanged("component5")
        let c6 = factory6(); component6 = c6
        _notifyPropertyChanged("component6")

        try c1.construct(); try c2.construct(); try c3.construct()
        try c4.construct(); try c5.construct(); try c6.construct()
    }

    open override func _onDestruct() throws {
        try component1?.destruct(); try component2?.destruct()
        try component3?.destruct(); try component4?.destruct()
        try component5?.destruct(); try component6?.destruct()
        try super._onDestruct()
    }

    open override func dispose() {
        component1?.dispose(); component2?.dispose()
        component3?.dispose(); component4?.dispose()
        component5?.dispose(); component6?.dispose()
        super.dispose()
    }

    public static func builder() -> AggregateVM6Builder<C1, C2, C3, C4, C5, C6> {
        AggregateVM6Builder<C1, C2, C3, C4, C5, C6>()
    }
}
