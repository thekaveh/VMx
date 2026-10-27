//
// API tests for the child-transition helper and `ownMember` (spec/02 §6.1 and
// §7.1, ADR-0162). The file imports VMx without @testable, so the consumer
// subclasses below use the public API only (ADR-0066). No conformance-ID
// markers: LIFE-016..020 live in `ChildTransitionHelperConformanceTests`.
//
// `ownMember(self)` traps (ADR-0009: a non-throwing Swift API traps on a
// programming error), so XCTest cannot exercise it.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
import VMx

/// A consumer leaf VM that keeps its members in fields, registers them with
/// `ownMember`, and transitions them through the helper.
private final class DashboardVM: ComponentVMBase {
    let chart: ComponentVMBase
    let table: ComponentVMBase

    init(hub: MessageHubProtocol, dispatcher: Dispatcher, chartBackground: Bool = false) {
        chart = ComponentVMBase(
            name: "chart", hub: hub, dispatcher: dispatcher, background: chartBackground
        )
        table = ComponentVMBase(name: "table", hub: hub, dispatcher: dispatcher)
        super.init(name: "dashboard", hub: hub, dispatcher: dispatcher)
        ownMember(chart)
        ownMember(table)
    }

    override func _onConstruct() throws {
        try _transitionChildren([chart, table], construct: true)
    }

    override func _onDestruct() throws {
        try _transitionChildren([table, chart], construct: false)
    }
}

final class ChildTransitionHelperAPITests: XCTestCase {
    private var hub: MessageHub!
    private var dispatcher: ManualDispatcher!
    private var log: HelperEventLog!

    override func setUp() {
        super.setUp()
        hub = MessageHub()
        dispatcher = ManualDispatcher()
        log = HelperEventLog(hub: hub)
    }

    override func tearDown() {
        log = nil
        super.tearDown()
    }

    private func child(_ name: String, background: Bool = false) -> ComponentVMBase {
        ComponentVMBase(name: name, hub: hub, dispatcher: dispatcher, background: background)
    }

    private func pump() {
        for _ in 0..<10 {
            dispatcher.flushBackground()
            dispatcher.flushForeground()
        }
    }

    // ── Consumer subclass ───────────────────────────────────────────────

    func testConsumerSubclassConstructsDestructsAndDisposesItsMembers() throws {
        let vm = DashboardVM(hub: hub, dispatcher: dispatcher)

        try vm.construct()
        XCTAssertEqual([vm.status, vm.chart.status, vm.table.status],
                       [.constructed, .constructed, .constructed])

        log.clear()
        try vm.destruct()
        XCTAssertEqual(log.entries, [
            "dashboard:destructing",
            "table:destructing", "table:destructed",
            "chart:destructing", "chart:destructed",
            "dashboard:destructed",
        ])

        vm.dispose()
        XCTAssertEqual(log.disposedSenders, ["chart", "table", "dashboard"])
    }

    func testConsumerSubclassWaitsForBackgroundMember() throws {
        let vm = DashboardVM(hub: hub, dispatcher: dispatcher, chartBackground: true)

        try vm.construct()
        XCTAssertEqual(vm.status, .constructing)
        XCTAssertEqual(vm.table.status, .destructed)

        pump()
        XCTAssertEqual([vm.status, vm.chart.status, vm.table.status],
                       [.constructed, .constructed, .constructed])
    }

    // ── Usage guard ─────────────────────────────────────────────────────

    func testHelperOutsideAHookThrowsAndStartsNoChild() throws {
        let a = child("a")
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)

        XCTAssertThrowsError(try parent._transitionChildren([a], construct: true)) { error in
            let usage = error as? ChildTransitionError
            XCTAssertNotNil(usage)
            XCTAssertEqual(usage?.childName, "parent")
        }
        XCTAssertEqual(a.status, .destructed)
        XCTAssertEqual(parent.status, .destructed)

        try parent.construct()
        XCTAssertThrowsError(try parent._transitionChildren([a], construct: true))
        XCTAssertEqual(a.status, .destructed)
    }

    func testHelperFromAnotherVMsHookThrows() throws {
        let a = child("a")
        let other = HelperPanelVM(name: "other", hub: hub, dispatcher: dispatcher)
        var caught: Error?
        let caller = ComponentVMBase(
            name: "caller", hub: hub, dispatcher: dispatcher,
            onConstruct: {
                do { try other._transitionChildren([a], construct: true) } catch { caught = error }
            }
        )

        try caller.construct()

        XCTAssertTrue(caught is ChildTransitionError)
        XCTAssertEqual(a.status, .destructed)
    }

    func testHelperFromABackgroundHook() throws {
        let a = child("a"), b = child("b", background: true)
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher, background: true)
        parent.constructChildren = [a, b]

        try parent.construct()
        XCTAssertEqual(parent.status, .constructing)
        pump()

        XCTAssertEqual([parent.status, a.status, b.status], [.constructed, .constructed, .constructed])
    }

    func testThrowingAfterRollsTheParentBack() throws {
        let a = child("a")
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        parent.constructChildren = [a]
        parent.after = { throw HelperBoom() }

        XCTAssertThrowsError(try parent.construct()) { XCTAssertTrue($0 is HelperBoom) }
        XCTAssertEqual(parent.status, .destructed)
        XCTAssertEqual(a.status, .constructed)
    }

    func testBackgroundChildFailureRollsTheParentBack() throws {
        let a = ComponentVMBase(
            name: "a", hub: hub, dispatcher: dispatcher,
            onConstruct: { throw HelperBoom() }, background: true
        )
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        parent.constructChildren = [a]

        try parent.construct()
        XCTAssertEqual(parent.status, .constructing)
        pump()

        XCTAssertEqual(a.status, .destructed)
        XCTAssertEqual(parent.status, .destructed)
    }

    func testHelperJoinsChildAlreadyDestructing() throws {
        let a = child("a", background: true)
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        parent.constructChildren = [a]
        parent.destructChildren = [a]
        try parent.construct()
        pump()
        XCTAssertEqual(parent.status, .constructed)

        try a.destruct()
        XCTAssertEqual(a.status, .destructing)
        XCTAssertNoThrow(try parent.destruct())
        XCTAssertEqual(parent.status, .destructing)

        pump()
        XCTAssertEqual(a.status, .destructed)
        XCTAssertEqual(parent.status, .destructed)
        XCTAssertEqual(log.entries.filter { $0 == "a:destructing" }.count, 1)
    }

    // ── Reconstruct ─────────────────────────────────────────────────────

    func testReconstructRunsBothPhasesThroughTheHelper() throws {
        let a = child("a"), b = child("b")
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        parent.constructChildren = [a, b]
        parent.destructChildren = [b, a]
        try parent.construct()
        log.clear()

        try parent.reconstruct()

        XCTAssertEqual(log.entries, [
            "parent:destructing",
            "b:destructing", "b:destructed",
            "a:destructing", "a:destructed",
            "parent:destructed",
            "parent:constructing",
            "a:constructing", "a:constructed",
            "b:constructing", "b:constructed",
            "parent:constructed",
        ])
    }

    func testReconstructWaitsForBackgroundChildInBothPhases() throws {
        let a = child("a", background: true)
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        parent.constructChildren = [a]
        parent.destructChildren = [a]
        try parent.construct()
        pump()
        XCTAssertEqual(parent.status, .constructed)

        try parent.reconstruct()
        XCTAssertEqual(parent.status, .destructing)
        dispatcher.flushBackground()
        dispatcher.flushForeground()
        XCTAssertEqual(parent.status, .constructing)
        pump()

        XCTAssertEqual(a.status, .constructed)
        XCTAssertEqual(parent.status, .constructed)
    }

    // ── ownMember ───────────────────────────────────────────────────────

    func testOwnMemberAfterDisposedDisposesAtOnce() {
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        parent.dispose()
        let late = child("late")

        XCTAssertTrue(parent.ownMember(late) === late)
        XCTAssertEqual(late.status, .disposed)
    }

    func testOwnMemberDoesNotParentOrConstructTheMember() throws {
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        let member = child("member")
        parent.ownMember(member)

        try parent.construct()

        XCTAssertEqual(member.status, .destructed)
        XCTAssertFalse(member.canSelect())
    }

    func testReentrantDisposeDuringMemberCascadeIsANoOp() {
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        let member = child("member")
        parent.ownMember(member)
        var statusDuringReentry: ConstructionStatus?
        let reentry = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .filter { $0.senderName == "member" && $0.status == .disposed }
            .sink { _ in
                parent.dispose()
                statusDuringReentry = parent.status
            }
        defer { reentry.cancel() }

        parent.dispose()

        XCTAssertEqual(statusDuringReentry, .destructed)
        XCTAssertEqual(parent.status, .disposed)
        XCTAssertEqual(log.disposedSenders, ["member", "parent"])
    }

    func testMemberRegisteredDuringCascadeIsDisposed() {
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        let member = child("member")
        let late = child("late")
        parent.ownMember(member)
        let register = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .filter { $0.senderName == "member" && $0.status == .disposed }
            .sink { _ in parent.ownMember(late) }
        defer { register.cancel() }

        parent.dispose()

        XCTAssertEqual(late.status, .disposed)
        XCTAssertEqual(log.disposedSenders, ["member", "late", "parent"])
    }

    func testDisposeAbandonsPendingWalkBeforeDisposingMembers() throws {
        let vm = DashboardVM(hub: hub, dispatcher: dispatcher, chartBackground: true)
        try vm.construct()
        XCTAssertEqual(vm.status, .constructing)
        XCTAssertEqual(vm.chart.status, .constructing)

        vm.dispose()
        pump()

        // The disposed member does not roll the parent back first.
        XCTAssertFalse(log.entries.contains("dashboard:destructed"))
        XCTAssertEqual(log.disposedSenders, ["chart", "table", "dashboard"])
    }

    func testMemberRegisteredDuringGroupChildCascadeIsDisposedAtOnce() {
        let group = GroupVM<ComponentVMBase>(name: "group", hub: hub, dispatcher: dispatcher)
        let groupChild = child("groupChild")
        group.add(groupChild)
        let late = child("late")
        var lateStatusAtRegistration: ConstructionStatus?
        groupChild.own {
            group.ownMember(late)
            lateStatusAtRegistration = late.status
        }

        group.dispose()

        XCTAssertEqual(lateStatusAtRegistration, .disposed)
        XCTAssertEqual(log.disposedSenders, ["groupChild", "late", "group"])
    }

    func testMemberRegisteredDuringAggregateComponentCascadeIsDisposedAtOnce() throws {
        let component = child("component")
        let aggregate = try AggregateVM1<ComponentVMBase>.builder()
            .name("aggregate")
            .services(hub: hub, dispatcher: dispatcher)
            .component1 { component }
            .build()
        try aggregate.construct()
        let late = child("late")
        var lateStatusAtRegistration: ConstructionStatus?
        component.own {
            aggregate.ownMember(late)
            lateStatusAtRegistration = late.status
        }

        aggregate.dispose()

        XCTAssertEqual(lateStatusAtRegistration, .disposed)
        XCTAssertEqual(log.disposedSenders, ["component", "late", "aggregate"])
    }

    func testReentrantAggregateDisposeDuringComponentCascadeIsANoOp() throws {
        let component = child("component")
        let aggregate = try AggregateVM1<ComponentVMBase>.builder()
            .name("aggregate")
            .services(hub: hub, dispatcher: dispatcher)
            .component1 { component }
            .build()
        try aggregate.construct()
        var statusDuringReentry: ConstructionStatus?
        let reentry = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .filter { $0.senderName == "component" && $0.status == .disposed }
            .sink { _ in
                aggregate.dispose()
                statusDuringReentry = aggregate.status
            }
        defer { reentry.cancel() }

        aggregate.dispose()

        XCTAssertEqual(statusDuringReentry, .constructed)
        XCTAssertEqual(log.disposedSenders, ["component", "aggregate"])
    }

    func testDisposeFromAnotherThreadDuringMemberCascadeReturnsAtOnce() {
        final class Probe: @unchecked Sendable {
            var otherCallReturned = false
            var parentStatusWhenOtherCallReturned: ConstructionStatus?
        }
        final class BlockingMember: ComponentVMBase {
            var onDispose: () -> Void = {}
            override func _onDispose() {
                super._onDispose()
                onDispose()
            }
        }
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        let m1 = BlockingMember(name: "m1", hub: hub, dispatcher: dispatcher)
        let m2 = child("m2")
        parent.ownMember(m1)
        parent.ownMember(m2)
        let probe = Probe()
        let returned = DispatchSemaphore(value: 0)
        m1.onDispose = {
            // Block m1's disposal (and so the parent's member cascade) until
            // another thread's parent.dispose() has returned.
            DispatchQueue.global().async {
                parent.dispose()
                probe.parentStatusWhenOtherCallReturned = parent.status
                probe.otherCallReturned = true
                returned.signal()
            }
            XCTAssertEqual(returned.wait(timeout: .now() + 10), .success)
        }

        parent.dispose()

        XCTAssertTrue(probe.otherCallReturned)
        XCTAssertNotNil(probe.parentStatusWhenOtherCallReturned)
        XCTAssertNotEqual(probe.parentStatusWhenOtherCallReturned, .disposed)
        XCTAssertEqual(parent.status, .disposed)
        XCTAssertEqual(log.disposedSenders, ["m1", "m2", "parent"])
    }

    func testMemberRegisteredTwiceIsHarmless() {
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        let member = child("member")
        parent.ownMember(member)
        parent.ownMember(member)

        parent.dispose()

        XCTAssertEqual(log.disposedSenders, ["member", "parent"])
    }

    func testMembersAreDisposedBeforeOwnedResources() {
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        let member = child("member")
        parent.ownMember(member)
        var memberStatusAtCleanup: ConstructionStatus?
        parent.own { memberStatusAtCleanup = member.status }

        parent.dispose()

        XCTAssertEqual(memberStatusAtCleanup, .disposed)
    }
}
