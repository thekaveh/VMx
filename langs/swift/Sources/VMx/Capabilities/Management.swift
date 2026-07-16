//
// Management capability micro-interface — `Managable`.
//
// Ports langs/typescript/src/capabilities/management.ts. See
// spec/14-capabilities.md §Management and
// spec/ADRs/0057-v3-capability-micro-interface-granularity.md.
//
// An independent, opt-in contract for VMs that expose a "manage this item"
// affordance (e.g. open a detail / settings surface for the item). Generic over
// the item type via `associatedtype Item` (Swift protocols cannot be generic —
// mirrors the `<T>` of the other flavors; see ADR-0059 §2.3).
//
// Swift idiom: bare protocol names (no `I`-prefix), camelCase members.
//

/// A VM that can manage an item.
public protocol Managable {
    associatedtype Item
    /// Whether `manage(_:)` may currently be invoked for `item`.
    func canManage(_ item: Item) -> Bool
    /// Manage `item`.
    func manage(_ item: Item)
}
