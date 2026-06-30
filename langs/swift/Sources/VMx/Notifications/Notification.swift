//
// Notification.swift — VMx notification primitives.
//
// NotificationType, NotificationReaction, Notification.
// See spec/16-notifications.md §1, ADR-0013.
//
import Foundation

/// The kind of a posted notification. See spec/16-notifications.md §1.1.
public enum NotificationType: Sendable, CaseIterable {
    /// Something failed; user attention required.
    case error
    /// Informational; user acknowledgement is enough.
    case notification
    /// A decision is required (Approve / Reject).
    case confirmation
}

/// The outcome of a resolved notification. See spec/16-notifications.md §1.2.
public enum NotificationReaction: Sendable, Equatable, CaseIterable {
    /// Default; the notification has not been resolved yet.
    case pending
    /// User accepted / acknowledged the notification.
    case approve
    /// User declined the notification.
    case reject
}

/// Identity-distinct notification value object. See spec/16-notifications.md §1.3.
///
/// Must be a `class` (not a struct) so that two `Notification` instances with
/// identical `type` and `message` remain independent postings identifiable by
/// `ObjectIdentifier` — each posting can be queued and resolved separately.
public final class Notification: Sendable {
    public let type: NotificationType
    public let message: String

    public init(type: NotificationType, message: String) {
        self.type = type
        self.message = message
    }
}
