//
// AsyncRelayCommandTests — CMD-012, CMD-016, CMD-018, CMD-019.
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
import Foundation
@testable import VMx

private actor CancellationObservation {
    private(set) var bodyWasCancelled = false

    func recordBodyCancellation() {
        bodyWasCancelled = Task.isCancelled
    }
}

private final class AdmissionBodyReleaseGate: @unchecked Sendable {
    private let lock = NSLock()
    private var released = false
    private var continuation: CheckedContinuation<Void, Never>?

    func wait() async {
        await withCheckedContinuation { continuation in
            lock.lock()
            let resumeImmediately = released
            if !resumeImmediately {
                self.continuation = continuation
            }
            lock.unlock()

            if resumeImmediately {
                continuation.resume()
            }
        }
    }

    func release() {
        lock.lock()
        released = true
        let pending = continuation
        continuation = nil
        lock.unlock()

        pending?.resume()
    }
}

private actor CancellationRaceGate {
    private var observed = false
    private var released = false
    private var observationWaiters: [CheckedContinuation<Void, Never>] = []
    private var releaseWaiters: [CheckedContinuation<Void, Never>] = []

    func runUntilReleasedAfterCancellation() async throws {
        while !Task.isCancelled {
            await Task.yield()
        }
        observed = true
        observationWaiters.forEach { $0.resume() }
        observationWaiters.removeAll()
        if !released {
            await withCheckedContinuation { releaseWaiters.append($0) }
        }
        throw CancellationError()
    }

    func waitUntilObserved() async {
        if observed { return }
        await withCheckedContinuation { observationWaiters.append($0) }
    }

    func release() {
        released = true
        releaseWaiters.forEach { $0.resume() }
        releaseWaiters.removeAll()
    }
}

private final class ReentrantAdmissionState: @unchecked Sendable {
    private let queue = DispatchQueue(label: "VMxTests.ReentrantAdmissionState")
    private var didReenter = false
    private var calls = 0
    private var command: AsyncRelayCommand?
    private(set) var nestedFinished = false

    func install(_ command: AsyncRelayCommand) {
        queue.sync { self.command = command }
    }

    func predicate() -> Bool {
        let nestedCommand = queue.sync { () -> AsyncRelayCommand? in
            guard !didReenter else { return nil }
            didReenter = true
            return command
        }
        guard let nestedCommand else { return true }
        let finished = DispatchSemaphore(value: 0)
        Task.detached {
            try? await nestedCommand.executeAsync()
            finished.signal()
        }
        let result = finished.wait(timeout: .now() + 1)
        queue.sync { nestedFinished = result == .success }
        return true
    }

    func recordCall() {
        queue.sync { calls += 1 }
    }

    func snapshot() -> (calls: Int, nestedFinished: Bool) {
        queue.sync { (calls, nestedFinished) }
    }
}

final class AsyncRelayCommandTests: XCTestCase {

    // MARK: - CMD-012

    func testTasklessExecutionIsANoop() async throws {
        let command = AsyncRelayCommand.builder().build()
        var notifications = 0
        let subscription = command.canExecuteChanged.sink { notifications += 1 }

        command.execute()
        try await command.executeAsync()

        XCTAssertFalse(command.isExecuting)
        XCTAssertEqual(notifications, 0)
        subscription.cancel()
        command.dispose()
    }

    func testPredicateCannotReentrantlyAdmitSecondExecution() async throws {
        let state = ReentrantAdmissionState()
        let command = AsyncRelayCommand.builder()
            .task { state.recordCall() }
            .predicate { state.predicate() }
            .build()
        state.install(command)

        try await command.executeAsync()

        let snapshot = state.snapshot()
        XCTAssertTrue(snapshot.nestedFinished)
        XCTAssertEqual(snapshot.calls, 1)
        command.dispose()
    }

    /// CMD-018 — async imperative raise while idle emits exactly once.
    func testCmd018ImperativeRaiseWhileIdleEmitsOnce() {
        let cmd = AsyncRelayCommand.builder().build()
        var fires = 0
        let cancel = cmd.canExecuteChanged.sink { fires += 1 }

        cmd.raiseCanExecuteChanged()

        XCTAssertEqual(fires, 1)
        cancel.cancel()
    }

    /// CMD-019 — async imperative raise while in flight is additive with state flips.
    func testCmd019ImperativeRaiseWhileInFlightIsAdditive() async {
        let startedExp = expectation(description: "CMD-019: body is running")
        let cmd = AsyncRelayCommand.builder()
            .task {
                startedExp.fulfill()
                while !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: 1_000_000)
                }
                try Task.checkCancellation()
            }
            .build()
        var fires = 0
        let cancel = cmd.canExecuteChanged.sink { fires += 1 }

        let run = Task<Void, Error> { try await cmd.executeAsync() }
        await fulfillment(of: [startedExp], timeout: 2.0)
        XCTAssertEqual(fires, 1)
        cmd.raiseCanExecuteChanged()
        XCTAssertEqual(fires, 2)
        cmd.cancel()
        _ = try? await run.value

        XCTAssertEqual(fires, 3)
        cancel.cancel()
        cmd.dispose()
    }

    /// CMD-016 — async imperative raise after disposal is a no-op.
    func testCmd016ImperativeRaiseAfterDisposalIsNoOp() {
        let cmd = AsyncRelayCommand.builder().build()
        cmd.dispose()
        var fires = 0
        let cancel = cmd.canExecuteChanged.sink { fires += 1 }

        cmd.raiseCanExecuteChanged()

        XCTAssertEqual(fires, 0)
        cancel.cancel()
    }

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

    /// CMD-012 — cancellation during the synchronous admission notification
    /// reaches the body even before its cancellation handle is installed.
    func testCmd012ImmediateCancelDuringAdmissionIsNeverLost() async {
        let admissionCancelled = expectation(
            description: "CMD-012 admission callback requested cancellation"
        )
        let bodyObservedCancellation = expectation(
            description: "CMD-012 body observed admission cancellation"
        )
        let runFinished = expectation(
            description: "CMD-012 admission execution finished"
        )
        let bodyGate = AdmissionBodyReleaseGate()
        let timeout: TimeInterval = 5.0

        let cmd = AsyncRelayCommand.builder()
            .task {
                try await withTaskCancellationHandler {
                    await bodyGate.wait()
                    try Task.checkCancellation()
                } onCancel: {
                    bodyObservedCancellation.fulfill()
                }
            }
            .build()

        // The start notification is synchronous, before bodyTask exists or
        // cancelHandle is installed. The finish notification has isExecuting
        // false and therefore cannot request a second cancellation.
        let subscription = cmd.canExecuteChanged.sink {
            guard cmd.isExecuting else { return }
            cmd.cancel()
            admissionCancelled.fulfill()
        }

        let run = Task<Result<Void, Error>, Never> {
            defer { runFinished.fulfill() }
            do {
                try await cmd.executeAsync()
                return .success(())
            } catch {
                return .failure(error)
            }
        }
        defer {
            // Cleanup must never depend on cancellation reaching the body.
            bodyGate.release()
            subscription.cancel()
            run.cancel()
            cmd.dispose()
        }

        let admissionResult = await XCTWaiter.fulfillment(
            of: [admissionCancelled], timeout: timeout
        )
        XCTAssertEqual(
            admissionResult, .completed,
            "CMD-012 admission setup failed: synchronous cancellation callback did not run"
        )

        if admissionResult == .completed {
            let cancellationResult = await XCTWaiter.fulfillment(
                of: [bodyObservedCancellation], timeout: timeout
            )
            XCTAssertEqual(
                cancellationResult, .completed,
                "CMD-012 admission regression: pending command cancellation did not reach the body"
            )
        }

        // This executes after a failed cancellation expectation as well as a
        // successful one, allowing the mutant's uncancelled body to finish.
        bodyGate.release()
        let completionResult = await XCTWaiter.fulfillment(
            of: [runFinished], timeout: timeout
        )
        XCTAssertEqual(
            completionResult, .completed,
            "CMD-012 admission cleanup failed: execution did not finish after body release"
        )

        // The completion acknowledgment is emitted in the task's final defer,
        // after executeAsync has produced its Result; no further async work is
        // performed in that task before this join completes.
        switch await run.value {
        case .success:
            break
        case .failure(let error):
            XCTFail("CMD-012 admission execution unexpectedly failed: \(error)")
        }
        XCTAssertFalse(cmd.isExecuting)
        XCTAssertTrue(cmd.canExecute())
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

    /// CMD-012 — cancellation of the task awaiting `executeAsync()` propagates
    /// into the command body and remains observable by the external awaiter.
    func testCmd012ParentTaskCancellationPropagatesToBody() async {
        let startedExp = expectation(description: "CMD-012 parent cancellation: body is running")
        let observation = CancellationObservation()
        let cmd = AsyncRelayCommand.builder()
            .task {
                startedExp.fulfill()
                do {
                    while true {
                        try await Task.sleep(nanoseconds: 1_000_000)
                    }
                } catch is CancellationError {
                    await observation.recordBodyCancellation()
                    throw CancellationError()
                }
            }
            .build()

        let run = Task<Void, Error> {
            try await cmd.executeAsync()
        }
        await fulfillment(of: [startedExp], timeout: 2.0)

        run.cancel()

        do {
            try await run.value
            XCTFail("parent-task cancellation must surface CancellationError")
        } catch is CancellationError {
            // Expected.
        } catch {
            XCTFail("parent-task cancellation must preserve CancellationError; got: \(error)")
        }

        let bodyWasCancelled = await observation.bodyWasCancelled
        XCTAssertTrue(bodyWasCancelled)
        XCTAssertFalse(cmd.isExecuting)
        cmd.dispose()
    }

    func testCmd012ExternalFirstCancellationRemainsThrowing() async {
        let startedExp = expectation(description: "external-first body is running")
        let gate = CancellationRaceGate()
        let cmd = AsyncRelayCommand.builder()
            .task {
                startedExp.fulfill()
                try await gate.runUntilReleasedAfterCancellation()
            }
            .build()
        let run = Task<Void, Error> { try await cmd.executeAsync() }
        await fulfillment(of: [startedExp], timeout: 2.0)

        run.cancel()
        await gate.waitUntilObserved()
        cmd.cancel()
        await gate.release()

        do {
            try await run.value
            XCTFail("external-first cancellation must remain throwing")
        } catch is CancellationError {
            // Expected.
        } catch {
            XCTFail("external-first cancellation must preserve CancellationError; got: \(error)")
        }
        cmd.dispose()
    }

    func testCmd012CommandFirstCancellationRemainsNonthrowing() async {
        let startedExp = expectation(description: "command-first body is running")
        let gate = CancellationRaceGate()
        let cmd = AsyncRelayCommand.builder()
            .task {
                startedExp.fulfill()
                try await gate.runUntilReleasedAfterCancellation()
            }
            .build()
        let run = Task<Void, Error> { try await cmd.executeAsync() }
        await fulfillment(of: [startedExp], timeout: 2.0)

        cmd.cancel()
        await gate.waitUntilObserved()
        run.cancel()
        await gate.release()

        do {
            try await run.value
        } catch {
            XCTFail("command-first cancellation must remain nonthrowing; got: \(error)")
        }
        cmd.dispose()
    }

    /// CMD-012 — fire-and-forget command cancellation is not routed to `errors`,
    /// even when `throwOnCancel()` is enabled for the awaitable path.
    func testCmd012ExecuteDoesNotRouteCancellationToErrorsWhenThrowOnCancelIsSet() async {
        let startedExp = expectation(description: "CMD-012 execute: body is running")
        let noErrorExp = expectation(description: "CMD-012 execute: no cancellation error")
        noErrorExp.isInverted = true

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

        let cancel = cmd.errors.sink { _ in noErrorExp.fulfill() }

        cmd.execute()
        await fulfillment(of: [startedExp], timeout: 2.0)
        cmd.cancel()
        await fulfillment(of: [noErrorExp], timeout: 0.2)

        XCTAssertFalse(cmd.isExecuting)
        cancel.cancel()
        cmd.dispose()
    }

    /// CMD-013 — disposed AsyncRelayCommand instances are inert.
    func testCmd013DisposedAsyncRelayCommandIsInert() async {
        var invoked = false
        let cmd = AsyncRelayCommand.builder()
            .task { invoked = true }
            .build()

        cmd.dispose()
        cmd.execute()
        try? await cmd.executeAsync()

        XCTAssertFalse(cmd.canExecute())
        XCTAssertFalse(invoked)
    }
}
