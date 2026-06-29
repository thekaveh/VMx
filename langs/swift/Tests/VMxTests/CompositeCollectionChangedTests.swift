//
// CompositeCollectionChangedTests.swift — CollectionChanged event conformance.
//
// Claimed IDs: COMP-001, COMP-002, GRP-001.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

final class CompositeCollectionChangedTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func leaf(_ name: String) -> ComponentVM {
        try! ComponentVM.builder().name(name).withNullServices().build()
    }

    // ── COMP-001 ─────────────────────────────────────────────────────────

    /// COMP-001 — Add emits CollectionChanged(action=.add) with correct payload.
    func testCOMP001CompositeAddEmitsCollectionChangedAdd() throws {
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [] }.build()
        try composite.construct()

        var events: [CollectionChangedEvent] = []
        composite.collectionChanged
            .sink { events.append($0) }
            .store(in: &cancellables)

        let child = leaf("child")
        composite.add(child)

        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events[0].action, .add)
        XCTAssertEqual(events[0].newItems.count, 1)
        XCTAssertTrue(events[0].newItems[0] === child)
        XCTAssertEqual(events[0].newIndex, 0)
        XCTAssertEqual(events[0].oldIndex, -1)
    }

    // ── COMP-002 ─────────────────────────────────────────────────────────

    /// COMP-002 — Remove emits CollectionChanged(action=.remove) with correct payload.
    func testCOMP002CompositeRemoveEmitsCollectionChangedRemove() throws {
        let child = leaf("child")
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [child] }.build()
        try composite.construct()

        var events: [CollectionChangedEvent] = []
        composite.collectionChanged
            .sink { events.append($0) }
            .store(in: &cancellables)

        let removed = composite.remove(child)

        XCTAssertTrue(removed)
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events[0].action, .remove)
        XCTAssertEqual(events[0].oldItems.count, 1)
        XCTAssertTrue(events[0].oldItems[0] === child)
        XCTAssertEqual(events[0].oldIndex, 0)
        XCTAssertEqual(events[0].newIndex, -1)
    }

    // ── GRP-001 ──────────────────────────────────────────────────────────

    /// GRP-001 — GroupVM add emits CollectionChanged(action=.add) with correct payload.
    func testGRP001GroupAddEmitsCollectionChangedAdd() throws {
        let group = try GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [] }.build()
        try group.construct()

        var events: [CollectionChangedEvent] = []
        group.collectionChanged
            .sink { events.append($0) }
            .store(in: &cancellables)

        let child = leaf("c1")
        group.add(child)

        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events[0].action, .add)
        XCTAssertEqual(events[0].newItems.count, 1)
        XCTAssertTrue(events[0].newItems[0] === child)
        XCTAssertEqual(events[0].newIndex, 0)
        XCTAssertEqual(events[0].oldIndex, -1)
    }
}
