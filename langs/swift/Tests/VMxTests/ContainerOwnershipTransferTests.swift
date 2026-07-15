//
// ContainerOwnershipTransferTests.swift — exclusive ownership conformance.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import Combine
import XCTest
@testable import VMx

private enum OwnershipTestError: Error {
    case constructFailed
}

private final class ThrowingOwnershipChild: ComponentVMBase {
    init(_ name: String, shouldFail: @escaping () -> Bool = { true }) {
        super.init(
            name: name,
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE,
            onConstruct: {
                if shouldFail { throw OwnershipTestError.constructFailed }
            }
        )
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
        let child = ThrowingOwnershipChild("child")
        let oldParent = CompositeVM<ThrowingOwnershipChild>(
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
}
