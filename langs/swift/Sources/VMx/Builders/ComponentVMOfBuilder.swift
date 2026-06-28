//
// ComponentVMOfBuilder<Model> — immutable fluent builder for
// `ComponentVMOf<Model>`.
//
// See spec/10-builders.md.
//
import Foundation

public struct ComponentVMOfBuilder<Model> {
    private var _name: String?
    private var _hint: String = ""
    // Wrap the model in a one-shot optional so we can detect "not set"
    // without needing a `Hashable` constraint and without using a
    // sentinel singleton.
    private var _model: ModelBox?
    private var _hub: MessageHubProtocol?
    private var _dispatcher: Dispatcher?
    private var _modeledHinter: ((Model) -> String)?
    private var _modelEquals: ((Model, Model) -> Bool)?
    private var _onModelChanged: ((Model) -> Void)?
    private var _onConstruct: (() -> Void)?
    private var _onDestruct: (() -> Void)?
    private var _background: Bool = false

    /// One-shot box used to distinguish "model was assigned (possibly nil
    /// generic)" from "model was never assigned" without resorting to a
    /// `Hashable`/sentinel hack.
    private struct ModelBox { let value: Model }

    public init() {}

    public func name(_ value: String) -> ComponentVMOfBuilder<Model> {
        var copy = self; copy._name = value; return copy
    }

    public func hint(_ value: String) -> ComponentVMOfBuilder<Model> {
        var copy = self; copy._hint = value; return copy
    }

    public func model(_ value: Model) -> ComponentVMOfBuilder<Model> {
        var copy = self; copy._model = ModelBox(value: value); return copy
    }

    public func services(
        hub: MessageHubProtocol, dispatcher: Dispatcher
    ) -> ComponentVMOfBuilder<Model> {
        var copy = self; copy._hub = hub; copy._dispatcher = dispatcher; return copy
    }

    public func modeledHinter(
        _ fn: @escaping (Model) -> String
    ) -> ComponentVMOfBuilder<Model> {
        var copy = self; copy._modeledHinter = fn; return copy
    }

    public func modelEquals(
        _ fn: @escaping (Model, Model) -> Bool
    ) -> ComponentVMOfBuilder<Model> {
        var copy = self; copy._modelEquals = fn; return copy
    }

    public func onModelChanged(
        _ cb: @escaping (Model) -> Void
    ) -> ComponentVMOfBuilder<Model> {
        var copy = self; copy._onModelChanged = cb; return copy
    }

    public func onConstruct(
        _ cb: @escaping () -> Void
    ) -> ComponentVMOfBuilder<Model> {
        var copy = self; copy._onConstruct = cb; return copy
    }

    public func onDestruct(
        _ cb: @escaping () -> Void
    ) -> ComponentVMOfBuilder<Model> {
        var copy = self; copy._onDestruct = cb; return copy
    }

    public func background(_ value: Bool) -> ComponentVMOfBuilder<Model> {
        var copy = self; copy._background = value; return copy
    }

    public func withNullServices() -> ComponentVMOfBuilder<Model> {
        services(hub: NullMessageHub.INSTANCE, dispatcher: NullDispatcher.INSTANCE)
    }

    public func build() throws -> ComponentVMOf<Model> {
        try _buildCore()
    }

    fileprivate func _buildCore() throws -> ComponentVMOf<Model> {
        guard let name = _name else {
            throw BuilderValidationError(missingField: "name")
        }
        guard let box = _model else {
            throw BuilderValidationError(missingField: "model")
        }
        guard let hub = _hub, let dispatcher = _dispatcher else {
            throw BuilderValidationError(missingField: "services")
        }
        let hinter = _modeledHinter ?? { _ in "" }
        // Non-Equatable models default to reference-identity suppression for
        // *class* models (and "always changed" for non-Equatable value models)
        // via `_defaultModelEquals`; Equatable models get `==` via the
        // constrained `build()` overload below.
        let equals = _modelEquals ?? { _defaultModelEquals($0, $1) }
        return ComponentVMOf<Model>(
            name: name,
            hint: _hint,
            initialModel: box.value,
            modeledHinter: hinter,
            modelEquals: equals,
            onModelChanged: _onModelChanged,
            hub: hub,
            dispatcher: dispatcher,
            onConstruct: _onConstruct,
            onDestruct: _onDestruct,
            background: _background
        )
    }
}

extension ComponentVMOfBuilder where Model: Equatable {
    /// Equatable-aware `build()` — defaults `modelEquals` to `==` so
    /// builder callers don't need to pass an explicit predicate. An
    /// explicit `.modelEquals(_:)` still overrides. Constraint-overloaded
    /// on the builder (not a static `builder()` variant) so call-site
    /// resolution stays unambiguous.
    public func build() throws -> ComponentVMOf<Model> {
        if _modelEquals == nil {
            return try modelEquals(==)._buildCore()
        }
        return try _buildCore()
    }
}
