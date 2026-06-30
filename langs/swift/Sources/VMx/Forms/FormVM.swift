//
// FormVM<Model> — snapshot/revert edit lifecycle ViewModel.
//
// Standalone (not a ComponentVMOf subclass) per spec/20-form-vm.md §1.1
// and ADR-0030.
//
// See spec/20-form-vm.md and ADR-0048 (injectable deep-equal + deep snapshot).
//

/// A ViewModel that wraps a mutable domain model with snapshot-based dirty
/// tracking and an edit lifecycle (approve / deny). Captures a snapshot at
/// construction; mutations via `setModel` update the live model only.
///
/// ``isDirty`` is `true` when the current model is not equal to the snapshot
/// according to the injectable `equals` predicate.
///
/// Commands (`approveCommand`, `denyCommand`) and the `onApproved` channel
/// are added in a follow-up increment.
public final class FormVM<Model> {

    // ── Stored state ──────────────────────────────────────────────────────────

    private var _model: Model
    private var _snapshot: Model

    private let persister: (Model) async throws -> Void
    private let hub: MessageHubProtocol
    private let strict: Bool
    private let snapshotter: (Model) -> Model
    private let equals: (Model, Model) -> Bool

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
    }

    // ── Properties ────────────────────────────────────────────────────────────

    /// The live, editable domain model.
    public private(set) var model: Model {
        get { _model }
        set { _model = newValue }
    }

    /// Read-only snapshot captured at construction (until the next successful
    /// approve).
    public private(set) var snapshot: Model {
        get { _snapshot }
        set { _snapshot = newValue }
    }

    /// `true` when `model` is not equal to `snapshot` under the `equals`
    /// predicate.
    public var isDirty: Bool {
        !equals(_model, _snapshot)
    }

    // ── Mutation ──────────────────────────────────────────────────────────────

    /// Replaces the current model. The snapshot is unaffected.
    public func setModel(_ newModel: Model) {
        _model = newModel
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
