//
// GroupVM conformance subset (GRP-001..GRP-006).
//
import XCTest
@testable import VMx

final class GroupVMTests: XCTestCase {

    private func leaf(_ name: String) -> ComponentVM {
        try! ComponentVM.builder().name(name).withNullServices().build()
    }

    /// GRP-001 — group reports the Group kind.
    func testGrp001Type() throws {
        let g = try GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [] }.build()
        XCTAssertEqual(g.type, .group)
    }

    /// GRP-002 — add appends to the peers list.
    func testGrp002AddAppends() {
        let g = try! GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [] }.build()
        let a = leaf("a")
        g.add(a)
        XCTAssertEqual(g.count, 1)
        XCTAssertTrue(g.at(0) === a)
    }

    /// GRP-003 — construct cascades to peers.
    func testGrp003ConstructCascades() {
        let a = leaf("a"); let b = leaf("b")
        let g = try! GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [a, b] }.build()
        g.construct()
        XCTAssertEqual(a.status, .constructed)
        XCTAssertEqual(b.status, .constructed)
    }

    /// GRP-004 — destruct cascades to peers.
    func testGrp004DestructCascades() {
        let a = leaf("a")
        let g = try! GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [a] }.build()
        g.construct()
        g.destruct()
        XCTAssertEqual(a.status, .destructed)
    }

    /// GRP-005 — Groups have no selection concept: a child's
    /// `canSelect()` is false (parent has no current child slot).
    func testGrp005GroupChildCannotSelect() {
        let a = leaf("a")
        let g = try! GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [a] }.build()
        g.construct()
        XCTAssertFalse(a.canSelect())
    }

    /// GRP-006 — dispose cascades to peers.
    func testGrp006DisposeCascade() {
        let a = leaf("a")
        let g = try! GroupVM<ComponentVM>.builder()
            .name("g").withNullServices().children { [a] }.build()
        g.construct()
        g.dispose()
        XCTAssertEqual(a.status, .disposed)
    }
}
