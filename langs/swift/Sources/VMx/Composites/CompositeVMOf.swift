//
// CompositeVMOf<Model, VM> — modeled composite viewmodel.
//
// Children come from a model factory `() -> [Model]` plus a mapper
// `(Model) -> VM`. See spec/06-composite-vm.md §Modeled variant.
//
import Foundation

public final class CompositeVMOf<Model, VM: ComponentVMBase>: CompositeVM<VM> {

    public init(
        name: String,
        hint: String = "",
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        childrenModels: @escaping () -> [Model],
        childModelToChildViewModel: @escaping (Model) -> VM,
        onConstruct: (() -> Void)? = nil,
        onDestruct: (() -> Void)? = nil,
        currentSelector: (([VM]) -> VM?)? = nil,
        onCurrentChanged: ((VM?) -> Void)? = nil,
        autoConstructOnAdd: Bool = false,
        asyncSelection: Bool = false
    ) {
        super.init(
            name: name, hint: hint,
            hub: hub, dispatcher: dispatcher,
            childrenFactory: { childrenModels().map(childModelToChildViewModel) },
            onConstruct: onConstruct, onDestruct: onDestruct,
            currentSelector: currentSelector,
            onCurrentChanged: onCurrentChanged,
            autoConstructOnAdd: autoConstructOnAdd,
            asyncSelection: asyncSelection
        )
    }

    /// Returns a fresh `CompositeVMOfBuilder` for this type pair.
    public static func builder() -> CompositeVMOfBuilder<Model, VM> {
        CompositeVMOfBuilder<Model, VM>()
    }
}
