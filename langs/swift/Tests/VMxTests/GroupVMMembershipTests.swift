//
// GroupVMMembershipTests.swift — GroupVM insert, replace, remove, clear, and
// repeated dispose: member order, change events, ownership, and rollback.
//
// Behavior tests without catalog IDs. They cover GroupVM paths the conformance
// suite did not exercise when the Swift coverage floor was measured (#362).
//
import Combine
import XCTest
@testable import VMx

private enum MembershipTestError: Error {
    case constructFailed
}

private final class CountingChild: ComponentVMBase {
    private(set) var disposeCalls = 0

    init(_ name: String) {
        super.init(name: name, hub: NullMessageHub.INSTANCE, dispatcher: NullDispatcher.INSTANCE)
    }

    override func dispose() {
        disposeCalls += 1
        super.dispose()
    }
}

final class GroupVMMembershipTests: XCTestCase {
    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func leaf(_ name: String, failConstruct: Bool = false) throws -> ComponentVM {
        try ComponentVM.builder()
            .name(name)
            .withNullServices()
            .onConstruct { if failConstruct { throw MembershipTestError.constructFailed } }
            .build()
    }

    private func group(
        _ name: String,
        autoConstructOnAdd: Bool = false
    ) throws -> GroupVM<ComponentVM> {
        try GroupVM<ComponentVM>.builder()
            .name(name)
            .withNullServices()
            .children { [] }
            .autoConstructOnAdd(autoConstructOnAdd)
            .build()
    }

    private func owner(of child: ComponentVMBase) -> ComponentVMBase? {
        child._ownershipParent?.ownershipOwner
    }

    /// Records each change event as "<action> <names> new:<index> old:<index>".
    private func record(_ group: GroupVM<ComponentVM>) -> () -> [String] {
        var log: [String] = []
        group.collectionChanged
            .sink { event in
                let names = (event.newItems + event.oldItems).map(\.name).joined(separator: ",")
                log.append("\(event.action) \(names) new:\(event.newIndex) old:\(event.oldIndex)")
            }
            .store(in: &cancellables)
        return { log }
    }

    private func assertIndexRejected(
        _ result: Result<Void, ContainerOwnershipError>,
        index: Int,
        count: Int,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        guard case let .failure(.attachmentFailed(error)) = result else {
            return XCTFail("expected an index rejection, got \(result)", file: file, line: line)
        }
        XCTAssertEqual(
            error as? VMCollectionIndexError,
            VMCollectionIndexError(index: index, count: count),
            file: file,
            line: line
        )
    }

    // MARK: — insert

    func testInsertPlacesTheChildAtItsIndexAndAnnouncesIt() throws {
        let a = try leaf("a"), b = try leaf("b"), c = try leaf("c")
        let g = try group("g")
        try g.addResult(a).get()
        try g.addResult(c).get()
        let events = record(g)

        try g.insertResult(b, at: 1).get()

        XCTAssertEqual(g.snapshot().map(\.name), ["a", "b", "c"])
        XCTAssertTrue(owner(of: b) === g)
        XCTAssertEqual(events(), ["add b new:1 old:-1"])
    }

    func testInsertOutsideTheMembersIsRejectedAndChangesNothing() throws {
        let a = try leaf("a"), stray = try leaf("stray")
        let g = try group("g")
        try g.addResult(a).get()
        let events = record(g)

        assertIndexRejected(g.insertResult(stray, at: 2), index: 2, count: 1)
        assertIndexRejected(g.insertResult(stray, at: -1), index: -1, count: 1)

        XCTAssertEqual(g.snapshot().map(\.name), ["a"])
        XCTAssertNil(owner(of: stray))
        XCTAssertEqual(events(), [])
    }

    func testInsertIntoAConstructedGroupConstructsTheChildBeforeAnnouncingIt() throws {
        let child = try leaf("child")
        let g = try group("g", autoConstructOnAdd: true)
        try g.construct()
        var statusWhenAnnounced: ConstructionStatus?
        g.collectionChanged
            .sink { _ in statusWhenAnnounced = child.status }
            .store(in: &cancellables)

        try g.insertResult(child, at: 0).get()

        XCTAssertEqual(statusWhenAnnounced, .constructed)
        XCTAssertTrue(g.at(0) === child)
    }

    func testAFailedConstructOnInsertReturnsTheChildToItsPreviousGroup() throws {
        let child = try leaf("child", failConstruct: true)
        let previous = try group("previous")
        try previous.addResult(child).get()
        let destination = try group("destination", autoConstructOnAdd: true)
        try destination.construct()
        let previousEvents = record(previous)
        let destinationEvents = record(destination)

        let result = destination.insertResult(child, at: 0)

        guard case let .failure(.attachmentFailed(error)) = result else {
            return XCTFail("expected the construct failure, got \(result)")
        }
        XCTAssertEqual(error as? MembershipTestError, .constructFailed)
        XCTAssertEqual(destination.count, 0)
        XCTAssertTrue(previous.at(0) === child)
        XCTAssertTrue(owner(of: child) === previous)
        XCTAssertEqual(previousEvents(), [])
        XCTAssertEqual(destinationEvents(), [])
    }

    // MARK: — replace

    func testReplaceMovesTheChildFromItsPreviousGroupAndFreesTheOldOne() throws {
        let a = try leaf("a"), b = try leaf("b"), moved = try leaf("moved")
        let previous = try group("previous")
        try previous.addResult(moved).get()
        let g = try group("g")
        try g.addResult(a).get()
        try g.addResult(b).get()
        let previousEvents = record(previous)
        let events = record(g)

        try g.replaceResult(at: 1, with: moved).get()

        XCTAssertEqual(g.snapshot().map(\.name), ["a", "moved"])
        XCTAssertEqual(previous.count, 0)
        XCTAssertTrue(owner(of: moved) === g)
        XCTAssertNil(owner(of: b))
        XCTAssertEqual(previousEvents(), ["remove moved new:-1 old:0"])
        XCTAssertEqual(events(), ["remove b new:-1 old:1", "add moved new:1 old:-1"])
    }

    func testReplaceOutsideTheMembersIsRejectedAndChangesNothing() throws {
        let a = try leaf("a"), stray = try leaf("stray")
        let g = try group("g")
        try g.addResult(a).get()
        let events = record(g)

        assertIndexRejected(g.replaceResult(at: 1, with: stray), index: 1, count: 1)

        XCTAssertTrue(g.at(0) === a)
        XCTAssertTrue(owner(of: a) === g)
        XCTAssertNil(owner(of: stray))
        XCTAssertEqual(events(), [])
    }

    func testAFailedConstructOnReplaceRestoresTheOldChild() throws {
        let kept = try leaf("kept"), failing = try leaf("failing", failConstruct: true)
        let g = try group("g", autoConstructOnAdd: true)
        try g.addResult(kept).get()
        try g.construct()
        let events = record(g)

        let result = g.replaceResult(at: 0, with: failing)

        guard case let .failure(.attachmentFailed(error)) = result else {
            return XCTFail("expected the construct failure, got \(result)")
        }
        XCTAssertEqual(error as? MembershipTestError, .constructFailed)
        XCTAssertTrue(g.at(0) === kept)
        XCTAssertTrue(owner(of: kept) === g)
        XCTAssertNil(owner(of: failing))
        XCTAssertEqual(events(), [])
    }

    // MARK: — remove and clear

    func testRemoveAtAndClearFreeTheirChildrenAndAnnounceIt() throws {
        let a = try leaf("a"), b = try leaf("b"), c = try leaf("c")
        let g = try group("g")
        for child in [a, b, c] { try g.addResult(child).get() }
        let events = record(g)

        g.removeAt(1)
        XCTAssertEqual(g.snapshot().map(\.name), ["a", "c"])
        XCTAssertNil(owner(of: b))
        XCTAssertFalse(g.remove(b))

        g.clear()

        XCTAssertEqual(g.count, 0)
        XCTAssertNil(owner(of: a))
        XCTAssertNil(owner(of: c))
        XCTAssertEqual(events(), ["remove b new:-1 old:1", "reset  new:-1 old:-1"])
    }

    // MARK: — dispose

    func testASecondDisposeDisposesNothingAgain() throws {
        let child = CountingChild("child")
        let g = try GroupVM<CountingChild>.builder()
            .name("g").withNullServices().children { [] }.build()
        try g.addResult(child).get()
        try g.construct()

        g.dispose()
        g.dispose()

        XCTAssertEqual(child.disposeCalls, 1)
        XCTAssertEqual(child.status, .disposed)
        XCTAssertEqual(g.status, .disposed)
    }
}
