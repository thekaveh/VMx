//
// DeferredDisposeHandoffTests.swift — #1153 (and #1064 for CompositeVM).
//
// A `dispose()` inside the caller's own membership transaction, or inside its
// own current publication, only records a deferral. When the transaction or
// the publication ends, the container calls `dispose()` again: the handoff.
// The deferral stays set until that call admits the disposal, so another
// thread's structural operation that starts in between is refused as
// disposal in progress (spec/06 §4.2, spec/07). Each test overrides
// `dispose()` and acts on the second main-thread call, which is the handoff,
// before the base disposal runs.
//
// Every wait is bounded by `hangGuard`; a regression shows up as a failed
// assertion or a timed-out wait, not a hang.
//

import Combine
import Foundation
import XCTest
@testable import VMx

private final class Shared<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: T
    init(_ value: T) { stored = value }
    var value: T {
        get { lock.withLock { stored } }
        set { lock.withLock { stored = newValue } }
    }
}

/// A group that runs `beforeDispose` on each main-thread `dispose()` call,
/// with the call's 1-based number, before the base disposal.
private final class HandoffGroup: GroupVM<ComponentVM> {
    var beforeDispose: ((Int) -> Void)?
    private(set) var mainCalls = 0

    override func dispose() {
        if Thread.isMainThread {
            mainCalls += 1
            beforeDispose?(mainCalls)
        }
        super.dispose()
    }
}

/// A composite that runs `beforeDispose` on each main-thread `dispose()`
/// call, with the call's 1-based number, before the base disposal.
private final class HandoffComposite: CompositeVM<ComponentVM> {
    var beforeDispose: ((Int) -> Void)?
    private(set) var mainCalls = 0

    override func dispose() {
        if Thread.isMainThread {
            mainCalls += 1
            beforeDispose?(mainCalls)
        }
        super.dispose()
    }
}

final class DeferredDisposeHandoffTests: XCTestCase {
    /// The hang guard for every wait. Tests resume as soon as the awaited
    /// event happens; only a regression waits this long.
    private let hangGuard: TimeInterval = 5
    private var cancellables = Set<AnyCancellable>()

    override func setUp() {
        super.setUp()
        XCTAssertTrue(Thread.isMainThread, "the handoff hooks act on main-thread calls only")
    }

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func deadline() -> DispatchTime { .now() + hangGuard }

    private func leaf(_ name: String) throws -> ComponentVM {
        try ComponentVM.builder().name(name).withNullServices().build()
    }

    private func makeGroup() -> HandoffGroup {
        HandoffGroup(name: "group", hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
    }

    private func makeComposite(onCurrentChanged: ((ComponentVM?) -> Void)? = nil) -> HandoffComposite {
        HandoffComposite(
            name: "composite", hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE,
            onCurrentChanged: onCurrentChanged
        )
    }

    /// Asserts that `result` is the container's disposal-in-progress refusal.
    private func assertDisposalRefusal(
        _ result: Result<Void, ContainerOwnershipError>?,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        guard case let .failure(.attachmentFailed(error))? = result else {
            return XCTFail(
                "the foreign add during the handoff was not refused: \(String(describing: result))",
                file: file, line: line
            )
        }
        XCTAssertTrue(
            String(describing: type(of: error)).hasSuffix("DisposalAdmissionError"),
            "expected a disposal-in-progress refusal, got \(error)",
            file: file, line: line
        )
    }

    /// Starts `body` on a new thread and waits for it within the hang guard.
    private func runOnWorker(_ body: @escaping () -> Void) -> DispatchTimeoutResult {
        let done = DispatchSemaphore(value: 0)
        Thread.detachNewThread {
            body()
            done.signal()
        }
        return done.wait(timeout: deadline())
    }

    // ── GroupVM (#1153) ─────────────────────────────────────────────────

    /// #1153 variant A: the handoff from the owner's transaction end joins a
    /// worker's `addResult(x)`. The add is refused as disposal in progress,
    /// `x` is neither a child nor disposed, and the group ends Disposed.
    func testGroupHandoffRefusesAForeignAddAfterTheOwnerTransactionEnds() throws {
        let b = try leaf("b")
        let x = try leaf("x")
        let group = makeGroup()
        try group.construct()
        let workerResult = Shared<Result<Void, ContainerOwnershipError>?>(nil)
        let workerJoin = Shared<DispatchTimeoutResult?>(nil)
        group.beforeDispose = { [unowned group, unowned self] call in
            guard call == 2 else { return } // the handoff from the transaction end
            workerJoin.value = self.runOnWorker { workerResult.value = group.addResult(x) }
        }
        group.collectionChanged.sink { [unowned group] _ in
            if Thread.isMainThread { group.dispose() }
        }.store(in: &cancellables)

        group.add(b)

        XCTAssertEqual(group.mainCalls, 2)
        XCTAssertEqual(workerJoin.value, .success)
        assertDisposalRefusal(workerResult.value)
        XCTAssertFalse(group.snapshot().contains { $0 === x })
        XCTAssertNil(x._parent)
        XCTAssertNotEqual(x.status, .disposed)
        XCTAssertEqual(b.status, .disposed)
        XCTAssertEqual(group.status, .disposed)
    }

    /// #1153 variant C: the handoff starts a worker's `addResult(x)` and
    /// returns once the add returns or reaches its handler. The worker's
    /// handler would wait for the main `add(b)` to return, while the main
    /// disposal would wait for the worker's transaction. The add is refused,
    /// so its handler never runs, the main add returns and the group ends
    /// Disposed.
    func testGroupHandoffDoesNotWaitForAForeignAddsHandler() throws {
        let b = try leaf("b")
        let x = try leaf("x")
        let group = makeGroup()
        try group.construct()
        let guardWait = hangGuard
        let workerProgress = DispatchSemaphore(value: 0)
        let workerDone = DispatchSemaphore(value: 0)
        let mainAddReturned = DispatchSemaphore(value: 0)
        let workerResult = Shared<Result<Void, ContainerOwnershipError>?>(nil)
        let handlerWait = Shared<DispatchTimeoutResult?>(nil)
        let hookWait = Shared<DispatchTimeoutResult?>(nil)
        group.beforeDispose = { [unowned group] call in
            guard call == 2 else { return } // the handoff from the transaction end
            Thread.detachNewThread {
                workerResult.value = group.addResult(x)
                workerProgress.signal()
                workerDone.signal()
            }
            hookWait.value = workerProgress.wait(timeout: .now() + guardWait)
        }
        group.collectionChanged.sink { [unowned group] _ in
            if Thread.isMainThread {
                group.dispose()
                return
            }
            // Only an admitted foreign add publishes here.
            workerProgress.signal()
            handlerWait.value = mainAddReturned.wait(timeout: .now() + guardWait)
        }.store(in: &cancellables)

        group.add(b)
        mainAddReturned.signal()

        XCTAssertEqual(workerDone.wait(timeout: deadline()), .success)
        XCTAssertEqual(hookWait.value, .success)
        XCTAssertNil(handlerWait.value, "the foreign add was admitted and its handler waited for the main add")
        assertDisposalRefusal(workerResult.value)
        XCTAssertEqual(group.mainCalls, 2)
        XCTAssertFalse(group.snapshot().contains { $0 === x })
        XCTAssertNotEqual(x.status, .disposed)
        XCTAssertEqual(group.status, .disposed)
    }

    // ── CompositeVM (#1064, #1153) ──────────────────────────────────────

    /// Variant A on `CompositeVM`: the handoff from the owner's transaction
    /// end refuses a worker's `addResult(x)` as disposal in progress.
    func testCompositeHandoffRefusesAForeignAddAfterTheOwnerTransactionEnds() throws {
        let b = try leaf("b")
        let x = try leaf("x")
        let composite = makeComposite()
        try composite.construct()
        let workerResult = Shared<Result<Void, ContainerOwnershipError>?>(nil)
        let workerJoin = Shared<DispatchTimeoutResult?>(nil)
        composite.beforeDispose = { [unowned composite, unowned self] call in
            guard call == 2 else { return } // the handoff from the transaction end
            workerJoin.value = self.runOnWorker { workerResult.value = composite.addResult(x) }
        }
        composite.collectionChanged.sink { [unowned composite] _ in
            if Thread.isMainThread { composite.dispose() }
        }.store(in: &cancellables)

        composite.add(b)

        XCTAssertEqual(composite.mainCalls, 2)
        XCTAssertEqual(workerJoin.value, .success)
        assertDisposalRefusal(workerResult.value)
        XCTAssertFalse(composite.snapshot().contains { $0 === x })
        XCTAssertNil(x._parent)
        XCTAssertNotEqual(x.status, .disposed)
        XCTAssertEqual(b.status, .disposed)
        XCTAssertEqual(composite.status, .disposed)
    }

    /// The same handoff from the end of a current publication (spec/06 §4.3
    /// rule 5): a `dispose()` from `onCurrentChanged` defers, and the handoff
    /// when the publication ends refuses a worker's `addResult(x)`.
    func testCompositePublicationHandoffRefusesAForeignAdd() throws {
        let b = try leaf("b")
        let x = try leaf("x")
        let compositeRef = Shared<HandoffComposite?>(nil)
        let composite = makeComposite(onCurrentChanged: { value in
            if Thread.isMainThread && value != nil { compositeRef.value?.dispose() }
        })
        compositeRef.value = composite
        composite.add(b)
        try composite.construct()
        let workerResult = Shared<Result<Void, ContainerOwnershipError>?>(nil)
        let workerJoin = Shared<DispatchTimeoutResult?>(nil)
        composite.beforeDispose = { [unowned composite, unowned self] call in
            guard call == 2 else { return } // the handoff from the publication end
            workerJoin.value = self.runOnWorker { workerResult.value = composite.addResult(x) }
        }

        try composite.setCurrent(b)

        XCTAssertEqual(composite.mainCalls, 2)
        XCTAssertEqual(workerJoin.value, .success)
        assertDisposalRefusal(workerResult.value)
        XCTAssertFalse(composite.snapshot().contains { $0 === x })
        XCTAssertNil(x._parent)
        XCTAssertNotEqual(x.status, .disposed)
        XCTAssertEqual(b.status, .disposed)
        XCTAssertEqual(composite.status, .disposed)
        compositeRef.value = nil
    }
}
