//
// ConfirmationAsyncInnerTests — conformance tests CMDD-014, CMDD-015,
// CMDD-016, CMDD-017.
//
// An awaited ConfirmationDecoratorCommand over an asynchronous inner command
// completes when the inner operation completes and invokes it once; failures
// reach exactly one channel on each path; the inner keeps its own admission and
// cancellation; nested wrappers are awaited end to end, and disposal neither
// cancels nor owns the inner (spec/04-commands.md §8.3.2, ADR-0145).
//
// Async bodies park on continuation gates that only the test releases, and
// every wait is bounded by an expectation timeout, so a regression fails
// instead of hanging. The short `settle()` window gives a wrong implementation
// time to finish early; it cannot change a correct outcome because every body
// is parked while it runs.
//
import XCTest
import Combine
@testable import VMx

final class ConfirmationAsyncInnerTests: XCTestCase {

    // MARK: - Helpers

    private enum TestError: Error, Equatable { case confirm, inner }

    /// Thread-safe ordered event log.
    private final class Log: @unchecked Sendable {
        private let lock = NSLock()
        private var storage: [String] = []

        func append(_ entry: String) {
            lock.lock()
            storage.append(entry)
            lock.unlock()
        }

        var entries: [String] {
            lock.lock()
            defer { lock.unlock() }
            return storage
        }

        func count(of entry: String) -> Int {
            entries.filter { $0 == entry }.count
        }
    }

    /// Thread-safe collector for an `errors` channel.
    private final class ErrorLog: @unchecked Sendable {
        private let lock = NSLock()
        private var storage: [Error] = []

        func append(_ error: Error) {
            lock.lock()
            storage.append(error)
            lock.unlock()
        }

        var errors: [Error] {
            lock.lock()
            defer { lock.unlock() }
            return storage
        }
    }

    /// Continuation gate: `wait()` parks until `release()`; waits after the
    /// release return immediately.
    private final class Gate: @unchecked Sendable {
        private let lock = NSLock()
        private var released = false
        private var waiters: [CheckedContinuation<Void, Never>] = []

        func wait() async {
            await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
                lock.lock()
                if released {
                    lock.unlock()
                    continuation.resume()
                    return
                }
                waiters.append(continuation)
                lock.unlock()
            }
        }

        func release() {
            lock.lock()
            released = true
            let pending = waiters
            waiters.removeAll()
            lock.unlock()
            pending.forEach { $0.resume() }
        }
    }

    /// A confirmation that stays pending until the test resolves it.
    private final class PendingConfirmation: @unchecked Sendable {
        let parked: XCTestExpectation
        private let lock = NSLock()
        private var continuation: CheckedContinuation<Bool, Error>?
        private var outcome: Result<Bool, Error>?

        init(_ parked: XCTestExpectation) { self.parked = parked }

        func wait() async throws -> Bool {
            try await withCheckedThrowingContinuation { continuation in
                lock.lock()
                if let outcome {
                    lock.unlock()
                    continuation.resume(with: outcome)
                    return
                }
                self.continuation = continuation
                lock.unlock()
                parked.fulfill()
            }
        }

        func resolve(_ result: Result<Bool, Error>) {
            lock.lock()
            let continuation = self.continuation
            self.continuation = nil
            if continuation == nil { outcome = result }
            lock.unlock()
            continuation?.resume(with: result)
        }
    }

    /// An `AsyncCommand` double that records which entry point ran.
    /// `executeAsync()` logs, parks on `gate`, and logs again when released;
    /// `execute()` only logs, so a fire-and-forget start is observable.
    private final class ProbeAsyncCommand: AsyncCommand {
        let log: Log
        let gate = Gate()
        private let entered: XCTestExpectation?
        private let executeCalled: XCTestExpectation?
        private let changes = PassthroughSubject<Void, Never>()

        init(
            log: Log = Log(),
            entered: XCTestExpectation? = nil,
            executeCalled: XCTestExpectation? = nil
        ) {
            self.log = log
            self.entered = entered
            self.executeCalled = executeCalled
        }

        var isExecuting: Bool { false }

        func executeAsync() async throws {
            log.append("executeAsync")
            entered?.fulfill()
            await gate.wait()
            log.append("executeAsync finished")
        }

        func cancel() { log.append("cancel") }

        func canExecute() -> Bool { true }

        func execute() {
            log.append("execute")
            executeCalled?.fulfill()
        }

        var canExecuteChanged: AnyPublisher<Void, Never> {
            changes.eraseToAnyPublisher()
        }
    }

    private let timeout: TimeInterval = 10

    /// Lets a wrong implementation complete early before a "still pending" check.
    private func settle() async {
        try? await Task.sleep(nanoseconds: 100_000_000)
    }

    /// Runs `operation` on a Task. Logs "awaiter completed" when it returns
    /// normally and fulfils `finished` on every exit path.
    private func startAwaiter(
        log: Log,
        finished: XCTestExpectation,
        _ operation: @escaping () async throws -> Void
    ) -> Task<Result<Void, Error>, Never> {
        Task<Result<Void, Error>, Never> {
            defer { finished.fulfill() }
            do {
                try await operation()
                log.append("awaiter completed")
                return .success(())
            } catch {
                return .failure(error)
            }
        }
    }

    private func assertCompletedNormally(
        _ result: Result<Void, Error>,
        _ message: String = "",
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        if case .failure(let error) = result {
            XCTFail("the awaiter must complete normally, got \(error). \(message)", file: file, line: line)
        }
    }

    private func failure(of result: Result<Void, Error>) -> Error? {
        if case .failure(let error) = result { return error }
        return nil
    }

    /// An `AsyncRelayCommand` whose body parks on `gate` and observes
    /// cancellation: a cancellation releases the gate and the body throws
    /// `CancellationError`.
    private func makeCancellableInner(
        throwOnCancel: Bool,
        entered: XCTestExpectation,
        gate: Gate
    ) -> AsyncRelayCommand {
        AsyncRelayCommand.builder()
            .throwOnCancel(throwOnCancel)
            .task {
                try await withTaskCancellationHandler {
                    entered.fulfill()
                    await gate.wait()
                    try Task.checkCancellation()
                } onCancel: {
                    gate.release()
                }
            }
            .build()
    }

    // MARK: - CMDD-014

    /// CMDD-014 — an awaited confirmation over an async inner completes only after the inner operation completes, through `executeAsync()` exactly once and never `execute()`.
    func testCmdd014AwaitedConfirmationCompletesWhenTheAsyncInnerCompletes() async {
        let entered = expectation(description: "inner executeAsync entered")
        let inner = ProbeAsyncCommand(entered: entered)
        defer { inner.gate.release() }
        let decorator = ConfirmationDecoratorCommand(inner) { true }
        let finished = expectation(description: "awaiter finished")

        let awaiter = startAwaiter(log: inner.log, finished: finished) {
            try await decorator.executeAsync()
        }
        await fulfillment(of: [entered], timeout: timeout)
        await settle()
        XCTAssertEqual(inner.log.entries, ["executeAsync"],
                       "the awaiter must not complete while the inner body is blocked")

        inner.gate.release()
        await fulfillment(of: [finished], timeout: timeout)
        let result = await awaiter.value
        assertCompletedNormally(result)
        XCTAssertEqual(inner.log.entries, ["executeAsync", "executeAsync finished", "awaiter completed"],
                       "executeAsync must run exactly once, execute never, and the awaiter must complete after it")
    }

    /// CMDD-014 — awaiting a confirmed `AsyncRelayCommand` waits for its gated body to finish.
    func testCmdd014AwaitedConfirmationWaitsForAnAsyncRelayCommandBody() async {
        let log = Log()
        let gate = Gate()
        let entered = expectation(description: "body entered")
        let inner = AsyncRelayCommand.builder()
            .task {
                log.append("body")
                entered.fulfill()
                await gate.wait()
                log.append("body finished")
            }
            .build()
        defer {
            gate.release()
            inner.dispose()
        }
        let decorator = ConfirmationDecoratorCommand(inner) { true }
        let finished = expectation(description: "awaiter finished")

        let awaiter = startAwaiter(log: log, finished: finished) {
            try await decorator.executeAsync()
        }
        await fulfillment(of: [entered], timeout: timeout)
        await settle()
        XCTAssertEqual(log.entries, ["body"],
                       "the awaiter must not complete while the inner body is blocked")
        XCTAssertTrue(inner.isExecuting)

        gate.release()
        await fulfillment(of: [finished], timeout: timeout)
        let result = await awaiter.value
        assertCompletedNormally(result)
        XCTAssertEqual(log.entries, ["body", "body finished", "awaiter completed"])
        XCTAssertFalse(inner.isExecuting)
    }

    /// CMDD-014 — when confirm resolves false the awaiter completes and the inner is not invoked.
    func testCmdd014ConfirmFalseCompletesWithoutInvokingTheInner() async {
        let inner = ProbeAsyncCommand()
        defer { inner.gate.release() }
        let decorator = ConfirmationDecoratorCommand(inner) { false }
        let finished = expectation(description: "awaiter finished")

        let awaiter = startAwaiter(log: inner.log, finished: finished) {
            try await decorator.executeAsync()
        }
        await fulfillment(of: [finished], timeout: timeout)
        let result = await awaiter.value
        assertCompletedNormally(result)
        XCTAssertEqual(inner.log.entries, ["awaiter completed"],
                       "neither inner entry point may run when confirm resolves false")
    }

    /// CMDD-014 — a synchronous inner runs `execute()` exactly once and the awaiter completes after it returns.
    func testCmdd014SynchronousInnerRunsOnceBeforeTheAwaiterCompletes() async {
        let log = Log()
        let inner = RelayCommand.builder()
            .task { log.append("execute") }
            .build()
        let decorator = ConfirmationDecoratorCommand(inner) { true }
        let finished = expectation(description: "awaiter finished")

        let awaiter = startAwaiter(log: log, finished: finished) {
            try await decorator.executeAsync()
        }
        await fulfillment(of: [finished], timeout: timeout)
        let result = await awaiter.value
        assertCompletedNormally(result)
        XCTAssertEqual(log.entries, ["execute", "awaiter completed"])
    }

    // MARK: - CMDD-015

    /// CMDD-015 — an awaited async inner failure propagates to the awaiter unchanged and reaches neither `errors` channel.
    func testCmdd015AwaitedInnerFailurePropagatesOnlyToTheAwaiter() async {
        let gate = Gate()
        let entered = expectation(description: "body entered")
        let inner = AsyncRelayCommand.builder()
            .task {
                entered.fulfill()
                await gate.wait()
                throw TestError.inner
            }
            .build()
        let decorator = ConfirmationDecoratorCommand(inner) { true }
        let innerErrors = ErrorLog()
        let decoratorErrors = ErrorLog()
        let subscriptions = [
            inner.errors.sink { innerErrors.append($0) },
            decorator.errors.sink { decoratorErrors.append($0) },
        ]
        defer {
            gate.release()
            subscriptions.forEach { $0.cancel() }
            inner.dispose()
        }
        let finished = expectation(description: "awaiter finished")

        let awaiter = startAwaiter(log: Log(), finished: finished) {
            try await decorator.executeAsync()
        }
        await fulfillment(of: [entered], timeout: timeout)
        gate.release()
        await fulfillment(of: [finished], timeout: timeout)
        let result = await awaiter.value
        XCTAssertEqual(failure(of: result) as? TestError, .inner,
                       "the inner failure must propagate to the awaiter unchanged")

        await settle()
        XCTAssertTrue(innerErrors.errors.isEmpty, "the inner's errors must stay silent for an awaited call")
        XCTAssertTrue(decoratorErrors.errors.isEmpty, "the decorator's errors must stay silent for an awaited call")
    }

    /// CMDD-015 — on the fire-and-forget path an async inner failure reaches the inner's `errors` exactly once and never the decorator's.
    func testCmdd015FireAndForgetInnerFailureReachesOnlyTheInnerErrors() async {
        let gate = Gate()
        let entered = expectation(description: "body entered")
        let inner = AsyncRelayCommand.builder()
            .task {
                entered.fulfill()
                await gate.wait()
                throw TestError.inner
            }
            .build()
        let decorator = ConfirmationDecoratorCommand(inner) { true }
        let innerFailed = expectation(description: "inner errors emitted")
        innerFailed.assertForOverFulfill = false
        let innerErrors = ErrorLog()
        let decoratorErrors = ErrorLog()
        let subscriptions = [
            inner.errors.sink { error in
                innerErrors.append(error)
                innerFailed.fulfill()
            },
            decorator.errors.sink { decoratorErrors.append($0) },
        ]
        defer {
            gate.release()
            subscriptions.forEach { $0.cancel() }
            inner.dispose()
        }

        decorator.execute()
        await fulfillment(of: [entered], timeout: timeout)
        gate.release()
        await fulfillment(of: [innerFailed], timeout: timeout)
        await settle()

        XCTAssertEqual(innerErrors.errors.count, 1, "the inner's errors must emit the failure exactly once")
        XCTAssertEqual(innerErrors.errors.first as? TestError, .inner)
        XCTAssertTrue(decoratorErrors.errors.isEmpty,
                      "the decorator must not re-emit an async inner's failure")
    }

    /// CMDD-015 — the fire-and-forget path starts an async inner through the inner's own `execute()`, never its `executeAsync()`.
    func testCmdd015FireAndForgetStartsAnAsyncInnerThroughItsOwnExecute() async {
        let executeCalled = expectation(description: "inner execute() called")
        let inner = ProbeAsyncCommand(executeCalled: executeCalled)
        defer { inner.gate.release() }
        let decorator = ConfirmationDecoratorCommand(inner) { true }

        decorator.execute()
        await fulfillment(of: [executeCalled], timeout: timeout)
        await settle()

        XCTAssertEqual(inner.log.entries, ["execute"],
                       "the decorator must start the inner once through execute() and not await executeAsync()")
    }

    /// CMDD-015 — a confirm failure on the fire-and-forget path reaches the decorator's `errors` exactly once and the inner is not invoked.
    func testCmdd015FireAndForgetConfirmFailureReachesOnlyTheDecoratorErrors() async {
        let log = Log()
        let inner = AsyncRelayCommand.builder()
            .task { log.append("body") }
            .build()
        let decorator = ConfirmationDecoratorCommand(inner) { throw TestError.confirm }
        let decoratorFailed = expectation(description: "decorator errors emitted")
        decoratorFailed.assertForOverFulfill = false
        let innerErrors = ErrorLog()
        let decoratorErrors = ErrorLog()
        let subscriptions = [
            inner.errors.sink { innerErrors.append($0) },
            decorator.errors.sink { error in
                decoratorErrors.append(error)
                decoratorFailed.fulfill()
            },
        ]
        defer {
            subscriptions.forEach { $0.cancel() }
            inner.dispose()
        }

        decorator.execute()
        await fulfillment(of: [decoratorFailed], timeout: timeout)
        await settle()

        XCTAssertEqual(decoratorErrors.errors.count, 1, "the decorator's errors must emit the confirm failure exactly once")
        XCTAssertEqual(decoratorErrors.errors.first as? TestError, .confirm)
        XCTAssertTrue(innerErrors.errors.isEmpty)
        XCTAssertEqual(log.entries, [], "the inner must not run when confirm fails")
    }

    // MARK: - CMDD-016

    /// CMDD-016 — a confirmed call reaching an already-executing `AsyncRelayCommand` is dropped by the inner, its body runs no second time, and the awaiter completes.
    func testCmdd016BusyInnerDropsTheConfirmedCallAndTheAwaiterCompletes() async {
        let log = Log()
        let gate = Gate()
        let entered = expectation(description: "body entered")
        entered.assertForOverFulfill = false
        let inner = AsyncRelayCommand.builder()
            .task {
                log.append("body")
                entered.fulfill()
                await gate.wait()
            }
            .build()
        defer {
            gate.release()
            inner.dispose()
        }
        let confirmation = PendingConfirmation(expectation(description: "confirm parked"))
        let decorator = ConfirmationDecoratorCommand(inner) { try await confirmation.wait() }
        let finished = expectation(description: "decorator awaiter finished")

        let awaiter = startAwaiter(log: log, finished: finished) {
            try await decorator.executeAsync()
        }
        await fulfillment(of: [confirmation.parked], timeout: timeout)

        // The inner becomes busy while the confirmation is pending.
        let directFinished = expectation(description: "direct execution finished")
        Task {
            try? await inner.executeAsync()
            directFinished.fulfill()
        }
        await fulfillment(of: [entered], timeout: timeout)
        XCTAssertTrue(inner.isExecuting)

        confirmation.resolve(.success(true))
        await fulfillment(of: [finished], timeout: timeout)
        let result = await awaiter.value
        assertCompletedNormally(result, "the awaiter completes when the dropped call returns")
        XCTAssertEqual(log.entries, ["body", "awaiter completed"],
                       "the busy inner must drop the confirmed call without a second body run")
        XCTAssertTrue(inner.isExecuting, "the dropped call must leave the first execution running")

        gate.release()
        await fulfillment(of: [directFinished], timeout: timeout)
        XCTAssertEqual(log.count(of: "body"), 1)
        XCTAssertFalse(inner.isExecuting)
    }

    /// CMDD-016 — cancelling the inner completes the awaiter with the inner's default non-throwing cancellation outcome.
    func testCmdd016InnerCancellationCompletesTheAwaiterNormallyByDefault() async {
        let gate = Gate()
        let entered = expectation(description: "body entered")
        let inner = makeCancellableInner(throwOnCancel: false, entered: entered, gate: gate)
        let decorator = ConfirmationDecoratorCommand(inner) { true }
        let decoratorErrors = ErrorLog()
        let subscription = decorator.errors.sink { decoratorErrors.append($0) }
        defer {
            gate.release()
            subscription.cancel()
            inner.dispose()
        }
        let finished = expectation(description: "awaiter finished")

        let awaiter = startAwaiter(log: Log(), finished: finished) {
            try await decorator.executeAsync()
        }
        await fulfillment(of: [entered], timeout: timeout)
        inner.cancel()
        await fulfillment(of: [finished], timeout: timeout)
        let result = await awaiter.value

        assertCompletedNormally(result, "the inner's default cancellation completes normally")
        XCTAssertFalse(inner.isExecuting)
        XCTAssertTrue(decoratorErrors.errors.isEmpty)
    }

    /// CMDD-016 — cancelling a `throwOnCancel()` inner surfaces its `CancellationError` to the awaiter unchanged.
    func testCmdd016ThrowOnCancelInnerCancellationReachesTheAwaiterUnchanged() async {
        let gate = Gate()
        let entered = expectation(description: "body entered")
        let inner = makeCancellableInner(throwOnCancel: true, entered: entered, gate: gate)
        let decorator = ConfirmationDecoratorCommand(inner) { true }
        let decoratorErrors = ErrorLog()
        let subscription = decorator.errors.sink { decoratorErrors.append($0) }
        defer {
            gate.release()
            subscription.cancel()
            inner.dispose()
        }
        let finished = expectation(description: "awaiter finished")

        let awaiter = startAwaiter(log: Log(), finished: finished) {
            try await decorator.executeAsync()
        }
        await fulfillment(of: [entered], timeout: timeout)
        inner.cancel()
        await fulfillment(of: [finished], timeout: timeout)
        let result = await awaiter.value

        XCTAssertTrue(failure(of: result) is CancellationError,
                      "the inner's throwing cancellation must reach the awaiter unchanged, got \(result)")
        XCTAssertFalse(inner.isExecuting)
        XCTAssertTrue(decoratorErrors.errors.isEmpty)
    }

    // MARK: - CMDD-017

    /// CMDD-017 — an outer decorator over an inner decorator awaits both confirmations and the async body, which runs exactly once.
    func testCmdd017NestedWrappersAreAwaitedEndToEnd() async {
        let log = Log()
        let gate = Gate()
        let entered = expectation(description: "body entered")
        let command = AsyncRelayCommand.builder()
            .task {
                log.append("body")
                entered.fulfill()
                await gate.wait()
                log.append("body finished")
            }
            .build()
        defer {
            gate.release()
            command.dispose()
        }
        let innerDecorator = ConfirmationDecoratorCommand(command) {
            log.append("inner confirm")
            return true
        }
        let outer = ConfirmationDecoratorCommand(innerDecorator) {
            log.append("outer confirm")
            return true
        }
        let finished = expectation(description: "outer awaiter finished")

        let awaiter = startAwaiter(log: log, finished: finished) {
            try await outer.executeAsync()
        }
        await fulfillment(of: [entered], timeout: timeout)
        await settle()
        XCTAssertEqual(log.entries, ["outer confirm", "inner confirm", "body"],
                       "the outer awaiter must not complete while the body is blocked")

        gate.release()
        await fulfillment(of: [finished], timeout: timeout)
        let result = await awaiter.value
        assertCompletedNormally(result)
        XCTAssertEqual(log.entries, ["outer confirm", "inner confirm", "body", "body finished", "awaiter completed"])
    }

    /// CMDD-017 — disposing a decorator while its async inner body is blocked neither cancels nor disposes the inner, and the awaiter completes when the body is released.
    func testCmdd017DisposalDuringTheInnerOperationLeavesTheInnerRunning() async {
        let log = Log()
        let gate = Gate()
        let entered = expectation(description: "body entered")
        entered.assertForOverFulfill = false
        let inner = AsyncRelayCommand.builder()
            .task {
                log.append("body")
                entered.fulfill()
                await gate.wait()
                log.append(Task.isCancelled ? "body cancelled" : "body finished")
            }
            .build()
        let innerCompletions = Log()
        let subscriptions = [
            inner.canExecuteChanged.sink(
                receiveCompletion: { _ in innerCompletions.append("canExecuteChanged completed") },
                receiveValue: {}
            ),
            inner.errors.sink(
                receiveCompletion: { _ in innerCompletions.append("errors completed") },
                receiveValue: { _ in }
            ),
        ]
        defer {
            gate.release()
            subscriptions.forEach { $0.cancel() }
            inner.dispose()
        }
        let decorator = ConfirmationDecoratorCommand(inner) { true }
        let finished = expectation(description: "awaiter finished")

        let awaiter = startAwaiter(log: log, finished: finished) {
            try await decorator.executeAsync()
        }
        await fulfillment(of: [entered], timeout: timeout)
        decorator.dispose()
        await settle()
        XCTAssertFalse(decorator.canExecute())
        XCTAssertTrue(inner.isExecuting, "disposing the decorator must not cancel the inner operation")
        XCTAssertEqual(log.entries, ["body"], "the awaiter must not complete while the inner body is blocked")

        gate.release()
        await fulfillment(of: [finished], timeout: timeout)
        let result = await awaiter.value
        assertCompletedNormally(result)
        XCTAssertEqual(log.entries, ["body", "body finished", "awaiter completed"],
                       "the inner body must finish uncancelled before the awaiter completes")
        XCTAssertEqual(innerCompletions.entries, [], "the decorator must not dispose the inner")

        // The inner is still usable by its owner.
        XCTAssertTrue(inner.canExecute())
        do {
            try await inner.executeAsync()
        } catch {
            XCTFail("the inner must stay usable after the decorator is disposed, got \(error)")
        }
        XCTAssertEqual(log.count(of: "body"), 2)
    }

    /// CMDD-017 — disposing a decorator while its confirmation is pending starts no inner work on either entry point once the confirmation resolves true.
    func testCmdd017DisposalDuringAPendingConfirmationStartsNoInnerWork() async {
        let inner = ProbeAsyncCommand()
        defer { inner.gate.release() }

        // Awaited entry point.
        let awaitedConfirmation = PendingConfirmation(expectation(description: "awaited confirm parked"))
        let awaitedDecorator = ConfirmationDecoratorCommand(inner) { try await awaitedConfirmation.wait() }
        let finished = expectation(description: "awaiter finished")
        let awaiter = startAwaiter(log: Log(), finished: finished) {
            try await awaitedDecorator.executeAsync()
        }
        await fulfillment(of: [awaitedConfirmation.parked], timeout: timeout)
        awaitedDecorator.dispose()
        awaitedConfirmation.resolve(.success(true))
        await fulfillment(of: [finished], timeout: timeout)
        let result = await awaiter.value
        assertCompletedNormally(result)

        // Fire-and-forget entry point.
        let firedConfirmation = PendingConfirmation(expectation(description: "fire-and-forget confirm parked"))
        let firedDecorator = ConfirmationDecoratorCommand(inner) { try await firedConfirmation.wait() }
        firedDecorator.execute()
        await fulfillment(of: [firedConfirmation.parked], timeout: timeout)
        firedDecorator.dispose()
        firedConfirmation.resolve(.success(true))
        await settle()

        XCTAssertEqual(inner.log.entries, [],
                       "a confirmation resolving after disposal must start no inner work")
    }
}
