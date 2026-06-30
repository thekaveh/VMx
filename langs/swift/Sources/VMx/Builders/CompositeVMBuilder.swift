//
// CompositeVMBuilder<Child> — immutable fluent builder for `CompositeVM`.
//
// See spec/10-builders.md. Validates `name`, `services`, `children` at
// `build()` per BLD-002.
//
import Foundation

public struct CompositeVMBuilder<Child: ComponentVMBase> {
    private var _name: String?
    private var _hint: String = ""
    private var _hub: MessageHubProtocol?
    private var _dispatcher: Dispatcher?
    private var _children: (() -> [Child])?
    private var _onConstruct: (() -> Void)?
    private var _onDestruct: (() -> Void)?
    private var _currentSelector: (([Child]) -> Child?)?
    private var _onCurrentChanged: ((Child?) -> Void)?
    private var _autoConstructOnAdd: Bool = false
    private var _asyncSelection: Bool = false

    public init() {}

    public func name(_ value: String) -> CompositeVMBuilder<Child> {
        var c = self; c._name = value; return c
    }
    public func hint(_ value: String) -> CompositeVMBuilder<Child> {
        var c = self; c._hint = value; return c
    }
    public func services(
        hub: MessageHubProtocol, dispatcher: Dispatcher
    ) -> CompositeVMBuilder<Child> {
        var c = self; c._hub = hub; c._dispatcher = dispatcher; return c
    }
    public func children(
        _ factory: @escaping () -> [Child]
    ) -> CompositeVMBuilder<Child> {
        var c = self; c._children = factory; return c
    }
    public func current(
        _ selector: @escaping ([Child]) -> Child?
    ) -> CompositeVMBuilder<Child> {
        var c = self; c._currentSelector = selector; return c
    }
    public func onCurrentChanged(
        _ cb: @escaping (Child?) -> Void
    ) -> CompositeVMBuilder<Child> {
        var c = self; c._onCurrentChanged = cb; return c
    }
    public func onConstruct(
        _ cb: @escaping () -> Void
    ) -> CompositeVMBuilder<Child> {
        var c = self; c._onConstruct = cb; return c
    }
    public func onDestruct(
        _ cb: @escaping () -> Void
    ) -> CompositeVMBuilder<Child> {
        var c = self; c._onDestruct = cb; return c
    }
    /// When `true`, any child passed to `add(_:)` on an already-Constructed
    /// composite is constructed immediately before the `CollectionChanged(.add)`
    /// event fires (COMP-012).
    public func autoConstructOnAdd(_ enabled: Bool = true) -> CompositeVMBuilder<Child> {
        var c = self; c._autoConstructOnAdd = enabled; return c
    }
    /// When `true`, `selectChild(_:)` / `current =` defer the Current assignment
    /// via the foreground dispatcher rather than applying it synchronously
    /// (COMP-010). A TOCTOU re-check at dispatch time drops the selection if the
    /// child was removed before the foreground scheduler advances.
    public func asyncSelection(_ enabled: Bool = true) -> CompositeVMBuilder<Child> {
        var c = self; c._asyncSelection = enabled; return c
    }
    public func withNullServices() -> CompositeVMBuilder<Child> {
        services(hub: NullMessageHub.INSTANCE, dispatcher: NullDispatcher.INSTANCE)
    }

    public func build() throws -> CompositeVM<Child> {
        guard let name = _name else {
            throw BuilderValidationError(missingField: "name")
        }
        guard let hub = _hub, let dispatcher = _dispatcher else {
            throw BuilderValidationError(missingField: "services")
        }
        guard let factory = _children else {
            throw BuilderValidationError(missingField: "children")
        }
        return CompositeVM<Child>(
            name: name, hint: _hint,
            hub: hub, dispatcher: dispatcher,
            childrenFactory: factory,
            onConstruct: _onConstruct, onDestruct: _onDestruct,
            currentSelector: _currentSelector,
            onCurrentChanged: _onCurrentChanged,
            autoConstructOnAdd: _autoConstructOnAdd,
            asyncSelection: _asyncSelection
        )
    }
}
