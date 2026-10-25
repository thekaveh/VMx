//
// LateChildStarts — the start records of auto-construct adds that a
// container's construct walk can pull as late children (spec/06 §5.1).
//
import Foundation

/// Test-only probe points of `LateChildStarts`.
enum LateChildStage {
    /// An add attached the child, registered its start record and has not
    /// tried to start the child yet.
    case attached
    /// The walk waits for an add to finish its start attempt.
    case walkWaitingOnAdd
}

/// The start records of auto-construct adds (spec/06 §5.1). An add that
/// attaches a child while the container is `Constructing` registers a record
/// under the membership gate, in the section that attaches the child, and
/// starts the child only after it releases the gate. The record marks that
/// this add tries to start the child; the add marks it done right after its
/// construct attempt. The construct walk never starts a late child: it takes
/// the child's record, waits until the attempt is done, then joins the child.
/// A late child without a record was not started by any add, so the walk
/// skips it.
///
/// Records belong to one walk: each construct walk begins a `Scope` before
/// its initial snapshot, and an add registers its record in the scope that
/// is current at the attach. A walk takes and drops only its own scope's
/// records, so a stale walk (cancelled, failed or replaced) never takes or
/// clears another walk's records. A record registered after its walk's last
/// pull goes into no scope and is dropped with the add.
final class LateChildStarts {
    /// One add's attempt to start the child it attached.
    final class Record {
        private let lock = NSLock()
        private var done = false
        private var onDone: [() -> Void] = []
        /// The walk scope this record was registered in; guarded by the
        /// owning `LateChildStarts` lock.
        fileprivate weak var scope: Scope?

        /// Whether the add finished its start attempt.
        var isDone: Bool { lock.withLock { done } }

        /// Runs `callback` once the add's start attempt is done. Returns
        /// `false` (dropping `callback`) when it already is.
        func whenDone(_ callback: @escaping () -> Void) -> Bool {
            lock.withLock {
                guard !done else { return false }
                onDone.append(callback)
                return true
            }
        }

        /// Marks the attempt done and runs the waiting callbacks.
        fileprivate func finish() {
            let callbacks: [() -> Void] = lock.withLock {
                done = true
                let callbacks = onDone
                onDone = []
                return callbacks
            }
            for callback in callbacks { callback() }
        }
    }

    /// The records of one construct walk. Its map is guarded by the owning
    /// `LateChildStarts` lock.
    final class Scope {
        fileprivate var records: [ObjectIdentifier: Record] = [:]
    }

    private let lock = NSLock()
    private var current: Scope?
    private var probe: ((ComponentVMBase, LateChildStage) -> Void)?

    /// Test-only seam: runs at each `LateChildStage`. Production code never
    /// sets it.
    var probeForTesting: ((ComponentVMBase, LateChildStage) -> Void)? {
        get { lock.withLock { probe } }
        set { lock.withLock { probe = newValue } }
    }

    /// Test-only: the number of records the current walk scope holds.
    var recordCountForTesting: Int { lock.withLock { current?.records.count ?? 0 } }

    /// Begins a construct walk's scope and makes it current; an older scope
    /// is no longer current. Call under the membership gate, in the section
    /// that takes the walk's initial snapshot.
    func beginWalkLocked() -> Scope {
        lock.withLock {
            let scope = Scope()
            current = scope
            return scope
        }
    }

    /// Ends `scope`: drops its records, and clears it as current when it
    /// still is. Never touches another walk's scope.
    func endWalk(_ scope: Scope) {
        lock.withLock {
            if current === scope { current = nil }
            scope.records.removeAll()
        }
    }

    /// Call under the membership gate, in the section that attaches `child`.
    /// Returns a new record when this add will start the child (`starting`)
    /// and registers it in the current walk scope, if any. Otherwise removes
    /// any older record for the child from the current scope.
    func attachLocked(_ child: ComponentVMBase, starting: Bool) -> Record? {
        let key = ObjectIdentifier(child)
        let record = starting ? Record() : nil
        lock.withLock {
            guard let current else { return }
            record?.scope = current
            current.records[key] = record
        }
        return record
    }

    /// Marks the add's start attempt done. A record the walk can no longer
    /// pull (the container left `Constructing`) is removed.
    func finish(_ child: ComponentVMBase, _ record: Record, constructing: Bool) {
        record.finish()
        if !constructing { remove(child, record) }
    }

    /// Removes `record` from the scope it was registered in, if it is still
    /// the child's record there (an add rollback).
    func remove(_ child: ComponentVMBase, _ record: Record?) {
        guard let record else { return }
        lock.withLock {
            guard let scope = record.scope else { return }
            let key = ObjectIdentifier(child)
            if scope.records[key] === record { scope.records[key] = nil }
        }
    }

    /// The walk of `scope` takes the record of a late child it pulls; `nil`
    /// when no add of this walk tries to start the child.
    func take(_ child: ComponentVMBase, from scope: Scope) -> Record? {
        lock.withLock { scope.records.removeValue(forKey: ObjectIdentifier(child)) }
    }

    func probe(_ child: ComponentVMBase, _ stage: LateChildStage) {
        probeForTesting?(child, stage)
    }
}
