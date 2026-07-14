//
// FormVM<Model> — snapshot/revert edit lifecycle ViewModel.
//
// Standalone (not a ComponentVMOf subclass) per spec/20-form-vm.md §1.1
// and ADR-0030.
//
// See spec/20-form-vm.md and ADR-0048 (injectable deep-equal + deep snapshot).
//
import Combine
import Foundation

/// A ViewModel that wraps a mutable domain model with snapshot-based dirty
/// tracking and an edit lifecycle (approve / deny). Captures a snapshot at
/// construction; mutations via `setModel` update the live model only.
///
/// ``isDirty`` is `true` when the current model is not equal to the snapshot
/// according to the injectable `equals` predicate.
///
/// Use ``approveCommand`` (fire-and-forget) or ``approveAsync()`` (awaitable)
/// to persist; use ``denyCommand`` to revert. Persister failures surface on
/// ``approveErrors`` when the command path is used, and rethrow directly when
/// awaited via ``approveAsync()``.
public final class FormVM<Model> {

    // ── Stored state ──────────────────────────────────────────────────────────

    private var _model: Model
    private var _snapshot: Model
    private var _disposed = false
    private var activeMutations = 0
    private var mutationTeardownPending = false
    private var approvalPrePublishing = false
    private var deferredApprovalModels: [Model] = []
    private let stateGate = NSRecursiveLock()

    private let persister: (Model) async throws -> Void
    private let hub: MessageHubProtocol
    private let strict: Bool
    private let snapshotter: (Model) -> Model
    private let equals: (Model, Model) -> Bool
    private let validators: [String: (Model) -> String?]
    private let modelValidator: ((Model) -> [String: String?])?
    private let resetOnApproved: ((Model) throws -> Model)?
    private var _errors: [String: String]

    // ── Reactive channels (sealed) ────────────────────────────────────────────

    private let _onApproved = PassthroughSubject<Model, Never>()
    private let _approveErrors = PassthroughSubject<Error, Never>()
    private let _errorsChanged = PassthroughSubject<[String: String], Never>()
    /// Fires when `isDirty` transitions in strict mode; wired as a trigger on
    /// `approveCommand` so that subscribers to `canExecuteChanged` are notified.
    private let _approveCanExecSubject = PassthroughSubject<Void, Never>()

    // ── Init ──────────────────────────────────────────────────────────────────

    /// Designated initializer.
    ///
    /// - Parameters:
    ///   - initial: The starting model value; also forms the initial snapshot.
    ///   - persister: Async closure invoked on approve. Throw on failure.
    ///   - hub: Message hub (default: `NullMessageHub.INSTANCE`).
    ///   - strict: When `true`, approve is disabled while `isDirty` is false.
    ///   - snapshotter: Function that produces a snapshot copy of the model.
    ///     Defaults to identity `{ $0 }`, which is correct for value types
    ///     (Swift structs are copied on assignment).
    ///   - equals: Equality predicate for dirty-tracking.
    ///     `isDirty == !equals(model, snapshot)`.
    ///   - resetOnApproved: Optional throwing callback that derives the next
    ///     pristine model from the captured value after persistence succeeds.
    public init(
        initial: Model,
        persister: @escaping (Model) async throws -> Void,
        hub: MessageHubProtocol = NullMessageHub.INSTANCE,
        strict: Bool = false,
        snapshotter: @escaping (Model) -> Model = { $0 },
        validators: [String: (Model) -> String?] = [:],
        modelValidator: ((Model) -> [String: String?])? = nil,
        resetOnApproved: ((Model) throws -> Model)? = nil,
        equals: @escaping (Model, Model) -> Bool
    ) {
        self._model = initial
        self.persister = persister
        self.hub = hub
        self.strict = strict
        self.snapshotter = snapshotter
        self.equals = equals
        self.validators = validators
        self.modelValidator = modelValidator
        self.resetOnApproved = resetOnApproved
        // Capture snapshot at construction via snapshotter.
        self._snapshot = snapshotter(initial)
        self._errors = Self.validate(
            initial,
            validators: validators,
            modelValidator: modelValidator
        )

        // Phase 1: satisfy Swift's two-phase init by giving both commands a
        // placeholder before `self` is available for capture.
        self.denyCommand = RelayCommand(task: nil, predicate: nil, triggers: [])
        self.approveCommand = RelayCommand(task: nil, predicate: nil, triggers: [])

        // Phase 2: all stored properties are set; wire the real closures that
        // capture `self` (weakly to avoid retain cycles).
        wireCommands()
    }

    // ── Commands ──────────────────────────────────────────────────────────────

    /// Reverts `model` to `snapshotter(snapshot)` and publishes
    /// `FormRevertedMessage` + `PropertyChangedMessage("model")` on the hub.
    /// After execution `isDirty == false`.
    public private(set) var denyCommand: RelayCommand

    /// Fire-and-forget approve. Persister failures surface on ``approveErrors``;
    /// they do NOT propagate to the caller of `execute()` (use ``approveAsync()``
    /// directly when you need to `await` the outcome).
    public private(set) var approveCommand: RelayCommand

    // ── Properties ────────────────────────────────────────────────────────────

    /// The live, editable domain model.
    public var model: Model { withStateGate { _model } }

    /// Read-only snapshot captured at construction (until the next successful
    /// approve).
    public var snapshot: Model { withStateGate { _snapshot } }

    /// `true` when `model` is not equal to `snapshot` under the `equals`
    /// predicate.
    public var isDirty: Bool {
        let state = withStateGate { (_model, _snapshot) }
        return !equals(state.0, state.1)
    }

    /// Current validation errors keyed by field/property name.
    public var errors: [String: String] {
        withStateGate { _errors }
    }

    /// `true` when the current model has no validation errors.
    public var isValid: Bool {
        withStateGate { _errors.isEmpty }
    }

    /// Emits the persisted model value after each successful ``approveAsync()``
    /// call (including the command path). Does NOT emit on failure.
    public var onApproved: AnyPublisher<Model, Never> {
        _onApproved.eraseToAnyPublisher()
    }

    /// Emits the `Error` thrown by the persister when ``approveCommand`` (the
    /// fire-and-forget path) fails. The awaitable ``approveAsync()`` rethrows
    /// directly instead of surfacing here.
    public var approveErrors: AnyPublisher<Error, Never> {
        _approveErrors.eraseToAnyPublisher()
    }

    /// Emits only when the effective validation error map changes.
    public var errorsChanged: AnyPublisher<[String: String], Never> {
        _errorsChanged.eraseToAnyPublisher()
    }

    /// Returns the current validation error for a field, if any.
    public func fieldError(_ field: String) -> String? {
        withStateGate { _errors[field] }
    }

    // ── Mutation ──────────────────────────────────────────────────────────────

    /// Replaces the current model. The snapshot is unaffected.
    /// In strict mode fires `approveCommand.canExecuteChanged` when `isDirty`
    /// transitions so that UI bindings can re-evaluate the approve button state.
    /// A call begun after disposal returns before inspecting the candidate.
    public func setModel(_ newModel: Model) {
        stateGate.lock()
        guard !_disposed else {
            stateGate.unlock()
            return
        }
        if approvalPrePublishing {
            deferredApprovalModels.append(newModel)
            stateGate.unlock()
            return
        }
        activeMutations += 1
        var shouldPublish = false
        defer {
            stateGate.unlock()
            if shouldPublish {
                hub.send(PropertyChangedMessage(
                    sender: self,
                    senderName: "FormVM",
                    propertyName: "model"
                ))
            }
            endMutation()
        }

        guard !equals(_model, newModel) else { return }
        let wasDirty = !equals(_model, _snapshot)
        let wasValid = _errors.isEmpty
        _model = newModel
        let nextErrors = Self.validate(
            newModel,
            validators: validators,
            modelValidator: modelValidator
        )
        let nextDirty = !equals(newModel, _snapshot)
        let errorsChanged = nextErrors != _errors
        _errors = nextErrors
        let canExecuteChanged =
            (strict && nextDirty != wasDirty) || nextErrors.isEmpty != wasValid
        if errorsChanged {
            _errorsChanged.send(nextErrors)
        }
        if canExecuteChanged {
            _approveCanExecSubject.send(())
        }
        shouldPublish = true
    }

    // ── Async core ────────────────────────────────────────────────────────────

    /// Awaitable approve flow. Captures the current model **before** awaiting
    /// the persister, so a racing `setModel` cannot swap the persisted payload.
    ///
    /// On success: advances the snapshot and fires ``onApproved``.
    /// On persister throw: mutates nothing and rethrows.
    /// After `dispose()`: returns immediately (no-op).
    public func approveAsync() async throws {
        let captured = withStateGate { (_disposed || !_errors.isEmpty, _model) }
        guard !captured.0 else { return }
        let current = captured.1

        // Throw path — no state mutation if this throws.
        try await persister(current)

        try withStateGate {
            guard !_disposed else { return }
            try completeApproval(current)
        }
        drainDeferredApprovalModels()
    }

    // ── Dispose ───────────────────────────────────────────────────────────────

    /// Complete both reactive channels and dispose the commands. Idempotent.
    public func dispose() {
        stateGate.lock()
        guard !_disposed else {
            stateGate.unlock()
            return
        }
        _disposed = true
        let shouldTearDown = activeMutations == 0
        if !shouldTearDown {
            mutationTeardownPending = true
        }
        stateGate.unlock()
        if shouldTearDown { tearDown() }
    }

    // ── Wire commands post-init ───────────────────────────────────────────────

    /// Called once from `init` (after every stored property is set) to replace
    /// the placeholder commands with the real closures that capture `self`.
    fileprivate func wireCommands() {
        denyCommand = RelayCommand(
            task: { [weak self] in self?.performDeny() },
            predicate: nil,
            triggers: []
        )
        approveCommand = RelayCommand(
            task: { [weak self] in
                guard let self else { return }
                Task {
                    do {
                        try await self.approveAsync()
                    } catch {
                        self.emitApproveError(error)
                    }
                }
            },
            predicate: { [weak self] in
                self?.canApprove() ?? false
            },
            triggers: [_approveCanExecSubject.eraseToAnyPublisher()]
        )
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    private func performDeny() {
        stateGate.lock()
        guard !_disposed else {
            stateGate.unlock()
            return
        }
        activeMutations += 1
        let current = _model
        let snapshot = _snapshot
        let currentErrors = _errors
        let nextModel = snapshotter(snapshot)
        _model = nextModel
        let nextErrors = Self.validate(
            nextModel,
            validators: validators,
            modelValidator: modelValidator
        )
        let wasDirty = !equals(current, snapshot)
        let wasValid = currentErrors.isEmpty
        let nextDirty = !equals(nextModel, snapshot)
        let nextValid = nextErrors.isEmpty
        let errorsChanged = nextErrors != currentErrors
        let canExecuteChanged =
            (strict && nextDirty != wasDirty) || nextValid != wasValid

        _errors = nextErrors
        if errorsChanged {
            _errorsChanged.send(nextErrors)
        }
        stateGate.unlock()
        defer { endMutation() }

        hub.send(FormRevertedMessage(senderObject: self, senderName: "FormVM"))
        hub.send(PropertyChangedMessage(sender: self, senderName: "FormVM", propertyName: "model"))
        if canExecuteChanged {
            withStateGate { _approveCanExecSubject.send(()) }
        }
    }

    private func completeApproval(_ captured: Model) throws {
        guard !_disposed else { return }
        let current = _model
        let snapshot = _snapshot
        let currentErrors = _errors

        let nextModel: Model?
        let nextSnapshot: Model
        let nextErrors: [String: String]?
        if let resetOnApproved {
            let reset = try resetOnApproved(captured)
            guard !_disposed else { return }
            let preparedModel = snapshotter(reset)
            guard !_disposed else { return }
            nextModel = preparedModel
            nextSnapshot = snapshotter(reset)
            guard !_disposed else { return }
            nextErrors = Self.validate(
                preparedModel,
                validators: validators,
                modelValidator: modelValidator
            )
            guard !_disposed else { return }
        } else {
            nextModel = nil
            nextSnapshot = snapshotter(captured)
            guard !_disposed else { return }
            nextErrors = nil
        }

        let committedModel = nextModel ?? current
        let committedErrors = nextErrors ?? currentErrors
        let wasDirty = !equals(current, snapshot)
        guard !_disposed else { return }
        let wasValid = currentErrors.isEmpty
        let nextDirty = !equals(committedModel, nextSnapshot)
        guard !_disposed else { return }
        let nextValid = committedErrors.isEmpty
        let errorsChanged = committedErrors != currentErrors
        let canExecuteChanged =
            (strict && nextDirty != wasDirty) || nextValid != wasValid

        if let nextModel { _model = nextModel }
        _snapshot = nextSnapshot
        if nextErrors != nil { _errors = committedErrors }
        approvalPrePublishing = true
        defer { approvalPrePublishing = false }
        if errorsChanged {
            _errorsChanged.send(committedErrors)
            guard !_disposed else { return }
        }
        if canExecuteChanged {
            _approveCanExecSubject.send(())
            guard !_disposed else { return }
        }
        approvalPrePublishing = false
        _onApproved.send(captured)
    }

    private func drainDeferredApprovalModels() {
        let deferred = withStateGate { () -> [Model] in
            let models = deferredApprovalModels
            deferredApprovalModels.removeAll()
            return models
        }
        for model in deferred { setModel(model) }
    }

    private func canApprove() -> Bool {
        withStateGate {
            guard !_disposed, _errors.isEmpty else { return false }
            guard strict else { return true }
            return !equals(_model, _snapshot)
        }
    }

    private func endMutation() {
        stateGate.lock()
        activeMutations -= 1
        let shouldTearDown = activeMutations == 0 && mutationTeardownPending
        if shouldTearDown { mutationTeardownPending = false }
        stateGate.unlock()
        if shouldTearDown { tearDown() }
    }

    private func tearDown() {
        _onApproved.send(completion: .finished)
        _approveErrors.send(completion: .finished)
        _errorsChanged.send(completion: .finished)
        _approveCanExecSubject.send(completion: .finished)
        denyCommand.dispose()
        approveCommand.dispose()
    }

    private func withStateGate<T>(_ action: () throws -> T) rethrows -> T {
        stateGate.lock()
        defer { stateGate.unlock() }
        return try action()
    }

    private static func validate(
        _ model: Model,
        validators: [String: (Model) -> String?],
        modelValidator: ((Model) -> [String: String?])?
    ) -> [String: String] {
        var errors: [String: String] = [:]
        for (field, validator) in validators {
            if let error = validator(model) {
                errors[field] = error
            }
        }
        if let modelValidator {
            for (field, error) in modelValidator(model) {
                if let error {
                    errors[field] = error
                } else {
                    errors.removeValue(forKey: field)
                }
            }
        }
        return errors
    }

    private func emitApproveError(_ error: Error) {
        withStateGate {
            guard !_disposed else { return }
            _approveErrors.send(error)
        }
    }
}

// ─── Builder entry point ─────────────────────────────────────────────────────

extension FormVM {
    /// Entry point for the immutable fluent builder. Mirrors the `.builder()`
    /// convention used by other VM family members. See spec/10-builders.md §3
    /// and ADR-0035 §2 FV1/FV2.
    public static func builder() -> FormVMBuilder<Model> {
        FormVMBuilder<Model>()
    }
}

// ─── Equatable convenience initializer ───────────────────────────────────────
//
// When `Model` conforms to `Equatable`, the caller does not need to supply an
// explicit `equals` predicate — structural `==` is the correct default.
// Mirrors the `ComponentVMOf` Equatable convenience-init pattern exactly.

extension FormVM where Model: Equatable {
    /// Convenience initializer for `Equatable` models — defaults `equals` to
    /// `==`.
    public convenience init(
        initial: Model,
        persister: @escaping (Model) async throws -> Void,
        hub: MessageHubProtocol = NullMessageHub.INSTANCE,
        strict: Bool = false,
        snapshotter: @escaping (Model) -> Model = { $0 },
        validators: [String: (Model) -> String?] = [:],
        modelValidator: ((Model) -> [String: String?])? = nil,
        resetOnApproved: ((Model) throws -> Model)? = nil
    ) {
        self.init(
            initial: initial,
            persister: persister,
            hub: hub,
            strict: strict,
            snapshotter: snapshotter,
            validators: validators,
            modelValidator: modelValidator,
            resetOnApproved: resetOnApproved,
            equals: ==
        )
    }
}
