import Combine
import Foundation
import XCTest
@testable import VMx

private typealias ConcurrentNotification = VMx.Notification

private final class TwoPartyBarrier {
    private let condition = NSCondition()
    private var arrivals = 0

    func rendezvous(timeout: TimeInterval = 1) -> Bool {
        condition.lock()
        defer { condition.unlock() }
        arrivals += 1
        if arrivals == 2 {
            condition.broadcast()
            return true
        }
        let deadline = Date().addingTimeInterval(timeout)
        while arrivals < 2 {
            if !condition.wait(until: deadline) { return false }
        }
        return true
    }
}

private final class OneShotDrainGate {
    let entered = DispatchSemaphore(value: 0)
    let release = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var used = false

    func pause() {
        lock.lock()
        guard !used else {
            lock.unlock()
            return
        }
        used = true
        lock.unlock()
        entered.signal()
        release.wait()
    }
}

private final class EnqueueCounter {
    let second = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var count = 0

    func record() {
        lock.lock()
        count += 1
        let isSecond = count == 2
        lock.unlock()
        if isSecond { second.signal() }
    }
}

private final class PendingTrace {
    private let lock = NSLock()
    private var values: [[ObjectIdentifier]] = []
    private var completionCount = 0

    func append(_ notifications: [ConcurrentNotification]) {
        lock.lock()
        values.append(notifications.map(ObjectIdentifier.init))
        lock.unlock()
    }

    func complete() {
        lock.lock()
        completionCount += 1
        lock.unlock()
    }

    func snapshot() -> ([[ObjectIdentifier]], Int) {
        lock.lock()
        defer { lock.unlock() }
        return (values, completionCount)
    }
}

private final class FailureCounter {
    private let lock = NSLock()
    private var value = 0

    func increment() {
        lock.lock()
        value += 1
        lock.unlock()
    }

    func snapshot() -> Int {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}

final class NotificationHubConcurrencyTests: XCTestCase {
    func testPostThenResolvePublishesInMutationOrder() async {
        let gate = OneShotDrainGate()
        let counter = EnqueueCounter()
        let hub = NotificationHub(
            beforeDeliveryDrain: gate.pause,
            afterDeliveryEnqueued: counter.record
        )
        let notification = ConcurrentNotification(type: .confirmation, message: "ordered")
        let trace = PendingTrace()
        var cancellables = Set<AnyCancellable>()
        hub.pending.sink(
            receiveCompletion: { _ in trace.complete() },
            receiveValue: trace.append
        ).store(in: &cancellables)

        let posted = Task.detached { await hub.post(notification) }
        XCTAssertEqual(gate.entered.wait(timeout: .now() + 1), .success)
        let resolveReturned = expectation(description: "resolve returned")
        DispatchQueue.global().async {
            hub.resolve(notification, .approve)
            resolveReturned.fulfill()
        }
        XCTAssertEqual(counter.second.wait(timeout: .now() + 1), .success)
        let lateTrace = PendingTrace()
        hub.pending.sink(
            receiveCompletion: { _ in lateTrace.complete() },
            receiveValue: lateTrace.append
        ).store(in: &cancellables)
        XCTAssertEqual(lateTrace.snapshot().0, [[]],
                       "a subscriber must replay the current resolved state")
        gate.release.signal()

        await fulfillment(of: [resolveReturned], timeout: 1)
        let reaction = await posted.value
        XCTAssertEqual(reaction, .approve)
        let (values, completions) = trace.snapshot()
        XCTAssertEqual(values, [[], [ObjectIdentifier(notification)], []])
        XCTAssertEqual(completions, 0)
        XCTAssertEqual(lateTrace.snapshot().0, [[]],
                       "a new subscriber must not receive pre-subscription history")

        let late = expectation(description: "late snapshot")
        var replay: [ConcurrentNotification]?
        hub.pending.prefix(1).sink { value in
            replay = value
            late.fulfill()
        }.store(in: &cancellables)
        await fulfillment(of: [late], timeout: 1)
        XCTAssertEqual(replay?.count, 0)
    }

    func testPostThenDisposePublishesSnapshotBeforeCompletion() async {
        let gate = OneShotDrainGate()
        let counter = EnqueueCounter()
        let hub = NotificationHub(
            beforeDeliveryDrain: gate.pause,
            afterDeliveryEnqueued: counter.record
        )
        let notification = ConcurrentNotification(type: .notification, message: "dispose")
        let trace = PendingTrace()
        var cancellables = Set<AnyCancellable>()
        hub.pending.sink(
            receiveCompletion: { _ in trace.complete() },
            receiveValue: trace.append
        ).store(in: &cancellables)

        let posted = Task.detached { await hub.post(notification) }
        XCTAssertEqual(gate.entered.wait(timeout: .now() + 1), .success)
        let disposeReturned = expectation(description: "dispose returned")
        DispatchQueue.global().async {
            hub.dispose()
            disposeReturned.fulfill()
        }
        XCTAssertEqual(counter.second.wait(timeout: .now() + 1), .success)
        gate.release.signal()

        await fulfillment(of: [disposeReturned], timeout: 1)
        let reaction = await posted.value
        XCTAssertEqual(reaction, .pending)
        let (values, completions) = trace.snapshot()
        XCTAssertEqual(values, [[], [ObjectIdentifier(notification)]])
        XCTAssertEqual(completions, 1)
    }

    func testReentrantResolveDrainsAfterCurrentSnapshot() async {
        let hub = NotificationHub()
        let notification = ConcurrentNotification(type: .confirmation, message: "reentrant")
        let trace = PendingTrace()
        var cancellables = Set<AnyCancellable>()
        hub.pending.sink { snapshot in
            trace.append(snapshot)
            if snapshot.contains(where: { $0 === notification }) {
                hub.resolve(notification, .reject)
            }
        }.store(in: &cancellables)

        let reaction = await hub.post(notification)
        XCTAssertEqual(reaction, .reject)
        let (values, completions) = trace.snapshot()
        XCTAssertEqual(values, [[], [ObjectIdentifier(notification)], []])
        XCTAssertEqual(completions, 0)
    }

    func testOpposingHubCallbacksResolveWithoutDeadlock() async {
        let hubA = NotificationHub()
        let hubB = NotificationHub()
        let notificationA = ConcurrentNotification(type: .confirmation, message: "a")
        let notificationB = ConcurrentNotification(type: .confirmation, message: "b")
        let barrier = TwoPartyBarrier()
        let callbacksEntered = expectation(description: "both pending callbacks entered")
        callbacksEntered.expectedFulfillmentCount = 2
        let reactionsCompleted = expectation(description: "both posts resolved")
        let barrierFailures = FailureCounter()
        var cancellables = Set<AnyCancellable>()

        hubA.pending.sink { snapshot in
            guard snapshot.contains(where: { $0 === notificationA }) else { return }
            callbacksEntered.fulfill()
            if !barrier.rendezvous() {
                barrierFailures.increment()
                return
            }
            hubB.resolve(notificationB, .reject)
        }.store(in: &cancellables)
        hubB.pending.sink { snapshot in
            guard snapshot.contains(where: { $0 === notificationB }) else { return }
            callbacksEntered.fulfill()
            if !barrier.rendezvous() {
                barrierFailures.increment()
                return
            }
            hubA.resolve(notificationA, .approve)
        }.store(in: &cancellables)

        let postA = Task.detached { await hubA.post(notificationA) }
        let postB = Task.detached { await hubB.post(notificationB) }
        Task {
            let reactionA = await postA.value
            let reactionB = await postB.value
            XCTAssertEqual(reactionA, .approve)
            XCTAssertEqual(reactionB, .reject)
            reactionsCompleted.fulfill()
        }

        await fulfillment(of: [callbacksEntered, reactionsCompleted], timeout: 2)
        XCTAssertEqual(barrierFailures.snapshot(), 0)
    }
}
