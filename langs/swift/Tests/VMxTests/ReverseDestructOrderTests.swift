//
// ReverseDestructOrderTests.swift — opt-in reverse child order for container
// destruct and dispose (spec/06 §5, spec/07 §2, ADR-0161).
//
// Claimed IDs: GRP-014, COMP-046.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import Combine
import XCTest
@testable import VMx

final class ReverseDestructOrderTests: XCTestCase {

    private var hub: MessageHub!
    /// `name:status` for every settled status message, in delivery order.
    private var log: [String] = []
    private var cancellable: AnyCancellable?

    override func setUp() {
        super.setUp()
        hub = MessageHub()
        log = []
        cancellable = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .filter { [.constructed, .destructed, .disposed].contains($0.status) }
            .sink { [unowned self] in log.append("\($0.senderName):\($0.status)") }
    }

    override func tearDown() {
        cancellable?.cancel()
        cancellable = nil
        super.tearDown()
    }

    // ── Helpers ──────────────────────────────────────────────────────────

    private func leaf(_ name: String, dispatcher: Dispatcher = ImmediateDispatcher.INSTANCE,
                      background: Bool = false) -> ComponentVM {
        try! ComponentVM.builder()
            .name(name)
            .services(hub: hub, dispatcher: dispatcher)
            .background(background)
            .build()
    }

    /// The settled `status` entries of the leaf children, in order.
    private func children(_ status: ConstructionStatus) -> [String] {
        log.filter { ["a", "b", "c"].contains($0.split(separator: ":")[0]) }
            .filter { $0.hasSuffix(":\(status)") }
            .map { String($0.split(separator: ":")[0]) }
    }

    /// Construct, destruct, reconstruct and dispose `container`, asserting the
    /// child order of each walk. With `.reverse` the destruct and dispose walks
    /// run c, b, a; construct always runs a, b, c.
    private func assertOrders(
        _ container: ComponentVMBase,
        name: String,
        reverse: Bool,
        file: StaticString = #filePath,
        line: UInt = #line
    ) throws {
        let forward = ["a", "b", "c"]
        let teardown = reverse ? ["c", "b", "a"] : forward

        try container.construct()
        XCTAssertEqual(children(.constructed), forward, "construct", file: file, line: line)

        log = []
        try container.destruct()
        XCTAssertEqual(children(.destructed), teardown, "destruct", file: file, line: line)
        XCTAssertEqual(log.last, "\(name):destructed", file: file, line: line)

        try container.construct()
        log = []
        try container.reconstruct()
        XCTAssertEqual(children(.destructed), teardown, "reconstruct destruct phase",
                       file: file, line: line)
        XCTAssertEqual(children(.constructed), forward, "reconstruct construct phase",
                       file: file, line: line)

        log = []
        container.dispose()
        XCTAssertEqual(children(.disposed), teardown, "dispose", file: file, line: line)
        // LIFE-013: every child is disposed before the parent publishes Disposed.
        XCTAssertEqual(log.last, "\(name):disposed", file: file, line: line)
        XCTAssertEqual(log.filter { $0.hasSuffix(":disposed") }.count, 4, file: file, line: line)
    }

    // ── GRP-014 ──────────────────────────────────────────────────────────

    /// GRP-014 — with `.destructOrder(.reverse)`, a group destructs (also in
    /// reconstruct) and disposes its children in reverse order, while
    /// construct keeps child order.
    func testGrp014ReverseDestructAndDisposeOrder() throws {
        let (a, b, c) = (leaf("a"), leaf("b"), leaf("c"))
        let group = try GroupVM<ComponentVM>.builder()
            .name("g")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [a, b, c] }
            .destructOrder(.reverse)
            .build()
        XCTAssertEqual(group.destructOrder, .reverse)
        try assertOrders(group, name: "g", reverse: true)
    }

    /// GRP-014 — the default (`.insertion`) keeps child order for destruct and
    /// dispose.
    func testGrp014DefaultKeepsInsertionOrder() throws {
        let (a, b, c) = (leaf("a"), leaf("b"), leaf("c"))
        let group = try GroupVM<ComponentVM>.builder()
            .name("g")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [a, b, c] }
            .build()
        XCTAssertEqual(group.destructOrder, .insertion)
        try assertOrders(group, name: "g", reverse: false)
    }

    /// GRP-014 — `create(_:)` honors `destructOrder: .reverse`.
    func testGrp014CreateOptionsReverse() throws {
        let (a, b, c) = (leaf("a"), leaf("b"), leaf("c"))
        let group = try GroupVM<ComponentVM>.create(GroupVMOptions(
            name: "g",
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            children: { [a, b, c] },
            destructOrder: .reverse
        ))
        try assertOrders(group, name: "g", reverse: true)
    }

    /// GRP-014 — with background children, the reverse walk waits for each
    /// child in reverse order: the next child starts only after the previous
    /// one settles.
    func testGrp014BackgroundWaitsFollowReverseOrder() throws {
        let dispatcher = ManualDispatcher()
        let (a, b, c) = (
            leaf("a", dispatcher: dispatcher, background: true),
            leaf("b", dispatcher: dispatcher, background: true),
            leaf("c", dispatcher: dispatcher, background: true)
        )
        let group = try GroupVM<ComponentVM>.builder()
            .name("g")
            .services(hub: hub, dispatcher: dispatcher)
            .children { [a, b, c] }
            .destructOrder(.reverse)
            .build()
        try group.construct()
        for _ in 0..<10 { dispatcher.flushBackground(); dispatcher.flushForeground() }
        XCTAssertEqual(group.status, .constructed)

        log = []
        try group.destruct()
        XCTAssertEqual(c.status, .destructing)
        XCTAssertEqual(b.status, .constructed)
        XCTAssertEqual(a.status, .constructed)
        for _ in 0..<10 { dispatcher.flushBackground(); dispatcher.flushForeground() }
        XCTAssertEqual(group.status, .destructed)
        XCTAssertEqual(children(.destructed), ["c", "b", "a"])
        XCTAssertEqual(log.last, "g:destructed")
    }

    // ── COMP-046 ─────────────────────────────────────────────────────────

    /// COMP-046 — with `.destructOrder(.reverse)`, a composite clears
    /// `current`, then destructs (also in reconstruct) and disposes its
    /// children in reverse order, while construct keeps child order.
    func testComp046ReverseDestructAndDisposeOrder() throws {
        let (a, b, c) = (leaf("a"), leaf("b"), leaf("c"))
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("p")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [a, b, c] }
            .current { $0.last }
            .destructOrder(.reverse)
            .build()
        XCTAssertEqual(composite.destructOrder, .reverse)
        try composite.construct()
        XCTAssertTrue(composite.current === c)
        try composite.destruct()
        XCTAssertNil(composite.current)
        log = []
        try assertOrders(composite, name: "p", reverse: true)
    }

    /// COMP-046 — the default (`.insertion`) keeps child order for destruct
    /// and dispose.
    func testComp046DefaultKeepsInsertionOrder() throws {
        let (a, b, c) = (leaf("a"), leaf("b"), leaf("c"))
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("p")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [a, b, c] }
            .build()
        XCTAssertEqual(composite.destructOrder, .insertion)
        try assertOrders(composite, name: "p", reverse: false)
    }

    /// COMP-046 — the modeled `CompositeVMOf` builder honors
    /// `.destructOrder(.reverse)`.
    func testComp046ModeledCompositeReverse() throws {
        let composite = try CompositeVMOf<String, ComponentVM>.builder()
            .name("m")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .childrenModels { ["a", "b", "c"] }
            .childModelToChildViewModel { [unowned self] in leaf($0) }
            .destructOrder(.reverse)
            .build()
        XCTAssertEqual(composite.destructOrder, .reverse)
        try assertOrders(composite, name: "m", reverse: true)
    }

    /// COMP-046 — `create(_:)` honors `destructOrder: .reverse`.
    func testComp046CreateOptionsReverse() throws {
        let (a, b, c) = (leaf("a"), leaf("b"), leaf("c"))
        let composite = try CompositeVM<ComponentVM>.create(CompositeVMOptions(
            name: "p",
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            children: { [a, b, c] },
            destructOrder: .reverse
        ))
        try assertOrders(composite, name: "p", reverse: true)
    }
}
