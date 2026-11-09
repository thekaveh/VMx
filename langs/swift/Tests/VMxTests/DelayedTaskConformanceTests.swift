//
// DelayedTaskConformanceTests.swift — DLY-001..DLY-005.
//
// See spec/11-threading.md §6.3, spec/12-conformance.md §33 and ADR-0219.
// Each test drives a `DelayedTask` over a `VirtualTimeScheduler` and moves
// time with `advance(by:)`.
//
import XCTest
import Combine
@testable import VMx

final class DelayedTaskConformanceTests: XCTestCase {

    /// DLY-001 — a scheduled action runs once at its due time.
    func testDly001ScheduledActionRunsOnceAtItsDueTime() {
        let scheduler = VirtualTimeScheduler()
        let task = DelayedTask(scheduler: scheduler)
        var runs = 0
        var pendingInsideAction: Bool?
        task.schedule(after: 10) {
            runs += 1
            pendingInsideAction = task.isPending
        }
        XCTAssertTrue(task.isPending)

        scheduler.advance(by: .seconds(9))
        XCTAssertEqual(runs, 0)
        XCTAssertTrue(task.isPending)

        scheduler.advance(by: .seconds(1))
        XCTAssertEqual(runs, 1)
        XCTAssertEqual(pendingInsideAction, false)
        XCTAssertFalse(task.isPending)

        scheduler.advance(by: .seconds(10))
        XCTAssertEqual(runs, 1)
    }

    /// DLY-001 — an action that schedules itself again repeats a polling loop.
    func testDly001ActionThatReschedulesItselfPolls() {
        let scheduler = VirtualTimeScheduler()
        let task = DelayedTask(scheduler: scheduler)
        var runTimes: [Double] = []
        func poll() {
            runTimes.append(scheduler.now.seconds)
            if runTimes.count < 3 { task.schedule(after: 5, poll) }
        }
        task.schedule(after: 5, poll)

        scheduler.advance(by: .seconds(30))

        XCTAssertEqual(runTimes, [5, 10, 15])
        XCTAssertFalse(task.isPending)
    }

    /// DLY-002 — a second schedule replaces the pending action and restarts the delay.
    func testDly002SecondScheduleReplacesPendingActionAndRestartsDelay() {
        let scheduler = VirtualTimeScheduler()
        let task = DelayedTask(scheduler: scheduler)
        var aRuns = 0
        var bRuns = 0
        task.schedule(after: 10) { aRuns += 1 }
        scheduler.advance(by: .seconds(6))
        task.schedule(after: 10) { bRuns += 1 }

        scheduler.advance(by: .seconds(9))
        XCTAssertEqual(scheduler.now.seconds, 15)
        XCTAssertEqual(aRuns, 0)
        XCTAssertEqual(bRuns, 0)
        XCTAssertTrue(task.isPending)

        scheduler.advance(by: .seconds(1))
        XCTAssertEqual(bRuns, 1)

        scheduler.advance(by: .seconds(10))
        XCTAssertEqual(aRuns, 0)
        XCTAssertEqual(bRuns, 1)
    }

    /// DLY-003 — cancel prevents the pending action.
    func testDly003CancelPreventsPendingAction() {
        let scheduler = VirtualTimeScheduler()
        let task = DelayedTask(scheduler: scheduler)

        task.cancel()
        XCTAssertFalse(task.isPending)

        var cancelledRuns = 0
        task.schedule(after: 10) { cancelledRuns += 1 }
        scheduler.advance(by: .seconds(4))
        task.cancel()
        XCTAssertFalse(task.isPending)
        scheduler.advance(by: .seconds(7))
        XCTAssertEqual(cancelledRuns, 0)

        var newRunTimes: [Double] = []
        task.schedule(after: 10) { newRunTimes.append(scheduler.now.seconds) }
        scheduler.advance(by: .seconds(9))
        XCTAssertEqual(newRunTimes, [])
        scheduler.advance(by: .seconds(1))
        XCTAssertEqual(newRunTimes, [21])
        XCTAssertEqual(cancelledRuns, 0)
    }

    /// DLY-004 — disposal cancels the pending action, and later calls have no effect.
    func testDly004DisposalCancelsPendingActionAndLaterCallsAreInert() {
        let scheduler = VirtualTimeScheduler()
        let task = DelayedTask(scheduler: scheduler)
        var runs = 0
        task.schedule(after: 10) { runs += 1 }

        task.dispose()
        task.dispose()
        XCTAssertFalse(task.isPending)
        scheduler.advance(by: .seconds(11))
        XCTAssertEqual(runs, 0)

        var lateRuns = 0
        task.schedule(after: 1) { lateRuns += 1 }
        XCTAssertFalse(task.isPending)
        task.cancel()
        XCTAssertFalse(task.isPending)
        scheduler.advance(by: .seconds(5))
        XCTAssertEqual(lateRuns, 0)

        var otherRuns = 0
        let other = scheduler.schedule(at: scheduler.now.advanced(by: .seconds(1))) {
            otherRuns += 1
        }
        scheduler.advance(by: .seconds(1))
        XCTAssertEqual(otherRuns, 1)
        other.cancel()
    }

    /// DLY-005 — Swift actions cannot fail: the action is a non-throwing
    /// closure, and the task stays usable after a run.
    func testDly005ActionIsNonThrowingAndTaskStaysUsable() {
        let scheduler = VirtualTimeScheduler()
        let task = DelayedTask(scheduler: scheduler)

        // Compile-time proof: `schedule` takes a non-throwing `() -> Void`.
        let schedule: (TimeInterval, @escaping () -> Void) -> Void = task.schedule(after:_:)

        var firstRuns = 0
        schedule(3) { firstRuns += 1 }
        scheduler.advance(by: .seconds(3))
        XCTAssertEqual(firstRuns, 1)
        XCTAssertFalse(task.isPending)

        var secondRuns = 0
        task.schedule(after: 3) { secondRuns += 1 }
        scheduler.advance(by: .seconds(5))
        XCTAssertEqual(secondRuns, 1)
        XCTAssertEqual(firstRuns, 1)
        XCTAssertFalse(task.isPending)
    }
}
