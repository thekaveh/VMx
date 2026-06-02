//
// CompositeVM conformance subset (COMP-001..COMP-010).
//
import XCTest
@testable import VMx

final class CompositeVMTests: XCTestCase {

    private func leaf(_ name: String) -> ComponentVM {
        try! ComponentVM.builder()
            .name(name)
            .withNullServices()
            .build()
    }

    /// COMP-001 — composite reports the Composite kind.
    func testComp001Type() throws {
        let c = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [self.leaf("a")] }
            .build()
        XCTAssertEqual(c.type, .composite)
    }

    /// COMP-002 — add appends to the children list.
    func testComp002AddAppends() {
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [] }.build()
        let a = leaf("a")
        c.add(a)
        XCTAssertEqual(c.count, 1)
        XCTAssertTrue(c.at(0) === a)
    }

    /// COMP-003 — construct cascades to children.
    func testComp003ConstructCascades() {
        let a = leaf("a"); let b = leaf("b")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices()
            .children { [a, b] }
            .build()
        c.construct()
        XCTAssertEqual(a.status, .constructed)
        XCTAssertEqual(b.status, .constructed)
    }

    /// COMP-004 — destruct cascades to children.
    func testComp004DestructCascades() {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        c.construct()
        c.destruct()
        XCTAssertEqual(a.status, .destructed)
    }

    /// COMP-005 — setting `current` to a child member updates the slot.
    func testComp005CurrentSet() {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        c.construct()
        c.current = a
        XCTAssertTrue(c.current === a)
        XCTAssertTrue(a.isCurrent)
    }

    /// COMP-006 — removing the current child drops the current slot.
    func testComp006RemoveCurrent() {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        c.construct()
        c.current = a
        XCTAssertTrue(c.remove(a))
        XCTAssertNil(c.current)
    }

    /// COMP-007 — clear-like behaviour via repeated remove drops all
    /// children. (Full `clear()` lands in the follow-up PR.)
    func testComp007RemoveAllChildren() {
        let a = leaf("a"); let b = leaf("b")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a, b] }.build()
        c.construct()
        _ = c.remove(a); _ = c.remove(b)
        XCTAssertEqual(c.count, 0)
    }

    /// COMP-008 — composite dispose cascades to children (LIFE-013 in
    /// the lifecycle suite is the canonical assertion; here we cover
    /// the composite path explicitly).
    func testComp008DisposeCascade() {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        c.construct()
        c.dispose()
        XCTAssertEqual(a.status, .disposed)
        XCTAssertEqual(c.status, .disposed)
    }

    /// COMP-009 — child's `_parent` is wired on add.
    func testComp009ChildParentWired() {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [] }.build()
        c.add(a)
        // Parent backpointer is internal; we observe its effect: a.canSelect()
        // should now return true once the leaf is in `.constructed` state.
        a.construct()
        XCTAssertTrue(a.canSelect())
    }

    /// COMP-010 — selecting via the child's `select()` updates parent's
    /// current slot.
    func testComp010SelectThroughChild() {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        c.construct()
        a.select()
        XCTAssertTrue(c.current === a)
    }
}
