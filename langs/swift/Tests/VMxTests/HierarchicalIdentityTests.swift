//
// HierarchicalVM core + tree identity conformance tests.
//
// Claimed IDs: HIER-001 (recursive generic constraint compiles; root
// isRoot/depth=0), HIER-002 (parent nil for root, identity ref for child after
// materialization), HIER-003 (depth 0/1/2 in a three-level tree), HIER-004
// (path root-first; cached identity-stable on re-read), HIER-005 (isLeaf /
// isRoot derivation), HIER-006 (isFirst / isLast sibling predicates, both false
// for root).
//
// Ported from the TypeScript HIER-001..006 blocks
// (tests/conformance/hier-001-to-014-hierarchical-vm.test.ts).
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
@testable import VMx

// ── Concrete CRTP node + model used across the suite ────────────────────────

private struct MyModel {
    let value: String
}

/// Concrete node satisfying the recursive generic constraint
/// `HierarchicalVM<MyModel, MyNode>` — the canonical CRTP shape.
private final class MyNode: HierarchicalVM<MyModel, MyNode> {}

final class HierarchicalIdentityTests: XCTestCase {

    // ── Helpers ─────────────────────────────────────────────────────────

    private func leafNode(_ hub: MessageHubProtocol, name: String = "") -> MyNode {
        MyNode(
            model: MyModel(value: "m"),
            childrenFactory: { _ in [] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            name: name
        )
    }

    private func parentNode(_ children: [MyNode], _ hub: MessageHubProtocol) -> MyNode {
        MyNode(
            model: MyModel(value: "m"),
            childrenFactory: { _ in children },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
    }

    // ── Tests ───────────────────────────────────────────────────────────

    /// HIER-001 — Recursive generic constraint compiles; a fresh root reports
    /// isRoot true and depth 0.
    func testHier001RecursiveGenericConstraintCompiles() {
        let node = leafNode(MessageHub())
        XCTAssertTrue(node.isRoot)
        XCTAssertEqual(node.depth, 0)
    }

    /// HIER-002 — parent is nil for the root and an identity reference to the
    /// root for a child once children are materialized.
    func testHier002ParentNilForRootRefForChild() {
        let hub = MessageHub()
        let child = leafNode(hub)
        let root = parentNode([child], hub)

        _ = root.children // force materialization (seeds child.parent)

        XCTAssertNil(root.parent)
        XCTAssertTrue(child.parent === root)
    }

    /// HIER-003 — depth derivation: root 0, child 1, grandchild 2.
    func testHier003DepthDerivation() {
        let hub = MessageHub()
        let grandchild = leafNode(hub)
        let child = parentNode([grandchild], hub)
        let root = parentNode([child], hub)

        _ = root.children
        _ = child.children

        XCTAssertEqual(root.depth, 0)
        XCTAssertEqual(child.depth, 1)
        XCTAssertEqual(grandchild.depth, 2)
    }

    /// HIER-004 — path returns a root-first snapshot and is identity-stable on
    /// re-read (the cached array yields the same element references). Swift
    /// arrays are value types, so the contract is element identity, not array
    /// reference identity.
    func testHier004PathCachedIdentityStable() {
        let hub = MessageHub()
        let grandchild = leafNode(hub)
        let child = parentNode([grandchild], hub)
        let root = parentNode([child], hub)

        _ = root.children
        _ = child.children

        let path = grandchild.path
        XCTAssertEqual(path.count, 3)
        XCTAssertTrue(path[0] === root)
        XCTAssertTrue(path[1] === child)
        XCTAssertTrue(path[2] === grandchild)

        // Re-read returns the same cached elements.
        let path2 = grandchild.path
        XCTAssertEqual(path2.count, 3)
        XCTAssertTrue(path2[0] === root)
        XCTAssertTrue(path2[1] === child)
        XCTAssertTrue(path2[2] === grandchild)
    }

    /// HIER-005 — isLeaf / isRoot derivation matches parent/children state.
    func testHier005IsLeafIsRoot() {
        let hub = MessageHub()
        let leaf = leafNode(hub)
        let root = parentNode([leaf], hub)

        _ = root.children

        XCTAssertTrue(root.isRoot)
        XCTAssertFalse(root.isLeaf)
        XCTAssertFalse(leaf.isRoot)
        XCTAssertTrue(leaf.isLeaf)
    }

    /// HIER-006 — isFirst / isLast position predicates; both false for the root.
    func testHier006IsFirstIsLast() {
        let hub = MessageHub()
        let c1 = leafNode(hub)
        let c2 = leafNode(hub)
        let c3 = leafNode(hub)
        let root = parentNode([c1, c2, c3], hub)

        _ = root.children

        XCTAssertTrue(c1.isFirst)
        XCTAssertFalse(c1.isLast)
        XCTAssertFalse(c2.isFirst)
        XCTAssertFalse(c2.isLast)
        XCTAssertFalse(c3.isFirst)
        XCTAssertTrue(c3.isLast)

        // Root has no parent → both predicates false.
        XCTAssertFalse(root.isFirst)
        XCTAssertFalse(root.isLast)
    }
}
