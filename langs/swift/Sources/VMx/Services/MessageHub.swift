//
// MessageHub — Combine-backed pub/sub stream for hub envelopes.
//
// See spec/03-messages.md for the hub contract (HUB-001..HUB-013).
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

/// Additive capability for hubs that support lossless message transactions.
/// Keeping this separate preserves source compatibility for custom
/// `MessageHubProtocol` implementations.
public protocol TransactionalMessageHubProtocol: MessageHubProtocol {
    /// Execute a synchronous transaction and defer messages until its
    /// outermost scope exits.
    func batch(_ transaction: () throws -> Void) throws
}

/// Development-only overflow diagnostic for a suspected publish cycle.
public struct MessageHubOverflowError: Error, CustomStringConvertible {
    public let limit: Int
    public let messageTypes: [String]

    public var description: String {
        "MessageHub drain exceeded \(limit) messages; possible publish cycle involving: "
            + messageTypes.joined(separator: ", ")
    }
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
public final class MessageHub: TransactionalMessageHubProtocol {
#if DEBUG
    private static let developmentDrainLimit = 10_000
#endif
    private let subject = PassthroughSubject<any Message, Never>()
    private let gate = NSRecursiveLock()
    private let diagnosticHandler: ((MessageHubOverflowError) -> Void)?
    private var pending: [any Message] = []
    private var pendingHead = 0
    private var disposed = false
    private var draining = false
    private var batchDepth = 0

    public init() {
        self.diagnosticHandler = nil
    }

    public init(diagnosticHandler: @escaping (MessageHubOverflowError) -> Void) {
        self.diagnosticHandler = diagnosticHandler
    }

    public var messages: AnyPublisher<any Message, Never> {
        subject.eraseToAnyPublisher()
    }

    public func send(_ message: any Message) {
        gate.lock()
        defer { gate.unlock() }
        guard !disposed else { return }
        pending.append(message)
        if batchDepth == 0 && !draining { drain() }
    }

    public func batch(_ transaction: () throws -> Void) throws {
        gate.lock()
        defer { gate.unlock() }
        batchDepth += 1
        do {
            try transaction()
        } catch {
            endBatch()
            throw error
        }
        endBatch()
    }

    private func endBatch() {
        batchDepth -= 1
        if batchDepth == 0 && !disposed && !draining { drain() }
    }

    private func drain() {
        draining = true
#if DEBUG
        var delivered = 0
        var messageTypes = Set<String>()
#endif
        defer {
            if disposed || pendingHead >= pending.count {
                pending.removeAll(keepingCapacity: true)
                pendingHead = 0
            }
            draining = false
        }

        while !disposed && pendingHead < pending.count {
            let message = pending[pendingHead]
            pendingHead += 1
#if DEBUG
            messageTypes.insert(String(describing: type(of: message)))
#endif
            subject.send(message)
#if DEBUG
            delivered += 1
            if delivered >= Self.developmentDrainLimit && pendingHead < pending.count {
                for queued in pending[pendingHead...] {
                    messageTypes.insert(String(describing: type(of: queued)))
                }
                pending.removeAll(keepingCapacity: true)
                pendingHead = 0
                let diagnostic = MessageHubOverflowError(
                    limit: Self.developmentDrainLimit,
                    messageTypes: messageTypes.sorted()
                )
                if let diagnosticHandler {
                    diagnosticHandler(diagnostic)
                } else {
                    assertionFailure(diagnostic.description)
                }
                return
            }
#endif
        }
    }

    /// Complete the underlying subject and stop accepting new sends.
    /// Idempotent.
    public func dispose() {
        gate.lock()
        defer { gate.unlock() }
        guard !disposed else { return }
        disposed = true
        pending.removeAll(keepingCapacity: false)
        pendingHead = 0
        subject.send(completion: .finished)
    }
}
