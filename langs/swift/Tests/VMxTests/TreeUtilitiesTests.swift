//
// Tree-utilities conformance tests — UTIL-001..003 (spec/13-tree-utilities.md).
// Ports langs/typescript/tests/conformance/treeUtilities.test.ts.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
@testable import VMx

final class TreeUtilitiesTests: XCTestCase {

    private func makeLeaf(_ name: String) -> ComponentVM {
        try! ComponentVM.builder().name(name).withNullServices().build()
    }

    /// UTIL-001 — walk yields root then all descendants in DFS pre-order.
    func testUtil001DfsPreOrder() throws {
        let leaf1 = makeLeaf("leaf1")
        let leaf2 = makeLeaf("leaf2")
        let leaf3 = makeLeaf("leaf3")

        // inner has leaf1 and leaf2 as children.
        let inner = try CompositeVM<ComponentVM>.builder()
            .name("inner").withNullServices()
            .children { [leaf1, leaf2] }
            .build()
        try inner.construct()

        // root has inner (CompositeVM) and leaf3 as children. Because inner is
        // CompositeVM<ComponentVM> (not ComponentVM), root must be typed as
        // CompositeVM<ComponentVMBase> to accept heterogeneous children.
        let root = try CompositeVM<ComponentVMBase>.builder()
            .name("root").withNullServices()
            .children { [inner as ComponentVMBase, leaf3] }
            .build()
        try root.construct()   // cascades to inner (no-op) and leaf3

        // DFS pre-order: root → inner → leaf1 → leaf2 → leaf3
        XCTAssertEqual(walk(root).map(\.name), ["root", "inner", "leaf1", "leaf2", "leaf3"])
    }

    /// UTIL-002 — walk skips nil aggregate slots; only populated components appear.
    /// Uses AggregateVM3 so multiple slots are exercised. Swift aggregate slots
    /// are `private(set)` (like the TS flavor), so a single null *middle* slot
    /// can't be forced from a test; the pre-construct all-null state exercises the
    /// same declaration-order null-filter the catalog scenario targets.
    func testUtil002AggregateNilSlotsSkipped() throws {
        let c1 = makeLeaf("c1"); let c2 = makeLeaf("c2"); let c3 = makeLeaf("c3")
        let agg = try AggregateVM3<ComponentVM, ComponentVM, ComponentVM>.builder()
            .name("agg").withNullServices()
            .component1 { c1 }.component2 { c2 }.component3 { c3 }
            .build()

        // Before construct: all three slots are nil — walk yields only the root.
        XCTAssertEqual(walk(agg).map(\.name), ["agg"])

        // After construct: every populated slot appears in declaration order.
        try agg.construct()
        XCTAssertEqual(walk(agg).map(\.name), ["agg", "c1", "c2", "c3"])
    }

    /// UTIL-002 — an AggregateVM6's sixth slot is reachable by walk (parity with
    /// C#/Python/TS, each of which carries this AggregateVM6 reachability guard).
    func testUtil002AggregateVM6SlotSixReachable() throws {
        let leaves = (1...6).map { makeLeaf("c\($0)") }
        let agg = try AggregateVM6<
            ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM
        >.builder()
            .name("agg6").withNullServices()
            .component1 { leaves[0] }.component2 { leaves[1] }.component3 { leaves[2] }
            .component4 { leaves[3] }.component5 { leaves[4] }.component6 { leaves[5] }
            .build()
        try agg.construct()
        XCTAssertEqual(walk(agg).map(\.name), ["agg6", "c1", "c2", "c3", "c4", "c5", "c6"])
    }

    /// UTIL-003 — find returns the first matching node and short-circuits.
    func testUtil003FindShortCircuits() throws {
        let c1 = makeLeaf("c1")
        let c2 = makeLeaf("c2")
        let c3 = makeLeaf("c3")

        // agg (AggregateVM2) has c1 and c2 as component slots.
        let agg = try AggregateVM2<ComponentVM, ComponentVM>.builder()
            .name("agg").withNullServices()
            .component1 { c1 }
            .component2 { c2 }
            .build()
        try agg.construct()   // populates component1 = c1, component2 = c2

        // root has agg (AggregateVM2) and c3 as children; uses ComponentVMBase
        // child type to accommodate heterogeneous children.
        let root = try CompositeVM<ComponentVMBase>.builder()
            .name("root").withNullServices()
            .children { [agg as ComponentVMBase, c3] }
            .build()
        try root.construct()  // cascades to agg (no-op) and c3

        // find visits in DFS pre-order: root, agg, c1, c2 — then stops.
        var visited: [String] = []
        let result = find(root) { node in
            visited.append(node.name)
            return node.name == "c2"
        }

        XCTAssertTrue(result === c2, "find must return the exact c2 instance")
        // Short-circuit: predicate stops after visiting "c2"; "c3" is never checked.
        XCTAssertEqual(visited.last, "c2")
        XCTAssertFalse(visited.contains("c3"), "c3 must not be visited after c2 matched")

        // When nothing matches, nil is returned and all nodes are visited.
        let missing = find(root) { $0.name == "ghost" }
        XCTAssertNil(missing)
    }
}
