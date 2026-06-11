//
// ComponentVMBase — open base class for every VMx viewmodel.
//
// Manages:
// - The five-state lifecycle (`construct`, `destruct`, `reconstruct`,
//   `dispose`) with transition validation matching the
//   `lifecycle-transitions.json` fixture.
// - Hub publishing (`ConstructionStatusChangedMessage`,
//   `PropertyChangedMessage`).
// - The five built-in commands (`select`, `deselect`, `selectNext`,
//   `selectPrevious`, `reconstruct`).
// - Parent/child selection delegation hooks.
//
// See spec/05-component-vm.md and spec/02-lifecycle.md.
//
import Foundation
import Combine

/// Minimal parent interface used by a child for selection delegation.
/// Mirrors `IParentVM` in the other flavors.
public protocol ParentVM: AnyObject {
    var currentChild: ComponentVMBase? { get }
    func selectChild(_ vm: ComponentVMBase)
    func deselectChild(_ vm: ComponentVMBase)
}

/// View-model kind tag. Mirrors `ViewModelType`.
public enum ViewModelType: String, Sendable {
    case component = "Component"
    case readOnlyComponent = "ReadOnlyComponent"
    case composite = "Composite"
    case group = "Group"
    case aggregate = "Aggregate"
}

open class ComponentVMBase {
    // ── Identity ────────────────────────────────────────────────────────

    public let name: String
    public let hint: String

    /// Subclasses override to declare their kind. Defaults to `.component`.
    open var type: ViewModelType { .component }

    // ── Services ────────────────────────────────────────────────────────

    /// Injected hub. `internal` so subclasses in the module can publish.
    let hub: MessageHubProtocol
    /// Injected dispatcher.
    let dispatcher: Dispatcher

    private let onConstructCb: (() -> Void)?
    private let onDestructCb: (() -> Void)?
    private let background: Bool

    // ── State ───────────────────────────────────────────────────────────

    private var _status: ConstructionStatus = .destructed
    private var inFlight = false
    private var _isCurrent = false

    /// Parent backpointer — set by `CompositeVM` / `GroupVM` when this VM
    /// is added as a child. `internal` so containers in the module can
    /// flip it.
    weak var _parent: ParentVM?

    // ── Reactive primitives ─────────────────────────────────────────────

    private let propertyChangedSubject = PassthroughSubject<String, Never>()
    private let statusTriggerSubject = PassthroughSubject<Void, Never>()
    private var triggersDisposed = false

    // ── Built-in commands ───────────────────────────────────────────────

    public private(set) var selectCommand: RelayCommand
    public private(set) var deselectCommand: RelayCommand
    public private(set) var selectNextCommand: RelayCommand
    public private(set) var selectPreviousCommand: RelayCommand
    public private(set) var reconstructCommand: RelayCommand

    // ── Construction ────────────────────────────────────────────────────

    public init(
        name: String,
        hint: String = "",
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        onConstruct: (() -> Void)? = nil,
        onDestruct: (() -> Void)? = nil,
        background: Bool = false
    ) {
        self.name = name
        self.hint = hint
        self.hub = hub
        self.dispatcher = dispatcher
        self.onConstructCb = onConstruct
        self.onDestructCb = onDestruct
        self.background = background

        // Capture the trigger publisher up front so it doesn't depend on
        // `self` capture order during init.
        let trigger = statusTriggerSubject.eraseToAnyPublisher()

        // Placeholders so phase-1 initialization completes; the real
        // self-capturing commands are assigned immediately below.
        self.selectCommand = RelayCommand(task: nil, predicate: nil, triggers: [])
        self.deselectCommand = RelayCommand(task: nil, predicate: nil, triggers: [])
        self.selectNextCommand = RelayCommand(
            task: nil, predicate: { false }, triggers: []
        )
        self.selectPreviousCommand = RelayCommand(
            task: nil, predicate: { false }, triggers: []
        )
        self.reconstructCommand = RelayCommand(task: nil, predicate: nil, triggers: [])

        _rewireBuiltinCommands(trigger: trigger)
    }

    /// Replaces the placeholder commands with real ones wired to the
    /// selection/lifecycle predicates and tasks per spec/05 §5, with the
    /// status trigger driving `canExecuteChanged`. `selectNext` /
    /// `selectPrevious` keep permanently-false predicates — canonical
    /// parity with the other flavors, which expose them without parent
    /// enumeration in the baseline surface.
    private func _rewireBuiltinCommands(trigger: AnyPublisher<Void, Never>) {
        selectCommand = RelayCommand(
            task: { [weak self] in self?.select() },
            predicate: { [weak self] in self?.canSelect() ?? false },
            triggers: [trigger]
        )
        deselectCommand = RelayCommand(
            task: { [weak self] in self?.deselect() },
            predicate: { [weak self] in self?.canDeselect() ?? false },
            triggers: [trigger]
        )
        selectNextCommand = RelayCommand(
            task: nil, predicate: { false }, triggers: [trigger]
        )
        selectPreviousCommand = RelayCommand(
            task: nil, predicate: { false }, triggers: [trigger]
        )
        reconstructCommand = RelayCommand(
            task: { [weak self] in self?.reconstruct() },
            predicate: { [weak self] in self?.canReconstruct() ?? false },
            triggers: [trigger]
        )
    }

    // ── Status ──────────────────────────────────────────────────────────

    public var status: ConstructionStatus { _status }

    public var isConstructed: Bool { _status == .constructed }

    // ── isCurrent ───────────────────────────────────────────────────────

    public var isCurrent: Bool { _isCurrent }

    /// Internal setter used by containers to flip the flag.
    func _setIsCurrent(_ value: Bool) {
        guard _isCurrent != value else { return }
        _isCurrent = value
        _raisePropertyChanged("isCurrent")
        hub.send(PropertyChangedMessage(
            sender: self, senderName: name, propertyName: "isCurrent"
        ))
    }

    // ── propertyChanged publisher ───────────────────────────────────────

    public var propertyChanged: AnyPublisher<String, Never> {
        propertyChangedSubject.eraseToAnyPublisher()
    }

    /// Subclasses call this to publish a property-changed event on the
    /// in-process publisher. Hub publishing is the caller's choice
    /// (most call sites also do a `hub.send(PropertyChangedMessage(...))`).
    func _raisePropertyChanged(_ propertyName: String) {
        guard !triggersDisposed else { return }
        propertyChangedSubject.send(propertyName)
    }

    // ── Lifecycle predicates ────────────────────────────────────────────

    public func canConstruct() -> Bool {
        _status == .destructed || _status == .constructed
    }

    public func canDestruct() -> Bool {
        _status == .constructed || _status == .destructed
    }

    public func canReconstruct() -> Bool {
        _status == .constructed
    }

    // ── Lifecycle operations ────────────────────────────────────────────

    public func construct() {
        if _status == .constructed { return }

        guard _isLegalTransition(from: _status, operation: "construct") else {
            // Swift surfaces illegal transitions as a trap rather than a
            // thrown error — a documented divergence (ADR-0037): traps are
            // the Swift-stdlib convention for API misuse, and a throwing
            // lifecycle would force `try` onto every legal call site.
            // Callers gate via canConstruct()/canDestruct()/canReconstruct().
            preconditionFailure(
                StatusTransitionError(
                    currentStatus: _status, attemptedOperation: "construct"
                ).description
            )
        }

        if inFlight {
            preconditionFailure(
                StatusTransitionError(
                    currentStatus: _status, attemptedOperation: "construct"
                ).description
            )
        }
        inFlight = true

        if background {
            _setStatus(.constructing)
            dispatcher.scheduleBackground { [weak self] in
                guard let self else { return }
                // dispose() may have run between scheduling and execution;
                // Disposed is terminal (spec/02 invariant 3), so skip the work.
                if self._status != .disposed {
                    self._onConstruct()
                    self._setStatus(.constructed)
                }
                self.inFlight = false
            }
        } else {
            defer { inFlight = false }
            _setStatus(.constructing)
            _onConstruct()
            _setStatus(.constructed)
        }
    }

    public func destruct() {
        if _status == .destructed { return }

        guard _isLegalTransition(from: _status, operation: "destruct") else {
            preconditionFailure(
                StatusTransitionError(
                    currentStatus: _status, attemptedOperation: "destruct"
                ).description
            )
        }

        if inFlight {
            preconditionFailure(
                StatusTransitionError(
                    currentStatus: _status, attemptedOperation: "destruct"
                ).description
            )
        }
        inFlight = true

        if background {
            _setStatus(.destructing)
            dispatcher.scheduleBackground { [weak self] in
                guard let self else { return }
                // dispose() may have run between scheduling and execution;
                // Disposed is terminal (spec/02 invariant 3), so skip the work.
                if self._status != .disposed {
                    self._onDestruct()
                    self._setStatus(.destructed)
                }
                self.inFlight = false
            }
        } else {
            defer { inFlight = false }
            _setStatus(.destructing)
            _onDestruct()
            _setStatus(.destructed)
        }
    }

    public func reconstruct() {
        guard _isLegalTransition(from: _status, operation: "reconstruct") else {
            preconditionFailure(
                StatusTransitionError(
                    currentStatus: _status, attemptedOperation: "reconstruct"
                ).description
            )
        }
        if inFlight {
            preconditionFailure(
                StatusTransitionError(
                    currentStatus: _status, attemptedOperation: "reconstruct"
                ).description
            )
        }
        inFlight = true
        defer { inFlight = false }

        _setStatus(.destructing)
        _onDestruct()
        _setStatus(.destructed)

        _setStatus(.constructing)
        _onConstruct()
        _setStatus(.constructed)
    }

    /// Idempotent terminal transition. From any non-Disposed state,
    /// transitions to `.disposed` and invokes `_onDispose()`. Subclasses
    /// override `_onDispose()` (and may override `dispose()` itself to
    /// cascade to children).
    open func dispose() {
        if _status == .disposed { return }

        _setStatus(.disposed)
        _onDispose()

        if !triggersDisposed {
            triggersDisposed = true
            statusTriggerSubject.send(completion: .finished)
            propertyChangedSubject.send(completion: .finished)
        }

        selectCommand.dispose()
        deselectCommand.dispose()
        selectNextCommand.dispose()
        selectPreviousCommand.dispose()
        reconstructCommand.dispose()
    }

    // ── Selection ───────────────────────────────────────────────────────

    public func canSelect() -> Bool {
        // spec/05 §5: parent non-nil, not already current, constructed.
        // No "parent has a selection slot" condition — a group child
        // reports true and select() is a no-op, same as the other flavors.
        guard let parent = _parent else { return false }
        return parent.currentChild !== self && _status == .constructed
    }

    public func select() {
        _parent?.selectChild(self)
    }

    public func canDeselect() -> Bool {
        guard let parent = _parent else { return false }
        return parent.currentChild === self
    }

    public func deselect() {
        _parent?.deselectChild(self)
    }

    // ── Overridable lifecycle hooks ─────────────────────────────────────

    /// Default: invoke the closure injected via the builder.
    open func _onConstruct() {
        onConstructCb?()
    }

    /// Default: invoke the closure injected via the builder.
    open func _onDestruct() {
        onDestructCb?()
    }

    /// Subclasses override for resource cleanup on terminal dispose.
    open func _onDispose() {}

    // ── Internal helpers ────────────────────────────────────────────────

    func _setStatus(_ newStatus: ConstructionStatus) {
        // Disposed is terminal (spec/02 invariant 3): a background transition
        // racing dispose() must neither resurrect the VM nor publish
        // post-dispose status messages.
        if _status == .disposed { return }

        _status = newStatus

        hub.send(ConstructionStatusChangedMessage(
            sender: self, senderName: name, status: newStatus
        ))

        _raisePropertyChanged("status")
        _raisePropertyChanged("isConstructed")

        if !triggersDisposed {
            statusTriggerSubject.send(())
        }
    }

    // ── Transition table (skeleton, hand-rolled) ────────────────────────
    //
    // The other flavors load this from `spec/fixtures/lifecycle-transitions.json`.
    // For the skeleton, we encode the legal-transition set directly. A
    // follow-up PR will source from the same JSON fixture used by the
    // other flavors (LIFE-011).

    private func _isLegalTransition(
        from current: ConstructionStatus,
        operation: String
    ) -> Bool {
        switch (current, operation) {
        case (.destructed, "construct"),
             (.constructed, "construct"):
            return true
        case (.constructed, "destruct"),
             (.destructed, "destruct"):
            return true
        case (.constructed, "reconstruct"):
            return true
        default:
            return false
        }
    }
}
