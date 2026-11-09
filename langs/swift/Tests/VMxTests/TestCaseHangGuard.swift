//
// Ends a single-process test run when one test case hangs (#1461).
//
// `swift test --parallel` runs each case in its own process. A single-process
// `swift test` (a local run, or the CI coverage job) runs every case in one
// process. There, a case that never returns, or a worker it leaves blocked on
// a process-wide lock such as the shared composite selection coordinator, would
// stop the run with no bound. The guard arms a timer when each case starts and
// cancels it when the case finishes. When the timer fires, it prints the
// case's name and ends the process with a failure status.
//
// `VMX_TEST_CASE_TIMEOUT_SECONDS` overrides the default bound of 300 s.
//
import XCTest
import Foundation

final class TestCaseHangGuard: NSObject, XCTestObservation, @unchecked Sendable {
    static let seconds: Int = {
        let text = ProcessInfo.processInfo.environment["VMX_TEST_CASE_TIMEOUT_SECONDS"] ?? ""
        return Int(text).flatMap { $0 > 0 ? $0 : nil } ?? 300
    }()

    private static let installation: TestCaseHangGuard = {
        let guardian = TestCaseHangGuard()
        XCTestObservationCenter.shared.addTestObserver(guardian)
        return guardian
    }()

    /// Registers the guard once per process.
    static func install() { _ = installation }

    private static let queue = DispatchQueue(label: "vmx.tests.case-hang-guard")
    private static var startedCases = 0

    /// The cases whose start the guard has seen in this process.
    static var observedCases: Int { queue.sync { startedCases } }

    private var timer: DispatchSourceTimer?

    func testCaseWillStart(_ testCase: XCTestCase) {
        let name = testCase.name
        let seconds = Self.seconds
        let queue = Self.queue
        queue.sync {
            Self.startedCases += 1
            timer?.cancel()
            let timer = DispatchSource.makeTimerSource(queue: queue)
            timer.schedule(deadline: .now() + .seconds(seconds))
            timer.setEventHandler {
                fputs(
                    "error: Test Case '\(name)' did not finish within \(seconds) s; "
                        + "ending the test process (#1461).\n",
                    stderr
                )
                fflush(stdout)
                fflush(stderr)
                _exit(EXIT_FAILURE)
            }
            timer.resume()
            self.timer = timer
        }
    }

    func testCaseDidFinish(_ testCase: XCTestCase) {
        Self.queue.sync {
            timer?.cancel()
            timer = nil
        }
    }
}

/// XCTest builds every class's default suite before the first case runs, so
/// the guard is in place for the whole run.
final class TestCaseHangGuardTests: XCTestCase {
    override class var defaultTestSuite: XCTestSuite {
        TestCaseHangGuard.install()
        return super.defaultTestSuite
    }

    func testTheGuardSawThisCaseStart() {
        XCTAssertGreaterThan(TestCaseHangGuard.observedCases, 0)
        XCTAssertGreaterThan(TestCaseHangGuard.seconds, 0)
    }
}
