import Dispatch
import Foundation
import XCTest
@testable import VMx

// Deep-chain tests for walk, walkExpanded, find, depth and path-cache
// invalidation (issue #1912). The tree is 10,000 levels deep. Each test body
// runs on a thread with a 512 KiB stack, so an implementation that recurses
// once per level overflows that stack and the test process crashes. The C#
// deep-chain tests use the same stack size.

private struct DeepChainModel {
    let value: String
}

private final class DeepChainNode: HierarchicalVM<DeepChainModel, DeepChainNode> {}

/// Collects an error thrown by a test body on its own thread.
private final class DeepChainOutcome {
    var error: Error?
}

final class HierarchicalDeepChainTests: XCTestCase {
    private static let levels = 10_000
    private static let stackBytes = 512 * 1024
    private static let budgetSeconds: Double = 60

    /// A chain of `levels` nodes. Children come from factories, so building the
    /// chain does not touch the path caches. The node at depth `d` materializes
    /// one child until the last level.
    private static func chain(
        _ levels: Int,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher
    ) -> DeepChainNode {
        func build(_ depth: Int) -> DeepChainNode {
            DeepChainNode(
                model: DeepChainModel(value: "n\(depth)"),
                childrenFactory: { _ in depth + 1 == levels ? [] : [build(depth + 1)] },
                hub: hub,
                dispatcher: dispatcher,
                name: "n\(depth)"
            )
        }
        return build(0)
    }

    /// Drops the children of every node below `root`. Each node then releases
    /// its child only from the array that holds the chain, so freeing the nodes
    /// does not recurse once per level. The nodes are detached deepest first:
    /// a detach then touches a node with no materialized children, so the whole
    /// teardown is linear. Top-down detaching re-walks the remaining subtree at
    /// every level, which is quadratic in the depth.
    private static func release(_ root: DeepChainNode) {
        var chain: [DeepChainNode] = [root]
        while let child = chain[chain.count - 1].children.first {
            chain.append(child)
        }
        for node in chain.reversed() {
            node.invalidateChildren()
        }
    }

    /// Runs `body` on a thread with a 512 KiB stack and waits for it to finish.
    /// An error thrown by `body` fails the test on the calling thread.
    private func runOnSmallStack(_ body: @escaping () throws -> Void) {
        let outcome = DeepChainOutcome()
        let finished = DispatchSemaphore(value: 0)
        let thread = Thread {
            do {
                try body()
            } catch {
                outcome.error = error
            }
            finished.signal()
        }
        thread.stackSize = Self.stackBytes
        thread.start()
        let result = finished.wait(timeout: .now() + Self.budgetSeconds)
        XCTAssertEqual(
            result,
            .success,
            "the deep-chain body finishes within \(Self.budgetSeconds) s"
        )
        if let error = outcome.error {
            XCTFail("the deep-chain body threw: \(error)")
        }
    }

    func testDeepChainWalkFindAndDepthReachTheLastLevel() {
        runOnSmallStack {
            let root = Self.chain(
                Self.levels,
                hub: MessageHub(),
                dispatcher: ImmediateDispatcher.INSTANCE
            )

            let nodes = try walk(root)
            let last = nodes[nodes.count - 1] as! DeepChainNode

            XCTAssertEqual(nodes.count, Self.levels)
            XCTAssertEqual(nodes.map(\.name), (0..<Self.levels).map { "n\($0)" })
            XCTAssertEqual(last.depth, Self.levels - 1)
            XCTAssertEqual(last.path.count, Self.levels)
            XCTAssertEqual(try walkExpanded(root).count, Self.levels)
            let hit = try find(root, where: { $0 === last })
            XCTAssertTrue(hit === last)

            Self.release(root)
        }
    }

    func testDeepChainMovesUnderANewParent() {
        runOnSmallStack {
            let hub = MessageHub()
            let dispatcher = ImmediateDispatcher.INSTANCE
            let root = Self.chain(Self.levels, hub: hub, dispatcher: dispatcher)
            // Materialize top-down in a loop, so the move itself is what recurses.
            var last = root
            while let child = last.children.first {
                last = child
            }
            // Cache the deepest path first, so the move has to invalidate it.
            XCTAssertEqual(last.depth, Self.levels - 1)
            XCTAssertEqual(last.path.count, Self.levels)
            let newRoot = DeepChainNode(
                model: DeepChainModel(value: "new-root"),
                childrenFactory: { _ in [] },
                hub: hub,
                dispatcher: dispatcher,
                name: "new-root"
            )

            if case .failure(let error) = newRoot.addChild(root) {
                XCTFail("the move was refused: \(error)")
            }

            XCTAssertTrue(root.parent === newRoot)
            XCTAssertEqual(last.depth, Self.levels)
            XCTAssertEqual(last.path.count, Self.levels + 1)
            XCTAssertTrue(last.path.first === newRoot)

            Self.release(newRoot)
        }
    }
}
