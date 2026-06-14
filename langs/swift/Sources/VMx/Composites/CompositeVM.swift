//
// CompositeVM<VM> — homogeneous-child container with a `current`
// selection slot.
//
// See spec/06-composite-vm.md. This is the skeleton flavor: it covers
// add / remove / select / current and the lifecycle cascade. Batch
// updates, autoConstructOnAdd, async selection, and the full
// CollectionChanged event surface land in a follow-up PR.
//
import Foundation

open class CompositeVM<Child: ComponentVMBase>: ComponentVMBase, ParentVM {
    private var children: [Child] = []
    private var _current: Child?
    private let childrenFactory: (() -> [Child])?
    private let currentSelector: (([Child]) -> Child?)?
    private let onCurrentChanged: ((Child?) -> Void)?
    private var populated = false

    public init(
        name: String,
        hint: String = "",
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        childrenFactory: (() -> [Child])? = nil,
        onConstruct: (() -> Void)? = nil,
        onDestruct: (() -> Void)? = nil,
        currentSelector: (([Child]) -> Child?)? = nil,
        onCurrentChanged: ((Child?) -> Void)? = nil
    ) {
        self.childrenFactory = childrenFactory
        self.currentSelector = currentSelector
        self.onCurrentChanged = onCurrentChanged
        super.init(
            name: name, hint: hint,
            hub: hub, dispatcher: dispatcher,
            onConstruct: onConstruct, onDestruct: onDestruct
        )
    }

    open override var type: ViewModelType { .composite }

    // ── ParentVM ────────────────────────────────────────────────────────

    public var currentChild: ComponentVMBase? { _current }

    public func selectChild(_ vm: ComponentVMBase) {
        for child in children where child === vm {
            _setCurrent(child)
            return
        }
    }

    public func deselectChild(_ vm: ComponentVMBase) {
        if _current === vm {
            _setCurrent(nil)
        }
    }

    // ── Public collection surface ───────────────────────────────────────

    public var count: Int { children.count }

    public func at(_ index: Int) -> Child {
        children[index]
    }

    public var current: Child? {
        get { _current }
        set { _setCurrent(newValue) }
    }

    public func add(_ child: Child) {
        children.append(child)
        child._parent = self
    }

    public func remove(_ child: Child) -> Bool {
        guard let idx = children.firstIndex(where: { $0 === child }) else {
            return false
        }
        removeAt(idx)
        return true
    }

    public func removeAt(_ index: Int) {
        let item = children.remove(at: index)
        item._parent = nil
        if _current === item {
            _setCurrent(nil)
        }
    }

    // ── Lifecycle overrides ─────────────────────────────────────────────

    open override func _onConstruct() {
        super._onConstruct()
        if !populated {
            populated = true
            if let factory = childrenFactory {
                for c in factory() { add(c) }
            }
        }
        for child in children { child.construct() }
        if let selector = currentSelector,
           let initial = selector(children),
           children.contains(where: { $0 === initial }) {
            _setCurrent(initial)
        }
    }

    open override func _onDestruct() {
        if _current != nil { _setCurrent(nil) }
        for child in children { child.destruct() }
        super._onDestruct()
    }

    open override func dispose() {
        // LIFE-013: depth-first dispose children, then self.
        for child in children { child.dispose() }
        super.dispose()
    }

    // ── Builder entrypoint ──────────────────────────────────────────────

    public static func builder() -> CompositeVMBuilder<Child> {
        CompositeVMBuilder<Child>()
    }

    // ── Internal ────────────────────────────────────────────────────────

    private func _setCurrent(_ value: Child?) {
        if let value, !children.contains(where: { $0 === value }) {
            preconditionFailure(
                "Cannot set current to '\(value.name)': not a child of this composite."
            )
        }
        if _current === value { return }

        let previous = _current
        _current = value

        previous?._setIsCurrent(false)
        value?._setIsCurrent(true)

        hub.send(PropertyChangedMessage(
            sender: self, senderName: name, propertyName: "current"
        ))
        _raisePropertyChanged("current")
        onCurrentChanged?(value)
    }
}
