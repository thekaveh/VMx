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
import Darwin

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
    private static let deliveryDepthKey = "VMx.MessageHub.deliveryDepth"
    private let subject = PassthroughSubject<any Message, Never>()
    private let gate = NSCondition()
    private let diagnosticHandler: ((MessageHubOverflowError) -> Void)?
    private var pending: [any Message] = []
    private var pendingHead = 0
    private var disposed = false
    private var drainerThread: UInt64?
    private var batchOwnerThread: UInt64?
    private var batchDepth = 0
    private var completionRequested = false
    private var completionStarted = false
    private var completionFinished = false

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
        let caller = Self.currentThread
        var shouldDrain = false
        gate.lock()
        while !disposed && hasForeignOwner(for: caller) {
            // A normal producer waits so its own thread performs synchronous
            // delivery. A send made by a subscriber may already be inside a
            // different hub's drain; enqueueing breaks opposing-hub wait cycles
            // and the target's active drainer still delivers it before exiting.
            if Self.isDelivering {
                break
            }
            gate.wait()
        }
        guard !disposed else {
            gate.unlock()
            return
        }
        pending.append(message)
        if batchOwnerThread == nil && drainerThread == nil {
            drainerThread = caller
            shouldDrain = true
        }
        gate.unlock()

        if shouldDrain {
            drain()
        }
    }

    public func batch(_ transaction: () throws -> Void) throws {
        let caller = Self.currentThread
        var entered = false
        gate.lock()
        while !disposed && hasForeignOwner(for: caller) {
            gate.wait()
        }
        if !disposed {
            batchOwnerThread = caller
            batchDepth += 1
            entered = true
        }
        gate.unlock()

        var transactionError: Error?
        do {
            try transaction()
        } catch {
            transactionError = error
        }

        var shouldDrain = false
        if entered {
            gate.lock()
            batchDepth -= 1
            if batchDepth == 0 {
                batchOwnerThread = nil
                if !disposed && pendingHead < pending.count && drainerThread == nil {
                    drainerThread = caller
                    shouldDrain = true
                }
                gate.broadcast()
            }
            gate.unlock()
        }
        if shouldDrain {
            drain()
        }
        if let transactionError {
            throw transactionError
        }
    }

    private func drain() {
#if DEBUG
        var delivered = 0
        var messageTypes = Set<String>()
#endif

        while true {
            var shouldComplete = false
            gate.lock()
            if disposed || pendingHead >= pending.count {
                pending.removeAll(keepingCapacity: true)
                pendingHead = 0
                drainerThread = nil
                if disposed && completionRequested && !completionStarted {
                    completionStarted = true
                    shouldComplete = true
                }
                gate.broadcast()
                gate.unlock()
                if shouldComplete {
                    completeSubject()
                }
                return
            }
            let message = pending[pendingHead]
            pendingHead += 1
            gate.unlock()
#if DEBUG
            messageTypes.insert(String(describing: type(of: message)))
#endif
            Self.withDeliveryContext {
                subject.send(message)
            }
#if DEBUG
            delivered += 1
            gate.lock()
            if delivered >= Self.developmentDrainLimit && pendingHead < pending.count && !disposed {
                for queuedMessage in pending[pendingHead...] {
                    messageTypes.insert(String(describing: type(of: queuedMessage)))
                }
                pending.removeAll(keepingCapacity: true)
                pendingHead = 0
                drainerThread = nil
                gate.broadcast()
                gate.unlock()
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
            gate.unlock()
#endif
        }
    }

    private func hasForeignOwner(for caller: UInt64) -> Bool {
        batchOwnerThread.map { $0 != caller } == true
            || drainerThread.map { $0 != caller } == true
    }

    private static var currentThread: UInt64 {
        UInt64(pthread_mach_thread_np(pthread_self()))
    }

    private static var isDelivering: Bool {
        (Thread.current.threadDictionary[deliveryDepthKey] as? Int ?? 0) > 0
    }

    private static func withDeliveryContext(_ delivery: () -> Void) {
        let dictionary = Thread.current.threadDictionary
        let previousDepth = dictionary[deliveryDepthKey] as? Int ?? 0
        dictionary[deliveryDepthKey] = previousDepth + 1
        defer {
            if previousDepth == 0 {
                dictionary.removeObject(forKey: deliveryDepthKey)
            } else {
                dictionary[deliveryDepthKey] = previousDepth
            }
        }
        delivery()
    }

    private func completeSubject() {
        Self.withDeliveryContext {
            subject.send(completion: .finished)
        }
        gate.lock()
        completionFinished = true
        gate.broadcast()
        gate.unlock()
    }

    /// Complete the underlying subject and stop accepting new sends.
    /// Idempotent.
    public func dispose() {
        let caller = Self.currentThread
        var shouldComplete = false
        var shouldWait = false
        gate.lock()
        guard !disposed else {
            gate.unlock()
            return
        }
        disposed = true
        pending.removeAll(keepingCapacity: false)
        pendingHead = 0
        if drainerThread == nil {
            completionStarted = true
            shouldComplete = true
        } else {
            completionRequested = true
            shouldWait = drainerThread != caller && !Self.isDelivering
        }
        gate.broadcast()
        if shouldWait {
            while !completionFinished {
                gate.wait()
            }
        }
        gate.unlock()

        if shouldComplete {
            completeSubject()
        }
    }
}
