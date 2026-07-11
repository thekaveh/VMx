import XCTest
@testable import VMx

private struct BatchModel {
    let key: String
    let parentKey: String?
}

private final class BatchNode: HierarchicalVM<BatchModel, BatchNode> {}

final class HierarchicalBatchAttachTests: XCTestCase {
    private func node(_ key: String, parent: String? = nil) -> BatchNode {
        BatchNode(
            model: BatchModel(key: key, parentKey: parent),
            childrenFactory: { _ in [] },
            hub: MessageHub(),
            dispatcher: ImmediateDispatcher.INSTANCE,
            name: key
        )
    }

    private func attach(
        _ root: BatchNode,
        _ items: [BatchNode],
        policy: MissingParentPolicy = .park
    ) -> BatchAttachResult<BatchNode> {
        root.attachMany(
            items,
            keyOf: { $0.model.key },
            parentKeyOf: { $0.model.parentKey },
            onMissingParent: policy
        )
    }

    /// HIER-023 — child-before-parent batches reach a stable fixpoint.
    func testHier023FixpointAndSiblingOrder() {
        let root = node("root")
        let grandchild = node("grandchild", parent: "child-a")
        let childB = node("child-b", parent: "parent")
        let childA = node("child-a", parent: "parent")
        let parent = node("parent")
        let result = attach(root, [grandchild, childB, childA, parent])

        XCTAssertEqual(result.added.count, 4)
        XCTAssertTrue(root.children.first === parent)
        XCTAssertTrue(parent.children[0] === childB)
        XCTAssertTrue(parent.children[1] === childA)
        XCTAssertTrue(childA.children.first === grandchild)
        XCTAssertEqual(grandchild.path.map(\.name), ["root", "parent", "child-a", "grandchild"])
        XCTAssertTrue(result.rejections.isEmpty)
    }

    /// HIER-024 — nil parent keys attach below the structural root in input order.
    func testHier024MultipleRootItems() {
        let root = node("root")
        let first = node("first")
        let second = node("second")
        let result = attach(root, [first, second])
        XCTAssertEqual(result.added.map(\.name), ["first", "second"])
        XCTAssertEqual(root.children.map(\.name), ["first", "second"])
    }

    /// HIER-025 — duplicate keys never replace the authoritative node.
    func testHier025DuplicateKeys() {
        let root = node("root")
        let existing = node("existing")
        root.addChild(existing)
        let conflict = node("existing")
        let first = node("new")
        let batchConflict = node("new")
        let result = attach(root, [conflict, first, batchConflict])

        XCTAssertEqual(result.added.map(\.name), ["new"])
        XCTAssertEqual(result.duplicates.count, 2)
        XCTAssertEqual(result.rejections.map(\.reason), [.duplicateExistingKey, .duplicateBatchKey])
        XCTAssertTrue(root.children[0] === existing)
        XCTAssertTrue(root.children[1] === first)
        XCTAssertEqual(attach(root, [first]).duplicates.count, 1)
    }

    /// HIER-026 — parked orphans retry when a later batch supplies the parent.
    func testHier026CrossBatchParking() {
        let root = node("root")
        let child = node("child", parent: "parent")
        XCTAssertEqual(attach(root, [child]).orphans.count, 1)
        XCTAssertEqual(root.parkedAttachCount, 1)

        let parent = node("parent")
        let result = attach(root, [parent])
        XCTAssertEqual(result.added.count, 2)
        XCTAssertTrue(child.parent === parent)
        XCTAssertEqual(root.parkedAttachCount, 0)
    }

    /// HIER-027 — reject policy does not retain unresolved items.
    func testHier027RejectPolicy() {
        let root = node("root")
        let child = node("child", parent: "parent")
        XCTAssertEqual(attach(root, [child], policy: .reject).orphans.count, 1)
        XCTAssertEqual(root.parkedAttachCount, 0)
        let parent = node("parent")
        _ = attach(root, [parent])
        XCTAssertNil(child.parent)
        XCTAssertTrue(parent.children.isEmpty)
    }

    /// HIER-028 — parent-key cycles are terminal non-throwing rejections.
    func testHier028CycleRejections() {
        let root = node("root")
        let first = node("first", parent: "second")
        let second = node("second", parent: "first")
        let result = attach(root, [first, second])
        XCTAssertTrue(result.added.isEmpty)
        XCTAssertTrue(result.orphans.isEmpty)
        XCTAssertEqual(result.rejections.map(\.reason), [.cycle, .cycle])
        XCTAssertEqual(root.parkedAttachCount, 0)
    }

    /// HIER-029 — failures are structured and existing parent links stay atomic.
    func testHier029StructuredAtomicRejections() {
        let root = node("root")
        let outside = node("outside")
        let attached = node("attached")
        outside.addChild(attached)
        let detachedSameKey = node("attached")
        let result = attach(root, [attached, detachedSameKey])
        XCTAssertEqual(result.rejections.first?.reason, .alreadyAttached)
        XCTAssertTrue(attached.parent === outside)
        XCTAssertTrue(outside.children.first === attached)
        XCTAssertTrue(result.added.first === detachedSameKey)
        XCTAssertTrue(root.children.first === detachedSameKey)

        let failed = root.attachMany(
            [node("bad")],
            keyOf: { _ in throw NSError(domain: "test", code: 1) },
            parentKeyOf: { _ in nil as String? }
        )
        XCTAssertEqual(failed.rejections.first?.reason, .selectorFailed)
    }

    /// HIER-030 — disposal clears root-owned parked state.
    func testHier030DisposeClearsParkedItems() {
        let root = node("root")
        _ = attach(root, [node("child", parent: "missing")])
        XCTAssertEqual(root.parkedAttachCount, 1)
        root.dispose()
        XCTAssertEqual(root.parkedAttachCount, 0)
    }
}
