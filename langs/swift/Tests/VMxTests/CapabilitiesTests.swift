//
// Capability micro-interface conformance tests.
//
// This cluster (Phase 3, Inc 1): selection / expansion / dialog —
// CAP-001..007, CAP-009, CAP-010 — plus search / filter / paging —
// CAP-008, CAP-021, CAP-022. Later CAP tasks (CRUD, container-current,
// composition) append to this file.
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
}
