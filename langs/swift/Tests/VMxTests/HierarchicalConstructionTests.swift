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
    /// a three-level tree (root → 2 children → 2 grandchildren each) built
    /// with eagerChildren on every node. The factory is not invoked before
    /// construct(); after root.construct() completes, the factory has run
    /// exactly once for every node in the tree and every descendant is
    /// materialized and Constructed without any explicit `children` access.
    func testHier008EagerChildLoading() throws {
        let hub = MessageHub()
        var invocations: [String: Int] = [:]
        var all: [MyNode] = []

        func makeNode(_ value: String, depth: Int) -> MyNode {
            let node = MyNode(
                model: MyModel(value: value),
                childrenFactory: { parent in
                    invocations[parent.model.value, default: 0] += 1
                    guard depth < 2 else { return [] }
                    return [
                        makeNode("\(value).0", depth: depth + 1),
                        makeNode("\(value).1", depth: depth + 1),
                    ]
                },
                hub: hub,
                dispatcher: ImmediateDispatcher.INSTANCE,
                eagerChildren: true
            )
            all.append(node)
            return node
        }

        let root = makeNode("root", depth: 0)

        // eagerChildren does NOT trigger the factory before construct().
        XCTAssertTrue(invocations.isEmpty)

        try root.construct()

        // root + 2 children + 4 grandchildren = 7 nodes, each factory ran once.
        XCTAssertEqual(all.count, 7)
        XCTAssertEqual(invocations.count, 7)
        for node in all {
            XCTAssertEqual(invocations[node.model.value], 1,
                "factory must run exactly once for \(node.model.value)")
            XCTAssertEqual(node.status, .constructed,
                "\(node.model.value) must be Constructed")
        }
        let expected: Set<String> = [
            "root", "root.0", "root.1",
            "root.0.0", "root.0.1", "root.1.0", "root.1.1",
        ]
        XCTAssertEqual(Set(invocations.keys), expected)

        // Accessing children afterwards returns the cached materialization.
        XCTAssertEqual(root.children.count, 2)
        XCTAssertEqual(root.children[0].children.count, 2)
        XCTAssertEqual(invocations.values.reduce(0, +), 7)
    }

    /// Eager construct reports invalid factory output as a thrown error and
    /// rolls the parent back (LIFE-014), instead of trapping.
    func testEagerConstructThrowsOnInvalidFactoryOutput() throws {
        let hub = MessageHub()
        let shared = MyNode(
            model: MyModel(value: "shared"),
            childrenFactory: { _ in [] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
        let root = MyNode(
            model: MyModel(value: "root"),
            childrenFactory: { _ in [shared, shared] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            eagerChildren: true
        )

        XCTAssertThrowsError(try root.construct()) { error in
            XCTAssertEqual(error as? HierarchyError, .invalidFactoryOutput)
        }
        XCTAssertNotEqual(root.status, .constructed)
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
