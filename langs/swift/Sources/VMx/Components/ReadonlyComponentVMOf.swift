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

    /// Builder producing a *readonly* VM. Shadows the inherited
    /// `ComponentVMOf.builder()`, which would otherwise build a writable
    /// `ComponentVMOf` even when invoked as `ReadonlyComponentVMOf.builder()`.
    public static func builder() -> ReadonlyComponentVMOfBuilder<Model> {
        ReadonlyComponentVMOfBuilder<Model>()
    }
}

extension ReadonlyComponentVMOf where Model: Equatable {
    /// Equatable-aware builder convenience — pre-seeds `modelEquals` with `==`.
    public static func builder() -> ReadonlyComponentVMOfBuilder<Model> {
        ReadonlyComponentVMOfBuilder<Model>().modelEquals(==)
    }
}
