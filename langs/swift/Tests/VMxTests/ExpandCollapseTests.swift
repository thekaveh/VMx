//
// Expand/collapse conformance tests — EXP-001..008
// (spec/14-capabilities.md §2.2, spec/13-tree-utilities.md, spec/05 §8).
//
// EXP-001..004 exercise the existing `ExpandableState` composition helper;
// EXP-005 exercises `walkExpanded`, which prunes at collapsed Expandable nodes;
// EXP-006..008 exercise the helper's expansion commands (ADR-0159).
//
// Ports langs/typescript/tests/conformance/expandCollapse.test.ts.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

// MARK: - EXP-005 test fixture

/// A minimal container node that is both `Expandable` and `_TreeContainer`.
/// Used exclusively in the EXP-005 tree-pruning test.
private final class ExpandableComposite: ComponentVMBase, Expandable, _TreeContainer {
    private var _children: [ComponentVMBase]
    private var _expanded: Bool

    init(_ name: String, children: [ComponentVMBase], expanded: Bool) {
        _children = children
        _expanded = expanded
        super.init(
            name: name,
            hub: NullMessageHub.INSTANCE,
            dispatcher: NullDispatcher.INSTANCE
        )
    }

    // Expandable
    var isExpanded: Bool { _expanded }
    func canExpand() -> Bool { !_expanded }
    func expand() { _expanded = true }

    // _TreeContainer
    var childComponents: [ComponentVMBase] { _children }
}

// MARK: - Tests

final class ExpandCollapseTests: XCTestCase {

    /// EXP-001 — fresh ExpandableState defaults to collapsed; canExpand true, canCollapse false.
    func testExp001DefaultsToCollapsed() {
        let state = ExpandableState()
        XCTAssertFalse(state.isExpanded)
        XCTAssertTrue(state.canExpand())
        XCTAssertFalse(state.canCollapse())
    }

    /// EXP-002 — expand() transitions to true and emits exactly one isExpandedChanged(true); repeat expand() is a no-op.
    func testExp002ExpandEmitsOnce() {
        let state = ExpandableState()
        var emissions: [Bool] = []
        let cancel = state.isExpandedChanged.sink { emissions.append($0) }

        state.expand()
        XCTAssertTrue(state.isExpanded)
        XCTAssertEqual(emissions, [true], "expand() must emit exactly one true")

        // Idempotent: second expand() is guarded — no further emission.
        state.expand()
        XCTAssertEqual(emissions, [true], "repeat expand() must not emit again")

        cancel.cancel()
    }

    /// EXP-003 — collapse() on an expanded state transitions to false and emits exactly one isExpandedChanged(false).
    func testExp003CollapseEmitsOnce() {
        let state = ExpandableState(initiallyExpanded: true)
        var emissions: [Bool] = []
        let cancel = state.isExpandedChanged.sink { emissions.append($0) }

        state.collapse()
        XCTAssertFalse(state.isExpanded)
        XCTAssertEqual(emissions, [false], "collapse() must emit exactly one false")

        cancel.cancel()
    }

    /// EXP-004 — toggleExpansion() alternates state; two toggles return to initial; third yields true.
    func testExp004ToggleAlternates() {
        let state = ExpandableState()
        state.toggleExpansion()
        XCTAssertTrue(state.isExpanded)
        state.toggleExpansion()
        XCTAssertFalse(state.isExpanded, "two toggles must return to initial collapsed state")
        state.toggleExpansion()
        XCTAssertTrue(state.isExpanded, "third toggle must yield expanded")
    }

    /// EXP-005 — walkExpanded prunes children of collapsed Expandable nodes; non-Expandable nodes are always descended.
    func testExp005WalkExpandedPrunesCollapsed() {
        // Leaves
        let a  = try! ComponentVM.builder().name("a").withNullServices().build()
        let b1 = try! ComponentVM.builder().name("b1").withNullServices().build()
        let b2 = try! ComponentVM.builder().name("b2").withNullServices().build()

        // b is Expandable and collapsed → its children (b1, b2) must be pruned.
        let b    = ExpandableComposite("b", children: [b1, b2], expanded: false)
        // root is Expandable and expanded → its children (a, b) ARE visited.
        let root = ExpandableComposite("root", children: [a, b], expanded: true)

        let result = walkExpanded(root)
        XCTAssertTrue(result.contains { $0 === root }, "root must appear")
        XCTAssertTrue(result.contains { $0 === a },    "a must appear (root is expanded)")
        XCTAssertTrue(result.contains { $0 === b },    "b must appear (root is expanded)")
        XCTAssertFalse(result.contains { $0 === b1 },  "b1 must be pruned (b is collapsed)")
        XCTAssertFalse(result.contains { $0 === b2 },  "b2 must be pruned (b is collapsed)")
        XCTAssertEqual(result.map(\.name), ["root", "a", "b"])

        // After expanding b, its children appear.
        b.expand()
        let expanded = walkExpanded(root)
        XCTAssertEqual(expanded.map(\.name), ["root", "a", "b", "b1", "b2"])
    }

    /// EXP-006 — expansion command predicates track the can* checks, and each command's canExecuteChanged fires once per effective expansion change.
    func testExp006CommandPredicatesTrackCanChecks() {
        let state = ExpandableState()
        let expand = state.expandCommand
        let collapse = state.collapseCommand
        let toggle = state.toggleExpansionCommand
        var counts = [0, 0, 0]
        var cancellables: [AnyCancellable] = []
        for (index, command) in [expand, collapse, toggle].enumerated() {
            cancellables.append(command.canExecuteChanged.sink { counts[index] += 1 })
        }

        XCTAssertTrue(expand.canExecute())
        XCTAssertFalse(collapse.canExecute())
        XCTAssertTrue(toggle.canExecute())

        state.expand()
        XCTAssertEqual(counts, [1, 1, 1])
        XCTAssertFalse(expand.canExecute())
        XCTAssertTrue(collapse.canExecute())
        XCTAssertTrue(toggle.canExecute())

        state.expand() // a no-op verb is not an expansion change
        XCTAssertEqual(counts, [1, 1, 1])

        state.collapse()
        XCTAssertEqual(counts, [2, 2, 2])
        XCTAssertTrue(expand.canExecute())
        XCTAssertFalse(collapse.canExecute())

        XCTAssertTrue(state.expandCommand === expand)
        XCTAssertTrue(state.collapseCommand === collapse)
        XCTAssertTrue(state.toggleExpansionCommand === toggle)
        cancellables.forEach { $0.cancel() }
    }

    /// EXP-007 — executing each expansion command performs its verb.
    func testExp007ExecutingCommandsPerformsVerbs() {
        let state = ExpandableState()
        var observed: [Bool] = []
        let cancel = state.isExpandedChanged.sink { observed.append($0) }

        state.expandCommand.execute()
        XCTAssertTrue(state.isExpanded)
        state.expandCommand.execute() // the predicate is false while expanded
        XCTAssertEqual(observed, [true])

        state.collapseCommand.execute()
        XCTAssertFalse(state.isExpanded)
        state.collapseCommand.execute()
        XCTAssertEqual(observed, [true, false])

        state.toggleExpansionCommand.execute()
        XCTAssertTrue(state.isExpanded)
        state.toggleExpansionCommand.execute()
        XCTAssertFalse(state.isExpanded)
        XCTAssertEqual(observed, [true, false, true, false])
        cancel.cancel()
    }

    /// EXP-008 — disposing the helper makes its expansion commands inert, including commands first read after disposal.
    func testExp008HelperDisposeMakesCommandsInert() {
        let state = ExpandableState()
        let commands = [state.expandCommand, state.collapseCommand, state.toggleExpansionCommand]
        var observed: [Bool] = []
        let cancel = state.isExpandedChanged.sink { observed.append($0) }

        state.dispose()

        for command in commands {
            XCTAssertFalse(command.canExecute())
            command.execute()
        }
        XCTAssertFalse(state.isExpanded)
        XCTAssertEqual(observed, [])

        let late = ExpandableState()
        late.dispose()
        for command in [late.expandCommand, late.collapseCommand, late.toggleExpansionCommand] {
            XCTAssertFalse(command.canExecute())
            command.execute()
        }
        XCTAssertFalse(late.isExpanded)
        XCTAssertTrue(late.expandCommand === late.expandCommand)
        cancel.cancel()
    }

    /// The cached commands hold the helper weakly, so they do not keep it alive.
    func testExpansionCommandsDoNotRetainTheHelper() {
        weak var weakState: ExpandableState?
        var command: RelayCommand?
        do {
            let state = ExpandableState()
            weakState = state
            command = state.toggleExpansionCommand
        }
        XCTAssertNil(weakState)
        XCTAssertFalse(command?.canExecute() ?? true)
    }
}
