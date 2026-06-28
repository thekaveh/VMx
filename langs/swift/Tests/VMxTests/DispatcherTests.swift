//
// Dispatcher tests — exercises the production `DefaultDispatcher` whose
// async foreground/background hops were previously wholly untested (VMX-099).
// `ImmediateDispatcher` is covered indirectly throughout the rest of the suite.
//
import XCTest
@testable import VMx

final class DispatcherTests: XCTestCase {

    /// VMX-099 — `scheduleForeground` runs synchronously when already on the
    /// main thread (the XCTest body runs on main).
    func testDefaultDispatcherForegroundRunsInlineOnMain() {
        let dispatcher = DefaultDispatcher()
        var ran = false
        dispatcher.scheduleForeground { ran = true }
        XCTAssertTrue(ran, "foreground work runs inline when already on main")
    }

    /// VMX-099 — `scheduleBackground` hops to a background queue and the work
    /// eventually runs off the main thread (the async hop was never exercised).
    func testDefaultDispatcherBackgroundRunsAsyncOffMain() {
        let dispatcher = DefaultDispatcher()
        let done = expectation(description: "background work ran")
        dispatcher.scheduleBackground {
            XCTAssertFalse(Thread.isMainThread, "background work runs off-main")
            done.fulfill()
        }
        wait(for: [done], timeout: 2.0)
    }

    /// VMX-099 — `scheduleForeground` called from a background thread hops to
    /// the main queue asynchronously (the off-main branch of the foreground
    /// path, previously unexercised).
    func testDefaultDispatcherForegroundFromBackgroundHopsToMain() {
        let dispatcher = DefaultDispatcher()
        let done = expectation(description: "foreground hop ran on main")
        DispatchQueue.global(qos: .userInitiated).async {
            dispatcher.scheduleForeground {
                XCTAssertTrue(Thread.isMainThread, "foreground hop targets the main queue")
                done.fulfill()
            }
        }
        wait(for: [done], timeout: 2.0)
    }
}
