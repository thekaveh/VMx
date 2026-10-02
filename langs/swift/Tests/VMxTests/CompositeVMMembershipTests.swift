//
// CompositeVMMembershipTests.swift — CompositeVM insert, removeAt, replace,
// clear, population from another composite, and selection of a non-member:
// member order, change events, ownership, rollback, and what happens to
// `current` when its child leaves.
//
// Behavior tests without catalog IDs. They cover CompositeVM paths the
// conformance suite did not exercise when the Swift coverage floor was
// measured (#362), and membership-transaction paths that only the ownership
// race tests reached, on whichever side of the race won (#520).
//
import Combine
import XCTest
@testable import VMx

private enum MembershipTestError: Error {
    case constructFailed
}

final class CompositeVMMembershipTests: XCTestCase {
    private var cancellables: Set<AnyCancellable> = []
    private var currentChanges: [String] = []

    override func tearDown() {
        cancellables.removeAll()
        currentChanges.removeAll()
        super.tearDown()
    }

    private func leaf(_ name: String, failConstruct: Bool = false) throws -> ComponentVM {
        try ComponentVM.builder()
            .name(name)
            .withNullServices()
            .onConstruct { if failConstruct { throw MembershipTestError.constructFailed } }
            .build()
    }

    /// A composite holding `children`, recording every current change in
    /// `currentChanges` ("nil" for a cleared current).
    private func composite(
        _ children: [ComponentVM],
        autoConstructOnAdd: Bool = false
    ) throws -> CompositeVM<ComponentVM> {
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .withNullServices()
            .children { [] }
            .onCurrentChanged { [weak self] current in
                self?.currentChanges.append(current?.name ?? "nil")
            }
            .autoConstructOnAdd(autoConstructOnAdd)
            .build()
        for child in children { try composite.addResult(child).get() }
        return composite
    }

    private func owner(of child: ComponentVMBase) -> ComponentVMBase? {
        child._ownershipParent?.ownershipOwner
    }

    /// Records each change event as "<action> <names> new:<index> old:<index>".
    private func record(_ composite: CompositeVM<ComponentVM>) -> () -> [String] {
        var log: [String] = []
        composite.collectionChanged
            .sink { event in
                let names = (event.newItems + event.oldItems).map(\.name).joined(separator: ",")
                log.append("\(event.action) \(names) new:\(event.newIndex) old:\(event.oldIndex)")
            }
            .store(in: &cancellables)
        return { log }
    }

    // MARK: — insert and replace

    func testInsertPlacesTheChildAtItsIndexAndAnnouncesIt() throws {
        let a = try leaf("a"), b = try leaf("b"), c = try leaf("c")
        let sut = try composite([a, c])
        let events = record(sut)

        try sut.insertResult(b, at: 1).get()

        XCTAssertEqual(sut.snapshot().map(\.name), ["a", "b", "c"])
        XCTAssertTrue(owner(of: b) === sut)
        XCTAssertEqual(events(), ["add b new:1 old:-1"])
    }

    func testInsertAndReplaceOutsideTheMembersAreRejectedAndChangeNothing() throws {
        let a = try leaf("a"), stray = try leaf("stray")
        let sut = try composite([a])
        let events = record(sut)

        for result in [sut.insertResult(stray, at: 2), sut.replaceResult(at: 1, with: stray)] {
            guard case let .failure(.attachmentFailed(error)) = result else {
                XCTFail("expected an index rejection, got \(result)")
                continue
            }
            XCTAssertTrue(error is VMCollectionIndexError, "got \(error)")
        }

        XCTAssertEqual(sut.snapshot().map(\.name), ["a"])
        XCTAssertNil(owner(of: stray))
        XCTAssertEqual(events(), [])
    }

    func testAFailedConstructOnInsertLeavesTheCompositeUnchanged() throws {
        let a = try leaf("a"), failing = try leaf("failing", failConstruct: true)
        let sut = try composite([a], autoConstructOnAdd: true)
        try sut.construct()
        let events = record(sut)

        let result = sut.insertResult(failing, at: 0)

        guard case let .failure(.attachmentFailed(error)) = result else {
            return XCTFail("expected the construct failure, got \(result)")
        }
        XCTAssertEqual(error as? MembershipTestError, .constructFailed)
        XCTAssertEqual(sut.snapshot().map(\.name), ["a"])
        XCTAssertNil(owner(of: failing))
        XCTAssertEqual(events(), [])
    }

    func testReplacingTheCurrentChildFreesItAndClearsCurrentOnce() throws {
        let a = try leaf("a"), b = try leaf("b"), replacement = try leaf("replacement")
        let sut = try composite([a, b])
        sut.current = a
        currentChanges.removeAll()
        let events = record(sut)

        try sut.replaceResult(at: 0, with: replacement).get()

        XCTAssertEqual(sut.snapshot().map(\.name), ["replacement", "b"])
        XCTAssertNil(sut.current)
        XCTAssertFalse(a.isCurrent)
        XCTAssertNil(owner(of: a))
        XCTAssertTrue(owner(of: replacement) === sut)
        XCTAssertEqual(currentChanges, ["nil"])
        XCTAssertEqual(
            events(),
            ["remove a new:-1 old:0", "add replacement new:0 old:-1"]
        )
    }

    // MARK: — removeAt and clear

    func testRemovingTheCurrentChildByIndexClearsCurrentOnce() throws {
        let a = try leaf("a"), b = try leaf("b")
        let sut = try composite([a, b])
        sut.current = b
        currentChanges.removeAll()
        let events = record(sut)

        sut.removeAt(1)

        XCTAssertEqual(sut.snapshot().map(\.name), ["a"])
        XCTAssertNil(sut.current)
        XCTAssertFalse(b.isCurrent)
        XCTAssertNil(owner(of: b))
        XCTAssertEqual(currentChanges, ["nil"])
        XCTAssertEqual(events(), ["remove b new:-1 old:1"])
    }

    func testRemovingASiblingByIndexKeepsCurrent() throws {
        let a = try leaf("a"), b = try leaf("b")
        let sut = try composite([a, b])
        sut.current = a
        currentChanges.removeAll()

        sut.removeAt(1)

        XCTAssertTrue(sut.current === a)
        XCTAssertTrue(a.isCurrent)
        XCTAssertEqual(currentChanges, [])
    }

    func testClearFreesEveryChildAndClearsCurrentOnce() throws {
        let a = try leaf("a"), b = try leaf("b")
        let sut = try composite([a, b])
        sut.current = b
        currentChanges.removeAll()
        let events = record(sut)

        sut.clear()

        XCTAssertEqual(sut.count, 0)
        XCTAssertNil(sut.current)
        XCTAssertNil(owner(of: a))
        XCTAssertNil(owner(of: b))
        XCTAssertEqual(currentChanges, ["nil"])
        XCTAssertEqual(events(), ["reset  new:-1 old:-1"])
    }

    // MARK: — population and selection

    func testPopulationMovesSeveralChildrenOutOfOneCompositeInOneTransaction() throws {
        let first = try leaf("first"), second = try leaf("second"), later = try leaf("later")
        let source = try composite([first, second])
        let sourceEvents = record(source)
        let destination = try CompositeVM<ComponentVM>.builder()
            .name("destination")
            .withNullServices()
            .children { [first, second] }
            .build()
        let destinationEvents = record(destination)

        try destination.construct()

        XCTAssertEqual(destination.snapshot().map(\.name), ["first", "second"])
        XCTAssertEqual(source.count, 0)
        XCTAssertTrue(owner(of: first) === destination)
        XCTAssertTrue(owner(of: second) === destination)
        XCTAssertEqual(
            sourceEvents(),
            ["remove first new:-1 old:0", "remove second new:-1 old:0"]
        )
        XCTAssertEqual(
            destinationEvents(),
            ["add first new:0 old:-1", "add second new:1 old:-1"]
        )
        // The source joined the destination's transaction once per child and
        // must be closed again, so it admits a new member.
        try source.addResult(later).get()
        XCTAssertEqual(source.snapshot().map(\.name), ["later"])
    }

    func testSelectingAConstructedNonMemberKeepsCurrent() throws {
        let a = try leaf("a"), stranger = try leaf("stranger")
        let sut = try composite([a])
        sut.current = a
        currentChanges.removeAll()
        try stranger.construct()

        sut.selectChild(stranger)

        XCTAssertTrue(sut.current === a)
        XCTAssertFalse(stranger.isCurrent)
        XCTAssertNil(owner(of: stranger))
        XCTAssertEqual(currentChanges, [])
    }
}
