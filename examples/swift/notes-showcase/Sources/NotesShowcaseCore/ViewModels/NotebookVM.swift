//
// NotebookVM — leaf view-model for a notebook tree node.
//
// Capabilities (scenario §6.2):
//   `Selectable`, `Deselectable`, `Expandable`, `Collapsible`,
//   `ExpansionTogglable`, `Reconstructable`.
//
// Implemented as a direct `ComponentVMBase` subclass (not `ComponentVM<M>`)
// so the capability mix-ins can be layered without the sealed generic wrapper.
// Cross-module subclassing enabled by ADR-0066: `hub`, `dispatcher`, and
// `_raisePropertyChanged` are `public` on the base class.
//
import Foundation
import Combine
import VMx

/// Leaf view-model for a notebook tree node.
///
/// Mirrors the C# Avalonia `NotebookVM`. Holds a `NotebookModel` (equality-
/// guarded setter), an owner-supplied `childrenGetter`, and delegates
/// expansion state to the library's `ExpandableState` helper.
public final class NotebookVM: ComponentVMBase,
                                Selectable, Deselectable,
                                Expandable, Collapsible, ExpansionTogglable {
    // `Reconstructable` is satisfied automatically via
    // `extension ComponentVMBase: Constructable, Destructable, Reconstructable {}`.

    // ── Private state ──────────────────────────────────────────────────────

    private var _model: NotebookModel
    private let _expansion: ExpandableState
    private var _childrenGetter: ((NotebookVM) -> [NotebookVM])?

    // ── Public properties ──────────────────────────────────────────────────

    /// Current notebook model. Equality-guarded; emits `PropertyChangedMessage`
    /// for `"model"` and `"notebookName"` on change.
    public var model: NotebookModel {
        get { _model }
        set {
            guard _model != newValue else { return }
            _model = newValue
            hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: "model"))
            _raisePropertyChanged("model")
            hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: "notebookName"))
            _raisePropertyChanged("notebookName")
        }
    }

    /// Notebook display name (derived from `model`).
    public var notebookName: String { _model.name }

    /// Child notebook VMs resolved via the owner-supplied getter.
    /// Returns an empty array when no getter has been wired (standalone VMs).
    public var children: [NotebookVM] {
        _childrenGetter.map { $0(self) } ?? []
    }

    // ── Children resolver ──────────────────────────────────────────────────

    /// Late-binds the children resolver (called by `NotebooksRootVM` after
    /// each `populateAsync` / `addNotebookAsync`). Emits a `PropertyChangedMessage`
    /// for `"children"` so already-bound views refresh.
    public func setChildrenGetter(_ getter: ((NotebookVM) -> [NotebookVM])?) {
        _childrenGetter = getter
        hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: "children"))
        _raisePropertyChanged("children")
    }

    /// Re-emits a `"children"` change notification (called by `NotebooksRootVM`
    /// whenever the flat collection mutates so already-bound parents refresh).
    public func notifyChildrenChanged() {
        hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: "children"))
        _raisePropertyChanged("children")
    }

    // ── Selectable / Deselectable (delegated to ComponentVMBase) ──────────
    // ComponentVMBase already provides canSelect/select/canDeselect/deselect;
    // the protocol conformance declarations above satisfy the contracts.

    // ── Expandable ─────────────────────────────────────────────────────────

    public var isExpanded: Bool { _expansion.isExpanded }

    public func canExpand() -> Bool { _expansion.canExpand() }

    public func expand() {
        guard _expansion.canExpand() else { return }
        _expansion.expand()
        _emitExpansionChange()
    }

    // ── Collapsible ────────────────────────────────────────────────────────

    public func canCollapse() -> Bool { _expansion.canCollapse() }

    public func collapse() {
        guard _expansion.canCollapse() else { return }
        _expansion.collapse()
        _emitExpansionChange()
    }

    // ── ExpansionTogglable ─────────────────────────────────────────────────

    public func canToggleExpansion() -> Bool { _expansion.canToggleExpansion() }

    public func toggleExpansion() {
        if _expansion.isExpanded { collapse() } else { expand() }
    }

    private func _emitExpansionChange() {
        hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: "isExpanded"))
        _raisePropertyChanged("isExpanded")
    }

    // ── Init ───────────────────────────────────────────────────────────────

    private init(
        name: String,
        hint: String,
        model: NotebookModel,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        initiallyExpanded: Bool,
        childrenGetter: ((NotebookVM) -> [NotebookVM])?
    ) {
        _model = model
        _expansion = ExpandableState(initiallyExpanded: initiallyExpanded)
        _childrenGetter = childrenGetter
        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)
    }

    // ── Dispose ────────────────────────────────────────────────────────────

    override public func _onDispose() {
        _expansion.dispose()
        super._onDispose()
    }

    // ── Builder ────────────────────────────────────────────────────────────

    /// Returns a new empty builder for `NotebookVM`.
    public static func builder() -> NotebookVMBuilder {
        NotebookVMBuilder()
    }

    /// Immutable fluent builder for `NotebookVM` (spec ch. 10).
    ///
    /// Required fields: `name(_:)`, `model(_:)`, `services(hub:dispatcher:)`.
    /// Optional fields: `initiallyExpanded(_:)` (default `false`), `childrenGetter(_:)`.
    public struct NotebookVMBuilder {
        private var _name: String?
        private var _hint: String = ""
        private var _model: NotebookModel?
        private var _hub: MessageHubProtocol?
        private var _dispatcher: Dispatcher?
        private var _initiallyExpanded: Bool = false
        private var _childrenGetter: ((NotebookVM) -> [NotebookVM])?

        fileprivate init() {}

        /// Sets the required VM name.
        public func name(_ value: String) -> NotebookVMBuilder {
            var copy = self; copy._name = value; return copy
        }

        /// Sets the optional hint.
        public func hint(_ value: String) -> NotebookVMBuilder {
            var copy = self; copy._hint = value; return copy
        }

        /// Sets the required notebook model.
        public func model(_ value: NotebookModel) -> NotebookVMBuilder {
            var copy = self; copy._model = value; return copy
        }

        /// Sets the required services (hub + dispatcher).
        public func services(hub: MessageHubProtocol, dispatcher: Dispatcher) -> NotebookVMBuilder {
            var copy = self
            copy._hub = hub
            copy._dispatcher = dispatcher
            return copy
        }

        /// Sets the optional initial expansion state (default `false`).
        public func initiallyExpanded(_ value: Bool = true) -> NotebookVMBuilder {
            var copy = self; copy._initiallyExpanded = value; return copy
        }

        /// Sets the optional children-getter callback. The owning
        /// `NotebooksRootVM` wires this so each notebook can resolve its
        /// children from the flat collection.
        public func childrenGetter(_ getter: @escaping (NotebookVM) -> [NotebookVM]) -> NotebookVMBuilder {
            var copy = self; copy._childrenGetter = getter; return copy
        }

        /// Validates required fields and constructs a `NotebookVM`.
        ///
        /// - Throws: `BuilderValidationError` if `name`, `model`, or `services` are missing.
        public func build() throws -> NotebookVM {
            guard let name = _name else {
                throw BuilderValidationError(missingField: "name")
            }
            guard let model = _model else {
                throw BuilderValidationError(missingField: "model")
            }
            guard let hub = _hub else {
                throw BuilderValidationError(missingField: "hub")
            }
            guard let dispatcher = _dispatcher else {
                throw BuilderValidationError(missingField: "dispatcher")
            }
            return NotebookVM(
                name: name,
                hint: _hint,
                model: model,
                hub: hub,
                dispatcher: dispatcher,
                initiallyExpanded: _initiallyExpanded,
                childrenGetter: _childrenGetter
            )
        }
    }
}
