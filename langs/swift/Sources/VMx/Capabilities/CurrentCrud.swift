//
// Container-current CRUD capability micro-interfaces — `CurrentDeletable`,
// `CurrentUpdatable`.
//
// Ports langs/typescript/src/capabilities/currentCrud.ts. See
// spec/14-capabilities.md §Container-current and
// spec/ADRs/0057-v3-capability-micro-interface-granularity.md.
//
// These mirror `Deletable` / `Updatable` but operate on the container's current
// child rather than an explicit item argument, so they take no parameter. Kept
// independent (ADR-0057): a container may expose current-delete without
// current-update, or either without the item-scoped CRUD verbs.
//
// Swift idiom: bare protocol names (no `I`-prefix), camelCase members.
//

/// A container that can delete its current child.
public protocol CurrentDeletable {
    /// Whether `deleteCurrent()` may currently be invoked.
    func canDeleteCurrent() -> Bool
    /// Delete the current child.
    func deleteCurrent()
}

/// A container that can update its current child.
public protocol CurrentUpdatable {
    /// Whether `updateCurrent()` may currently be invoked.
    func canUpdateCurrent() -> Bool
    /// Update the current child.
    func updateCurrent()
}
