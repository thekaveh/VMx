//
// MessageHub — Combine-backed pub/sub stream for hub envelopes.
//
// See spec/03-messages.md for the hub contract (HUB-001..HUB-007).
//
// HUB-007: a subscriber that throws / fails its handler must not break
// other subscribers or stop the hub. Combine sinks never re-enter the
// upstream subject, so the standard `subject.send` path satisfies the
// "doesn't crash other subscribers" half of HUB-007 by construction; the
// "subscriber raises" half is a no-op here because Swift sinks can't
// throw inertly. Throwing in a subscriber's `receiveValue` would crash
// the process — by convention, subscribers in Swift catch their own
// errors. Documented as a flavor-specific divergence.
//
import Foundation
import Combine

/// Pub/sub hub protocol. Mirrors `IMessageHub` in the C# / Python / TS
/// flavors. Publishes a stream of `Message`-conforming envelopes.
public protocol MessageHubProtocol: AnyObject {
    /// Hot publisher of hub envelopes. Subscribers see only messages
    /// posted *after* they subscribe (per HUB-002).
    var messages: AnyPublisher<any Message, Never> { get }

    /// Broadcast `message` to current subscribers.
    func send(_ message: any Message)
}

/// Default Combine-backed `MessageHubProtocol`. Uses a
/// `PassthroughSubject` for hot, multicast delivery.
public final class MessageHub: MessageHubProtocol {
    private let subject = PassthroughSubject<any Message, Never>()
    private var disposed = false

    public init() {}

    public var messages: AnyPublisher<any Message, Never> {
        subject.eraseToAnyPublisher()
    }

    public func send(_ message: any Message) {
        guard !disposed else { return }
        subject.send(message)
    }

    /// Complete the underlying subject and stop accepting new sends.
    /// Idempotent.
    public func dispose() {
        guard !disposed else { return }
        disposed = true
        subject.send(completion: .finished)
    }
}
