//
// AggregateVM2<C1, C2> — arity-2 aggregate viewmodel.
//
// See spec/08-aggregate-vm.md.
//
import Foundation

open class AggregateVM2<C1: ComponentVMBase, C2: ComponentVMBase>: ComponentVMBase {
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
        component1?.dispose()
        component2?.dispose()

        let c1 = factory1(); component1 = c1
        hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: "component1"))
        _raisePropertyChanged("component1")

        let c2 = factory2(); component2 = c2
        hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: "component2"))
        _raisePropertyChanged("component2")

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
