//
// FormVMBuilder<Model> — immutable fluent builder for FormVM<Model>.
//
// See spec/10-builders.md §3 and ADR-0035 §2 FV1/FV2.
//
// Required setters: initial, persister.
// Optional setters: hub, strict, snapshotter, equals.
//
// Each setter returns a NEW builder instance (BLD-001). build() validates
// required fields and throws BuilderValidationError naming the first missing
// one — "initial" before "persister" (BLD-002).
//

public struct FormVMBuilder<Model> {

    // ── Stored configuration ──────────────────────────────────────────────────

    private var _initial: InitialBox?
    private var _persister: ((Model) async throws -> Void)?
    private var _hub: MessageHubProtocol?
    private var _strict: Bool = false
    private var _snapshotter: ((Model) -> Model)?
    private var _equals: ((Model, Model) -> Bool)?

    /// One-shot box to distinguish "initial was assigned (possibly a nil-able
    /// generic)" from "initial was never set", without requiring Hashable.
    private struct InitialBox { let value: Model }

    // ── Init ──────────────────────────────────────────────────────────────────

    public init() {}

    // ── Setters (each returns a new builder copy) ─────────────────────────────

    /// Set the required initial domain model (also becomes the initial snapshot).
    public func initial(_ value: Model) -> FormVMBuilder<Model> {
        var copy = self; copy._initial = InitialBox(value: value); return copy
    }

    /// Set the required async persister `(Model) async throws -> Void`.
    public func persister(
        _ fn: @escaping (Model) async throws -> Void
    ) -> FormVMBuilder<Model> {
        var copy = self; copy._persister = fn; return copy
    }

    /// Set the optional message hub. Default: `NullMessageHub.INSTANCE`.
    public func hub(_ value: MessageHubProtocol) -> FormVMBuilder<Model> {
        var copy = self; copy._hub = value; return copy
    }

    /// Enable strict mode. Default: `false`.
    ///
    /// When `true`, `approveCommand.canExecute()` returns `false` while
    /// `isDirty == false`.
    public func strict(_ value: Bool) -> FormVMBuilder<Model> {
        var copy = self; copy._strict = value; return copy
    }

    /// Set a custom snapshot function.
    /// Default: identity `{ $0 }` (correct for Swift value types).
    public func snapshotter(
        _ fn: @escaping (Model) -> Model
    ) -> FormVMBuilder<Model> {
        var copy = self; copy._snapshotter = fn; return copy
    }

    /// Set a custom dirty-tracking equality predicate.
    /// Default (non-Equatable): `_defaultModelEquals` (reference identity for
    /// classes; "always changed" for non-Equatable value types). When `Model`
    /// conforms to `Equatable`, the constrained `build()` defaults to `==`.
    public func equals(
        _ fn: @escaping (Model, Model) -> Bool
    ) -> FormVMBuilder<Model> {
        var copy = self; copy._equals = fn; return copy
    }

    /// Pre-wire the hub to `NullMessageHub.INSTANCE`.
    /// Equivalent to `.hub(NullMessageHub.INSTANCE)`.
    public func withDefaultServices() -> FormVMBuilder<Model> {
        hub(NullMessageHub.INSTANCE)
    }

    // ── build() ───────────────────────────────────────────────────────────────

    /// Validate required fields and construct a `FormVM<Model>`.
    ///
    /// - Throws: `BuilderValidationError(missingField: "initial")` when the
    ///   initial model has not been set.
    /// - Throws: `BuilderValidationError(missingField: "persister")` when no
    ///   persister has been set.
    public func build() throws -> FormVM<Model> {
        try _buildCore()
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    fileprivate func _buildCore() throws -> FormVM<Model> {
        guard let box = _initial else {
            throw BuilderValidationError(missingField: "initial")
        }
        guard let persister = _persister else {
            throw BuilderValidationError(missingField: "persister")
        }
        let hub = _hub ?? NullMessageHub.INSTANCE
        let snapshotter = _snapshotter ?? { $0 }
        let equals = _equals ?? { _defaultModelEquals($0, $1) }
        return FormVM(
            initial: box.value,
            persister: persister,
            hub: hub,
            strict: _strict,
            snapshotter: snapshotter,
            equals: equals
        )
    }
}

// ─── Equatable-constrained build() ───────────────────────────────────────────
//
// When Model: Equatable and no explicit equals predicate is set, default to ==
// (structural equality) — matching the FormVM Equatable convenience init.
// An explicit .equals(_:) still overrides (check _equals before defaulting).

extension FormVMBuilder where Model: Equatable {
    /// Equatable-aware `build()` — defaults `equals` to `==` so builder
    /// callers don't need to supply an explicit predicate for Equatable models.
    public func build() throws -> FormVM<Model> {
        if _equals == nil {
            return try equals(==)._buildCore()
        }
        return try _buildCore()
    }
}
