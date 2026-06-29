//
// BatchUpdateTests.swift — batchUpdate conformance for CompositeVM / GroupVM.
//
// Claimed IDs: COMP-013, GRP-006.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

final class BatchUpdateTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func leaf(_ name: String) -> ComponentVM {
        try! ComponentVM.builder().name(name).withNullServices().build()
    }

    // ── COMP-013 ──────────────────────────────────────────────────────────

    /// COMP-013 — batchUpdate suppresses per-mutation CollectionChanged events
    /// and emits exactly one .reset when the handle is disposed (if dirty).
    func testCOMP013BatchUpdateSuppressesMutationEventsAndEmitsReset() throws {
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [] }.build()
        try composite.construct()

        var events: [CollectionChangedEvent] = []
        composite.collectionChanged
            .sink { events.append($0) }
            .store(in: &cancellables)

        let c1 = leaf("c1")
        let c2 = leaf("c2")
        let c3 = leaf("c3")

        let handle = composite.batchUpdate()
        composite.add(c1)
        composite.add(c2)
        composite.add(c3)
        XCTAssertTrue(composite.remove(c1), "remove inside the batch still mutates")

        // No granular events during the batch — adds AND removes are suppressed.
        XCTAssertEqual(events.count, 0, "no events should fire while batch is open")

        handle.dispose()

        // Exactly one reset after the batch ends (regardless of mutation count).
        XCTAssertEqual(events.count, 1, "exactly one reset event expected after dispose")
        XCTAssertEqual(events[0].action, .reset)

        // Post-batch state is correct: 3 added − 1 removed.
        XCTAssertEqual(composite.count, 2)
    }

    /// COMP-013 — A batch with no mutations emits nothing on dispose.
    func testCOMP013EmptyBatchEmitsNothing() throws {
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [] }.build()
        try composite.construct()

        var events: [CollectionChangedEvent] = []
        composite.collectionChanged
            .sink { events.append($0) }
            .store(in: &cancellables)

        let handle = composite.batchUpdate()
        handle.dispose()

        XCTAssertEqual(events.count, 0, "no mutations → no reset event")
    }

    /// COMP-013 — dispose() is idempotent; a second call does not emit again.
    func testCOMP013DisposeIsIdempotent() throws {
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [] }.build()
        try composite.construct()

        var events: [CollectionChangedEvent] = []
        composite.collectionChanged
            .sink { events.append($0) }
            .store(in: &cancellables)

        let handle = composite.batchUpdate()
        composite.add(leaf("c1"))
        handle.dispose()
        handle.dispose()  // second dispose — must be a no-op

        XCTAssertEqual(events.count, 1, "idempotent dispose must not emit twice")
    }

    // ── GRP-006 ───────────────────────────────────────────────────────────

    /// GRP-006 — GroupVM batchUpdate suppresses per-mutation CollectionChanged
    /// events and emits exactly one .reset when the handle is disposed (if dirty).
    func testGRP006BatchUpdateSuppressesMutationEventsAndEmitsReset() throws {
        let group = try GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [] }.build()
        try group.construct()

        var events: [CollectionChangedEvent] = []
        group.collectionChanged
            .sink { events.append($0) }
            .store(in: &cancellables)

        let handle = group.batchUpdate()
        group.add(leaf("c1"))
        group.add(leaf("c2"))

        // No granular events during the batch.
        XCTAssertEqual(events.count, 0, "no events should fire while batch is open")

        handle.dispose()

        // Exactly one reset after the batch ends.
        XCTAssertEqual(events.count, 1, "exactly one reset event expected after dispose")
        XCTAssertEqual(events[0].action, .reset)
    }

    /// GRP-006 — A GroupVM batch with no mutations emits nothing on dispose.
    func testGRP006EmptyBatchEmitsNothing() throws {
        let group = try GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [] }.build()
        try group.construct()

        var events: [CollectionChangedEvent] = []
        group.collectionChanged
            .sink { events.append($0) }
            .store(in: &cancellables)

        let handle = group.batchUpdate()
        handle.dispose()

        XCTAssertEqual(events.count, 0, "no mutations → no reset event")
    }
}
