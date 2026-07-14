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
// module); this target is CI-verified only (`swift.yml` on macos-latest).
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
        var structureCount = 0
        var bag = Set<AnyCancellable>()
        hub.messages.sink { msg in
            if msg is TreeStructureChangedMessage { structureCount += 1 }
        }.store(in: &bag)

        let leaf = makeNode(hub, name: "leaf")
        let mid = makeNode(hub, name: "mid", children: [leaf])
        let root = makeNode(hub, name: "root", children: [mid])

        // Materialize so parent backpointers are wired.
        _ = root.children
        _ = mid.children
        _ = leaf.path

        // Self-reparenting must throw.
        XCTAssertThrowsError(try leaf.reparentChild(leaf),
            "reparentChild(self) should throw HierarchyError.invalidReparent")

        // Reparenting an ancestor under its own descendant must throw.
        XCTAssertThrowsError(try leaf.reparentChild(root),
            "reparentChild(ancestor) should throw HierarchyError.invalidReparent")

        if case .success = leaf.addChild(leaf) {
            XCTFail("addChild(self) should return HierarchyError.invalidReparent")
        }
        if case .success = leaf.addChild(root) {
            XCTFail("addChild(ancestor) should return HierarchyError.invalidReparent")
        }

        // Tree structure must be completely unchanged.
        XCTAssertNil(root.parent, "root.parent should remain nil")
        XCTAssertTrue(mid.parent === root, "mid.parent should still be root")
        XCTAssertTrue(leaf.parent === mid, "leaf.parent should still be mid")
        XCTAssertEqual(leaf.depth, 2, "leaf.depth should remain 2")

        // No structure messages should have been published.
        XCTAssertEqual(structureCount, 0, "No TreeStructureChangedMessages expected on guard rejection")

        let newParent = makeNode(hub, name: "newParent")
        guard case .success = newParent.addChild(leaf) else {
            return XCTFail("cross-parent addChild should succeed")
        }
        XCTAssertTrue(mid.children.isEmpty)
        XCTAssertEqual(newParent.children.count, 1)
        XCTAssertTrue(newParent.children.first === leaf)
        XCTAssertTrue(leaf.parent === newParent)
        XCTAssertEqual(structureCount, 1)
    }
}
