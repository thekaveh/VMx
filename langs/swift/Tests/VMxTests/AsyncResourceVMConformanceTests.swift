import Combine
import XCTest
@testable import VMx

private enum AsyncResourceTestError: Error { case failed }

private final class DeferredValue<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Value, Never>?
    private var resolved: Value?

    var isWaiting: Bool {
        lock.lock()
        defer { lock.unlock() }
        return continuation != nil
    }

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
        let step = lock.withLock { steps.removeFirst() }
        return try await step()
    }
}

private final class LockedValues<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: [Value] = []

    func append(_ value: Value) {
        lock.withLock { storage.append(value) }
    }

    var values: [Value] {
        lock.withLock { storage }
    }
}

private final class LockedCount: @unchecked Sendable {
    private let lock = NSLock()
    private var storage = 0

    func increment() {
        lock.withLock { storage += 1 }
    }

    var value: Int {
        lock.withLock { storage }
    }
}

private final class WeakAsyncResourceBox<Value>: @unchecked Sendable {
    weak var value: AsyncResourceVM<Value>?
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
        let names = LockedValues<String>()
        let cancellable = vm.propertyChanged.sink { names.append($0) }

        await vm.load()

        XCTAssertEqual(vm.state.status, .ready)
        XCTAssertEqual(vm.state.value, 7)
        XCTAssertEqual(names.values, ["state", "state"])
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
        let cleaned = LockedValues<Int>()
        let vm = makeAsyncResourceVM(loader: queue.load) { cleaned.append($0) }
        await vm.load()
        let intent = Task { await vm.reload() }
        await eventually { vm.state.status == .loading }

        XCTAssertNil(vm.state.value)
        XCTAssertEqual(cleaned.values, [3])
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
        await eventually { first.isWaiting }
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
        let cleaned = LockedValues<Int>()
        let notifications = LockedCount()
        let vm = makeAsyncResourceVM(loader: queue.load) { cleaned.append($0) }
        let cancellable = vm.propertyChanged.sink { _ in notifications.increment() }
        let older = Task { await vm.load() }
        await eventually { vm.state.status == .loading }
        await eventually { first.isWaiting }
        let newer = Task { await vm.reload() }
        second.resolve(2)
        await newer.value
        let acceptedNotifications = notifications.value
        first.resolve(1)
        await older.value
        await eventually { cleaned.values == [1] }

        XCTAssertEqual(cleaned.values, [1])
        XCTAssertEqual(notifications.value, acceptedNotifications)
        cancellable.cancel()
    }

    /// ARES-010 — replacement and disposal clean accepted values exactly once.
    func testAres010ReplacementAndDisposalCleanup() async {
        let queue = LoaderQueue<Int>([{ 1 }, { 2 }])
        let cleaned = LockedValues<Int>()
        let vm = makeAsyncResourceVM(
            loader: queue.load,
            retention: .retainPrevious
        ) { cleaned.append($0) }

        await vm.load()
        await vm.reload()
        vm.dispose()
        vm.dispose()

        XCTAssertEqual(cleaned.values, [1, 2])
    }

    func testReplacementCleanupThatStartsReloadSuppressesSupersededNotification() async {
        let queue = LoaderQueue<Int>([{ 1 }, { 2 }, { 3 }])
        let owner = WeakAsyncResourceBox<Int>()
        let reentered = LockedCount()
        let vm = makeAsyncResourceVM(
            loader: queue.load,
            retention: .retainPrevious,
            cleanup: { value in
                guard value == 1, reentered.value == 0 else { return }
                reentered.increment()
                let completed = DispatchSemaphore(value: 0)
                Task {
                    await owner.value?.reload()
                    completed.signal()
                }
                completed.wait()
            }
        )
        owner.value = vm
        let names = LockedValues<String>()
        let subscription = vm.propertyChanged.sink { names.append($0) }

        await vm.load()
        let baseline = names.values.count
        await vm.reload()

        XCTAssertEqual(Array(names.values.dropFirst(baseline)), ["state", "state", "state"])
        XCTAssertEqual(vm.state.status, .ready)
        XCTAssertEqual(vm.state.value, 3)
        XCTAssertEqual(reentered.value, 1)
        withExtendedLifetime(subscription) {}
    }

    /// ARES-011 — disposal cancels active work and makes late completion inert.
    func testAres011DisposeMakesLateWorkInert() async {
        let deferred = DeferredValue<Int>()
        let cleaned = LockedValues<Int>()
        let vm = makeAsyncResourceVM(loader: deferred.get) { cleaned.append($0) }
        let intent = Task { await vm.load() }
        await eventually { vm.state.status == .loading }

        vm.dispose()
        await intent.value
        deferred.resolve(8)
        await eventually { cleaned.values == [8] }

        XCTAssertEqual(vm.status, .disposed)
        XCTAssertEqual(cleaned.values, [8])
    }

    func testReentrantDisposeDuringLoadingNotificationPreventsLoaderStart() async {
        let calls = LockedCount()
        let vm = makeAsyncResourceVM {
            calls.increment()
            return 1
        }
        let subscription = vm.propertyChanged.sink { propertyName in
            if propertyName == "state" {
                vm.dispose()
            }
        }

        await vm.load()

        XCTAssertEqual(calls.value, 0)
        XCTAssertEqual(vm.status, .disposed)
        withExtendedLifetime(subscription) {}
    }

    /// When a cleanup callback disposes the VM mid-reload, the `resourceDisposed`
    /// guard must (a) stop the loader from restarting and (b) suppress
    /// AsyncResourceVM's own "state" notification. The terminal Disposed
    /// transition still publishes the lifecycle pair "status"/"isConstructed"
    /// per LIFE-004 / spec/02 invariant 4 (every Status change publishes) —
    /// matching the C#/Python/TypeScript ARES-011 analogs.
    func testDiscardCleanupDisposalPreventsLoaderRestartAndSuppressesStateNotification() async {
        let calls = LockedCount()
        let owner = WeakAsyncResourceBox<Int>()
        let vm = makeAsyncResourceVM(
            loader: {
                calls.increment()
                return 1
            },
            cleanup: { _ in owner.value?.dispose() }
        )
        owner.value = vm
        await vm.load()
        let names = LockedValues<String>()
        let subscription = vm.propertyChanged.sink { names.append($0) }

        await vm.reload()

        XCTAssertEqual(calls.value, 1)
        XCTAssertFalse(names.values.contains("state"))
        XCTAssertEqual(names.values, ["status", "isConstructed"])
        XCTAssertEqual(vm.status, .disposed)
        withExtendedLifetime(subscription) {}
    }
}
