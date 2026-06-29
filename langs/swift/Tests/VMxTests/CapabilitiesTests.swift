//
// Capability micro-interface conformance tests.
//
// This cluster (Phase 3, Inc 1): selection / expansion / dialog —
// CAP-001..007, CAP-009, CAP-010. Later CAP tasks (search/filter/paging, CRUD,
// container-current, composition) append to this file.
//
// Ports the CAP-001..007 / 009 / 010 blocks of
// langs/typescript/tests/conformance/capabilities.test.ts. See
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
}
