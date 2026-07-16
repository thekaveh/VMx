import Combine
import XCTest
@testable import VMx

final class VirtualTimeSchedulerTests: XCTestCase {
    func testOverdueWorkDoesNotMoveVirtualTimeBackward() {
        let scheduler = VirtualTimeScheduler()
        scheduler.advance(toSeconds: 10)
        var observed = -1.0
        let token = scheduler.schedule(at: .init(5)) {
            observed = scheduler.now.seconds
        }

        scheduler.advance(toSeconds: 20)

        XCTAssertEqual(observed, 10)
        XCTAssertEqual(scheduler.now.seconds, 20)
        withExtendedLifetime(token) {}
    }

    func testVoidReturningScheduleRetainsWorkUntilAdvance() {
        let scheduler = VirtualTimeScheduler()
        var calls = 0

        scheduler.schedule(options: nil) { calls += 1 }
        scheduler.advance(toSeconds: 0)

        XCTAssertEqual(calls, 1)
    }

    func testCancellationBeforeAdmissionPreventsExecution() {
        let scheduler = VirtualTimeScheduler()
        var calls = 0
        let token = scheduler.schedule(at: .init(1)) { calls += 1 }

        token.cancel()
        scheduler.advance(toSeconds: 1)

        XCTAssertEqual(calls, 0)
    }
}
