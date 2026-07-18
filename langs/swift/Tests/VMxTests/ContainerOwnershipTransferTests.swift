//
// ContainerOwnershipTransferTests.swift — exclusive ownership conformance.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import Combine
import XCTest
@testable import VMx

private enum OwnershipTestError: Error, Equatable {
    case constructFailed
    case destructFailed
}

private final class ThrowingOwnershipChild: ComponentVMBase {
    init(_ name: String, shouldFail: @escaping () -> Bool = { true }) {
        super.init(
            name: name,
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE,
            onConstruct: {
                if shouldFail() { throw OwnershipTestError.constructFailed }
            }
        )
    }
}

private final class CompensatingOwnershipChild: ComponentVMBase {
    init(_ name: String, failConstruct: Bool = false, failDestruct: Bool = false) {
        super.init(
            name: name,
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE,
            onConstruct: {
                if failConstruct { throw OwnershipTestError.constructFailed }
            },
            onDestruct: {
                if failDestruct { throw OwnershipTestError.destructFailed }
            }
        )
    }
}

private final class OwnershipErrorStore: @unchecked Sendable {
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

final class ContainerOwnershipTransferTests: XCTestCase {
    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func leaf(_ name: String) throws -> ComponentVM {
        try ComponentVM.builder().name(name).withNullServices().build()
    }

    /// COMP-038 — Adding an owned child transfers it between composite/group parents.
    func testCOMP038AddingOwnedChildTransfersMembership() throws {
        let child = try leaf("child")
        let oldParent = try CompositeVM<ComponentVM>.builder()
            .name("old").withNullServices().children { [] }.build()
        let newParent = try GroupVM<ComponentVM>.builder()
            .name("new").withNullServices().children { [] }.build()

        try oldParent.addResult(child).get()
        try newParent.addResult(child).get()

        XCTAssertEqual(oldParent.count, 0)
        XCTAssertEqual(newParent.count, 1)
        XCTAssertTrue(newParent.at(0) === child)
    }

    /// COMP-039 — Duplicate ownership and ancestor cycles are rejected.
    func testCOMP039DuplicateAndCycleAreRejected() throws {
        let child = try leaf("child")
        let parent = try CompositeVM<ComponentVM>.builder()
            .name("parent").withNullServices().children { [] }.build()
        try parent.addResult(child).get()
        if case .failure(.duplicate) = parent.addResult(child) {
            // Expected.
        } else {
            XCTFail("adding the same child twice must report duplicate")
        }

        let ancestor = CompositeVM<ComponentVMBase>(
            name: "ancestor",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE
        )
        let descendant = CompositeVM<ComponentVMBase>(
            name: "descendant",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE
        )
        try ancestor.addResult(descendant).get()
        if case .failure(.cycle) = descendant.addResult(ancestor) {
            // Expected.
        } else {
            XCTFail("adding an ancestor beneath its descendant must report cycle")
        }
        XCTAssertTrue(ancestor.at(0) === descendant)
        XCTAssertEqual(descendant.count, 0)
    }

    /// COMP-040 — A failed destination attach restores exact old membership/current state.
    func testCOMP040FailedAttachRollsBackOldParentState() throws {
        var destination: CompositeVM<ThrowingOwnershipChild>!
        var child: ThrowingOwnershipChild!
        var reentrantRemovalAccepted = true
        child = ThrowingOwnershipChild("child", shouldFail: {
            reentrantRemovalAccepted = destination.remove(child)
            return true
        })
        let oldParent = CompositeVM<ThrowingOwnershipChild>(
            name: "old",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE
        )
        destination = CompositeVM<ThrowingOwnershipChild>(
            name: "destination",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE,
            autoConstructOnAdd: true
        )
        try oldParent.addResult(child).get()
        oldParent.current = child
        try destination.construct()

        if case .failure(.attachmentFailed) = destination.addResult(child) {
            // Expected.
        } else {
            XCTFail("failed child construction must report attachmentFailed")
        }

        XCTAssertEqual(oldParent.count, 1)
        XCTAssertTrue(oldParent.at(0) === child)
        XCTAssertTrue(oldParent.current === child)
        XCTAssertEqual(destination.count, 0)
        XCTAssertFalse(
            reentrantRemovalAccepted,
            "a candidate hook cannot mutate destination membership mid-transaction"
        )
    }

    /// COMP-040 — successful factory child construction followed by destination
    /// disposal restores the child's original destructed state and empty membership.
    func testCOMP040PopulationDisposalRollsBackConstructedChild() throws {
        var destination: CompositeVM<ComponentVM>!
        let child = try ComponentVM.builder()
            .name("population-child")
            .withNullServices()
            .onConstruct { destination.dispose() }
            .build()
        destination = CompositeVM<ComponentVM>(
            name: "destination",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE,
            childrenFactory: { [child] }
        )

        XCTAssertThrowsError(try destination.construct())
        XCTAssertEqual(destination.count, 0)
        XCTAssertEqual(child.status, .destructed)
        XCTAssertEqual(destination.status, .disposed)
    }

    /// COMP-040 — old-parent disposal waits until successful transfer commit.
    func testCOMP040DefersOldCompositeDisposalUntilTransferCommits() throws {
        var oldParent: CompositeVM<ThrowingOwnershipChild>!
        let child = ThrowingOwnershipChild("child", shouldFail: {
            oldParent.dispose()
            return false
        })
        oldParent = CompositeVM<ThrowingOwnershipChild>(
            name: "old",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE
        )
        let destination = GroupVM<ThrowingOwnershipChild>(
            name: "destination",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE,
            autoConstructOnAdd: true
        )
        try oldParent.addResult(child).get()
        try destination.construct()

        try destination.addResult(child).get()

        XCTAssertEqual(oldParent.status, .disposed)
        XCTAssertEqual(oldParent.count, 0)
        XCTAssertEqual(destination.count, 1)
        XCTAssertTrue(destination.at(0) === child)
        XCTAssertEqual(child.status, .constructed)
        XCTAssertTrue(child._ownershipParent?.ownershipOwner === destination)
    }

    /// COMP-040 — rollback restores membership before deferred old-parent disposal.
    func testCOMP040RollsBackBeforeDeferredOldGroupDisposal() throws {
        var oldParent: GroupVM<ThrowingOwnershipChild>!
        let child = ThrowingOwnershipChild("child", shouldFail: {
            oldParent.dispose()
            return true
        })
        oldParent = GroupVM<ThrowingOwnershipChild>(
            name: "old",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE
        )
        let destination = CompositeVM<ThrowingOwnershipChild>(
            name: "destination",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE,
            autoConstructOnAdd: true
        )
        try oldParent.addResult(child).get()
        try destination.construct()

        if case .failure(.attachmentFailed) = destination.addResult(child) {
            // Expected.
        } else {
            XCTFail("failed child construction must report attachmentFailed")
        }

        XCTAssertEqual(oldParent.status, .disposed)
        XCTAssertEqual(oldParent.count, 1)
        XCTAssertTrue(oldParent.at(0) === child)
        XCTAssertEqual(destination.count, 0)
        XCTAssertEqual(child.status, .disposed)
        XCTAssertTrue(child._ownershipParent?.ownershipOwner === oldParent)
    }

    /// COMP-040 — Lazy population rollback restores earlier transfers and is retryable.
    func testCOMP040LazyPopulationRollsBackAsOneTransaction() throws {
        let first = ThrowingOwnershipChild("first", shouldFail: { false })
        let blocker = ThrowingOwnershipChild("bulk-failing")
        let oldParent = CompositeVM<ThrowingOwnershipChild>(
            name: "bulk-old",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE
        )
        try oldParent.addResult(first).get()
        var batch = [first, blocker]
        let destination = GroupVM<ThrowingOwnershipChild>(
            name: "bulk-destination",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE,
            childrenFactory: { batch }
        )
        var events: [String] = []
        oldParent.collectionChanged
            .sink { _ in events.append("old") }
            .store(in: &cancellables)
        destination.collectionChanged
            .sink { _ in events.append("new") }
            .store(in: &cancellables)

        XCTAssertThrowsError(try destination.construct()) { error in
            guard let ownershipError = error as? ContainerOwnershipError,
                  case .attachmentFailed = ownershipError else {
                return XCTFail("expected attachmentFailed, got \(error)")
            }
        }

        XCTAssertEqual(oldParent.count, 1)
        XCTAssertTrue(oldParent.at(0) === first)
        XCTAssertEqual(first.status, .destructed)
        XCTAssertEqual(destination.count, 0)
        XCTAssertEqual(events, [])
        batch = []
        try destination.construct()
        XCTAssertEqual(destination.count, 0)
    }

    /// COMP-041 — Successful transfer publishes old remove before destination add.
    func testCOMP041TransferPublishesRemoveBeforeAdd() throws {
        let child = try leaf("child")
        let oldParent = try GroupVM<ComponentVM>.builder()
            .name("old").withNullServices().children { [] }.build()
        let destination = try CompositeVM<ComponentVM>.builder()
            .name("destination").withNullServices().children { [] }.build()
        try oldParent.addResult(child).get()

        var order: [String] = []
        oldParent.collectionChanged
            .sink { event in
                if event.action == .remove { order.append("remove") }
            }
            .store(in: &cancellables)
        destination.collectionChanged
            .sink { event in
                if event.action == .add { order.append("add") }
            }
            .store(in: &cancellables)

        try destination.addResult(child).get()

        XCTAssertEqual(order, ["remove", "add"])
    }

    func testBulkTransferRemoveCallbackDoesNotRetainOwnershipCoordinator() throws {
        let first = try leaf("first")
        let second = try leaf("second")
        let oldParent = try GroupVM<ComponentVM>.builder()
            .name("old").withNullServices().children { [] }.build()
        let secondOldParent = try GroupVM<ComponentVM>.builder()
            .name("second-old").withNullServices().children { [] }.build()
        try oldParent.addResult(first).get()
        try secondOldParent.addResult(second).get()
        let destination = try GroupVM<ComponentVM>.builder()
            .name("destination").withNullServices().children { [first, second] }.build()

        let unrelated = try leaf("unrelated")
        let unrelatedOld = try GroupVM<ComponentVM>.builder()
            .name("unrelated-old").withNullServices().children { [] }.build()
        try unrelatedOld.addResult(unrelated).get()
        let unrelatedDestination = try GroupVM<ComponentVM>.builder()
            .name("unrelated-destination").withNullServices().children { [] }.build()
        let workerDone = DispatchSemaphore(value: 0)
        var callbackObservedProgress = false
        var callbackStarted = false

        oldParent.collectionChanged
            .sink { event in
                guard event.action == .remove, !callbackStarted else { return }
                callbackStarted = true
                DispatchQueue.global().async {
                    _ = unrelatedDestination.addResult(unrelated)
                    workerDone.signal()
                }
                callbackObservedProgress = workerDone.wait(timeout: .now() + 1) == .success
            }
            .store(in: &cancellables)

        try destination.construct()

        XCTAssertTrue(callbackObservedProgress)
        XCTAssertEqual(unrelatedOld.count, 0)
        XCTAssertEqual(unrelatedDestination.count, 1)
        XCTAssertTrue(unrelatedDestination.at(0) === unrelated)
    }

    func testPopulationRejectsReentrantMutationInBothContainers() throws {
        var composite: CompositeVM<ThrowingOwnershipChild>!
        var compositeClearAttempted = false
        let compositeChild = ThrowingOwnershipChild("composite-child", shouldFail: {
            compositeClearAttempted = true
            composite.clear()
            return false
        })
        composite = CompositeVM<ThrowingOwnershipChild>(
            name: "composite",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE,
            childrenFactory: { [compositeChild] }
        )

        var group: GroupVM<ThrowingOwnershipChild>!
        var groupClearAttempted = false
        let groupChild = ThrowingOwnershipChild("group-child", shouldFail: {
            groupClearAttempted = true
            group.clear()
            return false
        })
        group = GroupVM<ThrowingOwnershipChild>(
            name: "group",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE,
            childrenFactory: { [groupChild] }
        )

        try composite.construct()
        try group.construct()

        XCTAssertTrue(compositeClearAttempted)
        XCTAssertTrue(groupClearAttempted)
        XCTAssertEqual(composite.count, 1)
        XCTAssertEqual(group.count, 1)
        XCTAssertTrue(composite.at(0) === compositeChild)
        XCTAssertTrue(group.at(0) === groupChild)
    }

    func testReversedConcurrentPopulationCompletesWithoutSplitOwnership() throws {
        let first = try leaf("first")
        let second = try leaf("second")
        let factoryAEntered = DispatchSemaphore(value: 0)
        let factoryBEntered = DispatchSemaphore(value: 0)
        let destinationA = CompositeVM<ComponentVM>(
            name: "destination-a",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE,
            childrenFactory: {
                factoryAEntered.signal()
                _ = factoryBEntered.wait(timeout: .now() + 2)
                return [first, second]
            }
        )
        let destinationB = GroupVM<ComponentVM>(
            name: "destination-b",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE,
            childrenFactory: {
                factoryBEntered.signal()
                _ = factoryAEntered.wait(timeout: .now() + 2)
                return [second, first]
            }
        )
        let errors = OwnershipErrorStore()
        let done = DispatchGroup()

        done.enter()
        DispatchQueue.global().async {
            defer { done.leave() }
            do { try destinationA.construct() } catch { errors.append(error) }
        }
        done.enter()
        DispatchQueue.global().async {
            defer { done.leave() }
            do { try destinationB.construct() } catch { errors.append(error) }
        }

        XCTAssertEqual(done.wait(timeout: .now() + 5), .success)
        XCTAssertTrue(errors.errors.isEmpty)
        XCTAssertEqual([destinationA.count, destinationB.count].sorted(), [0, 2])
        XCTAssertEqual(
            destinationA.snapshot().filter { $0 === first || $0 === second }.count
                + destinationB.snapshot().filter { $0 === first || $0 === second }.count,
            2
        )
    }

    func testPopulationSurfacesLifecycleCompensationFailure() {
        let first = CompensatingOwnershipChild("first", failDestruct: true)
        let blocker = CompensatingOwnershipChild("blocker", failConstruct: true)
        let destination = GroupVM<CompensatingOwnershipChild>(
            name: "destination",
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE,
            childrenFactory: { [first, blocker] }
        )

        XCTAssertThrowsError(try destination.construct()) { error in
            guard let ownershipError = error as? ContainerOwnershipError,
                  case let .attachmentFailed(underlying) = ownershipError,
                  let compensation = underlying as? OwnershipTestError,
                  compensation == .destructFailed else {
                return XCTFail("expected surfaced destruct compensation failure, got \(error)")
            }
        }
        XCTAssertEqual(destination.count, 0)
        XCTAssertNil(first._ownershipParent)
        XCTAssertNil(blocker._ownershipParent)
    }
}
