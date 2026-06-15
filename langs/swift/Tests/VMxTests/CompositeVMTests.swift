//
// CompositeVM conformance tests.
//
// Claimed IDs: COMP-003 (select via child delegation), COMP-004,
// COMP-005, COMP-025 (`current(selector)` builder hook), COMP-026
// (`onCurrentChanged(callback)` builder hook). COMP-001/002
// (CollectionChanged), COMP-006/010 (foreground dispatch), COMP-007
// (modeled composite), COMP-008, and COMP-009 (raises — a trap in
// this flavor, ADR-0037) are NOT claimed.
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

    /// Composite reports the Composite kind.
    func testCompositeType() throws {
        let c = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [self.leaf("a")] }
            .build()
        XCTAssertEqual(c.type, .composite)
    }

    /// `add` appends to the children list.
    func testAddAppends() {
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [] }.build()
        let a = leaf("a")
        c.add(a)
        XCTAssertEqual(c.count, 1)
        XCTAssertTrue(c.at(0) === a)
    }

    /// COMP-004 — construct cascades to (waits on) children.
    func testComp004ConstructCascades() {
        let a = leaf("a"); let b = leaf("b")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices()
            .children { [a, b] }
            .build()
        c.construct()
        XCTAssertEqual(a.status, .constructed)
        XCTAssertEqual(b.status, .constructed)
    }

    /// COMP-005 — destruct cascades to (waits on) children.
    func testComp005DestructCascades() {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        c.construct()
        c.destruct()
        XCTAssertEqual(a.status, .destructed)
    }

    /// Setting `current` to a child member updates the slot.
    func testCurrentSet() {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        c.construct()
        c.current = a
        XCTAssertTrue(c.current === a)
        XCTAssertTrue(a.isCurrent)
    }

    /// Removing the current child drops the current slot.
    func testRemoveCurrentDropsSlot() {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        c.construct()
        c.current = a
        XCTAssertTrue(c.remove(a))
        XCTAssertNil(c.current)
    }

    /// Clear-like behaviour via repeated remove drops all children.
    /// (Full `clear()` lands in a follow-up.)
    func testRemoveAllChildren() {
        let a = leaf("a"); let b = leaf("b")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a, b] }.build()
        c.construct()
        _ = c.remove(a); _ = c.remove(b)
        XCTAssertEqual(c.count, 0)
    }

    /// Dispose cascades to children (canonical assertion is LIFE-013 in
    /// the lifecycle suite; this covers the composite path explicitly).
    func testDisposeCascade() {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        c.construct()
        c.dispose()
        XCTAssertEqual(a.status, .disposed)
        XCTAssertEqual(c.status, .disposed)
    }

    /// Child's `_parent` is wired on add — observed via `canSelect()`.
    func testChildParentWiredOnAdd() {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [] }.build()
        c.add(a)
        a.construct()
        XCTAssertTrue(a.canSelect())
    }

    /// COMP-003 — selecting through the child (`select()` delegates to the
    /// parent's select-child path) sets the parent's `current` slot.
    func testComp003SelectThroughChildSetsCurrent() {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        c.construct()
        a.select()
        XCTAssertTrue(c.current === a)
    }

    // ── current(_:) builder hook (COMP-025) ─────────────────────────────

    func testCurrentSelectorDrivesInitialSelectionAfterConstruct() throws {
        let a = leaf("a"); let b = leaf("b"); let cChild = leaf("c")
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .withNullServices()
            .children { [a, b, cChild] }
            .current { children in Array(children)[1] }
            .build()
        composite.construct()

        XCTAssertTrue(composite.current === b)
    }

    func testCurrentSelectorReturningNilLeavesCurrentNil() throws {
        let a = leaf("a")
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .withNullServices()
            .children { [a] }
            .current { _ in nil }
            .build()
        composite.construct()

        XCTAssertNil(composite.current)
    }

    // ── onCurrentChanged(_:) builder hook (COMP-026) ────────────────────

    func testOnCurrentChangedFiresAfterEachCurrentChange() throws {
        let a = leaf("a"); let b = leaf("b")
        var observed: [ComponentVM?] = []

        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .withNullServices()
            .children { [a, b] }
            .onCurrentChanged { vm in observed.append(vm) }
            .build()
        composite.construct()
        composite.selectChild(b)
        composite.deselectChild(b)

        XCTAssertEqual(observed.count, 2)
        XCTAssertTrue(observed[0] === b)
        XCTAssertNil(observed[1])
    }

    func testOnCurrentChangedFiresOnceForInitialSelector() throws {
        let a = leaf("a")
        var observed: [ComponentVM?] = []

        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .withNullServices()
            .children { [a] }
            .current { children in Array(children).first }
            .onCurrentChanged { vm in observed.append(vm) }
            .build()
        composite.construct()

        XCTAssertEqual(observed.count, 1)
        XCTAssertTrue(observed[0] === a)
    }

    func testOnCurrentChangedDoesNotFireWhenSelectorReturnsNilOrOutOfSet() throws {
        let a = leaf("a")
        var observed: [ComponentVM?] = []

        // Case 1: selector returns nil.
        let c1 = try CompositeVM<ComponentVM>.builder()
            .name("c-null")
            .withNullServices()
            .children { [a] }
            .current { _ in nil }
            .onCurrentChanged { vm in observed.append(vm) }
            .build()
        c1.construct()
        XCTAssertTrue(observed.isEmpty)

        // Case 2: selector returns out-of-set.
        let foreign = leaf("foreign")
        let c2 = try CompositeVM<ComponentVM>.builder()
            .name("c-foreign")
            .withNullServices()
            .children { [a] }
            .current { _ in foreign }
            .onCurrentChanged { vm in observed.append(vm) }
            .build()
        c2.construct()
        XCTAssertTrue(observed.isEmpty)
    }

    // ── Conformance — COMP-025 / COMP-026 ───────────────────────────────

    /// COMP-025 — `current(selector)` builder hook drives initial selection
    /// during construct.
    func testCOMP025CurrentSelectorDrivesInitialSelection() throws {
        let a = leaf("a"); let b = leaf("b"); let cChild = leaf("c")
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .withNullServices()
            .children { [a, b, cChild] }
            .current { children in Array(children)[1] }
            .build()
        composite.construct()

        XCTAssertTrue(composite.current === b)
    }

    /// COMP-026 — `onCurrentChanged(callback)` fires synchronously after
    /// each `current` change.
    ///
    /// Spec/12 COMP-026 phrases the scenario as `composite.select_component(b)`
    /// then `composite.deselect_component(b)`. Swift's documented subset
    /// (langs/swift/README.md §5 and ADR-0037) exposes selection via the
    /// `IParentVM.selectChild` callback (`child.select()` delegates to it);
    /// there is no public `selectComponent` / `canSelectComponent` surface in
    /// Swift. Both code paths converge at `_setCurrent → onCurrentChanged?`,
    /// so the callback-ordering invariant is identical.
    func testCOMP026OnCurrentChangedFiresAfterEachChange() throws {
        let a = leaf("a"); let b = leaf("b")
        var observed: [ComponentVM?] = []

        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .withNullServices()
            .children { [a, b] }
            .onCurrentChanged { vm in observed.append(vm) }
            .build()
        composite.construct()
        composite.selectChild(b)
        composite.deselectChild(b)

        XCTAssertEqual(observed.count, 2)
        XCTAssertTrue(observed[0] === b)
        XCTAssertNil(observed[1])
    }
}
