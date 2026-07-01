import XCTest
@testable import VMx

private struct InvalidationModel {
    let value: String
}

private final class InvalidationNode: HierarchicalVM<InvalidationModel, InvalidationNode> {}

final class HierarchicalInvalidationTests: XCTestCase {
    private func node(
        _ hub: MessageHubProtocol = MessageHub(),
        childrenFactory: @escaping (InvalidationNode) -> [InvalidationNode] = { _ in [] }
    ) -> InvalidationNode {
        InvalidationNode(
            model: InvalidationModel(value: "m"),
            childrenFactory: childrenFactory,
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
    }

    /// HIER-019 — invalidateChildren reloads on next access.
    func testHIER019InvalidateChildrenReloadsOnNextAccess() {
        var calls = 0
        let root = node { _ in
            calls += 1
            return [self.node()]
        }
        let first = root.children[0]

        root.invalidateChildren()
        let second = root.children[0]

        XCTAssertEqual(calls, 2)
        XCTAssertFalse(second === first)
    }

    /// HIER-020 — invalidateChildren on an unmaterialized node is a no-op.
    func testHIER020InvalidateChildrenUnmaterializedIsNoop() {
        var calls = 0
        let root = node { _ in
            calls += 1
            return []
        }

        root.invalidateChildren()

        XCTAssertEqual(calls, 0)
    }

    /// HIER-021 — invalidateSubtree reloads materialized descendants.
    func testHIER021InvalidateSubtreeReloadsMaterializedDescendants() {
        var grandchildCalls = 0
        let child = node { _ in
            grandchildCalls += 1
            return [self.node()]
        }
        let root = node { _ in [child] }
        _ = root.children
        let firstGrandchild = child.children[0]

        root.invalidateSubtree()
        let reloadedChild = root.children[0]
        let secondGrandchild = reloadedChild.children[0]

        XCTAssertEqual(grandchildCalls, 2)
        XCTAssertFalse(secondGrandchild === firstGrandchild)
    }

    /// HIER-022 — invalidateChildren publishes children property changed.
    func testHIER022InvalidateChildrenPublishesChildrenPropertyChanged() {
        let hub = MessageHub()
        var seen: [PropertyChangedMessage] = []
        let token = hub.subscribe { message in
            if let propertyChanged = message as? PropertyChangedMessage {
                seen.append(propertyChanged)
            }
        }
        let root = node(hub) { _ in [self.node(hub)] }
        _ = root.children

        root.invalidateChildren()
        token.dispose()

        XCTAssertTrue(seen.contains { $0.senderObject === root && $0.propertyName == "children" })
    }
}
