//
// ComponentVMBuilder — immutable fluent builder for `ComponentVM`.
//
// See spec/10-builders.md.
//
import Foundation

public struct ComponentVMBuilder {
    private var _name: String?
    private var _hint: String = ""
    private var _hub: MessageHubProtocol?
    private var _dispatcher: Dispatcher?
    private var _onConstruct: (() -> Void)?
    private var _onDestruct: (() -> Void)?
    private var _background: Bool = false

    public init() {}

    public func name(_ value: String) -> ComponentVMBuilder {
        var copy = self
        copy._name = value
        return copy
    }

    public func hint(_ value: String) -> ComponentVMBuilder {
        var copy = self
        copy._hint = value
        return copy
    }

    public func services(
        hub: MessageHubProtocol,
        dispatcher: Dispatcher
    ) -> ComponentVMBuilder {
        var copy = self
        copy._hub = hub
        copy._dispatcher = dispatcher
        return copy
    }

    func _optionHub(_ hub: MessageHubProtocol) -> ComponentVMBuilder {
        var copy = self
        copy._hub = hub
        return copy
    }

    func _optionDispatcher(_ dispatcher: Dispatcher) -> ComponentVMBuilder {
        var copy = self
        copy._dispatcher = dispatcher
        return copy
    }

    public func onConstruct(_ cb: @escaping () -> Void) -> ComponentVMBuilder {
        var copy = self
        copy._onConstruct = cb
        return copy
    }

    public func onDestruct(_ cb: @escaping () -> Void) -> ComponentVMBuilder {
        var copy = self
        copy._onDestruct = cb
        return copy
    }

    public func background(_ value: Bool) -> ComponentVMBuilder {
        var copy = self
        copy._background = value
        return copy
    }

    /// Convenience wither wiring `NullMessageHub.INSTANCE` +
    /// `NullDispatcher.INSTANCE`. Mirrors `withNullServices` in TS /
    /// `with_null_services` in Python / `WithNullServices` in C# per
    /// ADR-0035.
    public func withNullServices() -> ComponentVMBuilder {
        services(hub: NullMessageHub.INSTANCE, dispatcher: NullDispatcher.INSTANCE)
    }

    public func build() throws -> ComponentVM {
        guard let name = _name else {
            throw BuilderValidationError(missingField: "name")
        }
        guard let hub = _hub, let dispatcher = _dispatcher else {
            throw BuilderValidationError(missingField: "services")
        }
        return ComponentVM(
            name: name,
            hint: _hint,
            hub: hub,
            dispatcher: dispatcher,
            onConstruct: _onConstruct,
            onDestruct: _onDestruct,
            background: _background
        )
    }
}
