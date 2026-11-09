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
    /// The throwing subscriber also stays attached: its handler runs for
    /// both messages (spec v3.30, ADR-0191).
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
        XCTAssertEqual(batchEntered.wait(timeout: .now() + hangGuard), .success)
        DispatchQueue.global().async {
            producerThread = pthread_mach_thread_np(pthread_self())
            sendStarted.signal()
            hub.send(concurrentMessage)
            sendFinished.signal()
            sendDone.fulfill()
        }
        XCTAssertEqual(sendStarted.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(
            sendFinished.wait(timeout: .now() + 0.05), .timedOut,
            "the active transaction must serialize another producer"
        )
        releaseBatch.signal()
        wait(for: [batchDone, sendDone], timeout: hangGuard)

        XCTAssertEqual(deliveryThread, producerThread)
        cancellable.cancel()
    }

    func testDisposeWaitsForForeignBatchBeforeCompleting() {
        let hub = MessageHub()
        let batchEntered = DispatchSemaphore(value: 0)
        let releaseBatch = DispatchSemaphore(value: 0)
        let batchReturned = DispatchSemaphore(value: 0)
        let disposeStarted = DispatchSemaphore(value: 0)
        let disposeReturned = DispatchSemaphore(value: 0)
        let completed = DispatchSemaphore(value: 0)
        let cancellable = hub.messages.sink(
            receiveCompletion: { _ in completed.signal() },
            receiveValue: { _ in }
        )

        DispatchQueue.global().async {
            try? hub.batch {
                batchEntered.signal()
                releaseBatch.wait()
            }
            batchReturned.signal()
        }
        XCTAssertEqual(batchEntered.wait(timeout: .now() + hangGuard), .success)
        DispatchQueue.global().async {
            disposeStarted.signal()
            hub.dispose()
            disposeReturned.signal()
        }

        XCTAssertEqual(disposeStarted.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(
            disposeReturned.wait(timeout: .now() + 0.05), .timedOut,
            "dispose must serialize with an active foreign batch"
        )
        XCTAssertEqual(
            completed.wait(timeout: .now() + 0.05), .timedOut,
            "completion must not overtake the active transaction"
        )
        releaseBatch.signal()
        XCTAssertEqual(batchReturned.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(disposeReturned.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(completed.wait(timeout: .now() + hangGuard), .success)
        cancellable.cancel()
    }

    func testCyclicDisposeCompletesWhenBatchOwnerReturns() {
        let batched = MessageHub()
        let source = MessageHub()
        let callbackEntered = DispatchSemaphore(value: 0)
        let aboutToSend = DispatchSemaphore(value: 0)
        let batchWaitingOnSource = DispatchSemaphore(value: 0)
        let workersReturned = DispatchSemaphore(value: 0)
        let completed = DispatchSemaphore(value: 0)
        let completionCount = LockedInt()
        let completionSubscription = batched.messages.sink(
            receiveCompletion: { _ in
                completionCount.increment()
                completed.signal()
            },
            receiveValue: { _ in }
        )
        source.onWaitRegisteredForTesting = {
            batchWaitingOnSource.signal()
        }
        let sourceSubscription = source.messages.sink { message in
            guard let changed = message as? PropertyChangedMessage,
                  changed.propertyName == "outer" else { return }
            callbackEntered.signal()
            aboutToSend.wait()
            batchWaitingOnSource.wait()
            batched.dispose()
        }

        DispatchQueue.global().async {
            try? batched.batch {
                callbackEntered.wait()
                aboutToSend.signal()
                source.send(self.msg("inner"))
            }
            workersReturned.signal()
        }
        DispatchQueue.global().async {
            source.send(self.msg("outer"))
            workersReturned.signal()
        }

        XCTAssertEqual(workersReturned.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(workersReturned.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(completed.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(completionCount.value, 1)
        source.onWaitRegisteredForTesting = nil
        completionSubscription.cancel()
        sourceSubscription.cancel()
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
        XCTAssertEqual(callbacksEntered.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(callbacksEntered.wait(timeout: .now() + hangGuard), .success)
        releaseCallbacks.signal()
        releaseCallbacks.signal()

        XCTAssertEqual(sendsReturned.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(sendsReturned.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(innerDeliveries.value, 2)
        leftSubscription.cancel()
        rightSubscription.cancel()
    }

    func testUnrelatedHubCallbackWaitsForBusyTargetAndRemainsSynchronous() {
        let source = MessageHub()
        let target = MessageHub()
        let batchEntered = DispatchSemaphore(value: 0)
        let releaseBatch = DispatchSemaphore(value: 0)
        let callbackEntered = DispatchSemaphore(value: 0)
        let callbackReturned = DispatchSemaphore(value: 0)
        let outerReturned = DispatchSemaphore(value: 0)
        let delivered = DispatchSemaphore(value: 0)
        let sourceSubscription = source.messages.sink { _ in
            callbackEntered.signal()
            target.send(self.msg("inner"))
            callbackReturned.signal()
        }
        let targetSubscription = target.messages.sink { _ in delivered.signal() }

        DispatchQueue.global().async {
            try? target.batch {
                batchEntered.signal()
                releaseBatch.wait()
            }
        }
        XCTAssertEqual(batchEntered.wait(timeout: .now() + hangGuard), .success)
        DispatchQueue.global().async {
            source.send(self.msg("outer"))
            outerReturned.signal()
        }

        XCTAssertEqual(callbackEntered.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(
            callbackReturned.wait(timeout: .now() + 0.05),
            .timedOut,
            "an unrelated callback must not bypass a busy target's synchronous send"
        )
        releaseBatch.signal()
        XCTAssertEqual(callbackReturned.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(outerReturned.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(delivered.wait(timeout: .now() + hangGuard), .success)
        sourceSubscription.cancel()
        targetSubscription.cancel()
    }

    func testOpposingNestedBatchesBorrowOnlyTheCycleEdge() {
        let left = MessageHub()
        let right = MessageHub()
        let outerBatchesEntered = DispatchSemaphore(value: 0)
        let releaseNestedBatches = DispatchSemaphore(value: 0)
        let transactionsReturned = DispatchSemaphore(value: 0)
        let deliveries = LockedInt()
        let leftSubscription = left.messages.sink { _ in deliveries.increment() }
        let rightSubscription = right.messages.sink { _ in deliveries.increment() }

        DispatchQueue.global().async {
            try? left.batch {
                outerBatchesEntered.signal()
                releaseNestedBatches.wait()
                try right.batch { right.send(self.msg("right-inner")) }
            }
            transactionsReturned.signal()
        }
        DispatchQueue.global().async {
            try? right.batch {
                outerBatchesEntered.signal()
                releaseNestedBatches.wait()
                try left.batch { left.send(self.msg("left-inner")) }
            }
            transactionsReturned.signal()
        }

        XCTAssertEqual(outerBatchesEntered.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(outerBatchesEntered.wait(timeout: .now() + hangGuard), .success)
        releaseNestedBatches.signal()
        releaseNestedBatches.signal()
        XCTAssertEqual(transactionsReturned.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(transactionsReturned.wait(timeout: .now() + hangGuard), .success)
        XCTAssertEqual(deliveries.value, 2)
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

// ── Borrowed batch scopes (spec/03 §4.2, ADR-0172, #1178) ───────────────────
//
// These tests run the #1178 shape on dedicated threads P and Q with hubs h,
// h2 and h3. P drains h2. Q drains or batches h and then waits for P on h2.
// P's h2 subscriber borrows h (its wait for Q would close a cycle), disposes
// h2 inside the borrowed body, and then acts. Every wait is bounded, so a
// regression fails instead of hanging the suite.

private final class BorrowBox<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: T
    init(_ value: T) { storage = value }
    var value: T {
        get { lock.withLock { storage } }
        set { lock.withLock { storage = newValue } }
    }
    func mutate(_ body: (inout T) -> Void) { lock.withLock { body(&storage) } }
}

/// One delivered or logged event: its name and the thread it ran on.
private struct BorrowEvent: Equatable {
    let name: String
    let thread: UInt64
}

private final class BorrowCycle {
    let h = MessageHub()
    let h2 = MessageHub()
    let h3 = MessageHub()
    let p = BorrowBox<UInt64>(0)
    let q = BorrowBox<UInt64>(0)
    let events = BorrowBox<[BorrowEvent]>([])
    let qWaitingForP = DispatchSemaphore(value: 0)
    let pWaitingForQ = DispatchSemaphore(value: 0)
    /// Set by P just before the action whose accepted wait it reports.
    let pActing = BorrowBox(false)
    private var cancellables: [AnyCancellable] = []
    /// Extra behavior for each `h` delivery, after it is logged.
    var onH: ((String) -> Void)?

    init() {
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { [p, q, pActing, qWaitingForP, pWaitingForQ] caller, accepted in
            guard accepted else { return }
            if caller == q.value { qWaitingForP.signal() }
            if caller == p.value, pActing.value { pWaitingForQ.signal() }
        }
        cancellables.append(h.messages.sink { [weak self] message in
            guard let self, let name = (message as? PropertyChangedMessage)?.propertyName else { return }
            self.log("h:" + name)
            self.onH?(name)
        })
        cancellables.append(h3.messages.sink { [weak self] message in
            guard let self, let name = (message as? PropertyChangedMessage)?.propertyName else { return }
            self.log("h3:" + name)
        })
    }

    func msg(_ name: String) -> PropertyChangedMessage {
        PropertyChangedMessage(sender: NSObject(), senderName: "hub", propertyName: name)
    }

    func log(_ name: String) {
        let thread = ThreadWaitGraph.currentThread
        events.mutate { $0.append(BorrowEvent(name: name, thread: thread)) }
    }

    func count(_ name: String) -> Int { events.value.filter { $0.name == name }.count }

    func index(_ name: String) -> Int? { events.value.firstIndex { $0.name == name } }

    func thread(of name: String) -> UInt64? { events.value.first { $0.name == name }?.thread }

    /// Runs the shape. `qAction` runs on Q once P drains h2, and must wait
    /// for P on h2. `pAction` runs on P inside its borrowed scope on h, after
    /// P disposes h2 and waits `pause`.
    func run(
        pause: TimeInterval = 0.3,
        qAction: @escaping (BorrowCycle) -> Void,
        pAction: @escaping (BorrowCycle) -> Void
    ) -> (pFinished: Bool, qFinished: Bool) {
        let pInSubscriber = DispatchSemaphore(value: 0)
        let pDone = DispatchSemaphore(value: 0)
        let qDone = DispatchSemaphore(value: 0)
        let once = BorrowBox(true)
        cancellables.append(h2.messages.sink { [weak self] message in
            guard let self, (message as? PropertyChangedMessage)?.propertyName == "p0" else { return }
            var first = false
            once.mutate { first = $0; $0 = false }
            guard first else { return }
            pInSubscriber.signal()
            guard self.qWaitingForP.wait(timeout: .now() + hangGuard) == .success else { return }
            try? self.h.batch {
                self.h2.dispose()
                if pause > 0 { Thread.sleep(forTimeInterval: pause) }
                pAction(self)
                self.log("body-end")
            }
        })
        Thread.detachNewThread { [self] in
            p.value = ThreadWaitGraph.currentThread
            h2.send(msg("p0"))
            pDone.signal()
        }
        guard pInSubscriber.wait(timeout: .now() + hangGuard) == .success else { return (false, false) }
        Thread.detachNewThread { [self] in
            q.value = ThreadWaitGraph.currentThread
            qAction(self)
            qDone.signal()
        }
        let pFinished = pDone.wait(timeout: .now() + hangGuard) == .success
        let qFinished = qDone.wait(timeout: .now() + hangGuard) == .success
        return (pFinished, qFinished)
    }

    /// Q batches h3, sends q0 on h and drains it; Q's h subscriber for q0
    /// sends on h2 and waits for P.
    static func drainThenWaitForP(_ cycle: BorrowCycle) {
        cycle.onH = { name in
            guard name == "q0" else { return }
            cycle.h2.send(cycle.msg("q1"))
        }
        try? cycle.h3.batch { cycle.h.send(cycle.msg("q0")) }
    }
}

final class MessageHubBorrowedScopeTests: XCTestCase {

    override func tearDown() {
        ThreadWaitGraph.shared.onWaitDecidedForTesting = nil
        super.tearDown()
    }

    private func assertFinished(
        _ outcome: (pFinished: Bool, qFinished: Bool),
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertTrue(outcome.pFinished, "thread P hung", file: file, line: line)
        XCTAssertTrue(outcome.qFinished, "thread Q hung", file: file, line: line)
    }

    /// HUB-013, #1178 variant 1. Q's drain of h has an empty queue when it
    /// meets P's borrowed scope, so it releases the drain instead of waiting.
    func testEmptyQueueDrainerReleasesTheDrainToABorrowedScope() {
        let cycle = BorrowCycle()
        let outcome = cycle.run(qAction: BorrowCycle.drainThenWaitForP) { cycle in
            cycle.h3.send(cycle.msg("pm"))
        }
        assertFinished(outcome)
        XCTAssertEqual(cycle.count("h3:pm"), 1)
        XCTAssertEqual(cycle.count("h:q0"), 1)
    }

    /// HUB-013, #1178 variant 3. The exit of Q's owned h batch does not claim
    /// the drain while P's borrowed scope is open; the borrowed exit drains.
    func testOwnedBatchExitLeavesTheDrainToTheLastBorrowedScope() {
        let cycle = BorrowCycle()
        let outcome = cycle.run(qAction: { cycle in
            try? cycle.h3.batch {
                try? cycle.h.batch {
                    cycle.h.send(cycle.msg("q2"))
                    cycle.h2.send(cycle.msg("q1"))
                }
            }
        }, pAction: { cycle in
            cycle.h3.send(cycle.msg("pm"))
        })
        assertFinished(outcome)
        XCTAssertEqual(cycle.count("h3:pm"), 1)
        XCTAssertEqual(cycle.count("h:q2"), 1)
    }

    /// HUB-013, #1178 variant 4. The borrower's own send enqueues without a
    /// wait, and h delivers it once, after the borrowed body exits.
    func testBorrowerSendEnqueuesForTheBorrowedScopeExit() {
        let cycle = BorrowCycle()
        let outcome = cycle.run(qAction: BorrowCycle.drainThenWaitForP) { cycle in
            cycle.pActing.value = true
            cycle.h.send(cycle.msg("pb"))
        }
        assertFinished(outcome)
        XCTAssertEqual(cycle.count("h:pb"), 1)
        XCTAssertEqual(
            cycle.pWaitingForQ.wait(timeout: .now()), .timedOut,
            "the borrower's own send waited"
        )
        if let pb = cycle.index("h:pb"), let end = cycle.index("body-end") {
            XCTAssertGreaterThan(pb, end, "pb reached subscribers inside the borrowed body")
        } else {
            XCTFail("missing events: \(cycle.events.value)")
        }
    }

    /// HUB-013, #1178 variant 5. After Q's nested h batch, Q's send, batch or
    /// dispose on h waits for P's borrowed scope with an edge.
    func testOwnerCallAfterItsNestedBatchWaitsForTheBorrowedScope() {
        let followUps: [(String, (BorrowCycle) -> Void)] = [
            ("send", { $0.h.send($0.msg("qx")) }),
            ("batch", { cycle in try? cycle.h.batch { cycle.h.send(cycle.msg("qx")) } }),
            ("dispose", { $0.h.dispose() }),
        ]
        for (label, followUp) in followUps {
            let cycle = BorrowCycle()
            let outcome = cycle.run(qAction: { cycle in
                try? cycle.h3.batch {
                    try? cycle.h.batch { cycle.h2.send(cycle.msg("q1")) }
                    followUp(cycle)
                }
            }, pAction: { cycle in
                cycle.h3.send(cycle.msg("pm"))
            })
            XCTAssertTrue(outcome.pFinished, "\(label): thread P hung")
            XCTAssertTrue(outcome.qFinished, "\(label): thread Q hung")
            XCTAssertEqual(cycle.count("h3:pm"), 1, label)
            ThreadWaitGraph.shared.onWaitDecidedForTesting = nil
        }
    }

    /// HUB-013, #1178 variant 6. Q's h subscriber returns only after P's send
    /// on h3 waits for Q. Q's drain then finds an empty queue and releases it.
    func testDrainerReleasesAfterTheBorrowerAlreadyWaitsForIt() {
        let cycle = BorrowCycle()
        let outcome = cycle.run(pause: 0, qAction: { cycle in
            cycle.onH = { name in
                guard name == "q0" else { return }
                cycle.h2.send(cycle.msg("q1"))
                _ = cycle.pWaitingForQ.wait(timeout: .now() + hangGuard)
            }
            try? cycle.h3.batch { cycle.h.send(cycle.msg("q0")) }
        }, pAction: { cycle in
            cycle.pActing.value = true
            cycle.h3.send(cycle.msg("pm"))
        })
        assertFinished(outcome)
        XCTAssertEqual(cycle.count("h3:pm"), 1)
    }

    /// spec/03 §4.2 rule 5 (the documented HUB-010 limitation). Q's drain of h
    /// still has `qLate` queued when it meets P's borrowed scope, and P
    /// already waits for Q. Q's wait would close the cycle, so Q releases the
    /// drain and its outermost send returns before `qLate` is delivered. P's
    /// last borrowed-scope exit delivers `qLate` on P's thread, in FIFO order.
    func testDrainerWithQueuedMessagesReleasesTheDrainOnARefusedWait() {
        let cycle = BorrowCycle()
        let qLateBeforeReturn = BorrowBox<Bool?>(nil)
        let outcome = cycle.run(pause: 0, qAction: { cycle in
            cycle.onH = { name in
                guard name == "q0" else { return }
                cycle.h.send(cycle.msg("qLate"))
                cycle.h2.send(cycle.msg("q1"))
                _ = cycle.pWaitingForQ.wait(timeout: .now() + hangGuard)
            }
            try? cycle.h3.batch {
                cycle.h.send(cycle.msg("q0"))
                qLateBeforeReturn.value = cycle.count("h:qLate") > 0
            }
        }, pAction: { cycle in
            cycle.pActing.value = true
            cycle.h3.send(cycle.msg("pm"))
        })
        assertFinished(outcome)
        XCTAssertEqual(cycle.count("h3:pm"), 1)
        XCTAssertEqual(cycle.count("h:qLate"), 1)
        XCTAssertEqual(qLateBeforeReturn.value, false, "the drainer delivered during the borrowed scope")
        XCTAssertEqual(cycle.thread(of: "h:qLate"), cycle.p.value, "the last borrowed-scope exit did not deliver")
        if let late = cycle.index("h:qLate"), let end = cycle.index("body-end"), let q0 = cycle.index("h:q0") {
            XCTAssertGreaterThan(late, end)
            XCTAssertGreaterThan(late, q0)
        } else {
            XCTFail("missing events: \(cycle.events.value)")
        }
    }

    /// spec/03 §4.2 rule 1. Two threads borrow h. A waiter W records a wait
    /// for borrower B2. When B2 exits while B1 still borrows, W's edge to B2
    /// goes and W waits again for B1. B2 then sends on a hub that W drains.
    /// That wait closes no live cycle, so B2's send stays synchronous instead
    /// of taking the refused-wait escape on W's stale edge.
    func testPartialBorrowerExitRetargetsTheWaiters() {
        let h = MessageHub()   // borrowed by B2, then by B1
        let a = MessageHub()   // B2 drains it; D waits for B2 on it
        let b = MessageHub()   // B1 drains it; B2 waits for B1 on it
        let c = MessageHub()   // W drains it
        let d = BorrowBox<UInt64>(0), b1 = BorrowBox<UInt64>(0)
        let b2 = BorrowBox<UInt64>(0), w = BorrowBox<UInt64>(0)
        let phase = BorrowBox("")
        let dWaiting = DispatchSemaphore(value: 0)
        let wWaiting = DispatchSemaphore(value: 0)
        let b2WaitingForB1 = DispatchSemaphore(value: 0)
        let b2WaitingForW = DispatchSemaphore(value: 0)
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            guard accepted else { return }
            if caller == d.value { dWaiting.signal() }
            if caller == w.value { wWaiting.signal() }
            if caller == b2.value, phase.value == "b2-on-b" { b2WaitingForB1.signal() }
            if caller == b2.value, phase.value == "b2-on-c" { b2WaitingForW.signal() }
        }
        defer { ThreadWaitGraph.shared.onWaitDecidedForTesting = nil }
        func msg(_ name: String) -> PropertyChangedMessage {
            PropertyChangedMessage(sender: NSObject(), senderName: "hub", propertyName: name)
        }
        func name(_ message: any Message) -> String? { (message as? PropertyChangedMessage)?.propertyName }

        let b1Draining = DispatchSemaphore(value: 0)
        let b2Draining = DispatchSemaphore(value: 0)
        let dBatchReturned = DispatchSemaphore(value: 0)
        let b2Exited = DispatchSemaphore(value: 0)
        let xDelivered = BorrowBox(false)
        let xBeforeReturn = BorrowBox<Bool?>(nil)
        var subscriptions: [AnyCancellable] = []
        // B2's a subscriber: borrow h (D, its batch owner, waits for B2).
        subscriptions.append(a.messages.sink { message in
            guard name(message) == "a0" else { return }
            b2Draining.signal()
            _ = dWaiting.wait(timeout: .now() + hangGuard)
            try? h.batch {
                a.dispose()
                _ = dBatchReturned.wait(timeout: .now() + hangGuard)
                Thread.detachNewThread {
                    w.value = ThreadWaitGraph.currentThread
                    c.send(msg("c0"))
                }
                _ = wWaiting.wait(timeout: .now() + hangGuard)
                phase.value = "b2-on-b"
                b.send(msg("b0"))
            }
            b2Exited.signal()
        })
        // B1's b subscriber: borrow h (B2, the only borrower, waits for B1).
        subscriptions.append(b.messages.sink { message in
            guard name(message) == "b1" else { return }
            b1Draining.signal()
            _ = b2WaitingForB1.wait(timeout: .now() + hangGuard)
            try? h.batch {
                b.dispose()
                _ = b2Exited.wait(timeout: .now() + hangGuard)
                // Hold the last borrowed scope until B2's send has decided.
                _ = b2WaitingForW.wait(timeout: .now() + hangGuard)
            }
        })
        // W's c subscriber: send on h, which waits for a borrower.
        subscriptions.append(c.messages.sink { message in
            if name(message) == "c0" { h.send(msg("w")) }
            if name(message) == "x" { xDelivered.value = true }
        })
        defer { subscriptions.forEach { $0.cancel() } }

        let b1Done = DispatchSemaphore(value: 0)
        let b2Done = DispatchSemaphore(value: 0)
        let dDone = DispatchSemaphore(value: 0)
        Thread.detachNewThread {
            b1.value = ThreadWaitGraph.currentThread
            b.send(msg("b1"))
            b1Done.signal()
        }
        XCTAssertEqual(b1Draining.wait(timeout: .now() + hangGuard), .success)
        Thread.detachNewThread {
            b2.value = ThreadWaitGraph.currentThread
            a.send(msg("a0"))
            phase.value = "b2-on-c"
            c.send(msg("x"))
            xBeforeReturn.value = xDelivered.value
            b2Done.signal()
        }
        XCTAssertEqual(b2Draining.wait(timeout: .now() + hangGuard), .success)
        Thread.detachNewThread {
            d.value = ThreadWaitGraph.currentThread
            try? h.batch { a.send(msg("d")) }
            dBatchReturned.signal()
            dDone.signal()
        }

        XCTAssertEqual(dDone.wait(timeout: .now() + hangGuard), .success, "D hung")
        XCTAssertEqual(b2Done.wait(timeout: .now() + hangGuard), .success, "B2 hung")
        XCTAssertEqual(b1Done.wait(timeout: .now() + hangGuard), .success, "B1 hung")
        XCTAssertEqual(xBeforeReturn.value, true, "B2's send escaped on a stale edge to W")
    }

    /// spec/03 §4.2 rule 2, with no cycle through the drainer. D drains h,
    /// and its h subscriber sends on h2, which B batch-owns, so B's h batch
    /// borrows h. B disposes h2, so D's subscriber returns with D's queue
    /// empty. B does not wait for D, so D's wait for the borrowed scope would
    /// close no cycle: D must release the drain instead of waiting, and its
    /// outermost send returns while B's borrowed scope is still open.
    func testEmptyQueueDrainerReturnsWhileTheBorrowedScopeIsOpen() {
        let h = MessageHub()
        let h2 = MessageHub()
        let d = BorrowBox<UInt64>(0)
        let dWaiting = DispatchSemaphore(value: 0)
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            if accepted, caller == d.value { dWaiting.signal() }
        }
        defer { ThreadWaitGraph.shared.onWaitDecidedForTesting = nil }
        func msg(_ name: String) -> PropertyChangedMessage {
            PropertyChangedMessage(sender: NSObject(), senderName: "hub", propertyName: name)
        }
        let subscription = h.messages.sink { message in
            guard (message as? PropertyChangedMessage)?.propertyName == "m1" else { return }
            h2.send(msg("x"))
        }
        defer { subscription.cancel() }
        let bOwnsH2 = DispatchSemaphore(value: 0)
        let dReturned = DispatchSemaphore(value: 0)
        let bDone = DispatchSemaphore(value: 0)
        let dDone = DispatchSemaphore(value: 0)
        let returnedDuringBorrow = BorrowBox<Bool?>(nil)
        Thread.detachNewThread {
            try? h2.batch {
                bOwnsH2.signal()
                _ = dWaiting.wait(timeout: .now() + hangGuard)
                try? h.batch {
                    h2.dispose()
                    returnedDuringBorrow.value = dReturned.wait(timeout: .now() + hangGuard) == .success
                }
            }
            bDone.signal()
        }
        XCTAssertEqual(bOwnsH2.wait(timeout: .now() + hangGuard), .success)
        Thread.detachNewThread {
            d.value = ThreadWaitGraph.currentThread
            h.send(msg("m1"))
            dReturned.signal()
            dDone.signal()
        }

        XCTAssertEqual(bDone.wait(timeout: .now() + hangGuard * 3), .success, "B hung")
        XCTAssertEqual(dDone.wait(timeout: .now() + hangGuard), .success, "D hung")
        XCTAssertEqual(
            returnedDuringBorrow.value, true,
            "the drainer waited for the borrowed scope with an empty queue"
        )
        h.dispose()
    }

    /// spec/03 §4.2 rule 3 with a batch owner. O batch-owns h, and its body
    /// sends on h2, which B batch-owns, so B's h batch borrows h. B disposes
    /// h in the borrowed body. The last of O and B to release h completes it:
    /// O's batch exits first when B exits last, and otherwise stays open
    /// until B's borrowed scope has exited.
    func testABorrowersDisposeIsFinishedByTheLastOwnerToReleaseTheHub() {
        for borrowerExitsLast in [true, false] {
            let label = borrowerExitsLast ? "borrower exits last" : "batch owner exits last"
            let h = MessageHub()
            let h2 = MessageHub()
            let o = BorrowBox<UInt64>(0)
            let b = BorrowBox<UInt64>(0)
            let oWaiting = DispatchSemaphore(value: 0)
            ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
                if accepted, caller == o.value { oWaiting.signal() }
            }
            let completedOn = BorrowBox<[UInt64]>([])
            let subscription = h.messages.sink(
                receiveCompletion: { _ in
                    let thread = ThreadWaitGraph.currentThread
                    completedOn.mutate { $0.append(thread) }
                },
                receiveValue: { _ in }
            )
            let bOwnsH2 = DispatchSemaphore(value: 0)
            let oReturned = DispatchSemaphore(value: 0)
            let bDone = DispatchSemaphore(value: 0)
            let oDone = DispatchSemaphore(value: 0)
            let completedBeforeBExit = BorrowBox<[UInt64]?>(nil)
            Thread.detachNewThread {
                b.value = ThreadWaitGraph.currentThread
                try? h2.batch {
                    bOwnsH2.signal()
                    XCTAssertEqual(
                        oWaiting.wait(timeout: .now() + hangGuard), .success,
                        "\(label): O never waited for B's h2 batch"
                    )
                    try? h.batch {
                        h.dispose()
                        guard borrowerExitsLast else { return }
                        // Releasing h2 lets O's h batch exit inside this borrow.
                        h2.dispose()
                        _ = oReturned.wait(timeout: .now() + hangGuard)
                        completedBeforeBExit.value = completedOn.value
                    }
                    if !borrowerExitsLast { completedBeforeBExit.value = completedOn.value }
                }
                bDone.signal()
            }
            XCTAssertEqual(bOwnsH2.wait(timeout: .now() + hangGuard), .success, label)
            Thread.detachNewThread {
                o.value = ThreadWaitGraph.currentThread
                try? h.batch {
                    h2.send(PropertyChangedMessage(sender: NSObject(), senderName: "hub", propertyName: "x"))
                }
                oReturned.signal()
                oDone.signal()
            }

            XCTAssertEqual(bDone.wait(timeout: .now() + hangGuard * 2), .success, "\(label): B hung")
            XCTAssertEqual(oDone.wait(timeout: .now() + hangGuard), .success, "\(label): O hung")
            XCTAssertEqual(completedBeforeBExit.value, [], "\(label): h completed too early")
            XCTAssertEqual(completedOn.value, [borrowerExitsLast ? b.value : o.value], label)
            subscription.cancel()
            ThreadWaitGraph.shared.onWaitDecidedForTesting = nil
        }
    }

    /// spec/03 §4.2 rule 3 with a drainer. D drains h, and D's h subscriber
    /// sends on h2, which B batch-owns, so D waits for B. B's h batch would
    /// close a cycle by waiting for D, so it borrows h. B disposes h in the
    /// borrowed body and exits it while D is still inside its subscriber. The
    /// borrowed exit leaves the disposal to D, whose drain completes h after
    /// the subscriber returns, as in C#, Python and Rust.
    func testABorrowersDisposeIsFinishedByTheDrainerThatIsStillDelivering() {
        let h = MessageHub()
        let h2 = MessageHub()
        let d = BorrowBox<UInt64>(0)
        let dWaiting = DispatchSemaphore(value: 0)
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            if accepted, caller == d.value { dWaiting.signal() }
        }
        defer { ThreadWaitGraph.shared.onWaitDecidedForTesting = nil }
        let inHandler = BorrowBox<Bool>(false)
        let completed = BorrowBox<[(UInt64, Bool)]>([])
        let subscription = h.messages.sink(
            receiveCompletion: { _ in
                let entry = (ThreadWaitGraph.currentThread, inHandler.value)
                completed.mutate { $0.append(entry) }
            },
            receiveValue: { _ in
                inHandler.value = true
                h2.send(PropertyChangedMessage(sender: NSObject(), senderName: "hub", propertyName: "forwarded"))
                inHandler.value = false
            }
        )
        let bOwnsH2 = DispatchSemaphore(value: 0)
        let bDone = DispatchSemaphore(value: 0)
        let dDone = DispatchSemaphore(value: 0)
        let completedAfterBorrow = BorrowBox<Int>(-1)
        Thread.detachNewThread {
            try? h2.batch {
                bOwnsH2.signal()
                XCTAssertEqual(
                    dWaiting.wait(timeout: .now() + hangGuard), .success,
                    "D never waited for B's h2 batch"
                )
                try? h.batch { h.dispose() }
                completedAfterBorrow.value = completed.value.count
            }
            bDone.signal()
        }
        XCTAssertEqual(bOwnsH2.wait(timeout: .now() + hangGuard), .success)
        Thread.detachNewThread {
            d.value = ThreadWaitGraph.currentThread
            h.send(PropertyChangedMessage(sender: NSObject(), senderName: "hub", propertyName: "m"))
            dDone.signal()
        }

        XCTAssertEqual(bDone.wait(timeout: .now() + hangGuard * 2), .success, "B hung")
        XCTAssertEqual(dDone.wait(timeout: .now() + hangGuard), .success, "D hung")
        XCTAssertEqual(completedAfterBorrow.value, 0, "B's borrow exit completed h while D was delivering")
        XCTAssertEqual(completed.value.map(\.0), [d.value])
        XCTAssertEqual(completed.value.map(\.1), [false], "h completed inside D's in-flight delivery")
        subscription.cancel()
    }

    /// #1223. The batch owner's nested batch waits for another thread's
    /// borrowed scope with an edge, like any other batch (spec/03 §4.1, §4.2
    /// rule 3), as in C#, Python and Rust. O batch-owns h, and its body sends
    /// on h2, which B batch-owns, so B's h batch borrows h. B disposes h2,
    /// which releases O. O's nested batch body starts only after B's borrowed
    /// scope exits.
    func testABatchOwnersNestedBatchWaitsForABorrowedScope() {
        let h = MessageHub()
        let h2 = MessageHub()
        let o = BorrowBox<UInt64>(0)
        let oWaiting = DispatchSemaphore(value: 0)
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            if accepted, caller == o.value { oWaiting.signal() }
        }
        defer { ThreadWaitGraph.shared.onWaitDecidedForTesting = nil }
        func msg(_ name: String) -> PropertyChangedMessage {
            PropertyChangedMessage(sender: NSObject(), senderName: "hub", propertyName: name)
        }
        let names = BorrowBox<[String]>([])
        let subscription = h.messages.sink { message in
            guard let name = (message as? PropertyChangedMessage)?.propertyName else { return }
            names.mutate { $0.append(name) }
        }
        defer { subscription.cancel() }
        let bOwnsH2 = DispatchSemaphore(value: 0)
        let bDone = DispatchSemaphore(value: 0)
        let oDone = DispatchSemaphore(value: 0)
        let borrowDone = BorrowBox(false)
        let nestedSawExit = BorrowBox<Bool?>(nil)
        Thread.detachNewThread {
            try? h2.batch {
                bOwnsH2.signal()
                XCTAssertEqual(
                    oWaiting.wait(timeout: .now() + hangGuard), .success,
                    "O never waited for B's h2 batch"
                )
                try? h.batch {
                    h.send(msg("b1"))
                    h2.dispose()
                    // Hold the borrowed scope until O waits for it, or until
                    // hangGuard elapses. O's accepted wait edge ends it early.
                    _ = oWaiting.wait(timeout: .now() + hangGuard)
                    borrowDone.value = true
                }
            }
            bDone.signal()
        }
        XCTAssertEqual(bOwnsH2.wait(timeout: .now() + hangGuard), .success)
        Thread.detachNewThread {
            o.value = ThreadWaitGraph.currentThread
            try? h.batch {
                h2.send(msg("x"))
                try? h.batch {
                    nestedSawExit.value = borrowDone.value
                    h.send(msg("o1"))
                }
                h.send(msg("o2"))
            }
            oDone.signal()
        }

        XCTAssertEqual(bDone.wait(timeout: .now() + hangGuard * 2), .success, "B hung")
        XCTAssertEqual(oDone.wait(timeout: .now() + hangGuard), .success, "O hung")
        XCTAssertEqual(
            nestedSawExit.value, true,
            "the batch owner's nested batch ran inside another thread's borrowed scope"
        )
        XCTAssertEqual(names.value, ["b1", "o1", "o2"])
    }

    /// #1223. The borrower B waits for the batch owner O through h3. O's
    /// nested h batch would wait for B, which closes the cycle, so that wait
    /// is refused and the nested batch enters a borrowed scope (spec/03 §4.1),
    /// as in C#, Python and Rust. Neither thread hangs.
    func testABatchOwnersCyclicNestedBatchBorrows() {
        let h = MessageHub()
        let h2 = MessageHub()
        let h3 = MessageHub()
        let o = BorrowBox<UInt64>(0)
        let b = BorrowBox<UInt64>(0)
        let oWaiting = DispatchSemaphore(value: 0)
        let bWaiting = DispatchSemaphore(value: 0)
        let oRefusals = BorrowBox(0)
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            if caller == o.value {
                if accepted { oWaiting.signal() } else { oRefusals.mutate { $0 += 1 } }
            }
            if accepted, caller == b.value { bWaiting.signal() }
        }
        defer { ThreadWaitGraph.shared.onWaitDecidedForTesting = nil }
        func msg(_ name: String) -> PropertyChangedMessage {
            PropertyChangedMessage(sender: NSObject(), senderName: "hub", propertyName: name)
        }
        func counter(_ hub: MessageHub, _ name: String, _ box: BorrowBox<Int>) -> AnyCancellable {
            hub.messages.sink { message in
                if (message as? PropertyChangedMessage)?.propertyName == name { box.mutate { $0 += 1 } }
            }
        }
        let o1 = BorrowBox(0)
        let b3 = BorrowBox(0)
        let subscriptions = [counter(h, "o1", o1), counter(h3, "b3", b3)]
        defer { subscriptions.forEach { $0.cancel() } }
        let bOwnsH2 = DispatchSemaphore(value: 0)
        let bDone = DispatchSemaphore(value: 0)
        let oDone = DispatchSemaphore(value: 0)
        let nestedRefused = BorrowBox<Bool?>(nil)
        Thread.detachNewThread {
            b.value = ThreadWaitGraph.currentThread
            try? h2.batch {
                bOwnsH2.signal()
                XCTAssertEqual(
                    oWaiting.wait(timeout: .now() + hangGuard), .success,
                    "O never waited for B's h2 batch"
                )
                try? h.batch {
                    h2.dispose()
                    // Waits for O's h3 batch, unless that wait closes a cycle.
                    h3.send(msg("b3"))
                }
            }
            bDone.signal()
        }
        XCTAssertEqual(bOwnsH2.wait(timeout: .now() + hangGuard), .success)
        Thread.detachNewThread {
            o.value = ThreadWaitGraph.currentThread
            try? h3.batch {
                try? h.batch {
                    h2.send(msg("x"))
                    XCTAssertEqual(
                        bWaiting.wait(timeout: .now() + hangGuard), .success,
                        "B never waited for O's h3 batch"
                    )
                    let refusalsBefore = oRefusals.value
                    try? h.batch {
                        nestedRefused.value = oRefusals.value == refusalsBefore + 1
                        h.send(msg("o1"))
                    }
                }
            }
            oDone.signal()
        }

        XCTAssertEqual(bDone.wait(timeout: .now() + hangGuard * 2), .success, "B hung")
        XCTAssertEqual(oDone.wait(timeout: .now() + hangGuard), .success, "O hung")
        XCTAssertEqual(nestedRefused.value, true, "the nested batch did not take the refused-wait borrow")
        XCTAssertEqual(o1.value, 1)
        XCTAssertEqual(b3.value, 1)
    }

    /// #1230. A borrower's batch on a disposed hub runs its body with no new
    /// borrowed scope, as in C#, Python and Rust (spec/03 §3.3, §4.2 rule 3).
    /// O batch-owns h, and its body sends on h2, which B batch-owns, so B's
    /// h batch borrows h. B disposes h in the borrowed body and then calls
    /// `batch`. B releases O, so h completes once, at B's outer exit.
    func testABorrowersBatchOnADisposedHubOpensNoScope() {
        let h = MessageHub()
        let h2 = MessageHub()
        let o = BorrowBox<UInt64>(0)
        let b = BorrowBox<UInt64>(0)
        let oWaiting = DispatchSemaphore(value: 0)
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            if accepted, caller == o.value { oWaiting.signal() }
        }
        defer { ThreadWaitGraph.shared.onWaitDecidedForTesting = nil }
        let completedOn = BorrowBox<[UInt64]>([])
        let subscription = h.messages.sink(
            receiveCompletion: { _ in
                let thread = ThreadWaitGraph.currentThread
                completedOn.mutate { $0.append(thread) }
            },
            receiveValue: { _ in }
        )
        defer { subscription.cancel() }
        let bOwnsH2 = DispatchSemaphore(value: 0)
        let oReturned = DispatchSemaphore(value: 0)
        let bDone = DispatchSemaphore(value: 0)
        let oDone = DispatchSemaphore(value: 0)
        let depthBefore = BorrowBox<Int?>(nil)
        let depthInBody = BorrowBox<Int?>(nil)
        let oReturnedInBorrow = BorrowBox<Bool?>(nil)
        let completedBeforeBExit = BorrowBox<[UInt64]?>(nil)
        Thread.detachNewThread {
            b.value = ThreadWaitGraph.currentThread
            try? h2.batch {
                bOwnsH2.signal()
                XCTAssertEqual(
                    oWaiting.wait(timeout: .now() + hangGuard), .success,
                    "O never waited for B's h2 batch"
                )
                try? h.batch {
                    h.dispose()
                    depthBefore.value = h.borrowedScopeDepthForTesting
                    try? h.batch { depthInBody.value = h.borrowedScopeDepthForTesting }
                    // Releasing h2 lets O's h batch exit inside this borrow.
                    h2.dispose()
                    oReturnedInBorrow.value = oReturned.wait(timeout: .now() + hangGuard) == .success
                    completedBeforeBExit.value = completedOn.value
                }
            }
            bDone.signal()
        }
        XCTAssertEqual(bOwnsH2.wait(timeout: .now() + hangGuard), .success)
        Thread.detachNewThread {
            o.value = ThreadWaitGraph.currentThread
            try? h.batch {
                h2.send(PropertyChangedMessage(sender: NSObject(), senderName: "hub", propertyName: "x"))
            }
            oReturned.signal()
            oDone.signal()
        }

        XCTAssertEqual(bDone.wait(timeout: .now() + hangGuard * 2), .success, "B hung")
        XCTAssertEqual(oDone.wait(timeout: .now() + hangGuard), .success, "O hung")
        XCTAssertEqual(depthBefore.value, 1)
        XCTAssertEqual(depthInBody.value, 1, "the batch on the disposed hub opened a borrowed scope")
        XCTAssertEqual(oReturnedInBorrow.value, true, "O's h batch did not exit inside B's borrow")
        XCTAssertEqual(completedBeforeBExit.value, [], "h completed before B's outer borrowed scope exited")
        XCTAssertEqual(completedOn.value, [b.value], "h did not complete once, at B's outer exit")
        XCTAssertEqual(h.borrowedScopeDepthForTesting, 0)
    }
}
