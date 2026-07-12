import Combine
import XCTest
@testable import VMx

private enum AsyncResourceTestError: Error { case failed }

private final class DeferredValue<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Value, Never>?
    private var resolved: Value?

    func get() async -> Value {
        await withCheckedContinuation { continuation in
            lock.lock()
            if let resolved {
                lock.unlock()
                continuation.resume(returning: resolved)
                return
            }
            self.continuation = continuation
            lock.unlock()
        }
    }

    func resolve(_ value: Value) {
        lock.lock()
        if let continuation {
            self.continuation = nil
            lock.unlock()
            continuation.resume(returning: value)
            return
        }
        resolved = value
        lock.unlock()
    }
}

private final class LoaderQueue<Value>: @unchecked Sendable {
    typealias Step = () async throws -> Value
    private let lock = NSLock()
    private var steps: [Step]

    init(_ steps: [Step]) {
        self.steps = steps
    }

    func load() async throws -> Value {
        lock.lock()
        let step = steps.removeFirst()
        lock.unlock()
        return try await step()
    }
}

private func makeAsyncResourceVM<Value>(
    loader: @escaping () async throws -> Value,
    retention: AsyncResourceRetention = .discardPrevious,
    cleanup: ((Value) -> Void)? = nil
) -> AsyncResourceVM<Value> {
    AsyncResourceVM(
        name: "resource",
        loader: loader,
        hub: MessageHub(),
        dispatcher: ImmediateDispatcher.INSTANCE,
        retention: retention,
        cleanupValue: cleanup
    )
}

private func eventually(
    _ predicate: @escaping () -> Bool,
    file: StaticString = #filePath,
    line: UInt = #line
) async {
    for _ in 0..<1_000 {
        if predicate() { return }
        await Task.yield()
    }
    XCTFail("condition was not reached", file: file, line: line)
}

final class AsyncResourceVMConformanceTests: XCTestCase {
    /// ARES-001 — initial state and command eligibility.
    func testAres001InitialStateAndCommands() {
        let vm = makeAsyncResourceVM { 1 }

        XCTAssertEqual(vm.state.status, .idle)
        XCTAssertTrue(vm.loadCommand.canExecute())
        XCTAssertFalse(vm.reloadCommand.canExecute())
        XCTAssertFalse(vm.cancelCommand.canExecute())
    }

    /// ARES-002 — successful load reaches Ready and notifies state.
    func testAres002SuccessfulLoadNotifies() async {
        let vm = makeAsyncResourceVM { 7 }
        var names: [String] = []
        let cancellable = vm.propertyChanged.sink { names.append($0) }

        await vm.load()

        XCTAssertEqual(vm.state.status, .ready)
        XCTAssertEqual(vm.state.value, 7)
        XCTAssertEqual(names, ["state", "state"])
        cancellable.cancel()
    }

    /// ARES-003 — loader failure becomes Error without escaping the intent.
    func testAres003FailureBecomesState() async {
        let vm: AsyncResourceVM<Int> = makeAsyncResourceVM {
            throw AsyncResourceTestError.failed
        }

        await vm.load()

        XCTAssertEqual(vm.state.status, .error)
        XCTAssertNotNil(vm.state.error)
        XCTAssertTrue(vm.reloadCommand.canExecute())
    }

    /// ARES-004 — reload retries an Error state and may reach Ready.
    func testAres004RetryReplacesError() async {
        let queue = LoaderQueue<Int>([
            { throw AsyncResourceTestError.failed },
            { 9 },
        ])
        let vm = makeAsyncResourceVM(loader: queue.load)

        await vm.load()
        await vm.reload()

        XCTAssertEqual(vm.state.status, .ready)
        XCTAssertEqual(vm.state.value, 9)
    }

    /// ARES-005 — cancellation restores the prior stable state without Error.
    func testAres005CancellationRestoresIdle() async {
        let deferred = DeferredValue<Int>()
        let vm = makeAsyncResourceVM(loader: deferred.get)
        let intent = Task { await vm.load() }
        await eventually { vm.state.status == .loading }

        vm.cancel()
        await intent.value

        XCTAssertEqual(vm.state.status, .idle)
        XCTAssertNil(vm.state.error)
        deferred.resolve(1)
    }

    /// ARES-006 — retained reload exposes and restores the previous value.
    func testAres006RetainedReloadRestoresValue() async {
        let deferred = DeferredValue<Int>()
        let queue = LoaderQueue<Int>([
            { 3 },
            { await deferred.get() },
        ])
        let vm = makeAsyncResourceVM(loader: queue.load, retention: .retainPrevious)
        await vm.load()
        let intent = Task { await vm.reload() }
        await eventually { vm.state.status == .loading }

        XCTAssertEqual(vm.state.value, 3)
        vm.cancel()
        await intent.value
        XCTAssertEqual(vm.state.status, .ready)
        XCTAssertEqual(vm.state.value, 3)
        deferred.resolve(4)
    }

    /// ARES-007 — discard mode releases the accepted value before loading.
    func testAres007DiscardReleasesBeforeLoading() async {
        let deferred = DeferredValue<Int>()
        let queue = LoaderQueue<Int>([
            { 3 },
            { await deferred.get() },
        ])
        var cleaned: [Int] = []
        let vm = makeAsyncResourceVM(loader: queue.load) { cleaned.append($0) }
        await vm.load()
        let intent = Task { await vm.reload() }
        await eventually { vm.state.status == .loading }

        XCTAssertNil(vm.state.value)
        XCTAssertEqual(cleaned, [3])
        vm.cancel()
        await intent.value
        deferred.resolve(4)
    }

    /// ARES-008 — overlapping operations use latest-start-wins ordering.
    func testAres008LatestStartWins() async {
        let first = DeferredValue<Int>()
        let second = DeferredValue<Int>()
        let queue = LoaderQueue<Int>([
            { await first.get() },
            { await second.get() },
        ])
        let vm = makeAsyncResourceVM(loader: queue.load)
        let older = Task { await vm.load() }
        await eventually { vm.state.status == .loading }
        let newer = Task { await vm.reload() }
        second.resolve(2)
        await newer.value
        first.resolve(1)
        await older.value

        XCTAssertEqual(vm.state.status, .ready)
        XCTAssertEqual(vm.state.value, 2)
    }

    /// ARES-009 — stale success is cleaned without another state notification.
    func testAres009StaleSuccessIsCleaned() async {
        let first = DeferredValue<Int>()
        let second = DeferredValue<Int>()
        let queue = LoaderQueue<Int>([
            { await first.get() },
            { await second.get() },
        ])
        var cleaned: [Int] = []
        var notifications = 0
        let vm = makeAsyncResourceVM(loader: queue.load) { cleaned.append($0) }
        let cancellable = vm.propertyChanged.sink { _ in notifications += 1 }
        let older = Task { await vm.load() }
        await eventually { vm.state.status == .loading }
        let newer = Task { await vm.reload() }
        second.resolve(2)
        await newer.value
        let acceptedNotifications = notifications
        first.resolve(1)
        await older.value
        await eventually { cleaned == [1] }

        XCTAssertEqual(cleaned, [1])
        XCTAssertEqual(notifications, acceptedNotifications)
        cancellable.cancel()
    }

    /// ARES-010 — replacement and disposal clean accepted values exactly once.
    func testAres010ReplacementAndDisposalCleanup() async {
        let queue = LoaderQueue<Int>([{ 1 }, { 2 }])
        var cleaned: [Int] = []
        let vm = makeAsyncResourceVM(
            loader: queue.load,
            retention: .retainPrevious
        ) { cleaned.append($0) }

        await vm.load()
        await vm.reload()
        vm.dispose()
        vm.dispose()

        XCTAssertEqual(cleaned, [1, 2])
    }

    /// ARES-011 — disposal cancels active work and makes late completion inert.
    func testAres011DisposeMakesLateWorkInert() async {
        let deferred = DeferredValue<Int>()
        var cleaned: [Int] = []
        let vm = makeAsyncResourceVM(loader: deferred.get) { cleaned.append($0) }
        let intent = Task { await vm.load() }
        await eventually { vm.state.status == .loading }

        vm.dispose()
        await intent.value
        deferred.resolve(8)
        await eventually { cleaned == [8] }

        XCTAssertEqual(vm.status, .disposed)
        XCTAssertEqual(cleaned, [8])
    }
}
