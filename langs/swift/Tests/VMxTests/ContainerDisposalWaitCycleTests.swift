//
// ContainerDisposalWaitCycleTests.swift — #717 regression tests.
//
// A cross-thread `dispose()` waits for the container's open membership
// transaction (ADR-0122) through the shared wait-for graph. When that wait
// would close a cycle, the disposal records its intent instead, and the
// transaction owner disposes the container when the transaction ends. No
// hub is involved. Every wait is bounded, so a regression fails instead of
// hanging the suite.
//

import Combine
import Foundation
import XCTest
@testable import VMx

private let cycleTimeout: TimeInterval = 5

/// A value shared with a test thread.
private final class SharedValue<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: T
    init(_ value: T) { storage = value }
    var value: T {
        get { lock.withLock { storage } }
        set { lock.withLock { storage = newValue } }
    }
}

/// The operations the tests need from a composite or a group.
private struct Container {
    let vm: ComponentVMBase
    let addResult: (ComponentVM) -> Result<Void, ContainerOwnershipError>
    let dispose: () -> Void
    let children: () -> [ComponentVMBase]
    let collectionChanged: AnyPublisher<CollectionChangedEvent, Never>

    func contains(_ child: ComponentVM) -> Bool {
        children().contains { $0 === child }
    }

    static func composite(_ name: String) -> Container {
        let vm = CompositeVM<ComponentVM>(
            name: name, hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
        return Container(
            vm: vm,
            addResult: vm.addResult,
            dispose: vm.dispose,
            children: { (0..<vm.count).map { vm.at($0) } },
            collectionChanged: vm.collectionChanged)
    }

    static func group(_ name: String) -> Container {
        let vm = GroupVM<ComponentVM>(
            name: name, hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
        return Container(
            vm: vm,
            addResult: vm.addResult,
            dispose: vm.dispose,
            children: { (0..<vm.count).map { vm.at($0) } },
            collectionChanged: vm.collectionChanged)
    }
}

final class ContainerDisposalWaitCycleTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        ThreadWaitGraph.shared.onWaitDecidedForTesting = nil
        cancellables.removeAll()
        super.tearDown()
    }

    private func child(_ name: String) throws -> ComponentVM {
        try ComponentVM.builder()
            .name(name)
            .services(hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
    }

    /// Signals `semaphore` once `thread` has registered a wait in the graph.
    private func signalWhenWaiting(_ thread: SharedValue<UInt64>, _ semaphore: DispatchSemaphore) {
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            if accepted, caller == thread.value { semaphore.signal() }
        }
    }

    /// The #717 reproduction. Thread B adds to Y and blocks in Y's
    /// `collectionChanged` sink. Thread A adds Y's child `c` to X, so A holds
    /// X's transaction and waits for Y's. B's sink then disposes X.
    private func runCrossContainerDisposal(_ x: Container, file: StaticString = #filePath, line: UInt = #line) throws {
        let y = Container.composite("y")
        let c = try child("c")
        guard case .success = y.addResult(c) else { return XCTFail("seeding y failed", file: file, line: line) }

        let threadA = SharedValue<UInt64>(0)
        let threadB = SharedValue<UInt64>(0)
        let bRefused = SharedValue(false)
        let aWaiting = DispatchSemaphore(value: 0)
        let bInSink = DispatchSemaphore(value: 0)
        let aDone = DispatchSemaphore(value: 0)
        let bDone = DispatchSemaphore(value: 0)
        let blockOnce = SharedValue(true)
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            if accepted, caller == threadA.value { aWaiting.signal() }
            if !accepted, caller == threadB.value { bRefused.value = true }
        }

        y.collectionChanged.sink { _ in
            guard blockOnce.value else { return }
            blockOnce.value = false
            bInSink.signal()
            _ = aWaiting.wait(timeout: .now() + cycleTimeout)
            x.dispose()
        }.store(in: &cancellables)

        Thread.detachNewThread {
            threadB.value = ThreadWaitGraph.currentThread
            _ = y.addResult(try! ComponentVM.builder()
                .name("e")
                .services(hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
                .build())
            bDone.signal()
        }
        XCTAssertEqual(bInSink.wait(timeout: .now() + cycleTimeout), .success, file: file, line: line)
        Thread.detachNewThread {
            threadA.value = ThreadWaitGraph.currentThread
            _ = x.addResult(c)
            aDone.signal()
        }

        XCTAssertEqual(aDone.wait(timeout: .now() + cycleTimeout), .success, "thread A (adding to x) hung", file: file, line: line)
        XCTAssertEqual(bDone.wait(timeout: .now() + cycleTimeout), .success, "thread B (disposing x) hung", file: file, line: line)
        XCTAssertTrue(bRefused.value, "the disposal's wait closed a cycle and was refused", file: file, line: line)
        XCTAssertEqual(x.vm.status, .disposed, file: file, line: line)
        XCTAssertEqual([x.contains(c), y.contains(c)].filter { $0 }.count, 1,
                       "c is a child of exactly one container", file: file, line: line)
    }

    func testCompositeDisposalThatWouldCloseAMembershipCycleDefersToTheOwner() throws {
        try runCrossContainerDisposal(.composite("x"))
    }

    func testGroupDisposalThatWouldCloseAMembershipCycleDefersToTheOwner() throws {
        try runCrossContainerDisposal(.group("x"))
    }

    /// Without a cycle, a cross-thread `dispose()` waits for the add to end
    /// and its child snapshot includes the added child (ADR-0122).
    private func runDisposalDuringAnAdd(_ x: Container, file: StaticString = #filePath, line: UInt = #line) throws {
        let added = try child("added")
        let threadB = SharedValue<UInt64>(0)
        let bWaiting = DispatchSemaphore(value: 0)
        let aInSink = DispatchSemaphore(value: 0)
        let disposed = DispatchSemaphore(value: 0)
        let addEnded = SharedValue(false)
        let addEndedBeforeDispose = SharedValue<Bool?>(nil)
        signalWhenWaiting(threadB, bWaiting)

        x.collectionChanged.sink { _ in
            aInSink.signal()
            _ = bWaiting.wait(timeout: .now() + cycleTimeout)
            addEnded.value = true
        }.store(in: &cancellables)

        let addReturned = DispatchSemaphore(value: 0)
        Thread.detachNewThread {
            _ = x.addResult(added)
            addReturned.signal()
        }
        XCTAssertEqual(aInSink.wait(timeout: .now() + cycleTimeout), .success, file: file, line: line)
        Thread.detachNewThread {
            threadB.value = ThreadWaitGraph.currentThread
            x.dispose()
            addEndedBeforeDispose.value = addEnded.value
            disposed.signal()
        }

        XCTAssertEqual(disposed.wait(timeout: .now() + cycleTimeout), .success, "dispose() hung", file: file, line: line)
        XCTAssertEqual(addReturned.wait(timeout: .now() + cycleTimeout), .success, "the add hung", file: file, line: line)
        XCTAssertEqual(addEndedBeforeDispose.value, true, "dispose() returned before the add ended", file: file, line: line)
        XCTAssertEqual(x.vm.status, .disposed, file: file, line: line)
        XCTAssertEqual(added.status, .disposed, "the disposal snapshot includes the added child", file: file, line: line)
    }

    func testCompositeDisposalWaitsForAnAddOnAnotherThread() throws {
        try runDisposalDuringAnAdd(.composite("x"))
    }

    func testGroupDisposalWaitsForAnAddOnAnotherThread() throws {
        try runDisposalDuringAnAdd(.group("x"))
    }
}
