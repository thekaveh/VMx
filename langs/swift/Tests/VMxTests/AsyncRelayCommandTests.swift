//
// AsyncRelayCommandTests — CMD-012: AsyncRelayCommand cancellation.
//
// See spec/04-commands.md §10, ADR-0056.
//
// Design notes:
// - Each test starts the command's body in an unstructured Task (`run`).
// - A reference-type `Started` box fulfills an `XCTestExpectation` from inside
//   the body so `isExecuting == true` is asserted *after* the body has actually
//   begun running (deterministic — no arbitrary sleep on the test side).
// - `await fulfillment(of:timeout:)` suspends the test until the body signals
//   readiness, then the test cancels and awaits the run Task.
//
import XCTest
import Combine
@testable import VMx

final class AsyncRelayCommandTests: XCTestCase {

    // MARK: - CMD-012

    /// CMD-012 — `cancel()` cancels an in-flight async task; `executeAsync()` completes
    /// normally by default (non-throwing DIA-007 alignment); `isExecuting` returns to false.
    func testCmd012CancelCompletesNormally() async {
        let startedExp = expectation(description: "CMD-012: body is running")

        let cmd = AsyncRelayCommand.builder()
            .task {
                // Signal that we are inside the body so the test can assert isExecuting.
                startedExp.fulfill()
                // Spin until Swift Task cancellation arrives, then cooperatively cancel.
                while !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: 1_000_000) // 1 ms
                }
                try Task.checkCancellation()
            }
            .build()

        XCTAssertTrue(cmd.canExecute(),
                      "command must be executable before first run")

        // Start the async body in a detached Task so we can cancel() while it runs.
        let run = Task<Void, Error> {
            try await cmd.executeAsync()
        }

        await fulfillment(of: [startedExp], timeout: 2.0)

        // Body is now in flight — assert in-flight state.
        XCTAssertTrue(cmd.isExecuting,
                      "isExecuting must be true while the body is running")
        XCTAssertFalse(cmd.canExecute(),
                       "canExecute must be false while executing (double-run guard)")

        // Cancel and await — must NOT throw (non-throwing default).
        cmd.cancel()

        var threwOnCancel = false
        do {
            try await run.value
        } catch {
            threwOnCancel = true
            XCTFail("executeAsync must complete normally on cancel by default; got: \(error)")
        }

        XCTAssertFalse(threwOnCancel)
        XCTAssertFalse(cmd.isExecuting,
                       "isExecuting must be false after cancel completes")
        XCTAssertTrue(cmd.canExecute(),
                      "canExecute must be true again after cancel (predicate nil → true)")
        cmd.dispose()
    }

    /// CMD-012 — `throwOnCancel()` mode: `cancel()` surfaces `CancellationError`
    /// to the awaiter of `executeAsync()` instead of completing normally.
    func testCmd012ThrowOnCancelSurfacesCancellationError() async {
        let startedExp = expectation(description: "CMD-012 throwOnCancel: body is running")

        let cmd = AsyncRelayCommand.builder()
            .throwOnCancel()
            .task {
                startedExp.fulfill()
                while !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: 1_000_000)
                }
                try Task.checkCancellation()
            }
            .build()

        let run = Task<Void, Error> {
            try await cmd.executeAsync()
        }

        await fulfillment(of: [startedExp], timeout: 2.0)

        cmd.cancel()

        var caughtCancellation = false
        do {
            try await run.value
            XCTFail("throwOnCancel mode must throw CancellationError, but completed normally")
        } catch is CancellationError {
            caughtCancellation = true
        } catch {
            XCTFail("throwOnCancel mode must throw CancellationError; got: \(error)")
        }

        XCTAssertTrue(caughtCancellation,
                      "awaiter must observe CancellationError when throwOnCancel is set")
        XCTAssertFalse(cmd.isExecuting,
                       "isExecuting must be false after cancel, even in throwOnCancel mode")
        cmd.dispose()
    }
}
