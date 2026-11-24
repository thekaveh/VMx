//
// HierarchicalVM structural mutation + hub notifications conformance tests.
//
// Claimed IDs: HIER-010 (addChild → PropertyChangedMessage("parent") with
// sender === child), HIER-011 (add/remove/reparent → correct
// TreeStructureChangedMessage shapes), HIER-018 (reparentChild rejects self-
// and ancestor-reparenting, tree unchanged, 0 TreeStructureChangedMessages).
//
// Ported from the TypeScript HIER-010/011 blocks
// (tests/conformance/hier-001-to-014-hierarchical-vm.test.ts) and the
// HIER-018 block (hier-018-reparent-guard.test.ts).
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-15).
//
import XCTest
import Combine
@testable import VMx

// ── Concrete CRTP node + model ───────────────────────────────────────────────

private struct MyModel {
    let value: String
}

private final class MyNode: HierarchicalVM<MyModel, MyNode> {}

// ── Test class ───────────────────────────────────────────────────────────────

final class HierarchicalMutationTests: XCTestCase {

    // ── Helpers ──────────────────────────────────────────────────────────

    private func makeNode(
        _ hub: MessageHubProtocol,
        name: String = "",
        children: [MyNode] = []
    ) -> MyNode {
        MyNode(
            model: MyModel(value: "m"),
            childrenFactory: { _ in children },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            name: name
        )
    }

    // ── Tests ────────────────────────────────────────────────────────────

    /// Supplementary path-cache check (not HIER-010, which covers the parent
    /// PropertyChangedMessage): a cached path does not keep its nodes alive.
    func testHier010CachedPathDoesNotRetainNodes() {
        let hub = MessageHub()
        weak var weakRoot: MyNode?
        weak var weakChild: MyNode?
        do {
            let root = makeNode(hub, name: "root")
            let child = makeNode(hub, name: "child")
            _ = root.addChild(child)
            XCTAssertEqual(child.path.count, 2)
            XCTAssertEqual(root.path.count, 1)
            weakRoot = root
            weakChild = child
        }

        XCTAssertNil(weakChild, "the child's cached path must not retain it")
        XCTAssertNil(weakRoot, "the root's cached path must not retain it")
    }

    /// HIER-010 — addChild emits PropertyChangedMessage("parent") with
    /// sender === child.
    func testHier010AddChildEmitsPropertyChanged() {
        let hub = MessageHub()
        var propMsgs: [PropertyChangedMessage] = []
        var bag = Set<AnyCancellable>()
        hub.messages.sink { msg in
            if let m = msg as? PropertyChangedMessage { propMsgs.append(m) }
        }.store(in: &bag)

        let child = makeNode(hub, name: "child")
        let parent = makeNode(hub, name: "parent")
        parent.addChild(child)

        let parentMsg = propMsgs.first(where: {
            $0.propertyName == "parent" && $0.sender === child
        })
        XCTAssertNotNil(
            parentMsg,
            "Expected a PropertyChangedMessage with propertyName 'parent' and sender === child"
        )
    }

    /// HIER-011 — addChild / removeChild / reparentChild each emit the correct
    /// TreeStructureChangedMessage shape.
    func testHier011TreeStructureChangedMessages() throws {
        let hub = MessageHub()
        var treeMsgs: [TreeStructureChangedMessage] = []
        var bag = Set<AnyCancellable>()
        hub.messages.sink { msg in
            if let m = msg as? TreeStructureChangedMessage { treeMsgs.append(m) }
        }.store(in: &bag)

        let parent = makeNode(hub, name: "parent")
        let child = makeNode(hub, name: "child")

        // ── Add ──────────────────────────────────────────────────────────
        parent.addChild(child)
        XCTAssertEqual(treeMsgs.count, 1, "addChild should emit exactly 1 structure message")
        let addMsg = try XCTUnwrap(treeMsgs.first)
        XCTAssertEqual(addMsg.change, .added)
        XCTAssertTrue(addMsg.sender === parent, "addMsg.sender should be parent")
        XCTAssertTrue(addMsg.affected === child, "addMsg.affected should be child")
        XCTAssertEqual(addMsg.index, 0)

        treeMsgs.removeAll()

        // ── Remove ───────────────────────────────────────────────────────
        parent.removeChild(child)
        XCTAssertEqual(treeMsgs.count, 1, "removeChild should emit exactly 1 structure message")
        let remMsg = try XCTUnwrap(treeMsgs.first)
        XCTAssertEqual(remMsg.change, .removed)
        XCTAssertEqual(remMsg.index, 0)

        treeMsgs.removeAll()

        // ── Reparent ─────────────────────────────────────────────────────
        parent.addChild(child)   // re-attach to parent
        treeMsgs.removeAll()

        let newParent = makeNode(hub, name: "newParent")
        try newParent.reparentChild(child)

        XCTAssertEqual(treeMsgs.count, 1, "reparentChild should emit exactly 1 structure message")
        let repMsg = try XCTUnwrap(treeMsgs.first)
        XCTAssertEqual(repMsg.change, .reparented)
        XCTAssertTrue(repMsg.sender === newParent, "repMsg.sender should be newParent")
        XCTAssertTrue(repMsg.affected === child, "repMsg.affected should be child")
        XCTAssertEqual(repMsg.index, -1)
    }

    /// HIER-018 — reparentChild rejects self- and ancestor-reparenting:
    /// throws, leaves the tree intact, and publishes 0 TreeStructureChangedMessages.
    func testHier018ReparentGuard() throws {
        let hub = MessageHub()
        var structureMessages: [TreeStructureChangedMessage] = []
        var bag = Set<AnyCancellable>()
        hub.messages.sink { msg in
            if let structure = msg as? TreeStructureChangedMessage { structureMessages.append(structure) }
        }.store(in: &bag)

        let leaf = makeNode(hub, name: "leaf")
        let mid = makeNode(hub, name: "mid", children: [leaf])
        let root = makeNode(hub, name: "root", children: [mid])

        // Materialize so parent backpointers are wired.
        _ = root.children
        _ = mid.children
        _ = leaf.path

        // Self-reparenting must throw HierarchyError.invalidReparent exactly.
        XCTAssertThrowsError(try leaf.reparentChild(leaf),
            "reparentChild(self) should throw HierarchyError.invalidReparent") { error in
            XCTAssertEqual(error as? HierarchyError, .invalidReparent)
        }

        // Reparenting an ancestor under its own descendant must throw the same error.
        XCTAssertThrowsError(try leaf.reparentChild(root),
            "reparentChild(ancestor) should throw HierarchyError.invalidReparent") { error in
            XCTAssertEqual(error as? HierarchyError, .invalidReparent)
        }

        assertInvalidReparent(leaf.addChild(leaf), "addChild(self)")
        assertInvalidReparent(leaf.addChild(root), "addChild(ancestor)")

        // Tree structure must be completely unchanged.
        XCTAssertNil(root.parent, "root.parent should remain nil")
        XCTAssertTrue(mid.parent === root, "mid.parent should still be root")
        XCTAssertTrue(leaf.parent === mid, "leaf.parent should still be mid")
        XCTAssertEqual(leaf.depth, 2, "leaf.depth should remain 2")

        // No structure messages should have been published.
        XCTAssertEqual(structureMessages.count, 0, "No TreeStructureChangedMessages expected on guard rejection")

        let newParent = makeNode(hub, name: "newParent")
        guard case .success = newParent.addChild(leaf) else {
            return XCTFail("cross-parent addChild should succeed")
        }
        XCTAssertTrue(mid.children.isEmpty)
        XCTAssertEqual(newParent.children.count, 1)
        XCTAssertTrue(newParent.children.first === leaf)
        XCTAssertTrue(leaf.parent === newParent)
        // The addChild transfer publishes exactly one message: Reparented, from newParent, for leaf.
        XCTAssertEqual(structureMessages.count, 1)
        let transfer = try XCTUnwrap(structureMessages.first)
        XCTAssertTrue(transfer.sender === newParent)
        XCTAssertTrue(transfer.affected === leaf)
        XCTAssertEqual(transfer.change, .reparented,
                       "HIER-018: the addChild transfer publishes Reparented, not Added")
    }

    /// Fails the test unless `result` is `.failure(.invalidReparent)`.
    private func assertInvalidReparent(_ result: Result<Void, HierarchyError>, _ label: String) {
        guard case .failure(let error) = result else {
            return XCTFail("\(label) should fail with HierarchyError.invalidReparent")
        }
        XCTAssertEqual(error, .invalidReparent, "\(label) error")
    }

    /// Runs `body` on its own thread and fails the test when it does not finish
    /// within `seconds`. A move that wrongly creates a children cycle makes the
    /// subtree restamp loop forever, so the watchdog turns that hang into a
    /// failure.
    /// `stackBytes` overrides the thread's stack size when it is positive. A body
    /// that releases a deep chain needs a larger stack than the default.
    private func runWatched(
        seconds: Double = 20,
        stackBytes: Int = 0,
        _ body: @escaping () throws -> Void
    ) {
        let finished = DispatchSemaphore(value: 0)
        let thread = Thread {
            do {
                try body()
            } catch {
                XCTFail("the body threw: \(error)")
            }
            finished.signal()
        }
        if stackBytes > 0 { thread.stackSize = stackBytes }
        thread.start()
        let result = finished.wait(timeout: .now() + seconds)
        XCTAssertEqual(result, .success, "the body finishes within \(seconds) s")
    }

    /// ADR-0248 R2 case (d): a parented node of the receiver's own tree is
    /// refused when it is an ancestor of the receiver, and the tree is unchanged.
    func testHier018RefusesAParentedAncestorInTheSameTree() {
        runWatched {
            let hub = MessageHub()
            let leaf = self.makeNode(hub, name: "leaf")
            let mid = self.makeNode(hub, name: "mid", children: [leaf])
            let root = self.makeNode(hub, name: "root", children: [mid])
            _ = root.children
            _ = mid.children

            self.assertInvalidReparent(leaf.addChild(mid), "addChild(parented ancestor)")
            XCTAssertThrowsError(try leaf.reparentChild(mid),
                "reparentChild(parented ancestor) should throw HierarchyError.invalidReparent") { error in
                XCTAssertEqual(error as? HierarchyError, .invalidReparent)
            }
            XCTAssertTrue(mid.parent === root, "mid.parent should remain root")
            XCTAssertTrue(leaf.parent === mid, "leaf.parent should remain mid")
        }
    }

    /// ADR-0248 R2 case (d), no cycle: a parented node of the same tree that is
    /// not an ancestor of the receiver transfers under it.
    func testHier018TransfersAParentedNodeWithinItsTree() {
        let hub = MessageHub()
        let b = makeNode(hub, name: "b")
        let a = makeNode(hub, name: "a", children: [b])
        let c = makeNode(hub, name: "c")
        let root = makeNode(hub, name: "root", children: [a, c])
        _ = root.children
        _ = a.children

        guard case .success = b.addChild(c) else {
            return XCTFail("moving a non-ancestor within one tree should succeed")
        }
        XCTAssertTrue(c.parent === b)
        XCTAssertEqual(root.children.map(\.name), ["a"])
        XCTAssertEqual(c.path.count, 4)
    }

    /// ADR-0248 R2 case (b): a parented node of another tree transfers, and its
    /// own subtree moves with it.
    func testHier018TransfersAParentedNodeFromAnotherTree() {
        let hub = MessageHub()
        let leaf = makeNode(hub, name: "leaf")
        let mid = makeNode(hub, name: "mid", children: [leaf])
        let oldRoot = makeNode(hub, name: "oldRoot", children: [mid])
        _ = oldRoot.children
        _ = mid.children

        let newRoot = makeNode(hub, name: "newRoot")
        guard case .success = newRoot.addChild(mid) else {
            return XCTFail("transferring a parented node from another tree should succeed")
        }
        XCTAssertTrue(mid.parent === newRoot)
        XCTAssertTrue(oldRoot.children.isEmpty)
        XCTAssertEqual(leaf.path.count, 3)
        XCTAssertTrue(leaf.path.first === newRoot)
    }

    // ── ADR-0249: cycle check after the stored root is released ──────────

    /// ADR-0249: a root released while its subtree is still held leaves the
    /// surviving subtree with a nil root link. The cycle check then walks the
    /// parent links to the topmost live ancestor, so that ancestor still cannot
    /// move under its own descendant. Without the walk, the move is accepted,
    /// a children cycle forms, and the subtree restamp never finishes.
    func testHier018CycleCheckSurvivesReleaseOfTheRoot() {
        runWatched {
            let hub = MessageHub()
            let leaf = self.makeNode(hub, name: "leaf")
            let mid = self.makeNode(hub, name: "mid", children: [leaf])
            weak var weakRoot: MyNode?
            do {
                let root = self.makeNode(hub, name: "root", children: [mid])
                _ = root.children
                _ = mid.children
                weakRoot = root
            }
            XCTAssertNil(weakRoot, "the root is released with no other reference")
            XCTAssertNil(mid.parent, "the surviving subtree has no parent")
            XCTAssertTrue(leaf.parent === mid, "leaf.parent should remain mid")

            self.assertInvalidReparent(leaf.addChild(mid), "addChild(surviving ancestor)")
            XCTAssertThrowsError(try leaf.reparentChild(mid),
                "reparentChild(surviving ancestor) should throw HierarchyError.invalidReparent") { error in
                XCTAssertEqual(error as? HierarchyError, .invalidReparent)
            }
            XCTAssertTrue(leaf.parent === mid, "leaf.parent should remain mid")
            XCTAssertNil(mid.parent)
        }
    }

    // ── ADR-0248 R2 cases (b) and (c): result checks under a deep receiver ──
    //
    // Cases (b) and (c) are O(1) shortcuts whose results equal the ancestor walk
    // they skip (ADR-0248 §2.2), so these tests check only the results. Their
    // cost is not a CI gate (ADR-0247 §2.7) and is measured outside CI.

    /// ADR-0248 R2 case (b): a parented node of another tree transfers under a
    /// deep receiver, and its old parent lets go of it.
    func testHier018CrossTreeTransferIntoDeepReceiver() {
        let hub = MessageHub()
        let (deepRoot, deepTail) = makeChain(hub, depth: 5_000)
        let leaf = makeNode(hub, name: "leaf")
        let owner = makeNode(hub, name: "owner", children: [leaf])
        _ = owner.children

        guard case .success = deepTail.addChild(leaf) else {
            return XCTFail("a parented node of another tree should transfer under a deep receiver")
        }
        XCTAssertTrue(leaf.parent === deepTail, "the transfer lands under the deep receiver")
        XCTAssertTrue(owner.children.isEmpty, "the old parent lets go of the transferred node")
        XCTAssertEqual(deepRoot.children.count, 1, "the deep chain keeps its one child")
        XCTAssertTrue(leaf.path.first === deepRoot, "the transferred node is under the deep root")
    }

    /// ADR-0248 R2 case (c): a parentless tree root is refused as a child of a
    /// node in its own deep chain, and the chain is unchanged. Only the result
    /// is checked. A wrongly accepted move would make a children cycle, so the
    /// body runs under the watchdog. It runs on a 16 MiB stack, because the
    /// 5,000-level chain is released on this thread.
    func testHier018RootCandidateRefusalUnderDeepReceiver() {
        runWatched(stackBytes: 16 * 1024 * 1024) {
            let hub = MessageHub()
            let (deepRoot, deepTail) = self.makeChain(hub, depth: 5_000)
            XCTAssertThrowsError(try deepTail.reparentChild(deepRoot),
                "reparentChild(tree root) should throw HierarchyError.invalidReparent") { error in
                XCTAssertEqual(error as? HierarchyError, .invalidReparent)
            }
            XCTAssertNil(deepRoot.parent, "a refused tree root stays a root")
            XCTAssertTrue(deepTail.path.first === deepRoot, "the deep chain is unchanged")
        }
    }

    // ── Chain helper ─────────────────────────────────────────────────────

    /// Builds a chain of `depth` edges with `addChild` and returns its root and
    /// tail. The caller keeps the root alive, or the chain loses its ancestors.
    private func makeChain(_ hub: MessageHubProtocol, depth: Int) -> (root: MyNode, tail: MyNode) {
        let root = makeNode(hub, name: "chain0")
        var tail = root
        for level in 1...depth {
            let next = makeNode(hub, name: "chain\(level)")
            _ = tail.addChild(next)
            tail = next
        }
        return (root, tail)
    }
}
