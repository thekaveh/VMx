import Combine
import XCTest
@testable import VMx

final class VMCollectionMoveConformanceTests: XCTestCase {
    private func leaf(_ name: String, onConstruct: (() -> Void)? = nil) -> ComponentVM {
        var builder = ComponentVM.builder().name(name).withNullServices()
        if let onConstruct { builder = builder.onConstruct(onConstruct) }
        return try! builder.build()
    }

    private func composite(_ children: [ComponentVM] = [], autoConstruct: Bool = false)
        -> CompositeVM<ComponentVM> {
        try! CompositeVM<ComponentVM>.builder()
            .name("composite").withNullServices().children { children }
            .autoConstructOnAdd(autoConstruct).build()
    }

    private func group(_ children: [ComponentVM] = []) -> GroupVM<ComponentVM> {
        try! GroupVM<ComponentVM>.builder()
            .name("group").withNullServices().children { children }.build()
    }

    private func acceptsCollection<C: VMCollection>(_ value: C) -> Int { value.count }
    private func acceptsSelectable<C: SelectableVMCollection>(_ value: C) -> C.Child? {
        value.current
    }

    /// COL-032 — composites and groups share VMCollection while selection remains composite-only.
    func testCOL032SharedContractSeparatesSelection() {
        XCTAssertEqual(acceptsCollection(composite()), 0)
        XCTAssertEqual(acceptsCollection(group()), 0)
        XCTAssertNil(acceptsSelectable(composite()))
    }

    /// COL-033 — forward move emits one Move event with both indices and the same item.
    func testCOL033ForwardMoveEmitsOneMoveEvent() throws {
        let a = leaf("a"), b = leaf("b"), c = leaf("c")
        let value = composite([a, b, c])
        try value.construct()
        var events: [CollectionChangedEvent] = []
        let cancel = value.collectionChanged.sink { events.append($0) }

        try value.move(from: 0, to: 2)

        XCTAssertTrue(value.at(0) === b && value.at(1) === c && value.at(2) === a)
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events[0].action, .move)
        XCTAssertEqual(events[0].oldIndex, 0)
        XCTAssertEqual(events[0].newIndex, 2)
        XCTAssertTrue(events[0].newItems[0] === a && events[0].oldItems[0] === a)
        cancel.cancel()
    }

    /// COL-034 — backward move is supported by GroupVM through the shared contract.
    func testCOL034BackwardMoveWorksForGroup() throws {
        let a = leaf("a"), b = leaf("b"), c = leaf("c")
        let value = group([a, b, c])
        try value.construct()
        var events: [CollectionChangedEvent] = []
        let cancel = value.collectionChanged.sink { events.append($0) }

        try value.move(from: 2, to: 0)

        XCTAssertTrue(value.at(0) === c && value.at(1) === a && value.at(2) === b)
        XCTAssertEqual(events.map(\.action), [.move])
        XCTAssertEqual(events[0].oldIndex, 2)
        XCTAssertEqual(events[0].newIndex, 0)
        cancel.cancel()
    }

    /// COL-035 — same-index move is a true no-op and emits no event.
    func testCOL035SameIndexIsTrueNoOp() throws {
        let a = leaf("a"), b = leaf("b"), c = leaf("c")
        let value = composite([a, b, c])
        try value.construct()
        var events: [CollectionChangedEvent] = []
        let cancel = value.collectionChanged.sink { events.append($0) }

        let batch = value.batchUpdate()
        try value.move(from: 1, to: 1)
        batch.dispose()

        XCTAssertTrue(value.at(0) === a && value.at(1) === b && value.at(2) === c)
        XCTAssertTrue(events.isEmpty)
        cancel.cancel()
    }

    /// COL-036 — invalid move bounds throw without mutation or publication.
    func testCOL036InvalidBoundsAreAtomic() throws {
        let a = leaf("a"), b = leaf("b"), c = leaf("c")
        let value = composite([a, b, c])
        try value.construct()
        var events: [CollectionChangedEvent] = []
        let cancel = value.collectionChanged.sink { events.append($0) }

        XCTAssertThrowsError(try value.move(from: -1, to: 0))
        XCTAssertThrowsError(try value.move(from: 0, to: 3))

        XCTAssertTrue(value.at(0) === a && value.at(1) === b && value.at(2) === c)
        XCTAssertTrue(events.isEmpty)
        cancel.cancel()
    }

    /// COL-037 — move preserves identity, parent, lifecycle, and current selection.
    func testCOL037MovePreservesIdentityParentLifecycleAndCurrent() throws {
        let a = leaf("a")
        let value = composite([a, leaf("b"), leaf("c")])
        try value.construct()
        value.current = a

        try value.move(from: 0, to: 2)

        XCTAssertTrue(value.at(2) === a)
        XCTAssertTrue(value.current === a)
        XCTAssertTrue(a.isCurrent)
        XCTAssertTrue(a.canDeselect())
        XCTAssertEqual(a.status, .constructed)
    }

    /// COL-038 — a move inside a batch produces exactly one Reset at batch end.
    func testCOL038BatchedMoveCollapsesToReset() throws {
        let value = composite([leaf("a"), leaf("b"), leaf("c")])
        try value.construct()
        var events: [CollectionChangedEvent] = []
        let cancel = value.collectionChanged.sink { events.append($0) }

        let batch = value.batchUpdate()
        try value.move(from: 0, to: 2)
        batch.dispose()

        XCTAssertEqual(events.map(\.action), [.reset])
        cancel.cancel()
    }

    /// COL-039 — moving an auto-constructed child never constructs it again.
    func testCOL039MoveDoesNotReconstructAutoConstructedChild() throws {
        var constructs = 0
        let value = composite([], autoConstruct: true)
        try value.construct()
        let moved = leaf("moved") { constructs += 1 }
        value.add(moved)
        value.add(leaf("other"))

        try value.move(from: 0, to: 1)

        XCTAssertTrue(value.at(1) === moved)
        XCTAssertEqual(constructs, 1)
    }
}
