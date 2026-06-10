//
// ComponentVMOf<Model> — modeled leaf viewmodel with a settable model.
//
// Mirrors C#'s `ComponentVM<M>` and TS / Python `ComponentVMOf<M>`.
//
// See spec/05-component-vm.md §Modeled variant.
//
import Foundation

open class ComponentVMOf<Model>: ComponentVMBase {
    private var _model: Model
    private let modeledHinter: (Model) -> String
    private let onModelChangedCb: ((Model) -> Void)?
    private var _modeledHint: String
    private let modelEquals: (Model, Model) -> Bool

    public init(
        name: String,
        hint: String = "",
        initialModel: Model,
        modeledHinter: @escaping (Model) -> String = { _ in "" },
        modelEquals: @escaping (Model, Model) -> Bool = { _, _ in false },
        onModelChanged: ((Model) -> Void)? = nil,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        onConstruct: (() -> Void)? = nil,
        onDestruct: (() -> Void)? = nil,
        background: Bool = false
    ) {
        self._model = initialModel
        self.modeledHinter = modeledHinter
        self.modelEquals = modelEquals
        self.onModelChangedCb = onModelChanged
        self._modeledHint = modeledHinter(initialModel)
        super.init(
            name: name,
            hint: hint,
            hub: hub,
            dispatcher: dispatcher,
            onConstruct: onConstruct,
            onDestruct: onDestruct,
            background: background
        )
    }

    open override var type: ViewModelType { .component }

    public var model: Model {
        get { _model }
        set { _setModel(newValue) }
    }

    public var modeledHint: String { _modeledHint }

    /// Internal setter so subclasses (e.g. `ReadonlyComponentVMOf`) can
    /// gate writes while still using the same machinery.
    func _setModel(_ value: Model) {
        if modelEquals(_model, value) { return }
        _model = value

        hub.send(PropertyChangedMessage(
            sender: self, senderName: name, propertyName: "model"
        ))
        _raisePropertyChanged("model")

        let newHint = modeledHinter(value)
        if newHint != _modeledHint {
            _modeledHint = newHint
            hub.send(PropertyChangedMessage(
                sender: self, senderName: name, propertyName: "modeledHint"
            ))
            _raisePropertyChanged("modeledHint")
        }

        onModelChangedCb?(value)
    }

    public static func builder() -> ComponentVMOfBuilder<Model> {
        ComponentVMOfBuilder<Model>()
    }
}

// ─── Equatable convenience overload ──────────────────────────────────────
//
// When the model conforms to `Equatable`, `ComponentVMOf<M>.builder()`
// callers don't need to pass an explicit `.modelEquals(...)` predicate —
// the builder defaults to `==`. See `ComponentVMOfBuilder` for details.

extension ComponentVMOf where Model: Equatable {
    /// Equatable-aware builder convenience — pre-seeds `modelEquals` with
    /// `==` so `ComponentVMOf<M>.builder()` callers don't need to pass an
    /// explicit predicate. An explicit `.modelEquals(_:)` still overrides.
    public static func builder() -> ComponentVMOfBuilder<Model> {
        ComponentVMOfBuilder<Model>().modelEquals(==)
    }

    /// Equatable-aware initializer convenience — defaults `modelEquals`
    /// to `==`.
    public convenience init(
        name: String,
        hint: String = "",
        initialModel: Model,
        modeledHinter: @escaping (Model) -> String = { _ in "" },
        onModelChanged: ((Model) -> Void)? = nil,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        onConstruct: (() -> Void)? = nil,
        onDestruct: (() -> Void)? = nil,
        background: Bool = false
    ) {
        self.init(
            name: name,
            hint: hint,
            initialModel: initialModel,
            modeledHinter: modeledHinter,
            modelEquals: ==,
            onModelChanged: onModelChanged,
            hub: hub,
            dispatcher: dispatcher,
            onConstruct: onConstruct,
            onDestruct: onDestruct,
            background: background
        )
    }
}
