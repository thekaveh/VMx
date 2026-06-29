//
// Capability micro-interface conformance tests — complete CAP coverage.
//
// This file covers all 22 capability IDs (CAP-001..022), ported in Phase 3,
// Inc 1: selection / expansion / dialog (CAP-001..007, CAP-009, CAP-010),
// search / filter / paging (CAP-008, CAP-021, CAP-022), and CRUD /
// container-current / management (CAP-011..020). No further CAP tasks remain.
//
// Ports the CAP-001..010 blocks of
// langs/typescript/tests/conformance/capabilities.test.ts and the
// cap-021-filterable / cap-022-pageable conformance files. See
// spec/14-capabilities.md and spec/ADRs/0057-v3-capability-micro-interface-granularity.md.
//
// Each test defines a small local fixture conforming to the capability protocol
// with a call-counter (or a flipped flag), calls the guard then the verb, and
// asserts the verb fired and the state changed. CAP-003/006 additionally assert
// that a double-toggle returns to the initial state.
//
// Swift has no runtime capability registry (unlike TypeScript's
// `declareCapabilities` — capabilities are advertised by static protocol
// conformance), so a fixture's conformance IS its capability declaration; these
// tests exercise the contract members directly.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

final class CapabilitiesTests: XCTestCase {

    /// CAP-001 — Selectable contract: guard reports availability, verb fires.
    func testCap001SelectableContract() {
        final class Fixture: Selectable {
            var calls = 0
            func canSelect() -> Bool { true }
            func select() { calls += 1 }
        }
        let f = Fixture()
        XCTAssertTrue(f.canSelect())
        f.select()
        XCTAssertEqual(f.calls, 1)
    }

    /// CAP-002 — Deselectable contract: guard reports availability, verb fires.
    func testCap002DeselectableContract() {
        final class Fixture: Deselectable {
            var calls = 0
            func canDeselect() -> Bool { true }
            func deselect() { calls += 1 }
        }
        let f = Fixture()
        XCTAssertTrue(f.canDeselect())
        f.deselect()
        XCTAssertEqual(f.calls, 1)
    }

    /// CAP-003 — SelectionTogglable contract: double-toggle returns to initial.
    func testCap003SelectionTogglableContract() {
        final class Fixture: SelectionTogglable {
            var selected = false
            func canToggleSelection() -> Bool { true }
            func toggleSelection() { selected.toggle() }
        }
        let f = Fixture()
        let initial = f.selected
        XCTAssertTrue(f.canToggleSelection())
        f.toggleSelection()
        XCTAssertNotEqual(f.selected, initial)
        f.toggleSelection()
        XCTAssertEqual(f.selected, initial)
    }

    /// CAP-004 — Expandable contract: guard reports availability, verb expands.
    func testCap004ExpandableContract() {
        final class Fixture: Expandable {
            var isExpanded = false
            func canExpand() -> Bool { true }
            func expand() { isExpanded = true }
        }
        let f = Fixture()
        XCTAssertFalse(f.isExpanded)
        XCTAssertTrue(f.canExpand())
        f.expand()
        XCTAssertTrue(f.isExpanded)
    }

    /// CAP-005 — Collapsible contract: guard reports availability, verb fires.
    func testCap005CollapsibleContract() {
        final class Fixture: Collapsible {
            var calls = 0
            func canCollapse() -> Bool { true }
            func collapse() { calls += 1 }
        }
        let f = Fixture()
        XCTAssertTrue(f.canCollapse())
        f.collapse()
        XCTAssertEqual(f.calls, 1)
    }

    /// CAP-006 — ExpansionTogglable contract: double-toggle returns to initial.
    func testCap006ExpansionTogglableContract() {
        final class Fixture: ExpansionTogglable {
            var expanded = false
            func canToggleExpansion() -> Bool { true }
            func toggleExpansion() { expanded.toggle() }
        }
        let f = Fixture()
        let initial = f.expanded
        XCTAssertTrue(f.canToggleExpansion())
        f.toggleExpansion()
        XCTAssertNotEqual(f.expanded, initial)
        f.toggleExpansion()
        XCTAssertEqual(f.expanded, initial)
    }

    /// CAP-007 — Closable contract: guard reports availability, verb fires.
    func testCap007ClosableContract() {
        final class Fixture: Closable {
            var calls = 0
            func canClose() -> Bool { true }
            func close() { calls += 1 }
        }
        let f = Fixture()
        XCTAssertTrue(f.canClose())
        f.close()
        XCTAssertEqual(f.calls, 1)
    }

    /// CAP-009 — Approvable contract: guard reports availability, verb fires.
    func testCap009ApprovableContract() {
        final class Fixture: Approvable {
            var calls = 0
            func canApprove() -> Bool { true }
            func approve() { calls += 1 }
        }
        let f = Fixture()
        XCTAssertTrue(f.canApprove())
        f.approve()
        XCTAssertEqual(f.calls, 1)
    }

    /// CAP-010 — Cancelable contract: guard reports availability, verb fires.
    func testCap010CancelableContract() {
        final class Fixture: Cancelable {
            var calls = 0
            func canCancel() -> Bool { true }
            func cancel() { calls += 1 }
        }
        let f = Fixture()
        XCTAssertTrue(f.canCancel())
        f.cancel()
        XCTAssertEqual(f.calls, 1)
    }

    // ── ExpandableState helper ───────────────────────────────────────────────
    // Not a conformance ID of its own — this exercises the concrete helper that
    // backs the expansion triple so it is verified by behavior, not merely
    // compiled. (No `XXX-NNN —` marker, so the coverage scraper ignores it.)

    /// ExpandableState flips state bidirectionally; expand/collapse are guarded
    /// no-ops at the boundary; `isExpandedChanged` publishes only transitions.
    func testExpandableStateTogglesBidirectionally() {
        let state = ExpandableState()
        XCTAssertFalse(state.isExpanded)

        var emissions: [Bool] = []
        var cancellables: Set<AnyCancellable> = []
        state.isExpandedChanged
            .sink { emissions.append($0) }
            .store(in: &cancellables)

        XCTAssertTrue(state.canExpand())
        state.expand()
        XCTAssertTrue(state.isExpanded)

        // Idempotent: a second expand is a guarded no-op (no extra emission).
        state.expand()
        XCTAssertTrue(state.isExpanded)

        XCTAssertTrue(state.canCollapse())
        state.collapse()
        XCTAssertFalse(state.isExpanded)

        // Double-toggle returns to the initial (collapsed) state.
        state.toggleExpansion()
        XCTAssertTrue(state.isExpanded)
        state.toggleExpansion()
        XCTAssertFalse(state.isExpanded)

        XCTAssertEqual(emissions, [true, false, true, false])
        state.dispose()
    }

    // ── Search / filter / paging — CAP-008, CAP-021, CAP-022 ─────────────────

    /// CAP-008 — Searchable contract: `searchTerm` is settable, guard reports
    /// availability, `search()` applies the current term. Ports the CAP-008
    /// block of capabilities.test.ts.
    func testCap008SearchableContract() {
        final class Fixture: Searchable {
            var searchTerm = ""
            var searched: [String] = []
            func canSearch() -> Bool { true }
            func search() { searched.append(searchTerm) }
        }
        let f = Fixture()
        f.searchTerm = "abc"
        XCTAssertTrue(f.canSearch())
        f.search()
        XCTAssertEqual(f.searchTerm, "abc")
        XCTAssertEqual(f.searched, ["abc"])
    }

    /// CAP-021 — Filterable contract: a settable `(Item) -> Bool` predicate,
    /// `nil` clears the filter, `canFilter()` reports the decision. Ports
    /// cap-021-filterable.test.ts. (Swift uses `associatedtype Item` because
    /// protocols cannot be generic — see Filter.swift / Task-10 ADR.)
    func testCap021FilterableContract() {
        final class Fixture: Filterable {
            typealias Item = Int
            var filter: ((Int) -> Bool)?
            // Mirrors the TS fixture: filtering is allowed exactly while a
            // predicate is present, so a `nil` reset disables it.
            func canFilter() -> Bool { filter != nil }
        }
        let f = Fixture()
        XCTAssertNil(f.filter)
        XCTAssertFalse(f.canFilter())

        // Set a predicate: it is retained and applied (closures aren't
        // Equatable, so assert the bound behavior rather than identity).
        f.filter = { $0 > 0 }
        XCTAssertNotNil(f.filter)
        XCTAssertTrue(f.canFilter())
        XCTAssertTrue(f.filter!(5))
        XCTAssertFalse(f.filter!(-1))

        // nil clears the filter.
        f.filter = nil
        XCTAssertNil(f.filter)
        XCTAssertFalse(f.canFilter())
    }

    /// CAP-022 — Pageable contract: `pageSize` / `currentPageIndex` mutate;
    /// `pageCount` / `isPagingEnabled` derive; `pageSize == 0` disables paging;
    /// navigation clamps and is a no-op at both bounds; resizing re-clamps the
    /// index; an empty source yields `pageCount == 0`. Ports the
    /// PageableFixture and every assertion of cap-022-pageable.test.ts.
    func testCap022PageableContract() {
        final class PageableFixture: Pageable {
            private let itemCount: Int
            private var storedPageSize = 10
            private var storedPageIndex = 0

            init(itemCount: Int) { self.itemCount = itemCount }

            var pageSize: Int {
                get { storedPageSize }
                set {
                    storedPageSize = newValue < 0 ? 0 : newValue
                    storedPageIndex = clamp(storedPageIndex)
                }
            }

            var currentPageIndex: Int {
                get { storedPageIndex }
                set { storedPageIndex = clamp(newValue) }
            }

            var pageCount: Int {
                if storedPageSize <= 0 { return 1 }
                // ceil(itemCount / pageSize) via integer arithmetic.
                return (itemCount + storedPageSize - 1) / storedPageSize
            }

            var isPagingEnabled: Bool { storedPageSize > 0 }

            func moveToFirstPage() { storedPageIndex = 0 }
            func moveToPreviousPage() { if storedPageIndex > 0 { storedPageIndex -= 1 } }
            func moveToNextPage() { if storedPageIndex < pageCount - 1 { storedPageIndex += 1 } }
            func moveToLastPage() { storedPageIndex = pageCount - 1 }

            private func clamp(_ index: Int) -> Int {
                if pageCount == 0 { return 0 } // empty source: index stays at 0
                let maxIndex = pageCount - 1
                if index < 0 { return 0 }
                if index > maxIndex { return maxIndex }
                return index
            }
        }

        // Initial state / derived values.
        let sut = PageableFixture(itemCount: 25)
        XCTAssertEqual(sut.pageSize, 10)
        XCTAssertEqual(sut.currentPageIndex, 0)
        XCTAssertTrue(sut.isPagingEnabled)
        XCTAssertEqual(sut.pageCount, 3) // ceil(25/10)

        // pageSize=0 disables paging, pageCount=1, navigation no-ops.
        let disabled = PageableFixture(itemCount: 25)
        disabled.pageSize = 0
        XCTAssertFalse(disabled.isPagingEnabled)
        XCTAssertEqual(disabled.pageCount, 1)
        disabled.moveToFirstPage()
        disabled.moveToLastPage()
        XCTAssertEqual(disabled.currentPageIndex, 0)

        // Clamping currentPageIndex above max and below 0.
        let clampSut = PageableFixture(itemCount: 25)
        clampSut.currentPageIndex = 99
        XCTAssertEqual(clampSut.currentPageIndex, 2) // clamped to pageCount-1
        clampSut.currentPageIndex = -1
        XCTAssertEqual(clampSut.currentPageIndex, 0) // clamped to 0

        // Navigation methods work and are no-ops at both bounds.
        let nav = PageableFixture(itemCount: 25)
        nav.currentPageIndex = 1
        nav.moveToFirstPage()
        XCTAssertEqual(nav.currentPageIndex, 0)
        nav.moveToLastPage()
        XCTAssertEqual(nav.currentPageIndex, 2)
        nav.moveToNextPage() // no-op at upper bound
        XCTAssertEqual(nav.currentPageIndex, 2)
        nav.moveToPreviousPage()
        XCTAssertEqual(nav.currentPageIndex, 1)
        nav.moveToFirstPage()
        nav.moveToPreviousPage() // no-op at lower bound
        XCTAssertEqual(nav.currentPageIndex, 0)
        nav.moveToNextPage()
        XCTAssertEqual(nav.currentPageIndex, 1)

        // pageSize resize re-clamps currentPageIndex.
        let resize = PageableFixture(itemCount: 25)
        resize.currentPageIndex = 2 // page 3 of 3
        resize.pageSize = 20        // pageCount = ceil(25/20) = 2 → pages 0..1
        XCTAssertEqual(resize.currentPageIndex, 1) // clamped from 2 to 1

        // itemCount=0 with pageSize>0 yields pageCount=0.
        let empty = PageableFixture(itemCount: 0)
        empty.pageSize = 5
        XCTAssertEqual(empty.pageCount, 0) // ceil(0/5) = 0 (empty source has no pages)
    }

    // ── CRUD / current / management — CAP-011..017 ───────────────────────────
    // Ports the CAP-011..017 blocks of capabilities.test.ts. Each fixture
    // conforms to one CRUD/current/management micro-interface, calls the guard
    // then the verb, and asserts the verb recorded its effect. The item-scoped
    // verbs (Savable/Managable/Deletable/Updatable) infer `associatedtype Item`
    // = String from the fixture's method signatures.

    /// CAP-011 — Savable contract: guard reports availability, `save(_:)`
    /// persists the item.
    func testCap011SavableContract() {
        final class Fixture: Savable {
            var saved: [String] = []
            func canSave(_ item: String) -> Bool { true }
            func save(_ item: String) { saved.append(item) }
        }
        let f = Fixture()
        XCTAssertTrue(f.canSave("a"))
        f.save("a")
        XCTAssertEqual(f.saved, ["a"])
    }

    /// CAP-012 — Managable contract: guard reports availability, `manage(_:)`
    /// records the item.
    func testCap012ManagableContract() {
        final class Fixture: Managable {
            var managed: [String] = []
            func canManage(_ item: String) -> Bool { true }
            func manage(_ item: String) { managed.append(item) }
        }
        let f = Fixture()
        XCTAssertTrue(f.canManage("x"))
        f.manage("x")
        XCTAssertEqual(f.managed, ["x"])
    }

    /// CAP-013 — NewCreatable contract: guard reports availability, `createNew()`
    /// fires.
    func testCap013NewCreatableContract() {
        final class Fixture: NewCreatable {
            var calls = 0
            func canCreateNew() -> Bool { true }
            func createNew() { calls += 1 }
        }
        let f = Fixture()
        XCTAssertTrue(f.canCreateNew())
        f.createNew()
        XCTAssertEqual(f.calls, 1)
    }

    /// CAP-014 — Deletable contract: guard reports availability, `delete(_:)`
    /// records the item.
    func testCap014DeletableContract() {
        final class Fixture: Deletable {
            var deleted: [String] = []
            func canDelete(_ item: String) -> Bool { true }
            func delete(_ item: String) { deleted.append(item) }
        }
        let f = Fixture()
        XCTAssertTrue(f.canDelete("a"))
        f.delete("a")
        XCTAssertEqual(f.deleted, ["a"])
    }

    /// CAP-015 — Updatable contract: guard reports availability, `update(_:)`
    /// records the item.
    func testCap015UpdatableContract() {
        final class Fixture: Updatable {
            var updated: [String] = []
            func canUpdate(_ item: String) -> Bool { true }
            func update(_ item: String) { updated.append(item) }
        }
        let f = Fixture()
        XCTAssertTrue(f.canUpdate("a"))
        f.update("a")
        XCTAssertEqual(f.updated, ["a"])
    }

    /// CAP-016 — CurrentDeletable contract: guard reports availability,
    /// `deleteCurrent()` fires.
    func testCap016CurrentDeletableContract() {
        final class Fixture: CurrentDeletable {
            var calls = 0
            func canDeleteCurrent() -> Bool { true }
            func deleteCurrent() { calls += 1 }
        }
        let f = Fixture()
        XCTAssertTrue(f.canDeleteCurrent())
        f.deleteCurrent()
        XCTAssertEqual(f.calls, 1)
    }

    /// CAP-017 — CurrentUpdatable contract: guard reports availability,
    /// `updateCurrent()` fires.
    func testCap017CurrentUpdatableContract() {
        final class Fixture: CurrentUpdatable {
            var calls = 0
            func canUpdateCurrent() -> Bool { true }
            func updateCurrent() { calls += 1 }
        }
        let f = Fixture()
        XCTAssertTrue(f.canUpdateCurrent())
        f.updateCurrent()
        XCTAssertEqual(f.calls, 1)
    }

    // ── Lifecycle triple / composition / opt-in — CAP-018..020 ───────────────

    /// CAP-018 — Lifecycle capability set: a VM exposes the lifecycle triple
    /// (Constructable / Destructable / Reconstructable) at the documented
    /// signatures. `ComponentVMBase` conforms to all three by inheritance, so a
    /// concrete VM is castable to each and its guards return `Bool`. Ports the
    /// matching block of capabilities.test.ts (which asserts the six members are
    /// present); Swift verifies the same via structural protocol conformance.
    func testCap018LifecycleCapabilitySet() {
        // Static type `Any` so the casts below are genuine runtime checks
        // (no "'is'/'as?' is always true/false" static-resolution warning).
        let vm: Any = ComponentVM(
            name: "life", hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE
        )
        let constructable = vm as? Constructable
        let destructable = vm as? Destructable
        let reconstructable = vm as? Reconstructable
        XCTAssertNotNil(constructable)
        XCTAssertNotNil(destructable)
        XCTAssertNotNil(reconstructable)
        // Guards are callable and return Bool. A fresh VM is `.destructed`:
        // construct is legal, destruct is a legal (no-op) target, reconstruct is
        // not (only legal from `.constructed`).
        XCTAssertTrue(constructable!.canConstruct())
        XCTAssertTrue(destructable!.canDestruct())
        XCTAssertFalse(reconstructable!.canReconstruct())
    }

    /// CAP-019 — Composition: a single VM may conform to several capabilities at
    /// once, and each verb records its effect independently. Mirrors the CAP-019
    /// block of capabilities.test.ts (5 simultaneous capabilities: Selectable,
    /// Expandable, Closable, Approvable, Cancelable). Structural protocol
    /// conformance is the Swift analogue of the TS `hasCapability` registry.
    func testCap019MultipleCapabilities() {
        final class Fixture: Selectable, Expandable, Closable, Approvable, Cancelable {
            var selects = 0
            var expands = 0
            var closes = 0
            var approves = 0
            var cancels = 0
            var isExpanded = false
            func canSelect() -> Bool { true }
            func select() { selects += 1 }
            func canExpand() -> Bool { true }
            func expand() { isExpanded = true; expands += 1 }
            func canClose() -> Bool { true }
            func close() { closes += 1 }
            func canApprove() -> Bool { true }
            func approve() { approves += 1 }
            func canCancel() -> Bool { true }
            func cancel() { cancels += 1 }
        }
        let f = Fixture()
        let anyF: Any = f
        XCTAssertTrue(anyF is Selectable)
        XCTAssertTrue(anyF is Expandable)
        XCTAssertTrue(anyF is Closable)
        XCTAssertTrue(anyF is Approvable)
        XCTAssertTrue(anyF is Cancelable)
        f.select()
        f.expand()
        f.close()
        f.approve()
        f.cancel()
        XCTAssertEqual(
            [f.selects, f.expands, f.closes, f.approves, f.cancels], [1, 1, 1, 1, 1]
        )
        XCTAssertTrue(f.isExpanded)
    }

    /// CAP-020 — Opt-in: the lifecycle triple is BASELINE (every core VM
    /// advertises Constructable / Destructable / Reconstructable by inheritance
    /// from `ComponentVMBase`), but non-baseline capabilities are NOT implicitly
    /// satisfied — even those whose verb *methods* happen to exist on the base
    /// (e.g. `ComponentVMBase` has `canSelect()`/`select()` yet does not declare
    /// `Selectable`, so it is not `Selectable`). Ports the CAP-020 block of
    /// capabilities.test.ts; replaces the TS runtime `hasCapability` registry
    /// with Swift structural `as?` / `is` conformance checks (a forced divergence
    /// recorded in the Task-10 ADR).
    func testCap020CapabilitiesAreOptIn() {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        // Static type `Any` so each check is a real runtime cast across the four
        // core VM kinds (Component / Composite / Group / Aggregate).
        let coreVMs: [Any] = [
            ComponentVM(name: "comp", hub: hub, dispatcher: dispatcher),
            CompositeVM<ComponentVM>(name: "composite", hub: hub, dispatcher: dispatcher),
            GroupVM<ComponentVM>(name: "group", hub: hub, dispatcher: dispatcher),
            AggregateVM1<ComponentVM>(name: "agg", hub: hub, dispatcher: dispatcher) {
                ComponentVM(name: "child", hub: hub, dispatcher: dispatcher)
            },
        ]
        for vm in coreVMs {
            // Baseline: the lifecycle triple is present on every core VM.
            XCTAssertTrue(vm is Constructable)
            XCTAssertTrue(vm is Destructable)
            XCTAssertTrue(vm is Reconstructable)
            // Non-baseline capabilities are NOT implicitly satisfied.
            XCTAssertNil(vm as? Selectable)
            XCTAssertNil(vm as? Expandable)
            XCTAssertNil(vm as? Closable)
            XCTAssertNil(vm as? NewCreatable)
            XCTAssertNil(vm as? CurrentDeletable)
            XCTAssertNil(vm as? Searchable)
        }
    }
}
