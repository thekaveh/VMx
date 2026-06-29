//
// AutoConstructOnAddTests.swift — autoConstructOnAdd conformance tests.
//
// Claimed IDs: COMP-012, GRP-005.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

final class AutoConstructOnAddTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    // ── COMP-012 ──────────────────────────────────────────────────────────

    /// COMP-012 — autoConstructOnAdd(true) constructs child before CollectionChanged(.add) fires on CompositeVM.
    func testCOMP012CompositeAutoConstructsChildBeforeAddEvent() throws {
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices()
            .children { [] }
            .autoConstructOnAdd(true)
            .build()
        try composite.construct()

        let child = try ComponentVM.builder().name("late-child").withNullServices().build()
        var statusAtEvent: [ConstructionStatus] = []
        composite.collectionChanged
            .sink { _ in statusAtEvent.append(child.status) }
            .store(in: &cancellables)

        composite.add(child)

        XCTAssertTrue(child.isConstructed, "child should be constructed after add")
        XCTAssertEqual(statusAtEvent.count, 1, "exactly one Add event should fire")
        XCTAssertEqual(
            statusAtEvent[0], .constructed,
            "child must be Constructed BEFORE the Add event is observed"
        )
    }

    // ── GRP-005 ───────────────────────────────────────────────────────────

    /// GRP-005 — autoConstructOnAdd(true) constructs child before CollectionChanged(.add) fires on GroupVM.
    func testGRP005GroupAutoConstructsChildBeforeAddEvent() throws {
        let group = try GroupVM<ComponentVM>.builder()
            .name("g").withNullServices()
            .children { [] }
            .autoConstructOnAdd(true)
            .build()
        try group.construct()

        let child = try ComponentVM.builder().name("late").withNullServices().build()
        var statusAtEvent: [ConstructionStatus] = []
        group.collectionChanged
            .sink { _ in statusAtEvent.append(child.status) }
            .store(in: &cancellables)

        group.add(child)

        XCTAssertTrue(child.isConstructed, "child should be constructed after add")
        XCTAssertEqual(statusAtEvent.count, 1, "exactly one Add event should fire")
        XCTAssertEqual(
            statusAtEvent[0], .constructed,
            "child must be Constructed BEFORE the Add event is observed"
        )
    }
}
