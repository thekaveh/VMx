//
// Child-transition walk cycle conformance tests (spec/02-lifecycle.md §6.1,
// ADR-0255).
//
// Claimed IDs: LIFE-020, LIFE-023, LIFE-024. A walk that lists its own
// view-model, or that would join a view-model whose walk waits back on the
// walking one, fails with ChildTransitionError and starts no child, so no
// view-model is left `.constructing`. The diamond case is the control: two
// walks that share a child still construct all three view-models.
//
// The file imports VMx without @testable, and reuses the leaf VM and the
// event log that ChildTransitionHelperConformanceTests.swift defines.
//
import XCTest
import VMx

final class ChildTransitionWalkCycleConformanceTests: XCTestCase {
    private var hub: MessageHub!
    private var dispatcher: ManualDispatcher!

    override func setUp() {
        super.setUp()
        hub = MessageHub()
        dispatcher = ManualDispatcher()
    }

    override func tearDown() {
        hub = nil
        dispatcher = nil
        super.tearDown()
    }

    private func child(
        _ name: String,
        onConstruct: (() throws -> Void)? = nil
    ) -> ComponentVMBase {
        ComponentVMBase(
            name: name,
            hub: hub,
            dispatcher: dispatcher,
            onConstruct: onConstruct
        )
    }

    private func walker(_ name: String) -> HelperPanelVM {
        HelperPanelVM(name: name, hub: hub, dispatcher: dispatcher)
    }

    /// Runs the foreground work that a resumed walk queues, until quiescent.
    private func pump() {
        for _ in 0..<10 {
            dispatcher.flushBackground()
            dispatcher.flushForeground()
        }
    }

    /// LIFE-023 — a walk that lists its own view-model fails with the usage
    /// error, and it starts no child.
    func testLife023WalkListingItsOwnViewModelFailsAndStartsNoChild() throws {
        let parent = walker("parent")
        var siblingRuns = 0
        let sibling = child("sibling", onConstruct: { siblingRuns += 1 })
        parent.constructChildren = [parent, sibling]

        XCTAssertThrowsError(try parent.construct()) { error in
            XCTAssertTrue(String(describing: error).contains("its own view-model"), "\(error)")
        }

        XCTAssertEqual(parent.status, .destructed)
        XCTAssertEqual(sibling.status, .destructed)
        XCTAssertEqual(siblingRuns, 0)
    }

    /// LIFE-024 — two walks that list each other: the construct of one fails,
    /// and both view-models end at a settled status.
    func testLife024TwoWalksThatListEachOtherBothSettle() throws {
        let p = walker("p")
        let q = walker("q")
        p.constructChildren = [q]
        q.constructChildren = [p]

        XCTAssertThrowsError(try p.construct()) { error in
            XCTAssertTrue(String(describing: error).contains("walk cycle"), "\(error)")
        }
        pump()

        XCTAssertEqual(p.status, .destructed)
        XCTAssertEqual(q.status, .destructed)
    }

    /// LIFE-024 — a leaf whose walk lists its own group: the group's construct
    /// fails and the group rolls back, and the leaf settles.
    func testLife024LeafWalkingItsOwnGroupFailsTheGroupAndRollsItBack() throws {
        let leaf = walker("leaf")
        let group = GroupVM<ComponentVMBase>(
            name: "group",
            hub: hub,
            dispatcher: dispatcher,
            childrenFactory: { [leaf as ComponentVMBase] }
        )
        leaf.constructChildren = [group]

        XCTAssertThrowsError(try group.construct()) { error in
            XCTAssertTrue(String(describing: error).contains("walk cycle"), "\(error)")
        }
        pump()

        XCTAssertEqual(group.status, .destructed)
        XCTAssertEqual(leaf.status, .destructed)
    }

    /// LIFE-020 — the diamond control: two walks that share a child construct
    /// all three view-models, and the shared child runs its hook once.
    func testLife020DiamondWalksConstructAllThreeViewModels() throws {
        var sharedRuns = 0
        let c = child("c", onConstruct: { sharedRuns += 1 })
        let a = walker("a")
        let b = walker("b")
        a.constructChildren = [c]
        b.constructChildren = [c]

        try a.construct()
        try b.construct()

        XCTAssertEqual(a.status, .constructed)
        XCTAssertEqual(b.status, .constructed)
        XCTAssertEqual(c.status, .constructed)
        XCTAssertEqual(sharedRuns, 1)
    }
}
