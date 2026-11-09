//
// ContainerBatch — the ref-counted collection-change batch shared by
// `CompositeVM` and `GroupVM` (spec v1.1, COMP-013, GRP-006). It owns the
// batch level and the dirty flag; each container member only forwards here.
//
import Foundation

/// A change inside an open batch only marks the batch dirty; the outermost
/// close delivers one `.reset` if any change occurred. Each call takes the
/// container's own delivery, so the batch holds no reference to it.
final class ContainerBatch {
    private var level = 0
    private var dirty = false

    /// Opens one batch level.
    func enter() {
        level += 1
    }

    /// Closes one batch level. A close at level 0 is ignored. The outermost
    /// close delivers the pending `.reset`.
    func exit(deliver: (CollectionChangedEvent) -> Void) {
        guard level > 0 else { return }
        level -= 1
        if level == 0 && dirty {
            dirty = false
            deliver(.reset())
        }
    }

    /// Delivers `event` now, or marks an open batch dirty.
    func emit(_ event: CollectionChangedEvent, deliver: (CollectionChangedEvent) -> Void) {
        if level > 0 {
            dirty = true
        } else {
            deliver(event)
        }
    }
}
