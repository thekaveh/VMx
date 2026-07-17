//
// MessageHub tests — HUB-007 per-subscriber exception isolation.
//
// Claimed IDs: HUB-007 (the *catchable* half — a subscriber that throws a
// Swift `Error` via the opt-in `subscribe(_:)` helper is isolated). The
// `subscribe(_:)` path wraps each delivery in do/catch so a thrown error is
// swallowed locally and does not affect other subscribers or stop the hub.
//
// The raw `messages` publisher path (non-throwing Combine sinks) does NOT
// provide this isolation for *trapping* handlers (force-unwrap nil,
// precondition, array-OOB): traps are uncatchable in Swift, equivalent to a
// segfault in the other flavors, and remain a documented divergence
// (ADR-0062 §2.4, ADR-0037, langs/swift/README §5).
//
import XCTest
import Combine
import Darwin
@testable import VMx

final class MessageHubTests: XCTestCase {

    private func msg(_ name: String) -> PropertyChangedMessage {
        PropertyChangedMessage(sender: NSObject(), senderName: "h", propertyName: name)
    }

    func testZeroArgumentInitializerRemainsFactoryCompatible() {
        // Intentional compile-time guard: this pins that `MessageHub.init` stays
        // usable as a `() -> MessageHub` factory (used by null-object and DI
        // wiring). There is no runtime behavior to assert beyond non-trapping
        // construction, which XCTAssertNotNil confirms.
        let factory: () -> MessageHub = MessageHub.init

        XCTAssertNotNil(factory())
    }

    /// HUB-007 — A throwing subscriber registered via `subscribe(_:)` is
    /// isolated: its thrown error is swallowed inside its own sink, so it
    /// neither stops the hub nor blocks delivery to the other subscribers.
    /// This is the Swift expression of HUB-007 via the opt-in `subscribe(_:)`
    /// path (the catchable-error half). The raw `messages` path for trapping
    /// handlers remains a documented divergence — see the file header and
    /// ADR-0062 §2.4.
    func testThrowingSubscriberIsIsolated() {
        struct SubError: Error {}
        let hub = MessageHub()
        var firstReceived = 0
        var secondSeen: [String] = []
        let c1 = hub.subscribe { _ in
            firstReceived += 1
            throw SubError()           // this subscriber always throws
        }
        let c2 = hub.subscribe { message in
            // Record content + order (not just a count), matching the
            // Python/C#/TypeScript HUB-007 corpus: a throwing subscriber must
            // not drop, reorder, or duplicate messages for the healthy one.
            if let pc = message as? PropertyChangedMessage {
                secondSeen.append(pc.propertyName)
            }
        }

        hub.send(msg("x"))
        hub.send(msg("y"))

        XCTAssertEqual(firstReceived, 2, "throwing subscriber keeps receiving")
        XCTAssertEqual(secondSeen, ["x", "y"],
                       "the healthy subscriber receives both messages, by value and in "
                       + "order, unaffected by the thrower")
        c1.cancel()
        c2.cancel()
    }

    /// `subscribe(_:)` delivers messages posted after subscription (HUB-002)
    /// to a non-throwing handler, and cancelling stops delivery.
    func testSubscribeDeliversThenCancelStops() {
        let hub = MessageHub()
        var seen: [String] = []
        let c = hub.subscribe { message in
            if let pc = message as? PropertyChangedMessage {
                seen.append(pc.propertyName)
            }
        }

        hub.send(msg("a"))
        c.cancel()
        hub.send(msg("b"))     // after cancel — not delivered

        XCTAssertEqual(seen, ["a"])
    }

    func testDevelopmentDrainDiagnosticNamesMessageType() {
#if DEBUG
        var diagnostic: MessageHubOverflowError?
        let hub = MessageHub { diagnostic = $0 }
        let cancellable = hub.messages.sink { message in hub.send(message) }

        hub.send(msg("cycle"))

        XCTAssertEqual(diagnostic?.limit, 10_000)
        XCTAssertTrue(diagnostic?.messageTypes.contains("PropertyChangedMessage") == true)
        cancellable.cancel()
#endif
    }

    func testConcurrentProducerWaitsForBatchThenDeliversOnOwnThread() {
        let hub = MessageHub()
        let batchEntered = DispatchSemaphore(value: 0)
        let releaseBatch = DispatchSemaphore(value: 0)
        let sendStarted = DispatchSemaphore(value: 0)
        let sendFinished = DispatchSemaphore(value: 0)
        let batchDone = expectation(description: "batch completed")
        let sendDone = expectation(description: "send completed")
        let concurrentMessage = msg("concurrent")
        var producerThread: UInt32 = 0
        var deliveryThread: UInt32 = 0
        let cancellable = hub.messages.sink { _ in
            deliveryThread = pthread_mach_thread_np(pthread_self())
        }

        DispatchQueue.global().async {
            try? hub.batch {
                batchEntered.signal()
                releaseBatch.wait()
            }
            batchDone.fulfill()
        }
        XCTAssertEqual(batchEntered.wait(timeout: .now() + 1), .success)
        DispatchQueue.global().async {
            producerThread = pthread_mach_thread_np(pthread_self())
            sendStarted.signal()
            hub.send(concurrentMessage)
            sendFinished.signal()
            sendDone.fulfill()
        }
        XCTAssertEqual(sendStarted.wait(timeout: .now() + 1), .success)
        XCTAssertEqual(
            sendFinished.wait(timeout: .now() + 0.05), .timedOut,
            "the active transaction must serialize another producer"
        )
        releaseBatch.signal()
        wait(for: [batchDone, sendDone], timeout: 2)

        XCTAssertEqual(deliveryThread, producerThread)
        cancellable.cancel()
    }

    func testOpposingHubCallbacksDoNotDeadlock() {
        let left = MessageHub()
        let right = MessageHub()
        let callbacksEntered = DispatchSemaphore(value: 0)
        let releaseCallbacks = DispatchSemaphore(value: 0)
        let sendsReturned = DispatchSemaphore(value: 0)
        let innerDeliveries = LockedInt()
        let leftSubscription = left.messages.sink { message in
            guard let changed = message as? PropertyChangedMessage else { return }
            if changed.propertyName == "outer" {
                callbacksEntered.signal()
                releaseCallbacks.wait()
                right.send(self.msg("inner"))
            } else {
                innerDeliveries.increment()
            }
        }
        let rightSubscription = right.messages.sink { message in
            guard let changed = message as? PropertyChangedMessage else { return }
            if changed.propertyName == "outer" {
                callbacksEntered.signal()
                releaseCallbacks.wait()
                left.send(self.msg("inner"))
            } else {
                innerDeliveries.increment()
            }
        }

        DispatchQueue.global().async {
            left.send(self.msg("outer"))
            sendsReturned.signal()
        }
        DispatchQueue.global().async {
            right.send(self.msg("outer"))
            sendsReturned.signal()
        }
        XCTAssertEqual(callbacksEntered.wait(timeout: .now() + 1), .success)
        XCTAssertEqual(callbacksEntered.wait(timeout: .now() + 1), .success)
        releaseCallbacks.signal()
        releaseCallbacks.signal()

        XCTAssertEqual(sendsReturned.wait(timeout: .now() + 1), .success)
        XCTAssertEqual(sendsReturned.wait(timeout: .now() + 1), .success)
        XCTAssertEqual(innerDeliveries.value, 2)
        leftSubscription.cancel()
        rightSubscription.cancel()
    }
}

private final class LockedInt {
    private let lock = NSLock()
    private var storage = 0

    func increment() {
        lock.withLock { storage += 1 }
    }

    var value: Int {
        lock.withLock { storage }
    }
}
