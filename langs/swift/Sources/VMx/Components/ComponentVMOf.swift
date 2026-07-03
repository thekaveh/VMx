//
// ComponentVMOf<Model> — modeled leaf viewmodel with a settable model.
//
// Mirrors C#'s `ComponentVM<M>` and TS / Python `ComponentVMOf<M>`.
//
// See spec/05-component-vm.md §Modeled variant.
//
import Foundation

/// Default `modelEquals` predicate for **non-`Equatable`** models.
///
/// HUB-005 requires that setting `model` to a value equal to the current one
/// publishes nothing. `Equatable` models get structural `==` (via the
/// constrained `init` / `build()` overloads). A non-`Equatable` model can't be
/// compared structurally, but if it is a **reference type (class)** we can
/// still suppress the redundant publish when the new model is the *same
/// instance* — matching the reference-identity suppression the C# / Python / TS
/// flavors apply. Non-`Equatable` **value** models (a `struct`/`enum` without
/// an `Equatable` conformance) fall through to "changed" so every set still
/// publishes — pass an explicit `.modelEquals(_:)` for structural suppression.
///
/// `@usableFromInline` so the public `ComponentVMOf.init` can name it as a
/// default-argument value (default args are emitted into the caller's module).
@usableFromInline
func _defaultModelEquals<Model>(_ lhs: Model, _ rhs: Model) -> Bool {
    // Only apply reference identity for actual class instances. A value type
    // would bridge to a freshly-boxed `AnyObject` here (or, for `Int` & friends,
    // to a tagged `NSNumber`), so gating on `is AnyClass` keeps value-model
    // behaviour unchanged — they report "not equal" and publish as before.
    guard type(of: lhs) is AnyClass else { return false }
    return (lhs as AnyObject) === (rhs as AnyObject)
}

public struct ComponentVMOfOptions<Model> {
    public var name: String?
    public var hint: String
    public var model: Model
    public var hub: MessageHubProtocol?
    public var dispatcher: Dispatcher?
    public var modeledHinter: ((Model) -> String)?
    public var modelEquals: ((Model, Model) -> Bool)?
    public var onModelChanged: ((Model) -> Void)?
    public var onConstruct: (() -> Void)?
    public var onDestruct: (() -> Void)?
    public var background: Bool

    public init(
        name: String? = nil,
        hint: String = "",
        model: Model,
        hub: MessageHubProtocol? = nil,
        dispatcher: Dispatcher? = nil,
        modeledHinter: ((Model) -> String)? = nil,
        modelEquals: ((Model, Model) -> Bool)? = nil,
        onModelChanged: ((Model) -> Void)? = nil,
        onConstruct: (() -> Void)? = nil,
        onDestruct: (() -> Void)? = nil,
        background: Bool = false
    ) {
        self.name = name
        self.hint = hint
        self.model = model
        self.hub = hub
        self.dispatcher = dispatcher
        self.modeledHinter = modeledHinter
        self.modelEquals = modelEquals
        self.onModelChanged = onModelChanged
        self.onConstruct = onConstruct
        self.onDestruct = onDestruct
        self.background = background
    }
}

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
        modelEquals: @escaping (Model, Model) -> Bool = { _defaultModelEquals($0, $1) },
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
        // Inert-disposed-VM principle extended to the model setter: a disposed VM
        // publishes nothing further. NOTE spec/02 invariant 3 specifies this only
        // for `IsCurrent` selection, not `model`, so model-set-after-dispose is
        // UNSPECIFIED and divergent cross-flavor — C#/Python/TS publish here
        // (ADR-0009). The model *field* is still updated above (so the getter
        // reflects the latest value — parity with C#, whose field write is
        // unconditional); only the hub send / raise / hint / callback is gated.
        guard status != .disposed else { return }

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

    public static func create(_ options: ComponentVMOfOptions<Model>) throws -> ComponentVMOf<Model> {
        var b = ComponentVMOf<Model>.builder()
            .hint(options.hint)
            .model(options.model)
            .background(options.background)
        if let name = options.name { b = b.name(name) }
        if let hub = options.hub, let dispatcher = options.dispatcher {
            b = b.services(hub: hub, dispatcher: dispatcher)
        }
        if let modeledHinter = options.modeledHinter { b = b.modeledHinter(modeledHinter) }
        if let modelEquals = options.modelEquals { b = b.modelEquals(modelEquals) }
        if let onModelChanged = options.onModelChanged { b = b.onModelChanged(onModelChanged) }
        if let onConstruct = options.onConstruct { b = b.onConstruct(onConstruct) }
        if let onDestruct = options.onDestruct { b = b.onDestruct(onDestruct) }
        return try b.build()
    }
}

// ─── Equatable convenience overload ──────────────────────────────────────
//
// When the model conforms to `Equatable`, `ComponentVMOf<M>.builder()`
// callers don't need to pass an explicit `.modelEquals(...)` predicate —
// the builder defaults to `==`. See `ComponentVMOfBuilder` for details.

extension ComponentVMOf where Model: Equatable {
    public static func create(_ options: ComponentVMOfOptions<Model>) throws -> ComponentVMOf<Model> {
        var b = ComponentVMOf<Model>.builder()
            .hint(options.hint)
            .model(options.model)
            .background(options.background)
        if let name = options.name { b = b.name(name) }
        if let hub = options.hub, let dispatcher = options.dispatcher {
            b = b.services(hub: hub, dispatcher: dispatcher)
        }
        if let modeledHinter = options.modeledHinter { b = b.modeledHinter(modeledHinter) }
        if let modelEquals = options.modelEquals { b = b.modelEquals(modelEquals) }
        if let onModelChanged = options.onModelChanged { b = b.onModelChanged(onModelChanged) }
        if let onConstruct = options.onConstruct { b = b.onConstruct(onConstruct) }
        if let onDestruct = options.onDestruct { b = b.onDestruct(onDestruct) }
        return try b.build()
    }

    /// Equatable-aware initializer convenience — defaults `modelEquals`
    /// to `==`. (The builder path gets the same default via the
    /// constraint-overloaded `ComponentVMOfBuilder.build()` — a static
    /// `builder()` overload here made annotation-free call sites
    /// ambiguous, which CI caught.)
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
