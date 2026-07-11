//
// ForwardingComponentVM<Model> — transparent forwarding decorator for
// `ComponentVMOf<Model>`.
//
// Every overridable member delegates to the wrapped instance by default
// (spec/09-forwarding.md §1). Subclasses override an individual member; the
// rest keep delegating. Mirrors `forwardingComponentVM.ts`.
//
// Swift port notes (verified against the source — see the Task-10 divergence
// ADR):
// - `name`/`hint` are `public let` on `ComponentVMBase` (stored constants),
//   so they are NOT overridable. They are immutable on both the decorator and
//   the wrapped instance, so they never diverge: the wrapped's values are
//   copied into `super.init` and stay correct for the decorator's lifetime.
// - FWD-002 overrides `modeledHint` (an overridable computed member); TS
//   overrides `hint`, but Swift `hint` is a non-overridable `let`, so
//   `modeledHint` is the closest overridable analog.
//
// See spec/09-forwarding.md.
//
import Foundation
import Combine

open class ForwardingComponentVM<Model>: ComponentVMOf<Model> {
    /// The decorated instance. `public` so subclasses (and instrumentation) can
    /// reach the wrapped VM directly.
    public let _wrapped: ComponentVMOf<Model>

    public init(_ wrapped: ComponentVMOf<Model>) {
        self._wrapped = wrapped
        // `name`/`hint` are immutable `let`s — copy the wrapped's values so the
        // (non-overridable) inherited getters return the wrapped's identity.
        // Every mutable/computed member below is overridden to delegate, so the
        // decorator's own model/hub state is never observed.
        super.init(
            name: wrapped.name,
            hint: wrapped.hint,
            initialModel: wrapped.model,
            hub: wrapped.hub,
            dispatcher: wrapped.dispatcher
        )
    }

    // ── Identity / kind ─────────────────────────────────────────────────
    open override var type: ViewModelType { _wrapped.type }

    // ── State ───────────────────────────────────────────────────────────
    open override var status: ConstructionStatus { _wrapped.status }
    open override var isConstructed: Bool { _wrapped.isConstructed }
    open override var isCurrent: Bool { _wrapped.isCurrent }
    open override var propertyChanged: AnyPublisher<String, Never> {
        _wrapped.propertyChanged
    }

    // ── Model ───────────────────────────────────────────────────────────
    open override var model: Model {
        get { _wrapped.model }
        set { _wrapped.model = newValue }
    }
    open override var modeledHint: String { _wrapped.modeledHint }

    // ── Built-in commands (override the getters to delegate) ────────────
    open override var selectCommand: RelayCommand { _wrapped.selectCommand }
    open override var deselectCommand: RelayCommand { _wrapped.deselectCommand }
    open override var selectNextCommand: RelayCommand { _wrapped.selectNextCommand }
    open override var selectPreviousCommand: RelayCommand { _wrapped.selectPreviousCommand }
    open override var reconstructCommand: RelayCommand { _wrapped.reconstructCommand }

    // ── Lifecycle ───────────────────────────────────────────────────────
    open override func canConstruct() -> Bool { _wrapped.canConstruct() }
    open override func construct() throws { try _wrapped.construct() }
    open override func canDestruct() -> Bool { _wrapped.canDestruct() }
    open override func destruct() throws { try _wrapped.destruct() }
    open override func canReconstruct() -> Bool { _wrapped.canReconstruct() }
    open override func reconstruct() throws { try _wrapped.reconstruct() }
    open override func own(_ cleanup: @escaping () throws -> Void) { _wrapped.own(cleanup) }
    open override func own(_ cancellable: any Cancellable) { _wrapped.own(cancellable) }
    open override func dispose() { _wrapped.dispose() }

    // ── Selection ───────────────────────────────────────────────────────
    open override func canSelect() -> Bool { _wrapped.canSelect() }
    open override func select() { _wrapped.select() }
    open override func canDeselect() -> Bool { _wrapped.canDeselect() }
    open override func deselect() { _wrapped.deselect() }
}
