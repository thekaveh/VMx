//
// CompositeVMMembershipTests.swift — CompositeVM insert, removeAt, replace,
// and clear: member order, change events, ownership, rollback, and what
// happens to `current` when its child leaves.
//
// Behavior tests without catalog IDs. They cover CompositeVM paths the
// conformance suite did not exercise when the Swift coverage floor was
// measured (#362).
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
}
