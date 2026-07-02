//
// ComponentVM — non-modeled leaf viewmodel.
//
// See spec/05-component-vm.md §Variants.
//
import Foundation

public struct ComponentVMOptions {
    public var name: String?
    public var hint: String
    public var hub: MessageHubProtocol?
    public var dispatcher: Dispatcher?
    public var onConstruct: (() -> Void)?
    public var onDestruct: (() -> Void)?
    public var background: Bool

    public init(
        name: String? = nil,
        hint: String = "",
        hub: MessageHubProtocol? = nil,
        dispatcher: Dispatcher? = nil,
        onConstruct: (() -> Void)? = nil,
        onDestruct: (() -> Void)? = nil,
        background: Bool = false
    ) {
        self.name = name
        self.hint = hint
        self.hub = hub
        self.dispatcher = dispatcher
        self.onConstruct = onConstruct
        self.onDestruct = onDestruct
        self.background = background
    }
}

open class ComponentVM: ComponentVMBase {
    open override var type: ViewModelType { .component }

    /// Entrypoint for the immutable builder. Matches the TS `.builder()`
    /// static.
    public static func builder() -> ComponentVMBuilder {
        ComponentVMBuilder()
    }

    public static func create(_ options: ComponentVMOptions) throws -> ComponentVM {
        var b = ComponentVM.builder()
            .hint(options.hint)
            .background(options.background)
        if let name = options.name { b = b.name(name) }
        if let hub = options.hub, let dispatcher = options.dispatcher {
            b = b.services(hub: hub, dispatcher: dispatcher)
        }
        if let onConstruct = options.onConstruct { b = b.onConstruct(onConstruct) }
        if let onDestruct = options.onDestruct { b = b.onDestruct(onDestruct) }
        return try b.build()
    }
}
