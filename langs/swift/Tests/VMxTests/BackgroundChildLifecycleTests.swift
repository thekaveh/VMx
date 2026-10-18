//
// Background-child lifecycle tests (spec/02-lifecycle.md §6, LIFE-014).
//
// A composite / group / aggregate reaches Constructed only once every child
// has reached Constructed, and Destructed only once every child has reached
// Destructed — including children whose hooks run on the background
// dispatcher. A background child that fails rolls the parent back; disposing
// a parent while it waits publishes nothing further. `ManualDispatcher` pumps
// the background work deterministically.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

final class BackgroundChildLifecycleTests: XCTestCase {
    private struct Boom: Error {}

    private var hub: MessageHub!
    private var dispatcher: ManualDispatcher!
    private var statusLog: [String] = []
    private var cancellable: AnyCancellable?

    override func setUp() {
        super.setUp()
        hub = MessageHub()
        dispatcher = ManualDispatcher()
        statusLog = []
        cancellable = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .sink { [unowned self] in statusLog.append("\($0.senderName):\($0.status)") }
    }

    override func tearDown() {
        cancellable?.cancel()
        cancellable = nil
        super.tearDown()
    }

    private func background(_ name: String, failing: Bool = false) -> ComponentVM {
        var builder = ComponentVM.builder()
            .name(name)
            .services(hub: hub, dispatcher: dispatcher)
            .background(true)
        if failing { builder = builder.onConstruct { throw Boom() } }
        return try! builder.build()
    }

    /// Runs background hooks and their foreground completions until quiescent.
    private func pump() {
        for _ in 0..<10 {
            dispatcher.flushBackground()
            dispatcher.flushForeground()
        }
    }

    private func statuses(of name: String) -> [String] {
        statusLog.filter { $0.hasPrefix(name + ":") }
    }

    // ── Construct / destruct wait for background children ──────────────

    func testCompositeWaitsForBackgroundChildren() throws {
        let c1 = background("c1"), c2 = background("c2")
        let composite = CompositeVM<ComponentVM>(name: "comp", hub: hub, dispatcher: dispatcher)
        composite.add(c1)
        composite.add(c2)

        try composite.construct()
        XCTAssertEqual(composite.status, .constructing)
        XCTAssertEqual(c1.status, .constructing)
        pump()
        XCTAssertEqual(composite.status, .constructed)
        XCTAssertEqual(c1.status, .constructed)
        XCTAssertEqual(c2.status, .constructed)

        try composite.destruct()
        XCTAssertEqual(composite.status, .destructing)
        pump()
        XCTAssertEqual(composite.status, .destructed)
        XCTAssertEqual(c1.status, .destructed)
        XCTAssertEqual(c2.status, .destructed)
        XCTAssertEqual(statuses(of: "comp"), [
            "comp:constructing", "comp:constructed",
            "comp:destructing", "comp:destructed",
        ])
    }

    func testGroupWaitsForBackgroundChildren() throws {
        let g1 = background("g1"), g2 = background("g2")
        let group = GroupVM<ComponentVM>(name: "grp", hub: hub, dispatcher: dispatcher)
        group.add(g1)
        group.add(g2)

        try group.construct()
        XCTAssertEqual(group.status, .constructing)
        pump()
        XCTAssertEqual(group.status, .constructed)
        XCTAssertEqual(g1.status, .constructed)
        XCTAssertEqual(g2.status, .constructed)

        try group.destruct()
        XCTAssertEqual(group.status, .destructing)
        pump()
        XCTAssertEqual(group.status, .destructed)
        XCTAssertEqual(g1.status, .destructed)
        XCTAssertEqual(g2.status, .destructed)
    }

    func testAggregateWaitsForBackgroundComponents() throws {
        let aggregate = AggregateVM2<ComponentVM, ComponentVM>(
            name: "agg", hub: hub, dispatcher: dispatcher,
            factory1: { [unowned self] in background("a1") },
            factory2: { [unowned self] in background("a2") }
        )

        try aggregate.construct()
        XCTAssertEqual(aggregate.status, .constructing)
        pump()
        XCTAssertEqual(aggregate.status, .constructed)
        XCTAssertEqual(aggregate.component1?.status, .constructed)
        XCTAssertEqual(aggregate.component2?.status, .constructed)

        try aggregate.destruct()
        XCTAssertEqual(aggregate.status, .destructing)
        pump()
        XCTAssertEqual(aggregate.status, .destructed)
        XCTAssertEqual(aggregate.component1?.status, .destructed)
        XCTAssertEqual(aggregate.component2?.status, .destructed)
    }

    func testNestedCompositeWaitsForBackgroundLeaf() throws {
        let leaf = background("leaf")
        let inner = CompositeVM<ComponentVM>(name: "inner", hub: hub, dispatcher: dispatcher)
        inner.add(leaf)
        let outer = CompositeVM<CompositeVM<ComponentVM>>(
            name: "outer", hub: hub, dispatcher: dispatcher
        )
        outer.add(inner)

        try outer.construct()
        XCTAssertEqual(outer.status, .constructing)
        XCTAssertEqual(inner.status, .constructing)
        pump()
        XCTAssertEqual(outer.status, .constructed)
        XCTAssertEqual(inner.status, .constructed)
        XCTAssertEqual(leaf.status, .constructed)
    }

    /// COMP-025 — the selector runs once every child is Constructed.
    func testCompositeSelectorRunsAfterBackgroundChildrenConstruct() throws {
        let t1 = background("t1"), t2 = background("t2")
        let composite = CompositeVM<ComponentVM>(
            name: "comp", hub: hub, dispatcher: dispatcher,
            currentSelector: { $0.last }
        )
        composite.add(t1)
        composite.add(t2)

        try composite.construct()
        XCTAssertNil(composite.current)
        pump()
        XCTAssertTrue(composite.current === t2)
        XCTAssertEqual(composite.status, .constructed)
    }

    func testCompositeReconstructWaitsForBackgroundChildren() throws {
        let r1 = background("r1"), r2 = background("r2")
        let composite = CompositeVM<ComponentVM>(name: "comp", hub: hub, dispatcher: dispatcher)
        composite.add(r1)
        composite.add(r2)
        try composite.construct()
        pump()
        statusLog.removeAll()

        try composite.reconstruct()
        XCTAssertEqual(composite.status, .destructing)
        pump()
        XCTAssertEqual(composite.status, .constructed)
        XCTAssertEqual(r1.status, .constructed)
        XCTAssertEqual(r2.status, .constructed)
        XCTAssertEqual(statuses(of: "comp"), [
            "comp:destructing", "comp:destructed",
            "comp:constructing", "comp:constructed",
        ])
    }

    // ── LIFE-014: a failing background child rolls the parent back ─────

    func testFailingBackgroundChildRollsBackComposite() throws {
        let ok = background("ok"), bad = background("bad", failing: true)
        let composite = CompositeVM<ComponentVM>(name: "comp", hub: hub, dispatcher: dispatcher)
        composite.add(ok)
        composite.add(bad)

        try composite.construct()
        pump()
        XCTAssertEqual(composite.status, .destructed)
        XCTAssertEqual(bad.status, .destructed)
        XCTAssertTrue(composite.canConstruct(), "the rolled-back composite stays recoverable")
        XCTAssertEqual(statuses(of: "comp"), ["comp:constructing", "comp:destructed"])
    }

    func testFailingBackgroundChildRollsBackGroup() throws {
        let bad = background("bad", failing: true)
        let group = GroupVM<ComponentVM>(name: "grp", hub: hub, dispatcher: dispatcher)
        group.add(bad)

        try group.construct()
        pump()
        XCTAssertEqual(group.status, .destructed)
        XCTAssertEqual(bad.status, .destructed)
    }

    func testFailingBackgroundComponentRollsBackAggregate() throws {
        let aggregate = AggregateVM1<ComponentVM>(
            name: "agg", hub: hub, dispatcher: dispatcher,
            factory1: { [unowned self] in background("bad", failing: true) }
        )

        try aggregate.construct()
        pump()
        XCTAssertEqual(aggregate.status, .destructed)
        XCTAssertEqual(aggregate.component1?.status, .destructed)
    }

    // ── Dispose while waiting publishes no stray settle ────────────────

    func testDisposeWhileWaitingPublishesNoSettle() throws {
        let w1 = background("w1"), w2 = background("w2")
        let composite = CompositeVM<ComponentVM>(name: "comp", hub: hub, dispatcher: dispatcher)
        composite.add(w1)
        composite.add(w2)
        try composite.construct()
        composite.dispose()
        pump()
        XCTAssertEqual(composite.status, .disposed)
        XCTAssertEqual(w1.status, .disposed)
        XCTAssertEqual(w2.status, .disposed)
        XCTAssertEqual(statuses(of: "comp"), ["comp:constructing", "comp:disposed"])

        let g1 = background("g1")
        let group = GroupVM<ComponentVM>(name: "grp", hub: hub, dispatcher: dispatcher)
        group.add(g1)
        try group.construct()
        group.dispose()
        pump()
        XCTAssertEqual(g1.status, .disposed)
        XCTAssertEqual(statuses(of: "grp"), ["grp:constructing", "grp:disposed"])

        let aggregate = AggregateVM1<ComponentVM>(
            name: "agg", hub: hub, dispatcher: dispatcher,
            factory1: { [unowned self] in background("a1") }
        )
        try aggregate.construct()
        aggregate.dispose()
        pump()
        XCTAssertEqual(aggregate.component1?.status, .disposed)
        XCTAssertEqual(statuses(of: "agg"), ["agg:constructing", "agg:disposed"])
    }
}
