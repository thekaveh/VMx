//
// Selection capability micro-interfaces — `Selectable`, `Deselectable`,
// `SelectionTogglable`.
//
// Ports langs/typescript/src/capabilities/selection.ts. See
// spec/14-capabilities.md §2.1 and spec/ADRs/0057-v3-capability-micro-interface-granularity.md.
//
// Per ADR-0010 / ADR-0057 these are three independent, opt-in contracts — kept
// deliberately granular, NOT collapsed into one toggle interface. A VM may
// implement the two singular verbs without a toggle affordance, or implement
// `SelectionTogglable` alone. When all three are present `toggleSelection()`
// delegates to `select()` / `deselect()`, but `canToggleSelection()` is a
// capability in its own right and need not equal `canSelect() || canDeselect()`.
//
// Swift idiom: bare protocol names (no `I`-prefix), camelCase members.
//

/// A VM that can be selected.
public protocol Selectable {
    /// Whether `select()` may currently be invoked.
    func canSelect() -> Bool
    /// Select this VM.
    func select()
}

/// A VM that can be deselected.
public protocol Deselectable {
    /// Whether `deselect()` may currently be invoked.
    func canDeselect() -> Bool
    /// Clear this VM's selection.
    func deselect()
}

/// A VM that exposes a single "flip my selection" affordance. Independent of
/// `Selectable` / `Deselectable` (ADR-0057 §2.1).
public protocol SelectionTogglable {
    /// Whether `toggleSelection()` may currently be invoked.
    func canToggleSelection() -> Bool
    /// Flip this VM's selection state.
    func toggleSelection()
}
