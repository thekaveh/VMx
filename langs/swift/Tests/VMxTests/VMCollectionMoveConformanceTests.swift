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

    /// Drives every shared VMCollection operation through the protocol only.
    private func exerciseShared<C: VMCollection>(_ value: C, _ a: C.Child, _ b: C.Child) throws
        -> [CollectionChangedAction] {
        var actions: [CollectionChangedAction] = []
        let cancel = value.collectionChanged.sink { actions.append($0.action) }
        defer { cancel.cancel() }

        value.add(a)
        value.insert(b, at: 0)
        XCTAssertEqual(value.count, 2)
        XCTAssertTrue(value.at(0) === b && value.at(1) === a)
        XCTAssertEqual(value.map { ObjectIdentifier($0) }, [ObjectIdentifier(b), ObjectIdentifier(a)])
        try value.move(from: 0, to: 1)
        XCTAssertTrue(value.at(0) === a && value.at(1) === b)
        let batch = value.batchUpdate()
        XCTAssertTrue(value.remove(b))
        value.removeAt(0)
        batch.dispose()
        XCTAssertEqual(value.count, 0)
        return actions
    }

    /// COL-032 — composites and groups share VMCollection while selection remains composite-only.
    func testCOL032SharedContractSeparatesSelection() throws {
        let c = composite()
        let g = group()
        XCTAssertEqual(acceptsCollection(c), 0)
        XCTAssertEqual(acceptsCollection(g), 0)
        XCTAssertNil(acceptsSelectable(c))

        // Both satisfy the full shared capability: count, indexed/iterable
        // reads, observation, mutation, move, and batching.
        let expected: [CollectionChangedAction] = [.add, .add, .move, .reset]
        XCTAssertEqual(try exerciseShared(c, leaf("a"), leaf("b")), expected)
        XCTAssertEqual(try exerciseShared(g, leaf("a"), leaf("b")), expected)

        // Only the composite satisfies the selectable capability; the group
        // exposes no current-child slot.
        XCTAssertTrue((c as AnyObject) is any SelectableVMCollection)
        XCTAssertFalse((g as AnyObject) is any SelectableVMCollection,
                       "GroupVM must not satisfy SelectableVMCollection")
        XCTAssertFalse(Mirror(reflecting: g).children.contains { $0.label == "current" },
                       "GroupVM must expose no current slot")
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

    /// Supplementary disposal check (not COL-033, which covers a forward move):
    /// a disposed container rejects move, and a disposed group ignores removal
    /// and clear.
    func testCOL033DisposedContainersAreInert() {
        let c = composite()
        let g = group()
        for name in ["a", "b", "c"] {
            c.add(leaf(name))
            g.add(leaf(name))
        }
        c.dispose()
        g.dispose()

        XCTAssertThrowsError(try c.move(from: 0, to: 1))
        XCTAssertThrowsError(try g.move(from: 0, to: 1))
        XCTAssertFalse(g.remove(g.at(0)))
        g.removeAt(0)
        g.clear()

        XCTAssertEqual(c.count, 3)
        XCTAssertEqual(g.count, 3)
    }
}
