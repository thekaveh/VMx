//
// CompositeVM<VM> — homogeneous-child container with a `current`
// selection slot.
//
// See spec/06-composite-vm.md. The Swift flavor is at full library parity as
// of v3.1.0; this type covers child mutation, selection, lifecycle cascade,
// batch updates, async selection, and CollectionChanged events.
//
import Foundation
import Combine

public struct CompositeVMOptions<Child: ComponentVMBase> {
    public var name: String?
    public var hint: String
    public var hub: MessageHubProtocol?
    public var dispatcher: Dispatcher?
    public var children: (() -> [Child])?
    public var current: (([Child]) -> Child?)?
    public var onCurrentChanged: ((Child?) -> Void)?
    public var onConstruct: (() -> Void)?
    public var onDestruct: (() -> Void)?
    public var autoConstructOnAdd: Bool
    public var asyncSelection: Bool

    public init(
        name: String? = nil,
        hint: String = "",
        hub: MessageHubProtocol? = nil,
        dispatcher: Dispatcher? = nil,
        children: (() -> [Child])? = nil,
        current: (([Child]) -> Child?)? = nil,
        onCurrentChanged: ((Child?) -> Void)? = nil,
        onConstruct: (() -> Void)? = nil,
        onDestruct: (() -> Void)? = nil,
        autoConstructOnAdd: Bool = false,
        asyncSelection: Bool = false
    ) {
        self.name = name
        self.hint = hint
        self.hub = hub
        self.dispatcher = dispatcher
        self.children = children
        self.current = current
        self.onCurrentChanged = onCurrentChanged
        self.onConstruct = onConstruct
        self.onDestruct = onDestruct
        self.autoConstructOnAdd = autoConstructOnAdd
        self.asyncSelection = asyncSelection
    }
}

open class CompositeVM<Child: ComponentVMBase>: ComponentVMBase, ParentVM, _Batchable {
    private var children: [Child] = []
    private var _current: Child?
    private let childrenFactory: (() -> [Child])?
    private let currentSelector: (([Child]) -> Child?)?
    private let onCurrentChanged: ((Child?) -> Void)?
    private var populated = false
    private let _autoConstructOnAdd: Bool
    private let _asyncSelection: Bool

    // ── Batch-update state ──────────────────────────────────────────────

    private var _batchLevel = 0
    private var _batchDirty = false

    // ── CollectionChanged publisher ─────────────────────────────────────

    private let collectionChangedSubject = PassthroughSubject<CollectionChangedEvent, Never>()

    /// Emits a `CollectionChangedEvent` after each `add` or `remove` mutation.
    /// During a batch, granular events are suppressed; `dispose()` on the
    /// returned `BatchUpdateHandle` emits a single `.reset` (if dirty).
    public var collectionChanged: AnyPublisher<CollectionChangedEvent, Never> {
        collectionChangedSubject.eraseToAnyPublisher()
    }

    /// Begin a batch update. Per-mutation `CollectionChanged` events are
    /// suppressed until `dispose()` is called on the returned handle, at which
    /// point a single `.reset` event is emitted (only if a mutation occurred).
    /// Nested `batchUpdate()` calls are supported via a reference counter; the
    /// reset fires only when the outermost batch ends.
    public func batchUpdate() -> BatchUpdateHandle {
        _batchLevel += 1
        return BatchUpdateHandle(owner: self)
    }

    /// Called by `BatchUpdateHandle.dispose()` — do not call directly.
    func _exitBatch() {
        guard _batchLevel > 0 else { return }
        _batchLevel -= 1
        if _batchLevel == 0 && _batchDirty {
            _batchDirty = false
            collectionChangedSubject.send(.reset())
        }
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
        onCurrentChanged: ((Child?) -> Void)? = nil,
        autoConstructOnAdd: Bool = false,
        asyncSelection: Bool = false
    ) {
        self.childrenFactory = childrenFactory
        self.currentSelector = currentSelector
        self.onCurrentChanged = onCurrentChanged
        self._autoConstructOnAdd = autoConstructOnAdd
        self._asyncSelection = asyncSelection
        super.init(
            name: name, hint: hint,
            hub: hub, dispatcher: dispatcher,
            onConstruct: onConstruct, onDestruct: onDestruct
        )
    }

    open override var type: ViewModelType { .composite }

    // ── ParentVM ────────────────────────────────────────────────────────

    public var supportsChildSelection: Bool { true }

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

    /// Pre-flight predicate for `selectComponent(_:)`: returns `true` iff `vm`
    /// is a member of this composite **and** `vm.status == .constructed`.
    ///
    /// This is distinct from `canSetCurrent(_:)`, which checks membership only
    /// without the Constructed gate (spec/06 §3.1). Swift throws catchably
    /// (ADR-0053) where C# surfaces `InvalidOperationException`.
    public func canSelectComponent(_ vm: Child) -> Bool {
        children.contains(where: { $0 === vm }) && vm.status == .constructed
    }

    /// Selects `vm` as the current child, throwing `CompositeMembershipError`
    /// if `canSelectComponent(vm)` returns `false` (non-member or not yet
    /// constructed — spec/06 §3.1 / COMP-008).
    ///
    /// Swift convergence of the C#/TypeScript `selectComponent` throwing path
    /// (ADR-0053): catchable throw rather than a trap, unlike the `current`
    /// property setter which cannot be `throws` in Swift.
    public func selectComponent(_ vm: Child) throws {
        guard canSelectComponent(vm) else {
            throw CompositeMembershipError(memberName: vm.name, compositeName: name)
        }
        _setCurrent(vm)
    }

    /// Deselects `vm`, clearing the current slot, throwing
    /// `CompositeMembershipError` if `vm` is not the current selection
    /// (spec/06 §3.1 / COMP-011).
    ///
    /// Swift convergence of the C#/TypeScript `deselectComponent` throwing path
    /// (ADR-0053): catchable throw rather than a trap.
    public func deselectComponent(_ vm: Child) throws {
        guard _current === vm else {
            throw CompositeMembershipError(memberName: vm.name, compositeName: name)
        }
        _setCurrent(nil)
    }

    public func add(_ child: Child) {
        children.append(child)
        child._parent = self
        // When autoConstructOnAdd is set and the composite is already
        // Constructed, construct the child BEFORE emitting the Add event
        // (COMP-012). `add` is non-throwing per the public API contract;
        // failures surface through assertionFailure in debug/test builds.
        // Divergence from TS (which throws on failure) is recorded in ADR-0060.
        if _autoConstructOnAdd && isConstructed {
            do { try child.construct() } catch {
                assertionFailure("autoConstructOnAdd: child construct failed: \(error)")
            }
        }
        // Emit AFTER the child is appended, parent is wired, and (if
        // autoConstructOnAdd) the child has been constructed.
        let index = children.count - 1
        if _batchLevel > 0 {
            _batchDirty = true
        } else {
            collectionChangedSubject.send(.added(child, at: index))
        }
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
            // Structural removal: the current child is no longer a member, so the
            // clear MUST be synchronous (spec/06 §3 — a non-nil `current` must be a
            // member). Bypass `asyncSelection` like `_onDestruct` does, rather than
            // deferring via `_setCurrent(nil)` and transiently leaving `current`
            // pointing at the removed item. Parity with C#/Python/TypeScript
            // (`SetCurrent(null, async: false)`).
            _applyCurrentChange(nil)
        }
        // Emit AFTER the child has been removed and parent cleared.
        if _batchLevel > 0 {
            _batchDirty = true
        } else {
            collectionChangedSubject.send(.removed(item, at: index))
        }
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
        // hook to the composite's originating `construct()` call. Snapshot first
        // so child hooks can mutate the composite without perturbing the active
        // lifecycle iteration.
        let snapshot = children
        for child in snapshot { try child.construct() }
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
        // Bypass asyncSelection for teardown: destruct is synchronous and must
        // clear the current slot before children are destructed.
        if _current != nil { _applyCurrentChange(nil) }
        let snapshot = children
        for child in snapshot { try child.destruct() }
        try super._onDestruct()
    }

    open override func dispose() {
        // LIFE-013: depth-first dispose children, then self.
        let snapshot = children
        for child in snapshot { child.dispose() }
        super.dispose()
    }

    // ── Builder entrypoint ──────────────────────────────────────────────

    public static func builder() -> CompositeVMBuilder<Child> {
        CompositeVMBuilder<Child>()
    }

    public static func create(_ options: CompositeVMOptions<Child>) throws -> CompositeVM<Child> {
        var b = CompositeVM<Child>.builder()
            .hint(options.hint)
            .autoConstructOnAdd(options.autoConstructOnAdd)
            .asyncSelection(options.asyncSelection)
        if let name = options.name { b = b.name(name) }
        if let hub = options.hub, let dispatcher = options.dispatcher {
            b = b.services(hub: hub, dispatcher: dispatcher)
        }
        if let children = options.children { b = b.children(children) }
        if let current = options.current { b = b.current(current) }
        if let onCurrentChanged = options.onCurrentChanged { b = b.onCurrentChanged(onCurrentChanged) }
        if let onConstruct = options.onConstruct { b = b.onConstruct(onConstruct) }
        if let onDestruct = options.onDestruct { b = b.onDestruct(onDestruct) }
        return try b.build()
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
        if _asyncSelection {
            // COMP-010: defer the full current-change to the foreground dispatcher.
            // A TOCTOU re-check in `_applyCurrentChange` drops the deferred selection
            // if the child was removed between schedule and flush, upholding the
            // spec/06 §3 invariant that a non-null current is always a member.
            let captured = value
            dispatcher.scheduleForeground { [weak self] in
                self?._applyCurrentChange(captured)
            }
        } else {
            _applyCurrentChange(value)
        }
    }

    private func _applyCurrentChange(_ value: Child?) {
        // TOCTOU guard (COMP-010): re-validate membership after a foreground-
        // dispatched selection — the child may have been removed before the
        // deferred closure ran.
        if let value, !children.contains(where: { $0 === value }) { return }
        if _current === value { return }

        let previous = _current
        _current = value

        // COMP-006: marshal the previously-current child's isCurrent flip via
        // the foreground dispatcher so subscribers observe on the foreground
        // execution target. With ImmediateDispatcher / NullDispatcher this runs
        // synchronously (no behavioral change for the synchronous path); with
        // ManualDispatcher a test can prove the emission is buffered until
        // flushForeground() is called.
        if let prev = previous {
            dispatcher.scheduleForeground { [weak self, weak prev] in
                // COMP-006: only clear the previous child's isCurrent if it is
                // still not current when this deferred emit fires. Under a
                // deferring dispatcher an A→B→A sequence before flush re-selects
                // `prev`; clearing it unconditionally would leave `_current === prev`
                // yet `prev.isCurrent == false`, violating spec/06 §3.
                guard let prev, self?._current !== prev else { return }
                prev._setIsCurrent(false)
            }
        }
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
