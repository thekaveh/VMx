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
    public override var model: Model {
        get { super.model }
        // Swift does not allow narrowing a parent `var` setter to
        // unavailable, so we keep it visible but document the contract.
        set { /* read-only by spec — explicit writes should call _setModel. */ }
    }
}
