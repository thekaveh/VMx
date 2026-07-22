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

/// Process-wide wait-for graph for synchronous hub ownership. Registering a
/// wait is cheap and lets the second edge of a true cross-hub cycle defer
/// instead of deadlocking, while unrelated callbacks still wait synchronously.
private final class MessageHubWaitCoordinator: @unchecked Sendable {
    static let shared = MessageHubWaitCoordinator()

    private let lock = NSLock()
    private var waitingOn: [UInt64: UInt64] = [:]

    /// Returns `false` when adding `caller -> owner` would close a cycle.
    func beginWait(caller: UInt64, owner: UInt64) -> Bool {
        lock.lock()
        defer { lock.unlock() }

        waitingOn[caller] = owner
        var cursor = owner
        var visited = Set<UInt64>()
        while visited.insert(cursor).inserted, let next = waitingOn[cursor] {
            if next == caller {
                waitingOn.removeValue(forKey: caller)
                return false
            }
            cursor = next
        }
        return true
    }

    func endWait(caller: UInt64) {
        lock.lock()
        waitingOn.removeValue(forKey: caller)
        lock.unlock()
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
    // Test-only synchronization seam: tests install a non-blocking callback to
    // observe the exact point at which a foreign-owner wait edge is registered.
    internal var onWaitRegisteredForTesting: (() -> Void)?

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
            if !MessageHubWaitCoordinator.shared.beginWait(caller: caller, owner: owner) {
                // The target owner already waits (possibly transitively) on this
                // caller. Enqueue and return so that owner can finish its drain.
                break
            }
            onWaitRegisteredForTesting?()
            gate.wait()
            MessageHubWaitCoordinator.shared.endWait(caller: caller)
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
                if !MessageHubWaitCoordinator.shared.beginWait(caller: caller, owner: owner) {
                    borrowedBatchDepth += 1
                    borrowedBatchOwners[caller, default: 0] += 1
                    borrowed = true
                    break
                }
                gate.wait()
                MessageHubWaitCoordinator.shared.endWait(caller: caller)
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
                gate.broadcast()
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
                gate.broadcast()
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
            subject.send(message)
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

    private func foreignOwner(for caller: UInt64) -> UInt64? {
        if let owner = batchOwnerThread, owner != caller { return owner }
        if let owner = drainerThread, owner != caller { return owner }
        if let owner = borrowedBatchOwners.keys.first(where: { $0 != caller }) { return owner }
        return nil
    }

    private static var currentThread: UInt64 {
        UInt64(pthread_mach_thread_np(pthread_self()))
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
            if !MessageHubWaitCoordinator.shared.beginWait(caller: caller, owner: owner) {
                // The owner already waits (possibly transitively) on this
                // caller. Mark the hub disposed and let that owner claim
                // completion when it releases its batch/drain boundary.
                disposed = true
                pending.removeAll(keepingCapacity: false)
                pendingHead = 0
                completionRequested = true
                gate.broadcast()
                gate.unlock()
                return
            }
            onWaitRegisteredForTesting?()
            gate.wait()
            MessageHubWaitCoordinator.shared.endWait(caller: caller)
        }
        guard !disposed else {
            gate.unlock()
            return
        }
        disposed = true
        pending.removeAll(keepingCapacity: false)
        pendingHead = 0
        if drainerThread == nil && batchOwnerThread == nil && borrowedBatchDepth == 0 {
            completionStarted = true
            shouldComplete = true
        } else {
            completionRequested = true
        }
        gate.broadcast()
        gate.unlock()

        if shouldComplete {
            completeSubject()
        }
    }
}
