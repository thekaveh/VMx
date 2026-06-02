//
// ComponentVM — non-modeled leaf viewmodel.
//
// See spec/05-component-vm.md §Variants.
//
import Foundation

open class ComponentVM: ComponentVMBase {
    open override var type: ViewModelType { .component }

    /// Entrypoint for the immutable builder. Matches the TS `.builder()`
    /// static.
    public static func builder() -> ComponentVMBuilder {
        ComponentVMBuilder()
    }
}
