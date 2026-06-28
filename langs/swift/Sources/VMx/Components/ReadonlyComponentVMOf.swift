//
// ReadonlyComponentVMOf<Model> — modeled leaf with externally read-only
// model. The model can still mutate via internal channels but the public
// surface exposes a getter only.
//
// See spec/05-component-vm.md §Read-only modeled variant.
//
import Foundation

open class ReadonlyComponentVMOf<Model>: ComponentVMOf<Model> {
    open override var type: ViewModelType { .readOnlyComponent }

    /// Public read-only override. The protected setter from the parent
    /// remains accessible through `_setModel(_:)` for module-internal
    /// callers that legitimately need to update the model (e.g. a
    /// service-backed refresh).
    ///
    /// External writes via `vm.model = newValue` fail fast with
    /// `preconditionFailure` rather than silently no-op'ing. Swift cannot
    /// narrow a parent `var` setter to unavailable, so the setter remains
    /// visible — but invoking it is a programmer error per the read-only
    /// contract.
    public override var model: Model {
        get { super.model }
        set {
            _ = newValue
            preconditionFailure(
                "ReadonlyComponentVMOf.model is read-only — use the internal "
                + "_setModel(_:) for service-backed updates."
            )
        }
    }

    /// Builder entry point for the **read-only** modeled component.
    ///
    /// ⚠️ Do **not** call the inherited `ReadonlyComponentVMOf.builder()`: a
    /// same-named static override that returns `ReadonlyComponentVMOfBuilder`
    /// is inexpressible in Swift (a different-return shadow makes every
    /// annotation-free call ambiguous against the inherited
    /// `ComponentVMOf.builder()` — there is no derived-type preference for
    /// static members — and a same-signature redeclaration, even
    /// `@available(*, unavailable)`, is rejected as an illegal static
    /// override). The inherited `builder()` therefore still resolves here and
    /// produces a **WRITABLE** `ComponentVMOf<Model>`. It is statically typed
    /// as such (so it cannot masquerade as read-only), but it is the wrong
    /// entry point.
    ///
    /// Use this `readonlyBuilder()` (or `ReadonlyComponentVMOfBuilder<Model>()`
    /// directly) to obtain a builder that produces a read-only VM.
    public static func readonlyBuilder() -> ReadonlyComponentVMOfBuilder<Model> {
        ReadonlyComponentVMOfBuilder<Model>()
    }
}
