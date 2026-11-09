//
// HIER-042..044 — `attachMany` indexes the materialized subtree of a
// candidate (spec/18 §6, ADR-0212).
//
import XCTest
@testable import VMx

private struct SubtreeModel {
    let key: String
    let parentKey: String?
}

private final class SubtreeNode: HierarchicalVM<SubtreeModel, SubtreeNode> {}

final class HierarchicalBatchSubtreeIndexTests: XCTestCase {
    private func node(
        _ key: String,
        parent: String? = nil,
        factory: @escaping (SubtreeNode) -> [SubtreeNode] = { _ in [] }
    ) -> SubtreeNode {
        SubtreeNode(
            model: SubtreeModel(key: key, parentKey: parent),
            childrenFactory: factory,
            hub: MessageHub(),
            dispatcher: ImmediateDispatcher.INSTANCE,
            name: key
        )
    }

    private func attach(
        _ root: SubtreeNode,
        _ items: [SubtreeNode],
        policy: MissingParentPolicy = .park
    ) -> BatchAttachResult<SubtreeNode> {
        root.attachMany(
            items,
            keyOf: { $0.model.key },
            parentKeyOf: { $0.model.parentKey },
            onMissingParent: policy
        )
    }

    /// HIER-042 — a candidate attaches below a node of an attached subtree.
    func testHier042CandidateAttachesBelowAttachedSubtree() {
        let root = node("root")
        let p = node("p")
        let c = node("c")
        p.addChild(c)
        let x = node("x", parent: "c")

        let result = attach(root, [p, x])

        XCTAssertEqual(result.added.map(\.name), ["p", "x"])
        XCTAssertTrue(result.rejections.isEmpty)
        XCTAssertTrue(result.orphans.isEmpty)
        XCTAssertTrue(result.duplicates.isEmpty)
        XCTAssertEqual(root.children.map(\.name), ["p"])
        XCTAssertEqual(p.children.map(\.name), ["c"])
        XCTAssertTrue(c.children.first === x)
        XCTAssertEqual(x.path.map(\.name), ["root", "p", "c", "x"])
        XCTAssertEqual(root.parkedAttachCount, 0)
    }

    /// HIER-042 — a parent key that names the candidate's own descendant is a
    /// cycle, and reading subtree keys runs no children factory.
    func testHier042ParentKeyNamingOwnDescendantIsCycle() {
        var calls = 0
        let root = node("root")
        let q = node("q", parent: "d")
        let d = node("d") { _ in
            calls += 1
            return []
        }
        q.addChild(d)

        let result = attach(root, [q], policy: .park)

        XCTAssertEqual(calls, 0)
        XCTAssertTrue(result.added.isEmpty)
        XCTAssertTrue(result.orphans.isEmpty)
        XCTAssertEqual(result.rejections.count, 1)
        XCTAssertTrue(result.rejections.first?.item === q)
        XCTAssertEqual(result.rejections.first?.reason, .cycle)
        XCTAssertEqual(root.parkedAttachCount, 0)
        XCTAssertNil(q.parent)
    }

    /// HIER-043 — a descendant key in the index rejects the candidate.
    func testHier043DescendantKeyInIndexRejectsCandidate() {
        let root = node("root")
        let existing = node("c")
        root.addChild(existing)
        let p = node("p")
        let inner = node("c")
        p.addChild(inner)

        let result = attach(root, [p])

        XCTAssertTrue(result.added.isEmpty)
        XCTAssertEqual(result.duplicates.count, 1)
        XCTAssertTrue(result.duplicates.first === p)
        XCTAssertEqual(result.rejections.count, 1)
        XCTAssertEqual(result.rejections.first?.reason, .duplicateExistingKey)
        XCTAssertNil(p.parent)
        XCTAssertTrue(p.children.first === inner)
        XCTAssertEqual(root.children.count, 1)
        XCTAssertTrue(root.children.first === existing)
    }

    /// HIER-043 — a descendant key claimed first rejects a later candidate.
    func testHier043DescendantKeyClaimedFirstRejectsLaterCandidate() {
        let root = node("root")
        let p = node("p")
        let c = node("c")
        p.addChild(c)
        let c2 = node("c", parent: "p")

        let result = attach(root, [p, c2])

        XCTAssertEqual(result.added.count, 1)
        XCTAssertTrue(result.added.first === p)
        XCTAssertEqual(result.duplicates.count, 1)
        XCTAssertTrue(result.duplicates.first === c2)
        XCTAssertEqual(result.rejections.count, 1)
        XCTAssertEqual(result.rejections.first?.reason, .duplicateBatchKey)
        XCTAssertEqual(p.children.count, 1)
        XCTAssertTrue(p.children.first === c)
        XCTAssertNil(c2.parent)
    }

    /// HIER-043 — an earlier candidate key rejects a subtree that repeats it.
    func testHier043EarlierCandidateKeyRejectsRepeatingSubtree() {
        let root = node("root")
        let p = node("p")
        let c = node("c")
        p.addChild(c)
        let c2 = node("c", parent: "p")

        let result = attach(root, [c2, p])

        XCTAssertTrue(result.added.isEmpty)
        XCTAssertEqual(result.duplicates.count, 1)
        XCTAssertTrue(result.duplicates.first === p)
        XCTAssertEqual(result.orphans.count, 1)
        XCTAssertTrue(result.orphans.first === c2)
        XCTAssertEqual(result.rejections.count, 2)
        XCTAssertTrue(result.rejections.contains { $0.item === p && $0.reason == .duplicateBatchKey })
        XCTAssertTrue(result.rejections.contains { $0.item === c2 && $0.reason == .missingParent })
        XCTAssertNil(p.parent)
        XCTAssertNil(c2.parent)
        XCTAssertTrue(p.children.first === c)
    }

    /// HIER-043 — a node of an earlier candidate's subtree is rejected as
    /// `alreadyAttached` in either batch order and never as a duplicate.
    func testHier043NodeOfEarlierSubtreeIsAlreadyAttached() {
        for childFirst in [false, true] {
            let root = node("root")
            let p = node("p")
            let c = node("c")
            p.addChild(c)

            let result = attach(root, childFirst ? [c, p] : [p, c])

            XCTAssertEqual(result.added.count, 1, "childFirst: \(childFirst)")
            XCTAssertTrue(result.added.first === p)
            XCTAssertTrue(result.duplicates.isEmpty, "childFirst: \(childFirst)")
            XCTAssertEqual(result.rejections.count, 1)
            XCTAssertTrue(result.rejections.first?.item === c)
            XCTAssertEqual(result.rejections.first?.reason, .alreadyAttached)
            XCTAssertTrue(c.parent === p)
            XCTAssertEqual(p.children.count, 1)
            XCTAssertTrue(p.children.first === c)
        }
    }

    /// HIER-043 — a duplicate key inside one candidate's subtree rejects the
    /// candidate as `duplicateBatchKey`.
    func testHier043DuplicateKeyInsideOneSubtreeRejectsCandidate() {
        let root = node("root")
        let p = node("p")
        let d1 = node("d")
        let d2 = node("d")
        p.addChild(d1)
        p.addChild(d2)

        let result = attach(root, [p])

        XCTAssertTrue(result.added.isEmpty)
        XCTAssertEqual(result.duplicates.count, 1)
        XCTAssertTrue(result.duplicates.first === p)
        XCTAssertEqual(result.rejections.count, 1)
        XCTAssertTrue(result.rejections.first?.item === p)
        XCTAssertEqual(result.rejections.first?.reason, .duplicateBatchKey)
        XCTAssertNil(p.parent)
        XCTAssertEqual(p.children.count, 2)
        XCTAssertTrue(p.children.first === d1)
        XCTAssertTrue(p.children.last === d2)
    }

    /// HIER-043 — a descendant `keyOf` failure rejects a parked candidate as
    /// `selectorFailed` and keeps it parked.
    func testHier043DescendantSelectorFailureKeepsParkedCandidateParked() {
        struct KeyFailure: Error {}
        func attachFailing(
            _ root: SubtreeNode,
            _ items: [SubtreeNode]
        ) -> BatchAttachResult<SubtreeNode> {
            root.attachMany(
                items,
                keyOf: { node in
                    if node.model.key == "bad" { throw KeyFailure() }
                    return node.model.key
                },
                parentKeyOf: { $0.model.parentKey },
                onMissingParent: .park
            )
        }
        let root = node("root")
        let p = node("p", parent: "m")
        let parked = attachFailing(root, [p])
        XCTAssertEqual(parked.orphans.count, 1)
        XCTAssertTrue(parked.orphans.first === p)
        XCTAssertEqual(root.parkedAttachCount, 1)
        p.addChild(node("bad"))

        let result = attachFailing(root, [])

        XCTAssertTrue(result.added.isEmpty)
        XCTAssertTrue(result.duplicates.isEmpty)
        XCTAssertEqual(result.rejections.count, 1)
        XCTAssertTrue(result.rejections.first?.item === p)
        XCTAssertEqual(result.rejections.first?.reason, .selectorFailed)
        XCTAssertEqual(root.parkedAttachCount, 1)
        XCTAssertNil(p.parent)
    }

    /// HIER-044 — factory children that `addChild` materializes join the
    /// index only in the next batch.
    func testHier044FactoryChildrenJoinIndexInNextBatch() {
        let root = node("root")
        let f = node("f")
        let lazy = node("L") { _ in [f] }
        root.addChild(lazy)
        let y = node("y", parent: "L")
        let z = node("z", parent: "f")

        let first = attach(root, [y, z], policy: .park)

        XCTAssertEqual(first.added.map(\.name), ["y"])
        XCTAssertEqual(lazy.children.map(\.name), ["f", "y"])
        XCTAssertEqual(first.orphans.map(\.name), ["z"])
        XCTAssertEqual(first.rejections.count, 1)
        XCTAssertEqual(first.rejections.first?.reason, .missingParent)
        XCTAssertEqual(root.parkedAttachCount, 1)

        let second = attach(root, [])

        XCTAssertEqual(second.added.map(\.name), ["z"])
        XCTAssertTrue(second.rejections.isEmpty)
        XCTAssertTrue(z.parent === f)
        XCTAssertEqual(root.parkedAttachCount, 0)
    }
}
