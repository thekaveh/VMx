//
// ChildOrder — the order in which a `GroupVM` or `CompositeVM` destructs and
// disposes its children (spec/06 §5, spec/07 §2, ADR-0161).
//
import Foundation

/// The order in which a container destructs and disposes its children.
///
/// Set it with `destructOrder(_:)` on the `GroupVM`, `CompositeVM` and
/// `CompositeVMOf` builders, or with the `destructOrder` field of
/// `GroupVMOptions` and `CompositeVMOptions`. The order is fixed when the
/// container is built. Construct order does not change: children always
/// construct in child order (index 0 first).
public enum ChildOrder: Sendable, Equatable {
    /// Destruct and dispose children in child order, index 0 first. This is
    /// the default and the behavior before the option existed.
    case insertion
    /// Destruct and dispose children in reverse child order, last index
    /// first. A later child that depends on an earlier one is torn down
    /// before it. Every child is still disposed before the container
    /// publishes `Disposed` (LIFE-013). When a construct or destruct hook of
    /// the container runs on another thread, the container publishes
    /// `Disposed` first. It disposes its children after that hook returns
    /// (LIFE-015).
    case reverse

    /// `children` in this order.
    func arrange<Child>(_ children: [Child]) -> [Child] {
        switch self {
        case .insertion: return children
        case .reverse: return children.reversed()
        }
    }
}
