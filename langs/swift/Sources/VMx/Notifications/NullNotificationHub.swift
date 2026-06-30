//
// NullNotificationHub.swift — null-object variant per ADR-0017.
//
// See spec/16-notifications.md §3 and ADR-0017.
//
import Combine

/// Null-object `NotificationHubProtocol`: `post` returns `.approve` immediately
/// without suspension, `resolve` is a no-op, and `pending` is always empty.
///
/// Conforms to ADR-0017 (null-object pattern). The singleton `INSTANCE` is
/// provided for convenience; `public init()` matches `NullLocalizer` precedent
/// so it is injectable wherever a `NotificationHubProtocol` is required.
public final class NullNotificationHub: NotificationHubProtocol {
    /// Shared singleton instance. The hub is stateless.
    public static let INSTANCE = NullNotificationHub()

    public init() {}

    /// Always-empty pending snapshot; completes immediately on subscribe.
    public let pending: AnyPublisher<[Notification], Never> =
        Just([Notification]()).eraseToAnyPublisher()

    /// Returns `.approve` immediately without suspension.
    public func post(_ n: Notification) async -> NotificationReaction {
        return .approve
    }

    /// No-op: there are no pending notifications to resolve.
    public func resolve(_ n: Notification, _ reaction: NotificationReaction) {
        // intentional no-op
    }
}
