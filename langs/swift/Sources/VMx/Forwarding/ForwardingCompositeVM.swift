//
// ForwardingCompositeVM<Child> — transparent forwarding decorator for
// `CompositeVM<Child>`.
//
// Delegates every overridable member — the inherited component surface plus
// the composite collection/selection surface — to the wrapped composite by
// default (spec/09-forwarding.md §2). Subclasses override an individual member;
// the rest keep delegating. Mirrors `forwardingCompositeVM.ts`.
//
// `Sequence` conformance forwards iteration to the wrapped's children in order
// (FWD-003), so `Array(fwd)` / `for c in fwd` yield the wrapped children.
//
// Swift port note: Swift's `CompositeVM` is the skeleton flavor — it has no
// `insert`/`setAt`/`clear`/`collectionChanged`/`batchUpdate` surface, so this
// decorator mirrors only the real members (the TS decorator forwards more).
// `name`/`hint` are `let` (see ForwardingComponentVM) — copied at init.
//
// See spec/09-forwarding.md.
//
import Foundation
import Combine

open class ForwardingCompositeVM<Child: ComponentVMBase>: CompositeVM<Child> {
    /// The decorated composite. `public` so subclasses (and instrumentation)
    /// can reach the wrapped instance directly.
    public let _wrapped: CompositeVM<Child>

    public init(_ wrapped: CompositeVM<Child>) {
        self._wrapped = wrapped
        super.init(
            name: wrapped.name,
            hint: wrapped.hint,
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
    open override func dispose() { _wrapped.dispose() }

    // ── Selection (ComponentVMBase) ─────────────────────────────────────
    open override func canSelect() -> Bool { _wrapped.canSelect() }
    open override func select() { _wrapped.select() }
    open override func canDeselect() -> Bool { _wrapped.canDeselect() }
    open override func deselect() { _wrapped.deselect() }

    // ── ParentVM ────────────────────────────────────────────────────────
    open override var supportsChildSelection: Bool { _wrapped.supportsChildSelection }
    open override var currentChild: ComponentVMBase? { _wrapped.currentChild }
    open override func selectChild(_ vm: ComponentVMBase) { _wrapped.selectChild(vm) }
    open override func deselectChild(_ vm: ComponentVMBase) { _wrapped.deselectChild(vm) }

    // ── Collection surface ──────────────────────────────────────────────
    open override var count: Int { _wrapped.count }
    open override func at(_ index: Int) -> Child { _wrapped.at(index) }

    open override var current: Child? {
        get { _wrapped.current }
        set { _wrapped.current = newValue }
    }
    open override func canSetCurrent(_ value: Child?) -> Bool {
        _wrapped.canSetCurrent(value)
    }
    open override func setCurrent(_ value: Child?) throws {
        try _wrapped.setCurrent(value)
    }

    open override func add(_ child: Child) { _wrapped.add(child) }
    open override func remove(_ child: Child) -> Bool { _wrapped.remove(child) }
    open override func removeAt(_ index: Int) { _wrapped.removeAt(index) }
}

// ── Iteration forwarding (FWD-003) ──────────────────────────────────────
//
// Yields the wrapped composite's children in order, so iterating the decorator
// transparently iterates the wrapped instance.
extension ForwardingCompositeVM: Sequence {
    public func makeIterator() -> AnyIterator<Child> {
        // Capture the wrapped composite (not `self`) so the iterator keeps the
        // backing collection alive for the duration of iteration.
        let wrapped = _wrapped
        var index = 0
        return AnyIterator {
            guard index < wrapped.count else { return nil }
            defer { index += 1 }
            return wrapped.at(index)
        }
    }
}
