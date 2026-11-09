//
// DelayedTaskTests.swift — DelayedTask edge cases beyond DLY-001..DLY-005.
//
// See spec/11-threading.md §6.3 and ADR-0219.
//
import XCTest
import Combine
@testable import VMx

private final class RunCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var storage = 0

    func increment() {
        lock.lock()
        storage += 1
        lock.unlock()
    }

    var value: Int {
        lock.lock()
        defer { lock.unlock() }
        return storage
    }
}

final class DelayedTaskTests: XCTestCase {

    func testZeroAndNegativeDelaysRunAtTheNextOpportunityNotInsideSchedule() {
        let scheduler = VirtualTimeScheduler(now: 4)
        let task = DelayedTask(scheduler: scheduler)
        var runTimes: [Double] = []

        task.schedule(after: 0) { runTimes.append(scheduler.now.seconds) }
        XCTAssertEqual(runTimes, [])
        XCTAssertTrue(task.isPending)
        scheduler.advance(by: .seconds(0))
        XCTAssertEqual(runTimes, [4])

        task.schedule(after: -3) { runTimes.append(scheduler.now.seconds) }
        XCTAssertEqual(runTimes, [4])
        XCTAssertTrue(task.isPending)
        scheduler.advance(by: .seconds(0))
        XCTAssertEqual(runTimes, [4, 4])
        XCTAssertFalse(task.isPending)
    }

    func testSchedulesFromManyThreadsLeaveOnePendingAction() {
        let scheduler = VirtualTimeScheduler()
        let task = DelayedTask(scheduler: scheduler)
        let runs = RunCounter()

        DispatchQueue.concurrentPerform(iterations: 64) { _ in
            task.schedule(after: 1) { runs.increment() }
        }
        XCTAssertTrue(task.isPending)
        scheduler.advance(by: .seconds(2))

        XCTAssertEqual(runs.value, 1)
        XCTAssertFalse(task.isPending)
    }

    func testCancelFromManyThreadsLeavesNoPendingAction() {
        let scheduler = VirtualTimeScheduler()
        let task = DelayedTask(scheduler: scheduler)
        let runs = RunCounter()

        DispatchQueue.concurrentPerform(iterations: 64) { index in
            if index.isMultiple(of: 2) {
                task.schedule(after: 1) { runs.increment() }
            } else {
                task.cancel()
            }
        }
        task.cancel()
        scheduler.advance(by: .seconds(2))

        XCTAssertEqual(runs.value, 0)
        XCTAssertFalse(task.isPending)
    }

    func testReleasingTheTaskCancelsItsPendingAction() {
        let scheduler = VirtualTimeScheduler()
        var runs = 0
        var task: DelayedTask? = DelayedTask(scheduler: scheduler)
        weak var weakTask = task
        task?.schedule(after: 1) { runs += 1 }

        task = nil
        XCTAssertNil(weakTask)
        scheduler.advance(by: .seconds(2))

        XCTAssertEqual(runs, 0)
    }

    func testDisposeDoesNotDisposeTheScheduler() {
        let scheduler = VirtualTimeScheduler()
        let first = DelayedTask(scheduler: scheduler)
        let second = DelayedTask(scheduler: scheduler)
        var secondRuns = 0
        first.schedule(after: 1) {}
        second.schedule(after: 1) { secondRuns += 1 }

        first.dispose()
        scheduler.advance(by: .seconds(1))

        XCTAssertEqual(secondRuns, 1)
    }

    func testPollsInRealTimeOnADispatchQueue() {
        let queue = DispatchQueue(label: "vmx.delayed-task.test")
        let task = DelayedTask(scheduler: queue)
        let runs = RunCounter()
        let done = expectation(description: "three polls")
        func poll() {
            runs.increment()
            if runs.value < 3 {
                task.schedule(after: 0.01, poll)
            } else {
                done.fulfill()
            }
        }
        task.schedule(after: 0.01, poll)

        wait(for: [done], timeout: 5)
        XCTAssertEqual(runs.value, 3)
        XCTAssertFalse(task.isPending)
    }

    func testCancelledActionDoesNotRunOnADispatchQueue() {
        let queue = DispatchQueue(label: "vmx.delayed-task.cancel")
        let task = DelayedTask(scheduler: queue)
        let runs = RunCounter()
        task.schedule(after: 0.05) { runs.increment() }
        task.cancel()

        let later = expectation(description: "past due time")
        queue.asyncAfter(deadline: .now() + 0.2) { later.fulfill() }
        wait(for: [later], timeout: 5)

        XCTAssertEqual(runs.value, 0)
    }
}
