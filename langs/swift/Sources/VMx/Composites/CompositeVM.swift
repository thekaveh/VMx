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
import Combine

open class CompositeVM<Child: ComponentVMBase>: ComponentVMBase, ParentVM {
    private var children: [Child] = []
    private var _current: Child?
    private let childrenFactory: (() -> [Child])?
    private let currentSelector: (([Child]) -> Child?)?
    private let onCurrentChanged: ((Child?) -> Void)?
    private var populated = false

    // ── CollectionChanged publisher ─────────────────────────────────────

    private let collectionChangedSubject = PassthroughSubject<CollectionChangedEvent, Never>()

    /// Emits a `CollectionChangedEvent` after each `add` or `remove` mutation.
    public var collectionChanged: AnyPublisher<CollectionChangedEvent, Never> {
        collectionChangedSubject.eraseToAnyPublisher()
    }

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
        // Mirror C# `CanSelectComponent`: the target must be a member *and*
        // Constructed. C# throws on a violation; Swift keeps the existing
        // no-op rather than introducing an (uncatchable) trap — the
        // trap-vs-throw recoverability gap is tracked separately (ADR-0037).
        for child in children where child === vm && child.status == .constructed {
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

    /// The selected child, or `nil`.
    ///
    /// The **setter traps** (`preconditionFailure`) if assigned a value that is
    /// not a member of this composite (spec/06 §3.1 — `Current` must be a
    /// member). Swift property setters cannot be `throws`, so the recoverable
    /// path is `setCurrent(_:)` / `canSetCurrent(_:)` (VMX-026 / ADR-0053): they
    /// validate membership and throw a catchable `CompositeMembershipError`,
    /// mirroring the C#/Python/TypeScript catchable throw. The trapping setter
    /// is retained (not deprecated) for ergonomic binding of an already-validated
    /// member — assigning a known child or `nil` is the common case and never
    /// traps.
    public var current: Child? {
        get { _current }
        set { _setCurrent(newValue) }
    }

    /// Pre-flight predicate for `setCurrent(_:)` / the `current` setter: returns
    /// `true` iff `value` is `nil` or a member of this composite. Mirrors C#
    /// `CanSelectComponent` membership gating for the `Current` slot (spec/06
    /// §3.1).
    public func canSetCurrent(_ value: Child?) -> Bool {
        guard let value else { return true }
        return children.contains(where: { $0 === value })
    }

    /// Throwing, catchable alternative to the `current` property setter
    /// (VMX-026 / ADR-0053). Validates membership and throws
    /// `CompositeMembershipError` on a non-child, instead of trapping. A `nil`
    /// or member assignment behaves exactly like `current = value`.
    public func setCurrent(_ value: Child?) throws {
        guard canSetCurrent(value) else {
            throw CompositeMembershipError(
                memberName: value?.name ?? "<nil>", compositeName: name
            )
        }
        _setCurrent(value)
    }

    public func add(_ child: Child) {
        children.append(child)
        child._parent = self
        // Emit AFTER the child is appended and parent is wired.
        let index = children.count - 1
        collectionChangedSubject.send(.added(child, at: index))
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
        // Emit AFTER the child has been removed and parent cleared.
        collectionChangedSubject.send(.removed(item, at: index))
    }

    // ── Lifecycle overrides ─────────────────────────────────────────────

    open override func _onConstruct() throws {
        try super._onConstruct()
        if !populated {
            populated = true
            if let factory = childrenFactory {
                for c in factory() { add(c) }
            }
        }
        // A child's throwing `construct()` (ADR-0053) propagates up through this
        // hook to the composite's originating `construct()` call — parity with
        // the C#/Python/TypeScript cascade.
        for child in children { try child.construct() }
        if let selector = currentSelector,
           let initial = selector(children),
           children.contains(where: { $0 === initial }) {
            // Non-raising validated assignment (spec/06 §3.1 / COMP-025): the
            // membership is already checked above, so the internal setter never
            // hits its non-child trap here.
            _setCurrent(initial)
        }
    }

    open override func _onDestruct() throws {
        if _current != nil { _setCurrent(nil) }
        for child in children { try child.destruct() }
        try super._onDestruct()
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
        // Non-child assignment is a programmer error reachable only via the
        // (non-throwing) `current` property setter; `setCurrent(_:)` pre-validates
        // via `canSetCurrent(_:)` and throws `CompositeMembershipError` before
        // reaching here (VMX-026 / ADR-0053). The trap remains for the property
        // setter, which Swift cannot make `throws`.
        if let value, !children.contains(where: { $0 === value }) {
            preconditionFailure(
                "Cannot set current to '\(value.name)': not a child of this composite. "
                + "Use setCurrent(_:)/canSetCurrent(_:) for a catchable check."
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

/// Thrown by `CompositeVM.setCurrent(_:)` when the argument is not a member of
/// the composite's children (spec/06 §3.1 — `Current` must be a member; cf.
/// `COMP-009`). This is the Swift convergence (ADR-0053, VMX-026) of the
/// non-child `Current` assignment that C# surfaces as `InvalidOperationException`
/// and Python/TypeScript as a thrown error. The non-throwing `current` property
/// setter traps instead, because Swift setters cannot be `throws`.
public struct CompositeMembershipError: Error, CustomStringConvertible {
    public let memberName: String
    public let compositeName: String

    public init(memberName: String, compositeName: String) {
        self.memberName = memberName
        self.compositeName = compositeName
    }

    public var description: String {
        "Cannot set current to '\(memberName)': "
        + "not a child of composite '\(compositeName)'."
    }
}
