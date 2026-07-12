import Combine

/// Read-only ordered membership with payload-free structural notifications.
///
/// This capability is independent of `VMCollection`: external collection
/// conformers gain no new requirement and may opt in separately.
public protocol ObservableMembershipSource: AnyObject {
    associatedtype Item: AnyObject

    /// Return a shallow ordered snapshot of current membership.
    func snapshot() -> [Item]

    /// Observe Add, Remove, Replace, Move, and Reset as structural pulses.
    func subscribeMembership(_ callback: @escaping () -> Void) -> AnyCancellable
}
