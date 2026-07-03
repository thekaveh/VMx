//
// CompositeVM conformance tests.
//
// Claimed IDs: COMP-003 (select via child delegation), COMP-004,
// COMP-005, COMP-025 (`current(selector)` builder hook), COMP-026
// (`onCurrentChanged(callback)` builder hook). COMP-001/002
// (CollectionChanged), COMP-006/010 (foreground dispatch), COMP-007
// (modeled composite), COMP-008 are NOT claimed. COMP-009 (non-child
// `current` assignment raises) is now a *catchable throw* via
// `setCurrent(_:)`/`canSetCurrent(_:)` (VMX-026 / ADR-0053); the
// `current` property setter still traps because Swift setters cannot
// throw.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
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
    func testComp004ConstructCascades() throws {
        let a = leaf("a"); let b = leaf("b")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices()
            .children { [a, b] }
            .build()
        try c.construct()
        XCTAssertEqual(a.status, .constructed)
        XCTAssertEqual(b.status, .constructed)
    }

    /// COMP-005 — destruct cascades to (waits on) children, clears `current`,
    /// and the composite itself reaches `.destructed`.
    func testComp005DestructCascades() throws {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()
        c.current = a
        XCTAssertTrue(c.current === a)
        try c.destruct()
        XCTAssertEqual(a.status, .destructed)
        XCTAssertNil(c.current)                 // current cleared on destruct
        XCTAssertEqual(c.status, .destructed)   // composite itself destructed
    }

    /// Setting `current` to a child member updates the slot.
    func testCurrentSet() throws {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()
        c.current = a
        XCTAssertTrue(c.current === a)
        XCTAssertTrue(a.isCurrent)
    }

    /// Removing the current child drops the current slot.
    func testRemoveCurrentDropsSlot() throws {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()
        c.current = a
        XCTAssertTrue(c.remove(a))
        XCTAssertNil(c.current)
    }

    /// Clear-like behaviour via repeated remove drops all children.
    /// (Full `clear()` lands in a follow-up.)
    func testRemoveAllChildren() throws {
        let a = leaf("a"); let b = leaf("b")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a, b] }.build()
        try c.construct()
        _ = c.remove(a); _ = c.remove(b)
        XCTAssertEqual(c.count, 0)
    }

    /// Dispose cascades to children (canonical assertion is LIFE-013 in
    /// the lifecycle suite; this covers the composite path explicitly).
    func testDisposeCascade() throws {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()
        c.dispose()
        XCTAssertEqual(a.status, .disposed)
        XCTAssertEqual(c.status, .disposed)
    }

    /// Child's `_parent` is wired on add — observed via `canSelect()`.
    func testChildParentWiredOnAdd() throws {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [] }.build()
        c.add(a)
        try a.construct()
        XCTAssertTrue(a.canSelect())
    }

    /// COMP-003 — selecting through the child (`select()` delegates to the
    /// parent's select-child path) sets the parent's `current` slot.
    func testComp003SelectThroughChildSetsCurrent() throws {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()
        a.select()
        XCTAssertTrue(c.current === a)
        XCTAssertTrue(a.isCurrent)   // child's own isCurrent flag flips
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
        try composite.construct()

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
        try composite.construct()

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
        try composite.construct()
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
        try composite.construct()

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
        try c1.construct()
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
        try c2.construct()
        XCTAssertTrue(observed.isEmpty)
    }

    // ── Conformance — COMP-025 / COMP-026 ───────────────────────────────

    /// COMP-025 — `current(selector)` builder hook drives initial selection
    /// during construct. Three clauses (spec/12 COMP-025, parity with the
    /// Python/C# conformance tests):
    ///   1. the selector's return value becomes `current`;
    ///   2. the selector runs EXACTLY ONCE — after every child reached
    ///      `.constructed` and before the composite itself reaches
    ///      `.constructed`;
    ///   3. a null-returning selector leaves `current` nil AND publishes no
    ///      `PropertyChangedMessage("current")`.
    func testCOMP025CurrentSelectorDrivesInitialSelection() throws {
        let hub = MessageHub()
        let a = try ComponentVM.builder()
            .name("a").services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE).build()
        let b = try ComponentVM.builder()
            .name("b").services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE).build()
        let cChild = try ComponentVM.builder()
            .name("c").services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE).build()

        var selectorCalls = 0
        var allChildrenConstructedAtSelector = false
        var compositeStatusAtSelector: ConstructionStatus?
        weak var compositeRef: CompositeVM<ComponentVM>?

        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [a, b, cChild] }
            .current { children in
                selectorCalls += 1
                allChildrenConstructedAtSelector = children.allSatisfy { $0.status == .constructed }
                compositeStatusAtSelector = compositeRef?.status
                return Array(children)[1]
            }
            .build()
        compositeRef = composite

        try composite.construct()

        // Clause 1 — the selector's pick (b) becomes current.
        XCTAssertTrue(composite.current === b)
        // Clause 2 — exactly one selector call, after every child reached
        // Constructed and while the composite is still Constructing.
        XCTAssertEqual(selectorCalls, 1, "the selector must run exactly once during construct")
        XCTAssertTrue(allChildrenConstructedAtSelector,
                      "the selector must run after every child reached Constructed")
        XCTAssertEqual(compositeStatusAtSelector, .constructing,
                       "the selector must run before the composite itself reaches Constructed")

        // Clause 3 — a null-returning selector leaves current nil and publishes
        // no PropertyChangedMessage("current") on the hub.
        let hub2 = MessageHub()
        let a2 = try ComponentVM.builder()
            .name("a").services(hub: hub2, dispatcher: ImmediateDispatcher.INSTANCE).build()
        var propertyNames: [String] = []
        let cancel = hub2.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .sink { propertyNames.append($0.propertyName) }

        let composite2 = try CompositeVM<ComponentVM>.builder()
            .name("composite2")
            .services(hub: hub2, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [a2] }
            .current { _ in nil }
            .build()
        try composite2.construct()

        XCTAssertNil(composite2.current)
        XCTAssertFalse(propertyNames.contains("current"),
                       "a null-returning current selector must publish no "
                       + "PropertyChangedMessage(\"current\")")
        cancel.cancel()
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
        try composite.construct()
        composite.selectChild(b)
        composite.deselectChild(b)

        XCTAssertEqual(observed.count, 2)
        XCTAssertTrue(observed[0] === b)
        XCTAssertNil(observed[1])
    }

    /// VMX-098 — `selectChild` gates on Constructed, mirroring C#
    /// `CanSelectComponent` (`member && status == .constructed`). Selecting a
    /// member that is not yet constructed is a no-op (Swift keeps the no-op
    /// rather than the C# throw — trap-vs-throw is tracked separately,
    /// ADR-0037); once constructed, the same call selects it.
    func testSelectChildGatesOnConstructed() throws {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [] }.build()
        c.add(a)                       // member, but still .destructed

        c.selectChild(a)
        XCTAssertNil(c.current, "a non-constructed child must not be selectable")

        try a.construct()
        c.selectChild(a)
        XCTAssertTrue(c.current === a, "a constructed member is selectable")
        XCTAssertTrue(a.isCurrent)
    }

    // ── VMX-026 / ADR-0053 — throwing `setCurrent(_:)` + `canSetCurrent(_:)` ──

    /// VMX-026 — `setCurrent(_:)` throws a catchable `CompositeMembershipError`
    /// on a non-child (was a `preconditionFailure` trap with no predicate). This
    /// is the Swift convergence to the C#/Python/TypeScript catchable throw on a
    /// non-child `Current` assignment (spec/06 §3.1, COMP-009).
    func testVMX026SetCurrentThrowsOnNonChild() throws {
        let a = leaf("a")
        let foreign = leaf("foreign")
        let c = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()

        XCTAssertThrowsError(try c.setCurrent(foreign)) { error in
            guard let e = error as? CompositeMembershipError else {
                return XCTFail("expected CompositeMembershipError, got \(error)")
            }
            XCTAssertEqual(e.memberName, "foreign")
            XCTAssertEqual(e.compositeName, "c")
            XCTAssertTrue(e.description.contains("foreign"))
        }
        XCTAssertNil(c.current, "a failed setCurrent must not change the slot")
    }

    /// VMX-026 — `canSetCurrent(_:)` is the pre-flight predicate: true for a
    /// member or `nil`, false for a non-child.
    func testVMX026CanSetCurrentPredicate() throws {
        let a = leaf("a")
        let foreign = leaf("foreign")
        let c = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()

        XCTAssertTrue(c.canSetCurrent(a))
        XCTAssertTrue(c.canSetCurrent(nil))
        XCTAssertFalse(c.canSetCurrent(foreign))
    }

    /// VMX-026 — `setCurrent(_:)` accepts a member (selecting it) and `nil`
    /// (clearing it), behaving exactly like the property setter for the valid
    /// cases.
    func testVMX026SetCurrentAcceptsMemberAndNil() throws {
        let a = leaf("a")
        let c = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()

        try c.setCurrent(a)
        XCTAssertTrue(c.current === a)
        XCTAssertTrue(a.isCurrent)

        try c.setCurrent(nil)
        XCTAssertNil(c.current)
        XCTAssertFalse(a.isCurrent)
    }
}
