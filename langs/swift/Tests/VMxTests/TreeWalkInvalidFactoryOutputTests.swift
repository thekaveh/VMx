//
// Tree walks over invalid HierarchicalVM factory output (spec/13 §6,
// ADR-0170, #1060). `walk`, `walkExpanded` and `find` throw
// `HierarchyError.invalidFactoryOutput` instead of trapping, and the failing
// node stays unmaterialized so a later walk retries the factory (HIER-031).
//
import XCTest
@testable import VMx

private final class WalkNode: HierarchicalVM<String, WalkNode> {}

final class TreeWalkInvalidFactoryOutputTests: XCTestCase {
    private let hub = MessageHub()

    private func leaf(_ model: String) -> WalkNode {
        WalkNode(
            model: model,
            childrenFactory: { _ in [] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
    }

    private func assertInvalidFactoryOutput<T>(
        _ expression: @autoclosure () throws -> T,
        _ label: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertThrowsError(try expression(), label, file: file, line: line) { error in
            guard case HierarchyError.invalidFactoryOutput = error else {
                return XCTFail("\(label): unexpected error \(error)", file: file, line: line)
            }
        }
    }

    /// UTIL-004 — tree walks report invalid factory output as a recoverable
    /// error, assign no parent, retry the factory, and `find` returns a match
    /// before the failing node.
    func testUtil004WalksReportInvalidFactoryOutputBelowRoot() throws {
        let a = leaf("a")
        let c = leaf("c")
        let d = leaf("d")
        var snapshot = [c, c]
        var calls = 0
        let b = WalkNode(
            model: "b",
            childrenFactory: { _ in
                calls += 1
                return snapshot
            },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            name: "b"
        )
        let root = WalkNode(
            model: "root",
            childrenFactory: { _ in [a, b] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            name: "root"
        )
        XCTAssertEqual(root.children.count, 2)

        assertInvalidFactoryOutput(try walk(root), "walk")
        assertInvalidFactoryOutput(try walkExpanded(root), "walkExpanded")
        assertInvalidFactoryOutput(try find(root) { _ in false }, "find")
        XCTAssertEqual(calls, 3, "each walk retries the factory")
        XCTAssertNil(c.parent, "a rejected snapshot assigns no parent")
        guard case .failure = b.tryChildren() else {
            return XCTFail("b keeps no children cache, so a direct read fails again")
        }
        XCTAssertEqual(calls, 4, "a direct read runs the factory again")

        XCTAssertTrue(try find(root) { $0 === a } === a)
        XCTAssertEqual(calls, 4, "find returns a match before the failing node")

        snapshot = [c, d]
        XCTAssertEqual(try walk(root).count, 5)
        XCTAssertTrue(try walk(root)[3] === c)
        XCTAssertTrue(try walk(root)[4] === d)
    }

    /// `walk`, `walkExpanded` and `find` throw on a duplicate child identity,
    /// change nothing, and succeed once the factory returns valid output.
    func testWalksThrowOnInvalidFactoryOutputAndStayRetryable() throws {
        let dup = leaf("dup")
        let other = leaf("other")
        var snapshot = [dup, dup]
        var factoryCalls = 0
        let root = WalkNode(
            model: "root",
            childrenFactory: { _ in
                factoryCalls += 1
                return snapshot
            },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )

        assertInvalidFactoryOutput(try walk(root), "walk")
        assertInvalidFactoryOutput(try walkExpanded(root), "walkExpanded")
        assertInvalidFactoryOutput(try find(root) { _ in false }, "find")
        XCTAssertEqual(factoryCalls, 3, "each walk retries the factory")
        XCTAssertNil(dup.parent, "a rejected snapshot assigns no parent")

        // A predicate that matches the root returns before any child is read.
        XCTAssertTrue(try find(root) { $0 === root } === root)
        XCTAssertEqual(factoryCalls, 3)

        snapshot = [dup, other]
        guard case .success(let children) = root.tryChildren() else {
            return XCTFail("a valid retry must succeed (HIER-031)")
        }
        XCTAssertEqual(children.count, 2)
        XCTAssertEqual(try walk(root).count, 3)
        XCTAssertEqual(try walkExpanded(root).count, 3)
        XCTAssertTrue(try find(root) { $0 === other } === other)
    }

    /// The error propagates through a non-hierarchical container that holds
    /// the failing hierarchical node.
    func testWalkThrowsThroughCompositeContainer() throws {
        let dup = leaf("dup")
        let hierarchy = WalkNode(
            model: "hierarchy",
            childrenFactory: { _ in [dup, dup] },
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
        let composite = try CompositeVM<ComponentVMBase>.builder()
            .name("composite").withNullServices()
            .children { [hierarchy as ComponentVMBase] }
            .build()
        try composite.construct()

        assertInvalidFactoryOutput(try walk(composite), "walk")
        assertInvalidFactoryOutput(try walkExpanded(composite), "walkExpanded")
        assertInvalidFactoryOutput(try find(composite) { _ in false }, "find")
        XCTAssertTrue(try find(composite) { $0 === hierarchy } === hierarchy)
    }
}
