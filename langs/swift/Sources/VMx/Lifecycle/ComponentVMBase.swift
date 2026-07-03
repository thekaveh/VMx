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
    var supportsChildSelection: Bool { get }
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

    /// Injected hub. `public` (read-only) so subclasses — including consumer
    /// subclasses in another module — can publish messages on it. Swift has no
    /// `protected`; `internal` would not cross the module boundary, so the
    /// cross-module-subclassing surface (hub / dispatcher / raise) is `public`.
    public let hub: MessageHubProtocol
    /// Injected dispatcher (read-only `public` for the same cross-module reason).
    public let dispatcher: Dispatcher

    private let onConstructCb: (() throws -> Void)?
    private let onDestructCb: (() throws -> Void)?
    private let background: Bool

    // ── State ───────────────────────────────────────────────────────────

    private var _status: ConstructionStatus = .destructed
    private var inFlight = false
    private var _isCurrent = false

    /// Serializes every lifecycle state transition — the `_status` RMW, the
    /// hub publish, and the status-trigger emission inside `_setStatus` —
    /// against `dispose()`. Swift has no `volatile`, so this lock is also what
    /// gives `_status` / `inFlight` / `triggersDisposed` reads a memory barrier
    /// (the audit flags the unsynchronized plain-`var` access as an
    /// undefined-behaviour data race — VMX-002). A background completion
    /// (construct/destruct dispatched on the background queue) therefore cannot
    /// interleave with disposal: it observes the terminal `.disposed` state
    /// under the lock and aborts instead of resurrecting the VM, publishing a
    /// post-dispose status message, or sending on a finished Combine subject
    /// (spec/02 invariant 3 — Disposed is terminal). Recursive so a re-entrant
    /// lifecycle call from a same-thread subscriber cannot self-deadlock —
    /// parity with the C# `lock` / Python `RLock`.
    private let lifecycleLock = NSRecursiveLock()

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
        onConstruct: (() throws -> Void)? = nil,
        onDestruct: (() throws -> Void)? = nil,
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
            // `reconstruct()` is throwing (ADR-0053); the command is gated by
            // `canReconstruct()` so it never throws when fired, and a command
            // task has no error channel, so swallow with `try?`.
            task: { [weak self] in try? self?.reconstruct() },
            predicate: { [weak self] in self?.canReconstruct() ?? false },
            triggers: [trigger]
        )
    }

    // ── Status ──────────────────────────────────────────────────────────

    public var status: ConstructionStatus { _statusSnapshot() }

    public var isConstructed: Bool { _statusSnapshot() == .constructed }

    // ── isCurrent ───────────────────────────────────────────────────────

    public var isCurrent: Bool { _isCurrent }

    /// Internal setter used by containers to flip the flag.
    func _setIsCurrent(_ value: Bool) {
        guard _isCurrent != value else { return }
        // spec/02 invariant 3: a disposed VM publishes nothing further —
        // the trigger raise below was already gated, but the hub send was
        // not (pass-7 review).
        guard status != .disposed else { return }
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
    /// `public` so consumer subclasses in another module can fire it (Swift has
    /// no `protected`; this is the cross-module analogue of C#'s
    /// `protected RaisePropertyChanged`).
    public func _raisePropertyChanged(_ propertyName: String) {
        // `triggersDisposed` is flipped by `dispose()` under `lifecycleLock`;
        // read it (and emit) under the same lock so a background transition
        // never sends on a finished subject. Reentrant: `_setStatus` already
        // holds the lock when it calls through here.
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        guard !triggersDisposed else { return }
        propertyChangedSubject.send(propertyName)
    }

    // ── Lifecycle predicates ────────────────────────────────────────────

    public func canConstruct() -> Bool {
        let s = _statusSnapshot()
        return s == .destructed || s == .constructed
    }

    public func canDestruct() -> Bool {
        let s = _statusSnapshot()
        return s == .constructed || s == .destructed
    }

    public func canReconstruct() -> Bool {
        _statusSnapshot() == .constructed
    }

    // ── Lifecycle operations ────────────────────────────────────────────

    public func construct() throws {
        // Snapshot status + claim the in-flight guard atomically under the lock
        // so a concurrent transition cannot observe a torn `_status` / `inFlight`.
        lifecycleLock.lock()
        if _status == .constructed {
            lifecycleLock.unlock()
            return
        }
        let current = _status
        guard _isLegalTransition(from: current, operation: "construct") else {
            lifecycleLock.unlock()
            // v3 (ADR-0053): Swift converges to the throwing lifecycle contract.
            // An illegal transition surfaces a *catchable* `StatusTransitionError`
            // (was an uncatchable `preconditionFailure` trap under ADR-0037 §2.5).
            // Callers may still pre-flight via canConstruct()/canDestruct()/
            // canReconstruct().
            throw StatusTransitionError(
                currentStatus: current, attemptedOperation: "construct"
            )
        }

        if inFlight {
            lifecycleLock.unlock()
            // LIFE-008: a concurrent re-invocation while a transition is already
            // in flight now throws rather than trapping (ADR-0053).
            throw StatusTransitionError(
                currentStatus: current, attemptedOperation: "construct"
            )
        }
        inFlight = true
        lifecycleLock.unlock()

        if background {
            let priorStatus = _status           // .destructed — captured before any mutation
            _setStatus(.constructing)
            dispatcher.scheduleBackground { [weak self] in
                guard let self else { return }
                // dispose() may have run between scheduling and execution.
                // Re-check the terminal state under the lock and abort if
                // disposed (spec/02 invariant 3). `_setStatus` re-checks under
                // the same lock, so even a dispose() that lands while
                // `_onConstruct()` runs cannot complete the Constructed
                // transition — no resurrection, no post-dispose publish, no
                // send on a finished Combine subject (VMX-002).
                guard !self._isDisposed() else {
                    // Disposed before the hook ran: there is no terminal
                    // transition to emit. Release the in-flight guard inline —
                    // the VM is terminal, so no construct/destruct can succeed
                    // (LIFE-008 is moot post-dispose).
                    self._setInFlight(false)
                    return
                }
                // The background path has no completion/error future in this
                // flavor (VMX-049, deferred): a throwing hook / child
                // transition cannot be redelivered to the already-returned
                // caller, so it is caught here. The foreground form — the
                // common path — propagates via `throws`.
                let terminal: ConstructionStatus
                do {
                    try self._onConstruct()
                    terminal = .constructed
                } catch {
                    terminal = priorStatus         // LIFE-014: roll back to entry state
                    // swallowed: no async error channel on the bg path yet.
                }
                // spec/11 §4 step 3 (VMX-025): the TERMINAL transition — the
                // Constructed emission on success or the LIFE-014 rollback to
                // `priorStatus` on failure — is marshalled onto
                // IDispatcher.Foreground so subscribers observe the completion on
                // the foreground thread, not the pool thread. `_setInFlight(false)`
                // runs INSIDE this closure, AFTER the terminal emit, so the
                // LIFE-008 in-flight guard is not released until the transition
                // has fully settled. `_setStatus` still re-checks `.disposed`
                // under `lifecycleLock`, so a dispose() landing between the hook
                // and this foreground task cannot resurrect the VM. If `self` is
                // deallocated before this runs, the reset is moot (object gone).
                self.dispatcher.scheduleForeground { [weak self] in
                    guard let self else { return }
                    self._setStatus(terminal)
                    self._setInFlight(false)
                }
            }
        } else {
            defer { _setInFlight(false) }
            let priorStatus = _status           // .destructed — captured before any mutation
            _setStatus(.constructing)
            do {
                try _onConstruct()
            } catch {
                _setStatus(priorStatus)         // LIFE-014: roll back so the VM is recoverable
                throw error
            }
            _setStatus(.constructed)
        }
    }

    public func destruct() throws {
        lifecycleLock.lock()
        if _status == .destructed {
            lifecycleLock.unlock()
            return
        }
        let current = _status
        guard _isLegalTransition(from: current, operation: "destruct") else {
            lifecycleLock.unlock()
            // v3 (ADR-0053): catchable throw instead of a trap — see construct().
            throw StatusTransitionError(
                currentStatus: current, attemptedOperation: "destruct"
            )
        }

        if inFlight {
            lifecycleLock.unlock()
            // LIFE-008: concurrent re-invocation now throws (ADR-0053).
            throw StatusTransitionError(
                currentStatus: current, attemptedOperation: "destruct"
            )
        }
        inFlight = true
        lifecycleLock.unlock()

        if background {
            let priorStatus = _status           // .constructed — captured before any mutation
            _setStatus(.destructing)
            dispatcher.scheduleBackground { [weak self] in
                guard let self else { return }
                // dispose() may have run between scheduling and execution.
                // Re-check the terminal state under the lock and abort if
                // disposed (spec/02 invariant 3). `_setStatus` re-checks under
                // the same lock, so even a dispose() that lands while
                // `_onDestruct()` runs cannot complete the Destructed
                // transition — no resurrection, no post-dispose publish, no
                // send on a finished Combine subject (VMX-002).
                guard !self._isDisposed() else {
                    // Disposed before the hook ran: no terminal transition to
                    // emit. Release the in-flight guard inline — the VM is
                    // terminal (LIFE-008 is moot post-dispose).
                    self._setInFlight(false)
                    return
                }
                // Background path has no error channel yet (see construct()).
                let terminal: ConstructionStatus
                do {
                    try self._onDestruct()
                    terminal = .destructed
                } catch {
                    terminal = priorStatus         // LIFE-014: roll back to entry state
                    // swallowed: no async error channel on the bg path yet.
                }
                // spec/11 §4 step 3 (VMX-025): marshal the TERMINAL transition
                // (Destructed on success, or the LIFE-014 rollback to
                // `priorStatus`) onto IDispatcher.Foreground; release the
                // in-flight guard INSIDE the foreground closure, AFTER the
                // terminal emit. `_setStatus` re-checks `.disposed` under the
                // lock, so a racing dispose() cannot resurrect the VM.
                self.dispatcher.scheduleForeground { [weak self] in
                    guard let self else { return }
                    self._setStatus(terminal)
                    self._setInFlight(false)
                }
            }
        } else {
            defer { _setInFlight(false) }
            let priorStatus = _status           // .constructed — captured before any mutation
            _setStatus(.destructing)
            do {
                try _onDestruct()
            } catch {
                _setStatus(priorStatus)         // LIFE-014: roll back so the VM is recoverable
                throw error
            }
            _setStatus(.destructed)
        }
    }

    public func reconstruct() throws {
        lifecycleLock.lock()
        let current = _status
        guard _isLegalTransition(from: current, operation: "reconstruct") else {
            lifecycleLock.unlock()
            // v3 (ADR-0053): catchable throw instead of a trap — see construct().
            throw StatusTransitionError(
                currentStatus: current, attemptedOperation: "reconstruct"
            )
        }
        if inFlight {
            lifecycleLock.unlock()
            // LIFE-008: concurrent re-invocation now throws (ADR-0053).
            throw StatusTransitionError(
                currentStatus: current, attemptedOperation: "reconstruct"
            )
        }
        inFlight = true
        lifecycleLock.unlock()
        defer { _setInFlight(false) }

        _setStatus(.destructing)
        do {
            try _onDestruct()
        } catch {
            _setStatus(.constructed)
            throw error
        }
        _setStatus(.destructed)

        _setStatus(.constructing)
        do {
            try _onConstruct()
        } catch {
            _setStatus(.destructed)
            throw error
        }
        _setStatus(.constructed)
    }

    /// Idempotent terminal transition. From any non-Disposed state,
    /// transitions to `.disposed` and invokes `_onDispose()`. Subclasses
    /// override `_onDispose()` (and may override `dispose()` itself to
    /// cascade to children).
    open func dispose() {
        lifecycleLock.lock()
        if _status == .disposed {
            lifecycleLock.unlock()
            return
        }

        // `_setStatus(.disposed)` flips `_status` to `.disposed` atomically
        // under `lifecycleLock`, so a racing background transition re-checking
        // via `_isDisposed()` observes the terminal state and aborts.
        _setStatus(.disposed)
        lifecycleLock.unlock()
        _onDispose()

        // Tear down the trigger / property-changed subjects under the same lock
        // so the `triggersDisposed` flip and the `send(completion:)` cannot
        // interleave with an in-flight background `_setStatus`: that transition
        // either completes its guarded emission before this runs, or observes
        // `.disposed` / `triggersDisposed` under the lock and skips it — never a
        // send on an already-finished subject (VMX-002).
        lifecycleLock.lock()
        if !triggersDisposed {
            triggersDisposed = true
            statusTriggerSubject.send(completion: .finished)
            propertyChangedSubject.send(completion: .finished)
        }
        lifecycleLock.unlock()

        selectCommand.dispose()
        deselectCommand.dispose()
        selectNextCommand.dispose()
        selectPreviousCommand.dispose()
        reconstructCommand.dispose()
    }

    // ── Selection ───────────────────────────────────────────────────────

    public func canSelect() -> Bool {
        // spec/05 §5 + spec/07: parent non-nil, parent owns a selection slot,
        // not already current, constructed.
        guard let parent = _parent else { return false }
        return parent.supportsChildSelection &&
            parent.currentChild !== self &&
            _statusSnapshot() == .constructed
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
    ///
    /// Declared `throws` (ADR-0053) so container overrides can propagate a
    /// child's throwing `construct()` up to the originating `construct()` call —
    /// parity with the C#/Python/TypeScript cascade. The default body does not
    /// itself throw.
    open func _onConstruct() throws {
        try onConstructCb?()
    }

    /// Default: invoke the closure injected via the builder. Declared `throws`
    /// for symmetry with `_onConstruct()` (ADR-0053); the default body does not
    /// itself throw.
    open func _onDestruct() throws {
        try onDestructCb?()
    }

    /// Subclasses override for resource cleanup on terminal dispose.
    open func _onDispose() {}

    // ── Internal helpers ────────────────────────────────────────────────

    /// Reads `_status` under `lifecycleLock` so every read has a memory
    /// barrier (Swift has no `volatile`). Reentrant — safe to call while a
    /// lifecycle method already holds the lock.
    private func _statusSnapshot() -> ConstructionStatus {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        return _status
    }

    /// Reads the terminal-state flag under `lifecycleLock` so a background
    /// completion observes a concurrently in-progress `dispose()` and aborts
    /// its transition rather than resurrecting the VM (VMX-002).
    private func _isDisposed() -> Bool {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        return _status == .disposed
    }

    /// Writes the in-flight reentrancy guard under `lifecycleLock` so the
    /// background completion's reset is synchronized with the foreground
    /// claim (no torn `inFlight` access — VMX-002).
    private func _setInFlight(_ value: Bool) {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        inFlight = value
    }

    func _setStatus(_ newStatus: ConstructionStatus) {
        // The terminal check, the `_status` write, the hub publish and the
        // status-trigger send all run under `lifecycleLock` so the whole
        // transition is atomic with respect to `dispose()` — a background
        // transition racing `dispose()` can neither resurrect the VM, publish a
        // post-dispose status message, nor send on a finished Combine subject
        // (VMX-002; spec/02 invariant 3: Disposed is terminal). The lock is
        // recursive, so a same-thread subscriber re-entering a lifecycle call
        // from one of the emissions below cannot self-deadlock.
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }

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

    // ── Transition table (fixture-driven, LIFE-011) ─────────────────────
    //
    // Delegates to `LifecycleTransitionTable`, which decodes the bundled
    // `lifecycle-transitions.json` fixture — the cross-flavor source of truth.
    // The hand-rolled switch is replaced so Swift cannot drift from the
    // canonical table the way C#/Python/TypeScript cannot.

    private func _isLegalTransition(
        from current: ConstructionStatus,
        operation: String
    ) -> Bool {
        LifecycleTransitionTable.shared.isLegal(from: current, operation: operation)
    }
}
