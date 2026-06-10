//
// AggregateVM1<C1> — arity-1 aggregate viewmodel.
//
// See spec/08-aggregate-vm.md and ADR-0007.
//
import Foundation

open class AggregateVM1<C1: ComponentVMBase>: ComponentVMBase {
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

    open override func _onConstruct() {
        component1?.dispose()
        let c1 = factory1()
        component1 = c1
        hub.send(PropertyChangedMessage(
            sender: self, senderName: name, propertyName: "component1"
        ))
        _raisePropertyChanged("component1")
        c1.construct()
    }

    open override func _onDestruct() {
        component1?.destruct()
    }

    open override func dispose() {
        component1?.dispose()
        super.dispose()
    }

    public static func builder() -> AggregateVM1Builder<C1> {
        AggregateVM1Builder<C1>()
    }
}
