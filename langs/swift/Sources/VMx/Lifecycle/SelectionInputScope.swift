import Foundation

/// The per-thread selection-input scope of the Select and Deselect
/// notification (ADR-0242).
///
/// A container membership transaction, and an aggregate slot replacement, open
/// the scope. While it is open, a child whose selection inputs changed (its
/// `IsCurrent` flag or its `Parent` link) is queued, not notified. The
/// outermost scope on the thread runs the queue after the container has released
/// its membership gate and ended its transaction, so no `canExecuteChanged`
/// subscriber runs under a membership gate (spec/06 §4.3).
enum SelectionInputScope {
    /// The depth and the queue of one thread's scope.
    private final class State {
        var depth = 0
        var pending: [() -> Void] = []
    }

    private static let threadKey = "dev.vmx.selectionInputScope"

    private static var state: State {
        let dictionary = Thread.current.threadDictionary
        if let existing = dictionary[threadKey] as? State { return existing }
        let created = State()
        dictionary[threadKey] = created
        return created
    }

    /// Opens a scope on the calling thread. Pair each call with `leave()`.
    static func enter() {
        state.depth += 1
    }

    /// Closes a scope. The outermost close runs the queued notifications, after
    /// the caller has released every container lock.
    static func leave() {
        let current = state
        if current.depth > 0 { current.depth -= 1 }
        guard current.depth == 0 else { return }
        let queued = current.pending
        current.pending = []
        for emit in queued { emit() }
    }

    /// Queues `emit` for the open scope, or runs it at once when no scope is open.
    static func queue(_ emit: @escaping () -> Void) {
        let current = state
        guard current.depth > 0 else {
            emit()
            return
        }
        current.pending.append(emit)
    }
}
