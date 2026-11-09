//
// HierarchicalDisposedNodeTests.swift — a disposed node's child list is
// frozen (spec/18 §7.1, ADR-0190).
//
// Claimed IDs: HIER-041.
//
import Combine
import XCTest
@testable import VMx

private struct DisposedNodeModel {
    let key: String
    let parentKey: String?
}

private final class DisposedNode: HierarchicalVM<DisposedNodeModel, DisposedNode> {}

/// Records the tree and property messages one hub delivers.
private final class TreeMessageRecorder {
    private(set) var messages: [any Message] = []
    private var token: AnyCancellable?

    init(_ hub: MessageHub) {
        token = hub.subscribe { [weak self] message in
            if message is TreeStructureChangedMessage || message is PropertyChangedMessage {
                self?.messages.append(message)
            }
        }
    }

    func childrenChanges(from sender: AnyObject) -> Int {
        messages.filter {
            guard let changed = $0 as? PropertyChangedMessage else { return false }
            return changed.senderObject === sender && changed.propertyName == "children"
        }.count
    }

    func stop() {
        token?.cancel()
    }
}

final class HierarchicalDisposedNodeTests: XCTestCase {

    // ── Helpers ──────────────────────────────────────────────────────────

    private func node(
        _ hub: MessageHub,
        _ key: String,
        parent: String? = nil,
        children: @escaping (DisposedNode) -> [DisposedNode] = { _ in [] }
    ) -> DisposedNode {
        DisposedNode(
            model: DisposedNodeModel(key: key, parentKey: parent),
            childrenFactory: children,
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            name: key
        )
    }

    private func attach(
        _ receiver: DisposedNode,
        _ items: [DisposedNode],
        policy: MissingParentPolicy = .park
    ) -> BatchAttachResult<DisposedNode> {
        receiver.attachMany(
            items,
            keyOf: { $0.model.key },
            parentKeyOf: { $0.model.parentKey },
            onMissingParent: policy
        )
    }

    private func assertDisposedFailure(
        _ result: Result<Void, HierarchyError>,
        _ call: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        guard case .failure(.disposed) = result else {
            return XCTFail("\(call) must return .failure(.disposed)", file: file, line: line)
        }
    }

    private func assertDisposedThrow(
        _ call: String,
        file: StaticString = #filePath,
        line: UInt = #line,
        _ body: () throws -> Void
    ) {
        XCTAssertThrowsError(try body(), "\(call) must throw", file: file, line: line) { error in
            guard case HierarchyError.disposed = error else {
                return XCTFail("\(call) threw \(error), not .disposed", file: file, line: line)
            }
        }
    }

    /// A constructed tree `r → [a → [aa], b]` with every child list
    /// materialized, plus a detached node `d`.
    private struct Tree {
        let hub: MessageHub
        let r: DisposedNode
        let a: DisposedNode
        let b: DisposedNode
        let aa: DisposedNode
        let d: DisposedNode
    }

    private func makeTree() throws -> Tree {
        let hub = MessageHub()
        let aa = node(hub, "aa", parent: "a")
        let a = node(hub, "a") { _ in [aa] }
        let b = node(hub, "b")
        let r = node(hub, "r") { _ in [a, b] }
        let d = node(hub, "d", parent: "a")
        try r.construct()
        try a.construct()
        _ = r.children
        _ = a.children
        _ = b.children
        _ = aa.children
        return Tree(hub: hub, r: r, a: a, b: b, aa: aa, d: d)
    }

    // ── HIER-041 ─────────────────────────────────────────────────────────

    /// HIER-041 — every structural call on a disposed node refuses, also a
    /// call that would do nothing, and changes or publishes nothing.
    func testHIER041DisposedNodeRefusesEveryStructuralCall() throws {
        let tree = try makeTree()
        let (a, aa, d) = (tree.a, tree.aa, tree.d)
        a.dispose()
        XCTAssertEqual(a.status, .disposed)
        let recorder = TreeMessageRecorder(tree.hub)
        defer { recorder.stop() }

        assertDisposedFailure(a.addChild(d), "addChild(d)")
        assertDisposedFailure(a.removeChild(aa), "removeChild(aa)")
        assertDisposedThrow("reparentChild(d)") { try a.reparentChild(d) }
        assertDisposedFailure(a.addChild(aa), "addChild(member)")
        assertDisposedFailure(a.removeChild(d), "removeChild(non-member)")
        a.invalidateChildren()
        a.invalidateSubtree()
        let batch = attach(a, [d])

        XCTAssertTrue(batch.added.isEmpty)
        XCTAssertTrue(batch.orphans.isEmpty)
        XCTAssertEqual(batch.rejections.map(\.reason), [.attachmentFailed])
        XCTAssertTrue(batch.rejections.first?.item === d)
        XCTAssertEqual(a.children.map(\.name), ["aa"])
        XCTAssertTrue(aa.parent === a)
        XCTAssertNil(d.parent)
        XCTAssertEqual(tree.r.parkedAttachCount, 0)
        XCTAssertTrue(recorder.messages.isEmpty, "a refused call publishes nothing")
    }

    /// HIER-041 — a live node cannot take a child out of a disposed parent.
    func testHIER041TransferOutOfDisposedParentRefuses() throws {
        let tree = try makeTree()
        let (a, b, aa) = (tree.a, tree.b, tree.aa)
        a.dispose()
        let recorder = TreeMessageRecorder(tree.hub)
        defer { recorder.stop() }

        assertDisposedFailure(b.addChild(aa), "b.addChild(aa)")
        assertDisposedThrow("b.reparentChild(aa)") { try b.reparentChild(aa) }

        XCTAssertTrue(aa.parent === a)
        XCTAssertEqual(a.children.map(\.name), ["aa"])
        XCTAssertTrue(b.children.isEmpty)
        XCTAssertTrue(recorder.messages.isEmpty)
    }

    /// HIER-041 — on a live root, a candidate under a disposed parent gets
    /// `attachmentFailed`; it is neither an orphan nor parked.
    func testHIER041AttachManyRejectsCandidateUnderDisposedParent() throws {
        let tree = try makeTree()
        let (r, a, d) = (tree.r, tree.a, tree.d)
        a.dispose()

        let result = attach(r, [d])

        XCTAssertTrue(result.added.isEmpty)
        XCTAssertTrue(result.orphans.isEmpty)
        XCTAssertEqual(result.rejections.map(\.reason), [.attachmentFailed])
        XCTAssertEqual(r.parkedAttachCount, 0)
        XCTAssertNil(d.parent)
        XCTAssertEqual(a.children.map(\.name), ["aa"])
    }

    /// HIER-041 — `invalidateSubtree` on a live node skips a disposed
    /// descendant's own drop and still visits that node's children.
    func testHIER041InvalidateSubtreeSkipsDisposedDescendant() throws {
        let tree = try makeTree()
        let (r, a, aa) = (tree.r, tree.a, tree.aa)
        a.dispose()
        let recorder = TreeMessageRecorder(tree.hub)
        defer { recorder.stop() }

        r.invalidateSubtree()

        XCTAssertEqual(recorder.childrenChanges(from: aa), 1, "aa drops its cache")
        XCTAssertEqual(recorder.childrenChanges(from: r), 1, "r drops its cache")
        XCTAssertEqual(recorder.childrenChanges(from: a), 0, "a keeps its cache")
        XCTAssertTrue(aa.parent === a)
        XCTAssertEqual(a.children.map(\.name), ["aa"])
    }

    /// HIER-041 — `attachMany` on a live node refuses when the structural
    /// root is disposed; nothing is parked.
    func testHIER041AttachManyRefusesUnderDisposedRoot() throws {
        let hub = MessageHub()
        let c = node(hub, "c")
        let root = node(hub, "root") { _ in [c] }
        _ = root.children
        root.dispose()
        let item = node(hub, "item", parent: "missing")

        let result = attach(c, [item], policy: .park)

        XCTAssertTrue(result.added.isEmpty)
        XCTAssertTrue(result.orphans.isEmpty)
        XCTAssertEqual(result.rejections.map(\.reason), [.attachmentFailed])
        XCTAssertEqual(c.parkedAttachCount, 0)
        XCTAssertNil(item.parent)
    }

    /// HIER-041 — a live node can still remove and invalidate a disposed child.
    func testHIER041LiveNodeStillManagesDisposedChild() throws {
        let tree = try makeTree()
        let (r, a) = (tree.r, tree.a)
        a.dispose()

        guard case .success = r.removeChild(a) else {
            return XCTFail("a live node can remove a disposed child")
        }
        XCTAssertNil(a.parent)
        XCTAssertEqual(r.children.map(\.name), ["b"])
    }
}
