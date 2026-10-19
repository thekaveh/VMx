import Combine
import XCTest
@testable import VMx

private enum AsyncResourceTestError: Error { case failed }

/// Hang guard for signal waits. Tests resume as soon as the awaited event is
/// observed; this bound only turns a missing event into a failure.
private let signalTimeout: TimeInterval = 30

private final class DeferredValue<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Value, Never>?
    private var resolved: Value?

    /// Fulfilled once a loader parks in `get()`. The loader runs in an
    /// unstructured task, so tests await this signal instead of polling.
    let parked: XCTestExpectation

    init() {
        parked = XCTestExpectation(description: "loader parked in DeferredValue.get()")
        parked.assertForOverFulfill = false
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
            parked.fulfill()
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
    private var countExpectations: [(count: Int, expectation: XCTestExpectation)] = []

    func append(_ value: Value) {
        let reached: [XCTestExpectation] = lock.withLock {
            storage.append(value)
            let count = storage.count
            let met = countExpectations.filter { $0.count <= count }.map { $0.expectation }
            countExpectations.removeAll { $0.count <= count }
            return met
        }
        reached.forEach { $0.fulfill() }
    }

    /// Returns an expectation fulfilled once `count` values have been
    /// appended, including values appended before this call.
    func expectation(forCount count: Int, _ description: String) -> XCTestExpectation {
        let expectation = XCTestExpectation(description: description)
        let alreadyReached: Bool = lock.withLock {
            guard storage.count < count else { return true }
            countExpectations.append((count: count, expectation: expectation))
            return false
        }
        if alreadyReached { expectation.fulfill() }
        return expectation
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

/// Runs `body` inside a task-cancellation handler that counts every
/// cancellation delivered to the calling loader task.
private func recordingCancellation<Value>(
    _ count: LockedCount,
    _ body: () async throws -> Value
) async rethrows -> Value {
    try await withTaskCancellationHandler {
        try await body()
    } onCancel: {
        count.increment()
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
    /// Catalog clauses: Loading is observable before Ready(value), each
    /// visible transition publishes exactly one local + one hub "state"
    /// notification, and after success reload is enabled while load and
    /// cancel are disabled.
    func testAres002SuccessfulLoadNotifies() async {
        let deferred = DeferredValue<Int>()
        let hub = MessageHub()
        let vm = AsyncResourceVM(
            name: "resource",
            loader: deferred.get,
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
        let localStatuses = LockedValues<AsyncResourceStatus>()
        let localNames = LockedValues<String>()
        let hubNames = LockedValues<String>()
        let localCancellable = vm.propertyChanged.sink { name in
            localNames.append(name)
            localStatuses.append(vm.state.status)
        }
        let hubCancellable = hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.sender === vm }
            .sink { hubNames.append($0.propertyName) }

        let intent = Task { await vm.load() }
        await fulfillment(of: [deferred.parked], timeout: signalTimeout)

        // Loading snapshot: exactly one state pair so far.
        XCTAssertEqual(vm.state.status, .loading)
        XCTAssertNil(vm.state.value)
        XCTAssertEqual(localNames.values, ["state"])
        XCTAssertEqual(hubNames.values, ["state"])
        XCTAssertEqual(localStatuses.values, [.loading])

        deferred.resolve(7)
        await intent.value

        XCTAssertEqual(vm.state.status, .ready)
        XCTAssertEqual(vm.state.value, 7)
        XCTAssertEqual(localNames.values, ["state", "state"])
        XCTAssertEqual(hubNames.values, ["state", "state"])
        XCTAssertEqual(localStatuses.values, [.loading, .ready])
        XCTAssertTrue(vm.reloadCommand.canExecute())
        XCTAssertFalse(vm.loadCommand.canExecute())
        XCTAssertFalse(vm.cancelCommand.canExecute())
        withExtendedLifetime((localCancellable, hubCancellable)) {}
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

    /// ARES-003 — the fire-and-forget load reports failure only as state.
    func testAres003CommandFailureBecomesStateNotCommandError() async {
        let vm: AsyncResourceVM<Int> = makeAsyncResourceVM {
            throw AsyncResourceTestError.failed
        }
        let commandErrors = LockedCount()
        let errorsCancellable = vm.loadCommand.errors.sink { _ in commandErrors.increment() }
        let names = LockedValues<String>()
        let stateCancellable = vm.propertyChanged.sink { names.append($0) }
        let settled = names.expectation(forCount: 2, "Loading then Error published")

        vm.loadCommand.execute()
        await fulfillment(of: [settled], timeout: signalTimeout)

        XCTAssertEqual(vm.state.status, .error)
        XCTAssertNil(vm.state.value)
        XCTAssertTrue(vm.state.error is AsyncResourceTestError)
        XCTAssertEqual(commandErrors.value, 0)
        XCTAssertTrue(vm.reloadCommand.canExecute())
        withExtendedLifetime((errorsCancellable, stateCancellable)) {}
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
    /// Catalog clauses: the loader observes cancellation, cancellation via the
    /// cancel command restores Idle without error state or async-command
    /// error, and repeated cancel while Idle is inert.
    func testAres005CancelCommandIsObservedAndIdleCancelIsInert() async {
        let parked = expectation(description: "loader started")
        let observedCancellation = expectation(description: "loader observed cancellation")
        let vm: AsyncResourceVM<Int> = makeAsyncResourceVM {
            parked.fulfill()
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 1_000_000)
            }
            observedCancellation.fulfill()
            throw CancellationError()
        }
        let commandErrors = LockedCount()
        let errorsCancellable = vm.loadCommand.errors.sink { _ in commandErrors.increment() }

        vm.loadCommand.execute()
        await fulfillment(of: [parked], timeout: signalTimeout)
        XCTAssertEqual(vm.state.status, .loading)
        XCTAssertTrue(vm.cancelCommand.canExecute())

        vm.cancelCommand.execute()
        await fulfillment(of: [observedCancellation], timeout: signalTimeout)

        XCTAssertEqual(vm.state.status, .idle)
        XCTAssertNil(vm.state.error)
        XCTAssertNil(vm.state.value)
        // Let the command body settle before checking the error channel.
        try? await Task.sleep(nanoseconds: 20_000_000)
        XCTAssertEqual(commandErrors.value, 0)
        XCTAssertEqual(vm.state.status, .idle)
        XCTAssertFalse(vm.cancelCommand.canExecute())

        // Repeated cancel while Idle is inert: no state notification, no error.
        let notifications = LockedCount()
        let stateCancellable = vm.propertyChanged.sink { _ in notifications.increment() }
        vm.cancel()
        vm.cancelCommand.execute()
        vm.cancel()
        XCTAssertEqual(notifications.value, 0)
        XCTAssertEqual(vm.state.status, .idle)
        XCTAssertNil(vm.state.error)
        XCTAssertEqual(commandErrors.value, 0)
        withExtendedLifetime((errorsCancellable, stateCancellable)) {}
    }

    /// ARES-005 — direct `cancel()` restores Idle without Error.
    func testAres005CancellationRestoresIdle() async {
        let deferred = DeferredValue<Int>()
        let vm = makeAsyncResourceVM(loader: deferred.get)
        let intent = Task { await vm.load() }
        await fulfillment(of: [deferred.parked], timeout: signalTimeout)
        XCTAssertEqual(vm.state.status, .loading)

        vm.cancel()
        await intent.value

        XCTAssertEqual(vm.state.status, .idle)
        XCTAssertNil(vm.state.error)
        deferred.resolve(1)
    }

    /// ARES-006 — retained reload exposes and restores the previous value.
    /// Catalog clauses: Loading carries the old value, cancellation restores
    /// Ready(old) without cleaning it, and a later failed reload is Error
    /// carrying the old value and the current host error.
    func testAres006RetainedReloadRestoresValue() async {
        let deferred = DeferredValue<Int>()
        let queue = LoaderQueue<Int>([
            { 3 },
            { await deferred.get() },
            { throw AsyncResourceTestError.failed },
        ])
        let cleaned = LockedValues<Int>()
        let vm = makeAsyncResourceVM(loader: queue.load, retention: .retainPrevious) {
            cleaned.append($0)
        }
        await vm.load()
        let intent = Task { await vm.reload() }
        await fulfillment(of: [deferred.parked], timeout: signalTimeout)
        XCTAssertEqual(vm.state.status, .loading)

        XCTAssertEqual(vm.state.value, 3)
        vm.cancel()
        await intent.value
        XCTAssertEqual(vm.state.status, .ready)
        XCTAssertEqual(vm.state.value, 3)
        XCTAssertEqual(cleaned.values, [])

        await vm.reload()
        XCTAssertEqual(vm.state.status, .error)
        XCTAssertEqual(vm.state.value, 3)
        XCTAssertTrue(vm.state.error is AsyncResourceTestError)
        XCTAssertEqual(cleaned.values, [])
        deferred.resolve(4)
    }

    /// ARES-007 — discard mode releases the accepted value before loading.
    /// Catalog clauses: the old value is cleaned exactly once before the
    /// value-less Loading notification, cancellation restores Idle, and a
    /// later current failure is a value-less Error.
    func testAres007DiscardReleasesBeforeLoading() async {
        let deferred = DeferredValue<Int>()
        let queue = LoaderQueue<Int>([
            { 3 },
            { await deferred.get() },
            { throw AsyncResourceTestError.failed },
        ])
        let cleaned = LockedValues<Int>()
        let vm = makeAsyncResourceVM(loader: queue.load) { cleaned.append($0) }
        await vm.load()
        let cleanedAtLoading = LockedValues<[Int]>()
        let subscription = vm.propertyChanged.sink { _ in
            if vm.state.status == .loading {
                cleanedAtLoading.append(cleaned.values)
            }
        }
        let intent = Task { await vm.reload() }
        await fulfillment(of: [deferred.parked], timeout: signalTimeout)
        XCTAssertEqual(vm.state.status, .loading)

        XCTAssertNil(vm.state.value)
        XCTAssertEqual(cleaned.values, [3])
        XCTAssertEqual(cleanedAtLoading.values, [[3]])

        vm.cancel()
        await intent.value
        XCTAssertEqual(vm.state.status, .idle)
        XCTAssertNil(vm.state.value)

        // From Idle the next current operation is a load; it fails value-less.
        await vm.load()
        XCTAssertEqual(vm.state.status, .error)
        XCTAssertNil(vm.state.value)
        XCTAssertTrue(vm.state.error is AsyncResourceTestError)
        XCTAssertEqual(cleaned.values, [3])
        withExtendedLifetime(subscription) {}
        deferred.resolve(4)
    }

    /// ARES-008 — overlapping operations use latest-start-wins ordering.
    /// Catalog clauses: the older loader receives cancellation when the newer
    /// operation is admitted; only the newer settlement determines the final
    /// state; the older completion publishes no state or command notification.
    /// Order covered here: newer succeeds, then the older loader succeeds.
    func testAres008LatestStartWins() async {
        let first = DeferredValue<Int>()
        let second = DeferredValue<Int>()
        let olderCancellations = LockedCount()
        let queue = LoaderQueue<Int>([
            { await recordingCancellation(olderCancellations) { await first.get() } },
            { await second.get() },
        ])
        let cleaned = LockedValues<Int>()
        let vm = makeAsyncResourceVM(loader: queue.load) { cleaned.append($0) }
        let notifications = LockedCount()
        let cancellables = [vm.propertyChanged.sink { _ in notifications.increment() }]
            + [vm.loadCommand.canExecuteChanged, vm.reloadCommand.canExecuteChanged,
               vm.cancelCommand.canExecuteChanged]
            .map { $0.sink { notifications.increment() } }
        let older = Task { await vm.load() }
        await fulfillment(of: [first.parked], timeout: signalTimeout)
        XCTAssertEqual(vm.state.status, .loading)
        let newer = Task { await vm.reload() }
        await fulfillment(of: [second.parked], timeout: signalTimeout)
        XCTAssertEqual(olderCancellations.value, 1)
        XCTAssertEqual(vm.state.status, .loading)
        second.resolve(2)
        await newer.value
        XCTAssertEqual(vm.state.status, .ready)
        XCTAssertEqual(vm.state.value, 2)

        let settledNotifications = notifications.value
        // The stale success is cleaned (configured cleanup), which is the
        // observable signal that the older completion was processed.
        let staleProcessed = cleaned.expectation(forCount: 1, "older completion processed")
        first.resolve(1)
        await older.value
        await fulfillment(of: [staleProcessed], timeout: signalTimeout)

        XCTAssertEqual(notifications.value, settledNotifications)
        XCTAssertEqual(vm.state.status, .ready)
        XCTAssertEqual(vm.state.value, 2)
        XCTAssertEqual(olderCancellations.value, 1)
        withExtendedLifetime(cancellables) {}
    }

    /// ARES-008 — the older loader settles first; the newer failure decides.
    func testAres008OlderSettlesFirstNewerFailureDecides() async {
        let first = DeferredValue<Int>()
        let second = DeferredValue<Int>()
        let olderCancellations = LockedCount()
        let queue = LoaderQueue<Int>([
            { await recordingCancellation(olderCancellations) { await first.get() } },
            {
                _ = await second.get()
                throw AsyncResourceTestError.failed
            },
        ])
        let cleaned = LockedValues<Int>()
        let vm = makeAsyncResourceVM(loader: queue.load) { cleaned.append($0) }
        let notifications = LockedCount()
        let cancellables = [vm.propertyChanged.sink { _ in notifications.increment() }]
            + [vm.loadCommand.canExecuteChanged, vm.reloadCommand.canExecuteChanged,
               vm.cancelCommand.canExecuteChanged]
            .map { $0.sink { notifications.increment() } }
        let older = Task { await vm.load() }
        await fulfillment(of: [first.parked], timeout: signalTimeout)
        let newer = Task { await vm.reload() }
        await fulfillment(of: [second.parked], timeout: signalTimeout)
        XCTAssertEqual(olderCancellations.value, 1)

        let loadingNotifications = notifications.value
        let staleProcessed = cleaned.expectation(forCount: 1, "older completion processed")
        first.resolve(1)
        await older.value
        await fulfillment(of: [staleProcessed], timeout: signalTimeout)
        XCTAssertEqual(notifications.value, loadingNotifications)
        XCTAssertEqual(vm.state.status, .loading)
        XCTAssertNil(vm.state.value)

        second.resolve(0)
        await newer.value
        XCTAssertEqual(vm.state.status, .error)
        XCTAssertNil(vm.state.value)
        XCTAssertTrue(vm.state.error is AsyncResourceTestError)
        XCTAssertEqual(cleaned.values, [1])
        withExtendedLifetime(cancellables) {}
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
        await fulfillment(of: [first.parked], timeout: signalTimeout)
        XCTAssertEqual(vm.state.status, .loading)
        let newer = Task { await vm.reload() }
        second.resolve(2)
        await newer.value
        let acceptedNotifications = notifications.value
        let staleCleaned = cleaned.expectation(forCount: 1, "stale success cleaned")
        first.resolve(1)
        await older.value
        await fulfillment(of: [staleCleaned], timeout: signalTimeout)

        XCTAssertEqual(cleaned.values, [1])
        XCTAssertEqual(notifications.value, acceptedNotifications)
        // The stale value is never exposed or installed: the state still holds 2.
        XCTAssertEqual(vm.state.status, .ready)
        XCTAssertEqual(vm.state.value, 2)
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
        XCTAssertEqual(cleaned.values, [1])
        vm.dispose()
        vm.dispose()

        XCTAssertEqual(cleaned.values, [1, 2])
    }

    /// ARES-010 — without cleanup, neither a replaced nor the current value is
    /// implicitly disposed (values here are VMx view models).
    func testAres010WithoutCleanupNoValueIsDisposed() async {
        let hub = MessageHub()
        let produced = LockedValues<ComponentVMBase>()
        let vm = makeAsyncResourceVM(loader: {
            let value = ComponentVMBase(
                name: "value", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
            )
            produced.append(value)
            return value
        }, retention: .retainPrevious)

        await vm.load()
        await vm.reload()
        vm.dispose()
        vm.dispose()

        XCTAssertEqual(produced.values.count, 2)
        for value in produced.values {
            XCTAssertNotEqual(value.status, .disposed)
        }
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
        let cancellations = LockedCount()
        let vm = makeAsyncResourceVM(loader: {
            await recordingCancellation(cancellations) { await deferred.get() }
        }) { cleaned.append($0) }
        let intent = Task { await vm.load() }
        await fulfillment(of: [deferred.parked], timeout: signalTimeout)
        XCTAssertEqual(vm.state.status, .loading)
        XCTAssertEqual(cancellations.value, 0)

        let notifications = LockedCount()
        let stateCancellable = vm.propertyChanged.sink { _ in notifications.increment() }
        let commandCancellables = [
            vm.loadCommand.canExecuteChanged,
            vm.reloadCommand.canExecuteChanged,
            vm.cancelCommand.canExecuteChanged,
        ].map { $0.sink { notifications.increment() } }

        vm.dispose()
        vm.dispose()
        // The current loader received cancellation exactly once.
        XCTAssertEqual(cancellations.value, 1)
        await intent.value
        let statusAfterDispose = vm.state.status
        let notificationsAfterDispose = notifications.value

        XCTAssertFalse(vm.loadCommand.canExecute())
        XCTAssertFalse(vm.reloadCommand.canExecute())
        XCTAssertFalse(vm.cancelCommand.canExecute())
        await vm.load()
        await vm.reload()
        vm.cancel()
        let lateCleaned = cleaned.expectation(forCount: 1, "late success cleaned after disposal")
        deferred.resolve(8)
        await fulfillment(of: [lateCleaned], timeout: signalTimeout)

        XCTAssertEqual(vm.status, .disposed)
        XCTAssertEqual(vm.state.status, statusAfterDispose)
        XCTAssertNil(vm.state.value)
        XCTAssertEqual(notifications.value, notificationsAfterDispose)
        XCTAssertEqual(cleaned.values, [8])
        XCTAssertEqual(cancellations.value, 1)
        withExtendedLifetime((stateCancellable, commandCancellables)) {}
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
