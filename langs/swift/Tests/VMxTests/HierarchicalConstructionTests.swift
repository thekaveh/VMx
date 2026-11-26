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
// module); this target is CI-verified only (`swift.yml` on macos-15).
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

/// A node whose `_onConstruct()` runs an optional hook after the eager walk,
/// so a test can act inside a child's construct hook. `deferredChildren` is
/// walked after the hook, so the node's construct can wait on a background
/// child (spec/02 §6.1).
private final class HookNode: HierarchicalVM<MyModel, HookNode> {
    var onConstruct: (() -> Void)?
    var deferredChildren: [ComponentVMBase] = []

    override func _onConstruct() throws {
        try super._onConstruct()
        onConstruct?()
        if !deferredChildren.isEmpty {
            try _transitionChildren(deferredChildren, construct: true)
        }
    }
}

/// Runs queued foreground and background work until none is left, as the
/// `ManualDispatcher` tests in `BackgroundChildLifecycleTests` do.
private func pump(_ dispatcher: ManualDispatcher) {
    for _ in 0..<10 {
        dispatcher.flushBackground()
        dispatcher.flushForeground()
    }
}

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

    // ── Eager construction and a disposed child ──────────────────────────────

    /// HIER-045 — An eager parent's `construct()` skips a child that was disposed,
    /// as the child-transition walk does in the other flavors (spec/18 §3,
    /// ADR-0258). The parent's later `construct()` succeeds, and no lifecycle
    /// operation reaches the disposed child.
    func testEagerConstructSkipsDisposedChild() throws {
        let hub = MessageHub()
        let a = MyNode(model: MyModel(value: "a"), childrenFactory: { _ in [] },
                       hub: hub, dispatcher: ImmediateDispatcher.INSTANCE, name: "a")
        let b = MyNode(model: MyModel(value: "b"), childrenFactory: { _ in [] },
                       hub: hub, dispatcher: ImmediateDispatcher.INSTANCE, name: "b")
        let root = MyNode(model: MyModel(value: "root"), childrenFactory: { _ in [a, b] },
                          hub: hub, dispatcher: ImmediateDispatcher.INSTANCE, name: "root",
                          eagerChildren: true)

        var started: [String] = []
        root.childStartProbeForTesting = { started.append($0.name) }

        try root.construct()
        a.dispose()
        try root.destruct()
        // The walk must reach the live sibling after the disposed one. The old
        // loop stops at `a` and leaves `b` destructed.
        try b.destruct()
        started.removeAll()

        XCTAssertNoThrow(try root.construct())
        XCTAssertEqual(root.status, .constructed)
        XCTAssertEqual(a.status, .disposed)
        XCTAssertEqual(b.status, .constructed)
        // Call spy: the walk starts only the live child, never the disposed one.
        XCTAssertEqual(started, ["b"])
    }

    /// HIER-045 — `reconstruct()` of an eager parent also skips a disposed child:
    /// its destruct phase and its construct phase both complete (spec/18 §3,
    /// ADR-0258).
    func testEagerReconstructSkipsDisposedChild() throws {
        let hub = MessageHub()
        let a = MyNode(model: MyModel(value: "a"), childrenFactory: { _ in [] },
                       hub: hub, dispatcher: ImmediateDispatcher.INSTANCE, name: "a")
        let b = MyNode(model: MyModel(value: "b"), childrenFactory: { _ in [] },
                       hub: hub, dispatcher: ImmediateDispatcher.INSTANCE, name: "b")
        let root = MyNode(model: MyModel(value: "root"), childrenFactory: { _ in [a, b] },
                          hub: hub, dispatcher: ImmediateDispatcher.INSTANCE, name: "root",
                          eagerChildren: true)

        var started: [String] = []
        root.childStartProbeForTesting = { started.append($0.name) }

        try root.construct()
        a.dispose()
        // As in the construct test: the walk must reach `b` past the disposed `a`.
        try b.destruct()
        started.removeAll()

        XCTAssertNoThrow(try root.reconstruct())
        XCTAssertEqual(root.status, .constructed)
        XCTAssertEqual(a.status, .disposed)
        XCTAssertEqual(b.status, .constructed)
        XCTAssertEqual(started, ["b"])
    }

    /// A child's construct hook that disposes the eager parent stops the walk:
    /// the parent ends `.disposed`, and no later sibling starts (LIFE-015,
    /// spec/02 §6 "a disposed owner starts no further child").
    func testEagerConstructStopsWhenChildHookDisposesParent() throws {
        let hub = MessageHub()
        var parent: HookNode?
        let a = HookNode(model: MyModel(value: "a"), childrenFactory: { _ in [] },
                         hub: hub, dispatcher: ImmediateDispatcher.INSTANCE, name: "a")
        a.onConstruct = { parent?.dispose() }
        let b = HookNode(model: MyModel(value: "b"), childrenFactory: { _ in [] },
                         hub: hub, dispatcher: ImmediateDispatcher.INSTANCE, name: "b")
        let root = HookNode(model: MyModel(value: "root"), childrenFactory: { _ in [a, b] },
                            hub: hub, dispatcher: ImmediateDispatcher.INSTANCE, name: "root",
                            eagerChildren: true)
        parent = root

        try root.construct()

        XCTAssertEqual(root.status, .disposed)
        XCTAssertEqual(b.status, .destructed, "no sibling starts after the parent is disposed")
    }

    /// An eager parent reaches `.constructed` only after each child has reached
    /// `.constructed` (spec/18 §3). A child whose construct defers through a
    /// background grandchild stays `.constructing`, so the parent waits for it.
    /// The old loop reported the parent `.constructed` at that point.
    func testEagerConstructWaitsForChildThatDefersItsConstruct() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let grandchild = try ComponentVM.builder()
            .name("grandchild")
            .services(hub: hub, dispatcher: dispatcher)
            .background(true)
            .build()
        let child = HookNode(model: MyModel(value: "child"), childrenFactory: { _ in [] },
                             hub: hub, dispatcher: dispatcher, name: "child")
        child.deferredChildren = [grandchild]
        let root = HookNode(model: MyModel(value: "root"), childrenFactory: { _ in [child] },
                            hub: hub, dispatcher: dispatcher, name: "root",
                            eagerChildren: true)

        try root.construct()
        XCTAssertEqual(child.status, .constructing)
        XCTAssertEqual(root.status, .constructing, "the parent waits for the child that defers")

        pump(dispatcher)
        XCTAssertEqual(grandchild.status, .constructed)
        XCTAssertEqual(child.status, .constructed)
        XCTAssertEqual(root.status, .constructed)
    }

    /// A child already `.constructing` is joined by an eager parent's construct:
    /// the walk does not start it again, and the parent waits for it. The old
    /// loop threw "Cannot construct from state Constructing."
    func testEagerConstructJoinsChildAlreadyConstructing() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let grandchild = try ComponentVM.builder()
            .name("grandchild")
            .services(hub: hub, dispatcher: dispatcher)
            .background(true)
            .build()
        let child = HookNode(model: MyModel(value: "child"), childrenFactory: { _ in [] },
                             hub: hub, dispatcher: dispatcher, name: "child")
        child.deferredChildren = [grandchild]
        let root = HookNode(model: MyModel(value: "root"), childrenFactory: { _ in [child] },
                            hub: hub, dispatcher: dispatcher, name: "root",
                            eagerChildren: true)

        try child.construct()
        XCTAssertEqual(child.status, .constructing)

        XCTAssertNoThrow(try root.construct())
        XCTAssertEqual(root.status, .constructing, "the parent waits for the child it joined")

        pump(dispatcher)
        XCTAssertEqual(child.status, .constructed)
        XCTAssertEqual(root.status, .constructed)
    }

    /// A factory that lists its own node is rejected by `tryChildren()` before
    /// `tryChildren()` rejects a factory that lists its own node, and reports
    /// `HierarchyError.invalidFactoryOutput`. For the root, the rejection comes
    /// before the walk starts. For an inner node that lists itself, the
    /// rejection happens inside that node's construct, after the outer walk has
    /// started, and the outer walk rolls back with that error.
    func testEagerConstructRejectsFactoryThatListsItsOwnNode() throws {
        let hub = MessageHub()
        let root = MyNode(model: MyModel(value: "root"), childrenFactory: { parent in [parent] },
                          hub: hub, dispatcher: ImmediateDispatcher.INSTANCE, name: "root",
                          eagerChildren: true)
        XCTAssertThrowsError(try root.construct()) { error in
            XCTAssertEqual(error as? HierarchyError, .invalidFactoryOutput)
        }
        XCTAssertEqual(root.status, .destructed)

        let inner = MyNode(model: MyModel(value: "inner"), childrenFactory: { parent in [parent] },
                           hub: hub, dispatcher: ImmediateDispatcher.INSTANCE, name: "inner",
                           eagerChildren: true)
        let outer = MyNode(model: MyModel(value: "outer"), childrenFactory: { _ in [inner] },
                           hub: hub, dispatcher: ImmediateDispatcher.INSTANCE, name: "outer",
                           eagerChildren: true)
        XCTAssertThrowsError(try outer.construct()) { error in
            XCTAssertEqual(error as? HierarchyError, .invalidFactoryOutput)
        }
        XCTAssertEqual(inner.status, .destructed)
        XCTAssertEqual(outer.status, .destructed)
    }

    /// A child defers its construct through a background grandchild, and that
    /// grandchild's construct then fails. The child rolls back, and so does the
    /// eager parent, which had been waiting for it: both end `.destructed`.
    /// The old loop left the parent `.constructed` with the child `.destructed`.
    func testEagerConstructRollsBackWhenDeferredChildFails() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let grandchild = try ComponentVM.builder()
            .name("grandchild")
            .services(hub: hub, dispatcher: dispatcher)
            .background(true)
            .onConstruct { throw ConstructBoom() }
            .build()
        let child = HookNode(model: MyModel(value: "child"), childrenFactory: { _ in [] },
                             hub: hub, dispatcher: dispatcher, name: "child")
        child.deferredChildren = [grandchild]
        let root = HookNode(model: MyModel(value: "root"), childrenFactory: { _ in [child] },
                            hub: hub, dispatcher: dispatcher, name: "root",
                            eagerChildren: true)

        try root.construct()
        XCTAssertEqual(child.status, .constructing)

        pump(dispatcher)
        XCTAssertEqual(child.status, .destructed)
        XCTAssertEqual(root.status, .destructed, "the parent rolls back with the failed child")
    }
}

private struct ConstructBoom: Error {}
