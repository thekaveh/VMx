//
// AggregateVM1Builder<C1> — immutable fluent builder for `AggregateVM1`.
//
// See spec/10-builders.md.
//
import Foundation

public struct AggregateVM1Builder<C1: ComponentVMBase> {
    private var _name: String?
    private var _hint: String = ""
    private var _hub: MessageHubProtocol?
    private var _dispatcher: Dispatcher?
    private var _factory1: (() -> C1)?

    public init() {}

    public func name(_ v: String) -> Self { var c = self; c._name = v; return c }
    public func hint(_ v: String) -> Self { var c = self; c._hint = v; return c }
    public func services(hub: MessageHubProtocol, dispatcher: Dispatcher) -> Self {
        var c = self; c._hub = hub; c._dispatcher = dispatcher; return c
    }
    public func component1(_ f: @escaping () -> C1) -> Self {
        var c = self; c._factory1 = f; return c
    }
    public func withNullServices() -> Self {
        services(hub: NullMessageHub.INSTANCE, dispatcher: NullDispatcher.INSTANCE)
    }

    public func build() throws -> AggregateVM1<C1> {
        guard let name = _name else { throw BuilderValidationError(missingField: "name") }
        guard let hub = _hub, let dispatcher = _dispatcher
            else { throw BuilderValidationError(missingField: "services") }
        guard let f1 = _factory1 else { throw BuilderValidationError(missingField: "component1") }
        return AggregateVM1<C1>(
            name: name, hint: _hint,
            hub: hub, dispatcher: dispatcher,
            factory1: f1
        )
    }
}
