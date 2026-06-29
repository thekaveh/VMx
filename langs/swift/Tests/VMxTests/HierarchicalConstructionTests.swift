//
// HierarchicalVM child loading & depth-first construction conformance tests.
//
// Claimed IDs: HIER-007 (lazy factory — not invoked until children first
// accessed, then cached), HIER-008 (eagerChildren — factory runs at
// construct() time, not before), HIER-009 (depth-first construction order —
// deepest node reaches Constructed before its ancestors).
//
// Ported from the TypeScript HIER-007..009 blocks
// (tests/conformance/hier-001-to-014-hierarchical-vm.test.ts).
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import Combine
import XCTest
@testable import VMx

// ── Concrete CRTP node + model used across the suite ────────────────────────

private struct MyModel {
    let value: String
}

/// Concrete node satisfying the recursive generic constraint
/// `HierarchicalVM<MyModel, MyNode>` — the canonical CRTP shape.
private final class MyNode: HierarchicalVM<MyModel, MyNode> {}

final class HierarchicalConstructionTests: XCTestCase {

    // ── Tests ────────────────────────────────────────────────────────────────

    /// HIER-007 — lazy child loading: factory invocation counter stays 0 until
    /// children is first accessed, then stays at 1 on subsequent accesses
    /// (factory not re-run after the first materialization).
    func testHier007LazyChildLoading() {
        let hub = MessageHub()
        var factoryCallCount = 0

        let node = MyNode(
            model: MyModel(value: "root"),
            childrenFactory: { _ in
                factoryCallCount += 1
                return [MyNode(
                    model: MyModel(value: "child"),
                    childrenFactory: { _ in [] },
                    hub: hub,
                    dispatcher: ImmediateDispatcher.INSTANCE
                )]
            },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )

        // Factory must not be called before first access.
        XCTAssertEqual(factoryCallCount, 0)

        _ = node.children
        XCTAssertEqual(factoryCallCount, 1)

        // Second access returns the cached result — factory not called again.
        _ = node.children
        XCTAssertEqual(factoryCallCount, 1)
    }

    /// HIER-008 — eager child loading via eagerChildren constructor option:
    /// factory is not invoked until construct() is called, at which point the
    /// children are materialized and the tree is available.
    func testHier008EagerChildLoading() throws {
        let hub = MessageHub()
        var factoryInvoked = false
        let leaf = MyNode(
            model: MyModel(value: "leaf"),
            childrenFactory: { _ in [] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )

        let root = MyNode(
            model: MyModel(value: "root"),
            childrenFactory: { _ in
                factoryInvoked = true
                return [leaf]
            },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            eagerChildren: true
        )

        // eagerChildren does NOT trigger factory before construct().
        XCTAssertFalse(factoryInvoked)

        try root.construct()

        // After construct(), factory has run and children contains the leaf.
        XCTAssertTrue(factoryInvoked)
        XCTAssertTrue(root.children.contains(where: { $0 === leaf }))
    }

    /// HIER-009 — depth-first construction order: deepest node reaches
    /// Constructed first. Subscribes to the hub before constructing a three-level
    /// eager tree (root → child → grandchild) and asserts the order in which
    /// ConstructionStatusChangedMessage(.constructed) is emitted.
    func testHier009DepthFirstConstructionOrder() throws {
        let hub = MessageHub()
        var order: [String] = []

        // Collect the senderName each time a .constructed status is published.
        let cancel = hub.messages
            .compactMap { msg -> String? in
                guard let m = msg as? ConstructionStatusChangedMessage,
                      m.status == .constructed else { return nil }
                return m.senderName
            }
            .sink { order.append($0) }

        let grandchild = MyNode(
            model: MyModel(value: "grandchild"),
            childrenFactory: { _ in [] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            name: "grandchild",
            eagerChildren: true
        )
        let child = MyNode(
            model: MyModel(value: "child"),
            childrenFactory: { _ in [grandchild] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            name: "child",
            eagerChildren: true
        )
        let root = MyNode(
            model: MyModel(value: "root"),
            childrenFactory: { _ in [child] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            name: "root",
            eagerChildren: true
        )

        try root.construct()

        XCTAssertEqual(order, ["grandchild", "child", "root"])
        cancel.cancel()
    }
}
