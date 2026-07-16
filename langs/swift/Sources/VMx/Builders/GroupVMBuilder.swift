//
// GroupVMBuilder<Child> — immutable fluent builder for `GroupVM`.
//
// See spec/10-builders.md.
//
import Foundation

public struct GroupVMBuilder<Child: ComponentVMBase> {
    private var _name: String?
    private var _hint: String = ""
    private var _hub: MessageHubProtocol?
    private var _dispatcher: Dispatcher?
    private var _children: (() -> [Child])?
    private var _onConstruct: (() -> Void)?
    private var _onDestruct: (() -> Void)?
    private var _autoConstructOnAdd: Bool = false

    public init() {}

    public func name(_ value: String) -> GroupVMBuilder<Child> {
        var c = self; c._name = value; return c
    }
    public func hint(_ value: String) -> GroupVMBuilder<Child> {
        var c = self; c._hint = value; return c
    }
    public func services(
        hub: MessageHubProtocol, dispatcher: Dispatcher
    ) -> GroupVMBuilder<Child> {
        var c = self; c._hub = hub; c._dispatcher = dispatcher; return c
    }
    func _optionHub(_ hub: MessageHubProtocol) -> GroupVMBuilder<Child> {
        var c = self; c._hub = hub; return c
    }
    func _optionDispatcher(_ dispatcher: Dispatcher) -> GroupVMBuilder<Child> {
        var c = self; c._dispatcher = dispatcher; return c
    }
    public func children(
        _ factory: @escaping () -> [Child]
    ) -> GroupVMBuilder<Child> {
        var c = self; c._children = factory; return c
    }
    public func onConstruct(
        _ cb: @escaping () -> Void
    ) -> GroupVMBuilder<Child> {
        var c = self; c._onConstruct = cb; return c
    }
    public func onDestruct(
        _ cb: @escaping () -> Void
    ) -> GroupVMBuilder<Child> {
        var c = self; c._onDestruct = cb; return c
    }
    /// When `true`, any child passed to `add(_:)` on an already-Constructed
    /// group is constructed immediately before the `CollectionChanged(.add)`
    /// event fires (GRP-005).
    public func autoConstructOnAdd(_ enabled: Bool = true) -> GroupVMBuilder<Child> {
        var c = self; c._autoConstructOnAdd = enabled; return c
    }
    public func withNullServices() -> GroupVMBuilder<Child> {
        services(hub: NullMessageHub.INSTANCE, dispatcher: NullDispatcher.INSTANCE)
    }

    public func build() throws -> GroupVM<Child> {
        guard let name = _name else {
            throw BuilderValidationError(missingField: "name")
        }
        guard let hub = _hub, let dispatcher = _dispatcher else {
            throw BuilderValidationError(missingField: "services")
        }
        guard let factory = _children else {
            throw BuilderValidationError(missingField: "children")
        }
        return GroupVM<Child>(
            name: name, hint: _hint,
            hub: hub, dispatcher: dispatcher,
            childrenFactory: factory,
            onConstruct: _onConstruct, onDestruct: _onDestruct,
            autoConstructOnAdd: _autoConstructOnAdd
        )
    }
}
