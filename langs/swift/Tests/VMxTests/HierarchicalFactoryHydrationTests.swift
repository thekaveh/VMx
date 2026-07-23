import XCTest
@testable import VMx

private final class HydrationNode: HierarchicalVM<String, HydrationNode> {}

final class HierarchicalFactoryHydrationTests: XCTestCase {
    /// HIER-031 — factory hydration validates the complete snapshot before
    /// mutation, rejects invalid topology, and remains retryable.
    func testHier031AtomicFactoryHydration() {
        let hub = MessageHub()
        let first = HydrationNode(
            model: "first",
            childrenFactory: { _ in [] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
        let second = HydrationNode(
            model: "second",
            childrenFactory: { _ in [] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
        var snapshot = [first, first]
        let root = HydrationNode(
            model: "root",
            childrenFactory: { _ in snapshot },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )

        guard case .failure(.invalidFactoryOutput) = root.tryChildren() else {
            return XCTFail("duplicate identity must be rejected")
        }
        XCTAssertNil(first.parent)

        snapshot = [first, second]
        guard case .success(let children) = root.tryChildren() else {
            return XCTFail("valid retry must succeed")
        }
        XCTAssertEqual(children.count, 2)
        XCTAssertTrue(first.parent === root)
        XCTAssertTrue(second.parent === root)
    }

    /// HIER-031 — self, ancestor, and already-parented results are rejected.
    func testHier031RejectsInvalidTopology() {
        let hub = MessageHub()
        var selfNode: HydrationNode!
        selfNode = HydrationNode(
            model: "self",
            childrenFactory: { _ in [selfNode] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
        guard case .failure(.invalidFactoryOutput) = selfNode.tryChildren() else {
            return XCTFail("self must be rejected")
        }

        let attached = HydrationNode(
            model: "attached",
            childrenFactory: { _ in [] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
        let oldParent = HydrationNode(
            model: "old",
            childrenFactory: { _ in [] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
        _ = oldParent.addChild(attached)
        let newParent = HydrationNode(
            model: "new",
            childrenFactory: { _ in [attached] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
        guard case .failure(.invalidFactoryOutput) = newParent.tryChildren() else {
            return XCTFail("already-parented child must be rejected")
        }
        XCTAssertTrue(attached.parent === oldParent)

        let ancestor = HydrationNode(
            model: "ancestor",
            childrenFactory: { _ in [] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
        let descendant = HydrationNode(
            model: "descendant",
            childrenFactory: { _ in [ancestor] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
        _ = ancestor.addChild(descendant)
        guard case .failure(.invalidFactoryOutput) = descendant.tryChildren() else {
            return XCTFail("ancestor must be rejected")
        }
        XCTAssertTrue(descendant.parent === ancestor)
    }
}
