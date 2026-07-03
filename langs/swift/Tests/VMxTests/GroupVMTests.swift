//
// GroupVM conformance tests.
//
// Claimed IDs: GRP-002, GRP-003, GRP-004, GRP-011 (plus the group path of
// LIFE-013). GRP-001 (CollectionChanged on add), GRP-005 (AutoConstructOnAdd),
// and GRP-006 (BatchUpdate) are claimed in sibling files at total parity
// (ADR-0065): GRP-001 in CompositeCollectionChangedTests.swift, GRP-005 in
// AutoConstructOnAddTests.swift, GRP-006 in BatchUpdateTests.swift.
//
import XCTest
@testable import VMx

final class GroupVMTests: XCTestCase {

    private func leaf(_ name: String) -> ComponentVM {
        try! ComponentVM.builder().name(name).withNullServices().build()
    }

    /// Group reports the Group kind.
    func testGroupType() throws {
        let g = try GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [] }.build()
        XCTAssertEqual(g.type, .group)
    }

    /// `add` appends to the peers list.
    func testAddAppends() {
        let g = try! GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [] }.build()
        let a = leaf("a")
        g.add(a)
        XCTAssertEqual(g.count, 1)
        XCTAssertTrue(g.at(0) === a)
    }

    /// GRP-002 — Group lacks child-navigation/selection members, while
    /// the baseline SelectCommand/DeselectCommand remain present (they
    /// act on the group's own selection within its parent) and
    /// SelectNext/SelectPrevious predicates are permanently false.
    func testGrp002SurfaceContract() throws {
        let g = try GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [] }.build()
        try g.construct()
        XCTAssertFalse(g.selectNextCommand.canExecute())
        XCTAssertFalse(g.selectPreviousCommand.canExecute())
        // Present, but not executable without a parent to be selected in.
        XCTAssertFalse(g.selectCommand.canExecute())
        XCTAssertFalse(g.deselectCommand.canExecute())
    }

    /// GRP-003 — construct cascades to peers.
    func testGrp003ConstructCascades() throws {
        let a = leaf("a"); let b = leaf("b")
        let g = try! GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [a, b] }.build()
        try g.construct()
        XCTAssertEqual(a.status, .constructed)
        XCTAssertEqual(b.status, .constructed)
        // Catalog GRP-003: the group itself is also Constructed.
        XCTAssertEqual(g.status, .constructed)
    }

    /// GRP-004 — destruct cascades to peers.
    func testGrp004DestructCascades() throws {
        let a = leaf("a"); let b = leaf("b")
        let g = try! GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [a, b] }.build()
        try g.construct()
        try g.destruct()
        XCTAssertEqual(a.status, .destructed)
        XCTAssertEqual(b.status, .destructed)
        // Catalog GRP-004: the group itself is also Destructed.
        XCTAssertEqual(g.status, .destructed)
    }

    /// GRP-011 — a group child is a peer, so its inherited select command is
    /// disabled even though the group has set the child's parent.
    func testGrp011GroupChildrenAreNotSelectable() throws {
        let a = leaf("a")
        let g = try! GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [a] }.build()
        try g.construct()

        XCTAssertFalse(a.canSelect())
        XCTAssertFalse(a.selectCommand.canExecute())

        a.select()

        XCTAssertFalse(a.isCurrent)
        XCTAssertFalse(a.canDeselect())
    }

    /// LIFE-013 (group path) — dispose cascades to peers.
    func testLife013DisposeCascadesToPeers() throws {
        let a = leaf("a")
        let g = try! GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [a] }.build()
        try g.construct()
        g.dispose()
        XCTAssertEqual(a.status, .disposed)
    }
}
