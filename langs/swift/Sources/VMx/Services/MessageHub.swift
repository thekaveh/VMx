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
    private let gate = NSCondition()
    private let diagnosticHandler: ((MessageHubOverflowError) -> Void)?
    private var pending: [any Message] = []
    private var pendingHead = 0
    private var disposed = false
    private var drainerThread: UInt64?
    private var batchOwnerThread: UInt64?
    private var batchDepth = 0
    private var borrowedBatchDepth = 0
    private var borrowedBatchOwners: [UInt64: Int] = [:]
    private var completionRequested = false
    private var completionStarted = false
    // Wait edges registered on this hub since the last release; guarded by `gate`.
    private var registeredWaits = 0
    // Test-only synchronization seam: tests install a non-blocking callback to
    // observe the exact point at which a foreign-owner wait edge is registered.
    internal var onWaitRegisteredForTesting: (() -> Void)?
    // Test-only seam: runs on a woken `send` waiter once no foreign owner
    // remains, before the waiter ends its own edge. Called under `gate`.
    internal var onWaitEndedForTesting: (() -> Void)?

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
        while !disposed, let owner = foreignOwner(for: caller) {
            if !registerWaitLocked(caller: caller, owner: owner) {
                // The target owner already waits (possibly transitively) on this
                // caller. Enqueue and return so that owner can finish its drain.
                break
            }
            onWaitRegisteredForTesting?()
            gate.wait()
            if let hook = onWaitEndedForTesting, foreignOwner(for: caller) == nil { hook() }
            ThreadWaitGraph.shared.endWait(caller: caller)
        }
        guard !disposed else {
            gate.unlock()
            return
        }
        pending.append(message)
        if batchOwnerThread == nil && borrowedBatchDepth == 0 && drainerThread == nil {
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
        var borrowed = false
        gate.lock()
        if borrowedBatchOwners[caller] != nil {
            borrowedBatchDepth += 1
            borrowedBatchOwners[caller, default: 0] += 1
            borrowed = true
        } else {
            while !disposed, let owner = foreignOwner(for: caller) {
                if !registerWaitLocked(caller: caller, owner: owner) {
                    borrowedBatchDepth += 1
                    borrowedBatchOwners[caller, default: 0] += 1
                    borrowed = true
                    break
                }
                gate.wait()
                ThreadWaitGraph.shared.endWait(caller: caller)
            }
        }
        if !disposed && !borrowed {
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
        var shouldComplete = false
        if borrowed {
            gate.lock()
            borrowedBatchDepth -= 1
            if let ownerDepth = borrowedBatchOwners[caller], ownerDepth > 1 {
                borrowedBatchOwners[caller] = ownerDepth - 1
            } else {
                borrowedBatchOwners.removeValue(forKey: caller)
            }
            if borrowedBatchDepth == 0 {
                if !disposed && pendingHead < pending.count
                    && batchOwnerThread == nil && drainerThread == nil {
                    drainerThread = caller
                    shouldDrain = true
                } else if disposed && completionRequested && !completionStarted
                    && batchOwnerThread == nil && drainerThread == nil {
                    completionStarted = true
                    shouldComplete = true
                }
                wakeWaitersLocked()
            }
            gate.unlock()
        } else if entered {
            gate.lock()
            batchDepth -= 1
            if batchDepth == 0 {
                batchOwnerThread = nil
                if !disposed && pendingHead < pending.count && drainerThread == nil {
                    drainerThread = caller
                    shouldDrain = true
                } else if disposed && completionRequested && !completionStarted
                    && borrowedBatchDepth == 0 && drainerThread == nil {
                    completionStarted = true
                    shouldComplete = true
                }
                wakeWaitersLocked()
            }
            gate.unlock()
        }
        if shouldDrain {
            drain()
        }
        if shouldComplete {
            completeSubject()
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
            while !disposed && borrowedBatchDepth > 0 {
                gate.wait()
            }
            if disposed || pendingHead >= pending.count {
                // Queued messages are released after `gate` unlocks: a
                // message's deinit may send on this hub (non-recursive gate).
                let released = pending
                pending.removeAll(keepingCapacity: true)
                pendingHead = 0
                drainerThread = nil
                if disposed && completionRequested && !completionStarted {
                    completionStarted = true
                    shouldComplete = true
                }
                wakeWaitersLocked()
                gate.unlock()
                withExtendedLifetime(released) {}
                if shouldComplete {
                    completeSubject()
                }
                return
            }
            // `pending` keeps the delivered message alive until the drain ends;
            // the end-of-drain copy releases it after `gate` unlocks.
            let message = pending[pendingHead]
            pendingHead += 1
            gate.unlock()
#if DEBUG
            messageTypes.insert(String(describing: type(of: message)))
#endif
            subject.send(message)
#if DEBUG
            delivered += 1
            gate.lock()
            if delivered >= Self.developmentDrainLimit && pendingHead < pending.count && !disposed {
                for queuedMessage in pending[pendingHead...] {
                    messageTypes.insert(String(describing: type(of: queuedMessage)))
                }
                let released = pending
                pending.removeAll(keepingCapacity: true)
                pendingHead = 0
                drainerThread = nil
                wakeWaitersLocked()
                gate.unlock()
                withExtendedLifetime(released) {}
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

    /// Records `caller -> owner` on this hub in the shared wait graph.
    private func registerWaitLocked(caller: UInt64, owner: UInt64) -> Bool {
        guard ThreadWaitGraph.shared.beginWait(
            caller: caller, owner: owner, resource: ObjectIdentifier(self)
        ) else { return false }
        registeredWaits += 1
        return true
    }

    /// Ends every wait edge on this hub, then wakes the waiters under `gate`.
    /// A waiter that still finds a foreign owner registers a new edge. With no
    /// registered wait, the shared graph is not touched.
    private func wakeWaitersLocked() {
        if registeredWaits > 0 {
            registeredWaits = 0
            ThreadWaitGraph.shared.release(resource: ObjectIdentifier(self))
        }
        gate.broadcast()
    }

    private func foreignOwner(for caller: UInt64) -> UInt64? {
        if let owner = batchOwnerThread, owner != caller { return owner }
        if let owner = drainerThread, owner != caller { return owner }
        if let owner = borrowedBatchOwners.keys.first(where: { $0 != caller }) { return owner }
        return nil
    }

    private static var currentThread: UInt64 {
        ThreadWaitGraph.currentThread
    }

    private func completeSubject() {
        subject.send(completion: .finished)
    }

    /// Complete the underlying subject and stop accepting new sends.
    /// Idempotent.
    public func dispose() {
        let caller = Self.currentThread
        var shouldComplete = false
        gate.lock()
        while !disposed, let owner = foreignOwner(for: caller) {
            if !registerWaitLocked(caller: caller, owner: owner) {
                // The owner already waits (possibly transitively) on this
                // caller. Mark the hub disposed and let that owner claim
                // completion when it releases its batch/drain boundary.
                disposed = true
                let released = pending
                pending.removeAll(keepingCapacity: false)
                pendingHead = 0
                completionRequested = true
                wakeWaitersLocked()
                gate.unlock()
                withExtendedLifetime(released) {}
                return
            }
            onWaitRegisteredForTesting?()
            gate.wait()
            ThreadWaitGraph.shared.endWait(caller: caller)
        }
        guard !disposed else {
            gate.unlock()
            return
        }
        disposed = true
        // Dropped messages are released after `gate` unlocks (see drain()).
        let released = pending
        pending.removeAll(keepingCapacity: false)
        pendingHead = 0
        if drainerThread == nil && batchOwnerThread == nil && borrowedBatchDepth == 0 {
            completionStarted = true
            shouldComplete = true
        } else {
            completionRequested = true
        }
        wakeWaitersLocked()
        gate.unlock()
        withExtendedLifetime(released) {}

        if shouldComplete {
            completeSubject()
        }
    }
}
