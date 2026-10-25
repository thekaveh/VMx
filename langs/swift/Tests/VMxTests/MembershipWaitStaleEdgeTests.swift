//
// MembershipWaitStaleEdgeTests.swift — #736 regression tests.
//
// A membership waiter's edge must not outlive the transaction it waited for.
// Thread A, inside X's transaction, waits for Y's transaction, which thread B
// holds. When B ends Y's transaction, A wakes; the test then holds A between
// its wake and its own `endWait` while B starts an operation on X. B must wait
// for A's transaction and then succeed, not see a cycle that no longer exists.
//

import Combine
import Foundation
import XCTest
@testable import VMx

private let staleEdgeTimeout: TimeInterval = 5

private final class SharedValue<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: T
    init(_ value: T) { storage = value }
    var value: T {
        get { lock.withLock { storage } }
        set { lock.withLock { storage = newValue } }
    }
}

final class MembershipWaitStaleEdgeTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        ThreadWaitGraph.shared.onWaitDecidedForTesting = nil
        ThreadWaitGraph.shared.onMembershipWaitWokeForTesting = nil
        cancellables.removeAll()
        super.tearDown()
    }

    private func child(_ name: String) throws -> ComponentVM {
        try ComponentVM.builder()
            .name(name)
            .services(hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
    }

    private func composite(_ name: String) -> CompositeVM<ComponentVM> {
        CompositeVM<ComponentVM>(
            name: name, hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
    }

    /// Runs the #736 reproduction and returns once both threads finish.
    /// `operation` runs on thread B against X right after B's add to Y.
    private func runAfterAReleasedTransaction(
        x xAdd: @escaping (ComponentVM) -> Result<Void, ContainerOwnershipError>,
        yIsGroup: Bool = false,
        operation: @escaping () -> Void,
        file: StaticString = #filePath,
        line: UInt = #line
    ) throws {
        // Y is the container whose transaction A waits for, so Y's
        // `endMembershipTransaction` is the release under test.
        let yAdd: (ComponentVM) -> Result<Void, ContainerOwnershipError>
        let yChanged: AnyPublisher<CollectionChangedEvent, Never>
        if yIsGroup {
            let group = GroupVM<ComponentVM>(
                name: "y", hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
            yAdd = group.addResult
            yChanged = group.collectionChanged
        } else {
            let y = composite("y")
            yAdd = y.addResult
            yChanged = y.collectionChanged
        }
        let c = try child("c")
        try yAdd(c).get()

        let threadA = SharedValue<UInt64>(0)
        let threadB = SharedValue<UInt64>(0)
        let aWaiting = DispatchSemaphore(value: 0)
        let bDecided = DispatchSemaphore(value: 0)
        let bInSink = DispatchSemaphore(value: 0)
        let aDone = DispatchSemaphore(value: 0)
        let bDone = DispatchSemaphore(value: 0)
        let holdA = SharedValue(true)
        let blockOnce = SharedValue(true)
        let bAccepted = SharedValue<Bool?>(nil)
        let heldUntilBDecided = SharedValue<DispatchTimeoutResult?>(nil)
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            if accepted, caller == threadA.value { aWaiting.signal() }
            if caller == threadB.value, bAccepted.value == nil {
                bAccepted.value = accepted
                bDecided.signal()
            }
        }
        ThreadWaitGraph.shared.onMembershipWaitWokeForTesting = {
            guard ThreadWaitGraph.currentThread == threadA.value, holdA.value else { return }
            holdA.value = false
            heldUntilBDecided.value = bDecided.wait(timeout: .now() + staleEdgeTimeout)
        }
        yChanged.sink { _ in
            guard blockOnce.value else { return }
            blockOnce.value = false
            bInSink.signal()
            _ = aWaiting.wait(timeout: .now() + staleEdgeTimeout)
        }.store(in: &cancellables)

        Thread.detachNewThread {
            threadB.value = ThreadWaitGraph.currentThread
            _ = yAdd(try! ComponentVM.builder()
                .name("e")
                .services(hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
                .build())
            operation()
            bDone.signal()
        }
        XCTAssertEqual(bInSink.wait(timeout: .now() + staleEdgeTimeout), .success, file: file, line: line)
        Thread.detachNewThread {
            threadA.value = ThreadWaitGraph.currentThread
            _ = xAdd(c)
            aDone.signal()
        }

        XCTAssertEqual(aDone.wait(timeout: .now() + staleEdgeTimeout), .success, "thread A hung", file: file, line: line)
        XCTAssertEqual(bDone.wait(timeout: .now() + staleEdgeTimeout), .success, "thread B hung", file: file, line: line)
        XCTAssertFalse(holdA.value, "thread A was held between its wake and its endWait", file: file, line: line)
        XCTAssertEqual(heldUntilBDecided.value, .success, "B's wait on X was decided while A was held",
                       file: file, line: line)
        XCTAssertEqual(bAccepted.value, true, "B waited for A's transaction instead of seeing a stale cycle",
                       file: file, line: line)
    }

    private func constructedComposite(holding k: ComponentVM) throws -> CompositeVM<ComponentVM> {
        let x = composite("x")
        try x.addResult(k).get()
        try x.construct()
        return x
    }

    func testCompositeAddAfterAReleasedTransactionWaitsAndSucceeds() throws {
        let x = try constructedComposite(holding: try child("k"))
        let f = try child("f")
        let result = SharedValue<Result<Void, ContainerOwnershipError>?>(nil)
        try runAfterAReleasedTransaction(x: x.addResult) { result.value = x.addResult(f) }
        guard case .success = result.value else { return XCTFail("addResult: \(String(describing: result.value))") }
    }

    func testCompositeRemoveAfterAReleasedTransactionWaitsAndSucceeds() throws {
        let k = try child("k")
        let x = try constructedComposite(holding: k)
        let removed = SharedValue<Bool?>(nil)
        try runAfterAReleasedTransaction(x: x.addResult) { removed.value = x.remove(k) }
        XCTAssertEqual(removed.value, true)
    }

    func testCompositeSelectChildAfterAReleasedTransactionWaitsAndSelects() throws {
        let k = try child("k")
        let x = try constructedComposite(holding: k)
        try runAfterAReleasedTransaction(x: x.addResult) { x.selectChild(k) }
        XCTAssertTrue(x.current === k)
    }

    func testCompositeSetCurrentAfterAReleasedTransactionWaitsAndSelects() throws {
        let k = try child("k")
        let x = try constructedComposite(holding: k)
        try runAfterAReleasedTransaction(x: x.addResult) { try? x.setCurrent(k) }
        XCTAssertTrue(x.current === k)
    }

    func testGroupAddAfterAReleasedTransactionWaitsAndSucceeds() throws {
        let x = GroupVM<ComponentVM>(
            name: "x", hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
        try x.addResult(try child("k")).get()
        let f = try child("f")
        let result = SharedValue<Result<Void, ContainerOwnershipError>?>(nil)
        try runAfterAReleasedTransaction(x: x.addResult) { result.value = x.addResult(f) }
        guard case .success = result.value else { return XCTFail("addResult: \(String(describing: result.value))") }
    }

    func testAGroupReleasesItsWaitersBeforeWakingThem() throws {
        let x = try constructedComposite(holding: try child("k"))
        let f = try child("f")
        let result = SharedValue<Result<Void, ContainerOwnershipError>?>(nil)
        try runAfterAReleasedTransaction(x: x.addResult, yIsGroup: true) { result.value = x.addResult(f) }
        guard case .success = result.value else { return XCTFail("addResult: \(String(describing: result.value))") }
    }
}
