//
// FormVM<Model> — snapshot/revert edit lifecycle ViewModel.
//
// Standalone (not a ComponentVMOf subclass) per spec/20-form-vm.md §1.1
// and ADR-0030.
//
// See spec/20-form-vm.md and ADR-0048 (injectable deep-equal + deep snapshot).
//
import Combine

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

    private let persister: (Model) async throws -> Void
    private let hub: MessageHubProtocol
    private let strict: Bool
    private let snapshotter: (Model) -> Model
    private let equals: (Model, Model) -> Bool

    // ── Reactive channels (sealed) ────────────────────────────────────────────

    private let _onApproved = PassthroughSubject<Model, Never>()
    private let _approveErrors = PassthroughSubject<Error, Never>()

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
    public init(
        initial: Model,
        persister: @escaping (Model) async throws -> Void,
        hub: MessageHubProtocol = NullMessageHub.INSTANCE,
        strict: Bool = false,
        snapshotter: @escaping (Model) -> Model = { $0 },
        equals: @escaping (Model, Model) -> Bool
    ) {
        self._model = initial
        self.persister = persister
        self.hub = hub
        self.strict = strict
        self.snapshotter = snapshotter
        self.equals = equals
        // Capture snapshot at construction via snapshotter.
        self._snapshot = snapshotter(initial)

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
    public var model: Model { _model }

    /// Read-only snapshot captured at construction (until the next successful
    /// approve).
    public var snapshot: Model { _snapshot }

    /// `true` when `model` is not equal to `snapshot` under the `equals`
    /// predicate.
    public var isDirty: Bool {
        !equals(_model, _snapshot)
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

    // ── Mutation ──────────────────────────────────────────────────────────────

    /// Replaces the current model. The snapshot is unaffected.
    public func setModel(_ newModel: Model) {
        _model = newModel
    }

    // ── Async core ────────────────────────────────────────────────────────────

    /// Awaitable approve flow. Captures the current model **before** awaiting
    /// the persister, so a racing `setModel` cannot swap the persisted payload.
    ///
    /// On success: advances the snapshot and fires ``onApproved``.
    /// On persister throw: mutates nothing and rethrows.
    /// After `dispose()`: returns immediately (no-op).
    public func approveAsync() async throws {
        guard !_disposed else { return }

        // Capture before the suspension point so racing setModel calls cannot
        // change the value that was actually persisted (mirrors TS / C# / Python).
        let current = _model

        // Throw path — no state mutation if this throws.
        try await persister(current)

        guard !_disposed else { return }

        // Success: advance snapshot then notify.
        _snapshot = snapshotter(current)
        _onApproved.send(current)
    }

    // ── Dispose ───────────────────────────────────────────────────────────────

    /// Complete both reactive channels and dispose the commands. Idempotent.
    public func dispose() {
        guard !_disposed else { return }
        _disposed = true
        _onApproved.send(completion: .finished)
        _approveErrors.send(completion: .finished)
        denyCommand.dispose()
        approveCommand.dispose()
    }

    // ── Wire commands post-init ───────────────────────────────────────────────

    /// Called once by the factory helpers below to attach the real command
    /// closures after `self` is fully constructed.
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
                        self._approveErrors.send(error)
                    }
                }
            },
            predicate: { [weak self] in
                guard let self else { return true }
                if self.strict { return self.isDirty }
                return true
            },
            triggers: []
        )
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    private func performDeny() {
        guard !_disposed else { return }
        _model = snapshotter(_snapshot)
        hub.send(FormRevertedMessage(senderObject: self, senderName: "FormVM"))
        hub.send(PropertyChangedMessage(sender: self, senderName: "FormVM", propertyName: "model"))
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
        snapshotter: @escaping (Model) -> Model = { $0 }
    ) {
        self.init(
            initial: initial,
            persister: persister,
            hub: hub,
            strict: strict,
            snapshotter: snapshotter,
            equals: ==
        )
    }
}
