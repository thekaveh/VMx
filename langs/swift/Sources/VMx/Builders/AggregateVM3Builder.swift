//
// AggregateVM3Builder<C1, C2, C3> — immutable fluent builder.
//
import Foundation

public struct AggregateVM3Builder<
    C1: ComponentVMBase, C2: ComponentVMBase, C3: ComponentVMBase
> {
    private var _name: String?
    private var _hint: String = ""
    private var _hub: MessageHubProtocol?
    private var _dispatcher: Dispatcher?
    private var _factory1: (() -> C1)?
    private var _factory2: (() -> C2)?
    private var _factory3: (() -> C3)?

    public init() {}

    public func name(_ v: String) -> Self { var c = self; c._name = v; return c }
    public func hint(_ v: String) -> Self { var c = self; c._hint = v; return c }
    public func services(hub: MessageHubProtocol, dispatcher: Dispatcher) -> Self {
        var c = self; c._hub = hub; c._dispatcher = dispatcher; return c
    }
    public func component1(_ f: @escaping () -> C1) -> Self { var c = self; c._factory1 = f; return c }
    public func component2(_ f: @escaping () -> C2) -> Self { var c = self; c._factory2 = f; return c }
    public func component3(_ f: @escaping () -> C3) -> Self { var c = self; c._factory3 = f; return c }
    public func withNullServices() -> Self {
        services(hub: NullMessageHub.INSTANCE, dispatcher: NullDispatcher.INSTANCE)
    }

    public func build() throws -> AggregateVM3<C1, C2, C3> {
        guard let name = _name else { throw BuilderValidationError(missingField: "name") }
        guard let hub = _hub, let dispatcher = _dispatcher
            else { throw BuilderValidationError(missingField: "services") }
        guard let f1 = _factory1 else { throw BuilderValidationError(missingField: "component1") }
        guard let f2 = _factory2 else { throw BuilderValidationError(missingField: "component2") }
        guard let f3 = _factory3 else { throw BuilderValidationError(missingField: "component3") }
        return AggregateVM3<C1, C2, C3>(
            name: name, hint: _hint,
            hub: hub, dispatcher: dispatcher,
            factory1: f1, factory2: f2, factory3: f3
        )
    }
}
