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

    // The readonly builder entry point is `ReadonlyComponentVMOfBuilder<Model>()`
    // directly. A subclass `builder()` shadow is not expressible: a
    // different-return variant makes every annotation-free call ambiguous
    // against the inherited `ComponentVMOf.builder()` (no derived-type
    // preference for static members), and a same-signature redeclaration —
    // even `@available(*, unavailable)` — is rejected as an illegal static
    // override. Note that the *inherited* `builder()` therefore still
    // resolves here and produces a WRITABLE `ComponentVMOf<Model>`; the
    // result is statically typed as such, so it cannot masquerade as
    // readonly, but prefer the dedicated builder.
}
