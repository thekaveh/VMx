//
// Child-transition helper and member-disposal conformance tests
// (spec/02-lifecycle.md §6.1 and §7.1, ADR-0162).
//
// Claimed IDs: LIFE-016..020. The file imports VMx without @testable, so every
// consumer subclass below compiles against the public API only, as a subclass
// in another module does (ADR-0066). `ManualDispatcher` pumps the background
// work deterministically.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
import VMx

/// Records each `ConstructionStatusChangedMessage` as `"name:status"`, and the
/// other events a test appends, in order.
final class HelperEventLog {
    private(set) var entries: [String] = []
    private var cancellable: AnyCancellable?

    init(hub: MessageHub) {
        cancellable = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .sink { [unowned self] in entries.append("\($0.senderName):\($0.status)") }
    }

    func append(_ entry: String) { entries.append(entry) }
    func clear() { entries.removeAll() }

    /// The names of the senders that published `.disposed`, in order.
    var disposedSenders: [String] {
        entries.filter { $0.hasSuffix(":disposed") }.map { String($0.dropLast(":disposed".count)) }
    }

    func index(of entry: String) -> Int? { entries.firstIndex(of: entry) }
}

/// A leaf view-model in a consumer module. Its hooks pass the configured
/// children to the child-transition helper.
final class HelperPanelVM: ComponentVMBase {
    var constructChildren: [ComponentVMBase] = []
    var destructChildren: [ComponentVMBase] = []
    var after: (() throws -> Void)?

    init(
        name: String = "parent",
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        background: Bool = false
    ) {
        super.init(name: name, hub: hub, dispatcher: dispatcher, background: background)
    }

    override func _onConstruct() throws {
        try super._onConstruct()
        try _transitionChildren(constructChildren, construct: true, after: after)
    }

    override func _onDestruct() throws {
        try super._onDestruct()
        try _transitionChildren(destructChildren, construct: false)
    }
}

struct HelperBoom: Error {}

final class ChildTransitionHelperConformanceTests: XCTestCase {
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

    private func child(
        _ name: String,
        background: Bool = false,
        onConstruct: (() throws -> Void)? = nil
    ) -> ComponentVMBase {
        ComponentVMBase(
            name: name,
            hub: hub,
            dispatcher: dispatcher,
            onConstruct: onConstruct,
            background: background
        )
    }

    /// Runs background hooks and their foreground completions until quiescent.
    private func pump() {
        for _ in 0..<10 {
            dispatcher.flushBackground()
            dispatcher.flushForeground()
        }
    }

    /// LIFE-016 — the helper waits for a background child, runs `after` once,
    /// and only then does the parent publish Constructed.
    func testLife016HelperWaitsForBackgroundChild() throws {
        let a = child("a", background: true)
        let b = child("b")
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        var afterRuns = 0
        parent.constructChildren = [a, b]
        parent.after = { [log] in
            afterRuns += 1
            log?.append("after")
        }

        try parent.construct()

        XCTAssertEqual(parent.status, .constructing)
        XCTAssertEqual(a.status, .constructing)
        XCTAssertEqual(b.status, .destructed)
        XCTAssertEqual(afterRuns, 0)

        pump()

        XCTAssertEqual(a.status, .constructed)
        XCTAssertEqual(b.status, .constructed)
        XCTAssertEqual(afterRuns, 1)
        XCTAssertEqual(parent.status, .constructed)
        let aDone = try XCTUnwrap(log.index(of: "a:constructed"))
        let bDone = try XCTUnwrap(log.index(of: "b:constructed"))
        let afterDone = try XCTUnwrap(log.index(of: "after"))
        let parentDone = try XCTUnwrap(log.index(of: "parent:constructed"))
        XCTAssertLessThan(aDone, bDone)
        XCTAssertLessThan(bDone, afterDone)
        XCTAssertLessThan(afterDone, parentDone)
    }

    /// LIFE-017 — a child failure in the helper rolls the parent back, keeps
    /// the sibling that already constructed, and never starts the next child.
    func testLife017ChildFailureRollsParentBack() throws {
        let a = child("a")
        let b = child("b", onConstruct: { throw HelperBoom() })
        let c = child("c")
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        parent.constructChildren = [a, b, c]

        XCTAssertThrowsError(try parent.construct()) { error in
            XCTAssertTrue(error is HelperBoom)
        }

        XCTAssertEqual(parent.status, .destructed)
        XCTAssertEqual(a.status, .constructed)
        XCTAssertEqual(b.status, .destructed)
        XCTAssertEqual(c.status, .destructed)
        XCTAssertNil(log.index(of: "c:constructing"))
    }

    /// LIFE-018 — registered members are disposed depth-first, in
    /// registration order, before the parent publishes Disposed.
    func testLife018MembersDisposedDepthFirstBeforeParent() throws {
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        let first = GroupVM<ComponentVMBase>(name: "first", hub: hub, dispatcher: dispatcher)
        first.add(child("firstChild"))
        let second = child("second")
        XCTAssertTrue(parent.ownMember(first) === first)
        parent.ownMember(second)
        try first.construct()
        try parent.construct()
        XCTAssertEqual(parent.status, .constructed)

        parent.dispose()

        XCTAssertEqual(log.disposedSenders, ["firstChild", "first", "second", "parent"])
    }

    /// LIFE-018 (failing member) — when the first member's disposal hook
    /// raises, the second member and the parent still reach Disposed. Swift
    /// disposal does not throw, so the failure is not reported (ADR-0162 §2.2).
    func testLife018FailingMemberDoesNotStopTheCascade() throws {
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        let first = child("first")
        var cleanupRan = false
        first.own {
            cleanupRan = true
            throw HelperBoom()
        }
        let second = child("second")
        parent.ownMember(first)
        parent.ownMember(second)
        try parent.construct()

        parent.dispose()

        XCTAssertTrue(cleanupRan)
        XCTAssertEqual(first.status, .disposed)
        XCTAssertEqual(second.status, .disposed)
        XCTAssertEqual(parent.status, .disposed)
        XCTAssertEqual(log.disposedSenders, ["first", "second", "parent"])
    }

    /// LIFE-018 (late member) — a member registered after the parent reached
    /// Disposed is disposed when it is registered.
    func testLife018MemberRegisteredAfterDisposalIsDisposedAtOnce() {
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        parent.dispose()
        XCTAssertEqual(parent.status, .disposed)

        let late = child("late")
        let returned = parent.ownMember(late)

        XCTAssertTrue(returned === late)
        XCTAssertEqual(late.status, .disposed)
    }

    /// LIFE-019 — the helper destructs children in the order the caller
    /// passes, one at a time, and the parent publishes Destructed after the
    /// last one.
    func testLife019HelperDestructsInCallerOrder() throws {
        let a = child("a"), b = child("b"), c = child("c")
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        parent.constructChildren = [a, b, c]
        parent.destructChildren = [c, b, a]
        try parent.construct()
        XCTAssertEqual([a.status, b.status, c.status], [.constructed, .constructed, .constructed])
        log.clear()

        try parent.destruct()

        XCTAssertEqual(log.entries, [
            "parent:destructing",
            "c:destructing", "c:destructed",
            "b:destructing", "b:destructed",
            "a:destructing", "a:destructed",
            "parent:destructed",
        ])
    }

    /// LIFE-020 — the helper joins a child that is already in transit: no
    /// concurrent-operation error, the child's hook runs once, and the parent
    /// publishes Constructed only after the child does.
    func testLife020HelperJoinsChildInTransit() throws {
        var hookRuns = 0
        let a = child("a", background: true, onConstruct: { hookRuns += 1 })
        try a.construct()
        XCTAssertEqual(a.status, .constructing)
        let parent = HelperPanelVM(hub: hub, dispatcher: dispatcher)
        parent.constructChildren = [a]

        XCTAssertNoThrow(try parent.construct())
        XCTAssertEqual(parent.status, .constructing)

        pump()

        XCTAssertEqual(hookRuns, 1)
        XCTAssertEqual(a.status, .constructed)
        XCTAssertEqual(parent.status, .constructed)
        let aDone = try XCTUnwrap(log.index(of: "a:constructed"))
        let parentDone = try XCTUnwrap(log.index(of: "parent:constructed"))
        XCTAssertLessThan(aDone, parentDone)
    }
}
