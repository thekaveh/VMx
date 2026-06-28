//
// MessageHub — Combine-backed pub/sub stream for hub envelopes.
//
// See spec/03-messages.md for the hub contract (HUB-001..HUB-007).
//
// HUB-007: a subscriber whose handler fails must not break other
// subscribers or stop the hub. There are two failure shapes in Swift:
//
//   1. A handler that throws a *catchable* Swift `Error`. A plain Combine
//      `.sink(receiveValue:)` closure is non-throwing, so the raw `messages`
//      publisher cannot express this — but `subscribe(_:)` below accepts a
//      throwing handler and isolates it: the thrown error is caught inside
//      that subscriber's own sink, so delivery to every *other* subscriber
//      proceeds unaffected. This is the structural match to the C# / Python /
//      TS per-subscriber try/catch isolation contract.
//   2. A handler that *traps* (force-unwrap nil, `precondition`, array OOB).
//      Traps are uncatchable in Swift (as segfaults are in the other
//      flavors), so they remain a process kill — by convention Swift
//      subscribers guard their own preconditions. Documented divergence.
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

extension MessageHubProtocol {
    /// Subscribe with a throwing-capable handler. A handler that throws a
    /// (catchable) Swift `Error` is *isolated* — its error is swallowed here
    /// so it cannot break delivery to the other subscribers (HUB-007). This is
    /// the Swift expression of the per-subscriber try/catch isolation the
    /// C# / Python / TS hubs apply around every delivery.
    ///
    /// Prefer this over hand-rolling `messages.sink` when the handler can
    /// throw. (A handler that *traps* rather than throws still terminates the
    /// process — traps are uncatchable in Swift, see the file header.)
    ///
    /// Returns an `AnyCancellable`; retain it for as long as the subscription
    /// should live, or cancel it to unsubscribe.
    public func subscribe(
        _ handler: @escaping (any Message) throws -> Void
    ) -> AnyCancellable {
        messages.sink { message in
            do {
                try handler(message)
            } catch {
                // HUB-007: isolate the throwing subscriber. Swallowing here
                // keeps the failure local — the upstream subject and every
                // other subscriber are unaffected.
            }
        }
    }
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
