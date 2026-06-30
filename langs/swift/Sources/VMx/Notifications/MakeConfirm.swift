//
// MakeConfirm.swift — bridge from NotificationHubProtocol to async Bool predicate.
//
// See spec/16-notifications.md §"Bridging command decorators".
//

/// Returns an async predicate that posts a `.confirmation` notification with
/// `prompt` to `hub` and returns `true` iff the hub resolves it with `.approve`.
///
/// Used by `ConfirmationDecoratorCommand` to decouple command confirmation from
/// the hub protocol. See spec/16-notifications.md §4.
public func makeConfirm(
    _ hub: NotificationHubProtocol,
    _ prompt: String
) -> () async -> Bool {
    { await hub.post(Notification(type: .confirmation, message: prompt)) == .approve }
}
