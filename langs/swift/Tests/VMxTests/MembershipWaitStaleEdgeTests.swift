//
// MembershipWaitStaleEdgeTests.swift — #736 regression tests.
//
// A membership waiter's edge must not outlive the transaction it waited for.
// Only a disposal waits for another thread's membership transaction
// (ADR-0187), so both waits here are disposals. Thread A, inside X's
// transaction, disposes Y, whose transaction thread B holds. When B ends Y's
// transaction, A wakes; the test then holds A between its wake and its own
// `endWait` while B disposes X. B must wait for A's transaction and then
// dispose X, not see a cycle that no longer exists.
//

import Combine
import Foundation
import XCTest
@testable import VMx

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

    /// The operations the tests need from a composite or a group.
    private struct Container {
        let vm: ComponentVMBase
        let add: (ComponentVM) -> Result<Void, ContainerOwnershipError>
        let dispose: () -> Void
        let changes: AnyPublisher<CollectionChangedEvent, Never>
    }

    private func container(_ name: String, group: Bool) -> Container {
        if group {
            let g = GroupVM<ComponentVM>(
                name: name, hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
            return Container(vm: g, add: g.addResult, dispose: g.dispose, changes: g.collectionChanged)
        }
        let c = composite(name)
        return Container(vm: c, add: c.addResult, dispose: c.dispose, changes: c.collectionChanged)
    }

    /// Runs the #736 reproduction and returns once both threads finish.
    /// Thread B disposes X right after its add to Y.
    private func runDisposalAfterAReleasedTransaction(
        xIsGroup: Bool = false,
        yIsGroup: Bool = false,
        file: StaticString = #filePath,
        line: UInt = #line
    ) throws {
        // Y is the container whose transaction A waits for, so Y's
        // `endMembershipTransaction` is the release under test.
        let x = container("x", group: xIsGroup)
        let y = container("y", group: yIsGroup)

        let threadA = SharedValue<UInt64>(0)
        let threadB = SharedValue<UInt64>(0)
        let aWaiting = DispatchSemaphore(value: 0)
        let bDecided = DispatchSemaphore(value: 0)
        let bInSink = DispatchSemaphore(value: 0)
        let aDone = DispatchSemaphore(value: 0)
        let bDone = DispatchSemaphore(value: 0)
        let holdA = SharedValue(true)
        let blockOnce = SharedValue(true)
        let disposeYOnce = SharedValue(true)
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
            heldUntilBDecided.value = bDecided.wait(timeout: .now() + hangGuard)
        }
        y.changes.sink { _ in
            guard blockOnce.value else { return }
            blockOnce.value = false
            bInSink.signal()
            _ = aWaiting.wait(timeout: .now() + hangGuard)
        }.store(in: &cancellables)
        x.changes.sink { _ in
            guard disposeYOnce.value else { return }
            disposeYOnce.value = false
            y.dispose()
        }.store(in: &cancellables)

        Thread.detachNewThread {
            threadB.value = ThreadWaitGraph.currentThread
            _ = y.add(try! ComponentVM.builder()
                .name("e")
                .services(hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
                .build())
            x.dispose()
            bDone.signal()
        }
        XCTAssertEqual(bInSink.wait(timeout: .now() + hangGuard), .success, file: file, line: line)
        let c = try child("c")
        Thread.detachNewThread {
            threadA.value = ThreadWaitGraph.currentThread
            _ = x.add(c)
            aDone.signal()
        }

        XCTAssertEqual(aDone.wait(timeout: .now() + hangGuard), .success, "thread A hung", file: file, line: line)
        XCTAssertEqual(bDone.wait(timeout: .now() + hangGuard), .success, "thread B hung", file: file, line: line)
        XCTAssertFalse(holdA.value, "thread A was held between its wake and its endWait", file: file, line: line)
        XCTAssertEqual(heldUntilBDecided.value, .success, "B's wait on X was decided while A was held",
                       file: file, line: line)
        XCTAssertEqual(bAccepted.value, true, "B waited for A's transaction instead of seeing a stale cycle",
                       file: file, line: line)
        XCTAssertEqual(y.vm.status, .disposed, file: file, line: line)
        XCTAssertEqual(x.vm.status, .disposed, file: file, line: line)
        XCTAssertEqual(c.status, .disposed, "B's disposal waited for A's add", file: file, line: line)
    }

    func testCompositeDisposalAfterAReleasedTransactionWaitsAndSucceeds() throws {
        try runDisposalAfterAReleasedTransaction()
    }

    // A selection registers no membership wait (spec/06 §4.3 rule 1,
    // ADR-0173), and a membership change fails at once (ADR-0187), so
    // neither has a stale-edge case.

    func testGroupDisposalAfterAReleasedTransactionWaitsAndSucceeds() throws {
        try runDisposalAfterAReleasedTransaction(xIsGroup: true)
    }

    func testAGroupReleasesItsWaitersBeforeWakingThem() throws {
        try runDisposalAfterAReleasedTransaction(yIsGroup: true)
    }
}
