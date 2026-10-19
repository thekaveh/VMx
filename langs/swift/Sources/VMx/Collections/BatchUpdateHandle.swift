//
// BatchUpdateHandle.swift — disposable handle for batch collection mutations.
//
// See spec/06-composite-vm.md §Batch updates and spec/07-group-vm.md §Batch
// updates (COMP-013, GRP-006).
//
// Swift divergence: the `using`-statement / `Symbol.dispose` resource-
// management protocol that TypeScript 5.2 and C# 8 provide does not exist in
// Swift. Callers SHOULD call `dispose()` explicitly (e.g. `defer { h.dispose() }`
// is the idiomatic Swift pattern) for deterministic timing; as a safety net the
// handle also disposes in `deinit`, so a handle dropped without an explicit
// `dispose()` cannot strand the container in batch mode. This divergence is
// recorded in ADR-0060.
//

/// Internal protocol implemented by containers that support batch updates.
/// The leading underscore marks it as a VMx-internal detail (not public API).
protocol _Batchable: AnyObject {
    func _exitBatch()
}

/// Returned by `CompositeVM.batchUpdate()` / `GroupVM.batchUpdate()`.
///
/// While the handle is live, per-mutation `CollectionChanged` events (.add /
/// .remove) are suppressed. Calling `dispose()` ends the batch: if any mutation
/// occurred a single `.reset` event is emitted. `dispose()` is idempotent —
/// subsequent calls are no-ops.
public final class BatchUpdateHandle {
    private let endBatch: () -> Void
    private var disposed = false

    init(owner: some _Batchable) {
        endBatch = { [weak owner] in owner?._exitBatch() }
    }

    /// Creates a handle that runs `endBatch` once, on the first `dispose()` or
    /// on deallocation. A custom `VMCollection` returns one from `batchUpdate()`.
    /// The handle holds `endBatch` strongly, so capture the collection weakly
    /// (`[weak self]`) when the collection also keeps the handle.
    public init(endBatch: @escaping () -> Void) {
        self.endBatch = endBatch
    }

    /// End the batch. Emits a single `.reset` `CollectionChangedEvent` if any
    /// mutation occurred during the batch. Idempotent — safe to call more than
    /// once.
    public func dispose() {
        guard !disposed else { return }
        disposed = true
        endBatch()
    }

    /// Safety net: a handle dropped without an explicit `dispose()` still ends
    /// its batch on deallocation, so it cannot strand the container in batch
    /// mode. Idempotent with an explicit `dispose()`.
    deinit {
        dispose()
    }
}
