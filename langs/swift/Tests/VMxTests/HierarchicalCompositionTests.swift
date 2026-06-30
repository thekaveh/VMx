//
// HierarchicalVM capability composition conformance tests — HIER-012, HIER-013, HIER-014.
//
// HIER-012: a collapsed HierarchicalVM node composes ExpandableState and
//           gates walkExpanded descent — collapsed root yields only itself;
//           after expand(), root + child are yielded.
// HIER-013: SearchableState composed over a node's materialized children
//           filters them by search term.
// HIER-014: ModeledCrudCommands composed over a HierarchicalVM tree —
//           createNewCommand adds a child node; deleteCurrentCommand removes it.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

// ── Shared test model ────────────────────────────────────────────────────────

private struct HierModel {
    let value: String
}

// ── HIER-012 helper ──────────────────────────────────────────────────────────

/// Concrete CRTP node that composes `ExpandableState` and declares `Expandable`
/// conformance so `walkExpanded` can gate descent at collapsed nodes (HIER-012).
/// `HierarchicalVM` already conforms to `_TreeContainer` (via the extension in
/// TreeWalk.swift), so `walkExpanded` can enumerate children once expanded.
private final class ExpandableHierNode: HierarchicalVM<HierModel, ExpandableHierNode>, Expandable {
    private let expansion: ExpandableState

    init(
        children: [ExpandableHierNode],
        initiallyExpanded: Bool,
        hub: MessageHubProtocol
    ) {
        self.expansion = ExpandableState(initiallyExpanded: initiallyExpanded)
        super.init(
            model: HierModel(value: "m"),
            childrenFactory: { _ in children },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
    }

    var isExpanded: Bool { expansion.isExpanded }
    func canExpand() -> Bool { expansion.canExpand() }
    func expand() { expansion.expand() }
}

// ── HIER-013 helper ──────────────────────────────────────────────────────────

private final class SearchHierNode: HierarchicalVM<HierModel, SearchHierNode> {}

// ── HIER-014 helpers ─────────────────────────────────────────────────────────

private final class CrudHierNode: HierarchicalVM<HierModel, CrudHierNode> {}

/// Reference holder for mutable state that must be captured by @escaping closures.
/// A `final class` avoids the "@escaping capture of 'var'" restriction while keeping
/// mutation visible across closures (HIER-014).
private final class Ref<T: AnyObject> {
    var value: T?
    init(_ value: T? = nil) { self.value = value }
}

// MARK: - Tests

final class HierarchicalCompositionTests: XCTestCase {

    /// HIER-012 — walkExpanded honors ExpandableState lazy boundary when composed
    /// on a HierarchicalVM node: a collapsed node gates descent; after expand() the
    /// child is included.
    func testHier012WalkExpandedHonorsExpandableState() {
        let hub = MessageHub()
        let childLeaf = ExpandableHierNode(children: [], initiallyExpanded: true, hub: hub)
        let root = ExpandableHierNode(children: [childLeaf], initiallyExpanded: false, hub: hub)
        _ = root.children // force materialization so parent back-pointer is wired

        // Collapsed root: walkExpanded yields only root; child is pruned.
        let walkedCollapsed = walkExpanded(root)
        XCTAssertEqual(walkedCollapsed.count, 1,
            "Collapsed root must yield only itself")
        XCTAssertTrue(walkedCollapsed[0] === root,
            "The single yielded node must be root")

        root.expand()
        let walkedExpanded = walkExpanded(root)
        XCTAssertEqual(walkedExpanded.count, 2,
            "After expand(), root + childLeaf must be yielded")
    }

    /// HIER-013 — SearchableState composed over a node's materialized children
    /// filters them: setting searchTerm = "an" retains only "banana".
    func testHier013SearchableStateFiltersChildren() {
        let hub = MessageHub()
        let apple  = SearchHierNode(model: HierModel(value: "apple"),
                                    childrenFactory: { _ in [] }, hub: hub,
                                    dispatcher: ImmediateDispatcher.INSTANCE)
        let banana = SearchHierNode(model: HierModel(value: "banana"),
                                    childrenFactory: { _ in [] }, hub: hub,
                                    dispatcher: ImmediateDispatcher.INSTANCE)
        let cherry = SearchHierNode(model: HierModel(value: "cherry"),
                                    childrenFactory: { _ in [] }, hub: hub,
                                    dispatcher: ImmediateDispatcher.INSTANCE)
        let root = SearchHierNode(
            model: HierModel(value: "root"),
            childrenFactory: { _ in [apple, banana, cherry] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )

        let search = SearchableState<SearchHierNode>(
            items: { root.children },
            predicate: { node, term in
                node.model.value.lowercased().contains(term.lowercased())
            }
        )

        var result: [SearchHierNode] = []
        var bag = Set<AnyCancellable>()
        search.filtered.sink { result = $0 }.store(in: &bag)

        search.searchTerm = "an"
        search.search() // force immediate recompute, bypassing debounce

        XCTAssertEqual(result.count, 1, "Only 'banana' should match 'an'")
        XCTAssertEqual(result.first?.model.value, "banana")

        search.dispose()
    }

    /// HIER-014 — ModeledCrudCommands composition mutates the HierarchicalVM tree:
    /// createNewCommand appends a child node; deleteCurrentCommand removes it.
    func testHier014ModeledCrudCommandsMutatesTree() {
        let hub = MessageHub()
        let root = CrudHierNode(
            model: HierModel(value: "root"),
            childrenFactory: { _ in [] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )

        // Reference holder so @escaping closures can mutate the selected node
        // without capturing a 'var' inout (reference-safe pattern).
        let currentHolder = Ref<CrudHierNode>()

        let crud = ModeledCrudCommands<CrudHierNode>(
            current: { currentHolder.value },
            createNew: {
                let child = CrudHierNode(
                    model: HierModel(value: "created"),
                    childrenFactory: { _ in [] },
                    hub: hub,
                    dispatcher: ImmediateDispatcher.INSTANCE
                )
                root.addChild(child)
                currentHolder.value = child
            },
            updateCurrent: { _ in /* no-op for this test */ },
            deleteCurrent: { vm in
                root.removeChild(vm)
                currentHolder.value = nil
            }
        )

        // Create: createNewCommand adds a child and sets current.
        crud.createNewCommand.execute()
        XCTAssertEqual(root.children.count, 1,
            "createNewCommand must append a child to root")
        XCTAssertNotNil(currentHolder.value,
            "current must be set after createNewCommand")

        // Delete: deleteCurrentCommand removes current child and clears selection.
        crud.deleteCurrentCommand.execute()
        XCTAssertEqual(root.children.count, 0,
            "deleteCurrentCommand must remove the child from root")
        XCTAssertNil(currentHolder.value,
            "current must be cleared after deleteCurrentCommand")

        crud.dispose()
    }
}
