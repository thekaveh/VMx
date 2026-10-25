//
// Late-child start tests (spec/06 §5.1, spec/02 §6).
//
// With auto-construct-on-add, the construct walk of a composite or group
// joins each child added while it runs. An add attaches the child under the
// membership gate and starts it only after it releases the gate, so the walk
// can pull the child in that gap. These tests pause a cross-thread add in that
// gap through the test-only `lateChildProbeForTesting` seam and check that
// the walk never starts the child: it waits until the add's start attempt is
// done, then joins the child, instead of failing the container. Every wait is
// bounded, so a regression fails instead of hanging.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
import Foundation
@testable import VMx

final class LateChildStartTests: XCTestCase {
    private struct Boom: Error {}

    /// The bound on every wait in these tests, in seconds.
    private let bound: TimeInterval = 5

    /// A thread-safe log of `sender:status` entries and a hook-run counter.
    private final class Recorder {
        private let lock = NSLock()
        private var entries: [String] = []
        private var count = 0

        func append(_ entry: String) { lock.withLock { entries.append(entry) } }
        var snapshot: [String] { lock.withLock { entries } }
        func increment() { lock.withLock { count += 1 } }
        var runs: Int { lock.withLock { count } }
    }

    /// A thread-safe flag.
    private final class Flag {
        private let lock = NSLock()
        private var value = false
        func set() { lock.withLock { value = true } }
        var isSet: Bool { lock.withLock { value } }
    }

    private struct Harness {
        let hub: MessageHub
        let dispatcher: ManualDispatcher
        let root: ComponentVMBase
        let add: (ComponentVM) -> Bool
        let contains: (ComponentVM) -> Bool
        let setProbe: (((ComponentVMBase, LateChildStage) -> Void)?) -> Void
        let log: Recorder
        let subscription: AnyCancellable
    }

    /// A container with auto-construct-on-add whose one factory child is a
    /// background child, so `construct()` leaves the container Constructing.
    private func makeHarness(_ kind: String) throws -> Harness {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let log = Recorder()
        let subscription = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .sink { log.append("\($0.senderName):\($0.status)") }
        let first = try ComponentVM.builder()
            .name("first")
            .services(hub: hub, dispatcher: dispatcher)
            .background(true)
            .build()
        if kind == "composite" {
            let root = CompositeVM<ComponentVM>(
                name: "root", hub: hub, dispatcher: dispatcher,
                childrenFactory: { [first] }, autoConstructOnAdd: true
            )
            return Harness(
                hub: hub, dispatcher: dispatcher, root: root,
                add: { child in
                    if case .success = root.addResult(child) { return true }
                    return false
                },
                contains: { child in root.snapshot().contains { $0 === child } },
                setProbe: { root.lateChildProbeForTesting = $0 },
                log: log, subscription: subscription
            )
        }
        let root = GroupVM<ComponentVM>(
            name: "root", hub: hub, dispatcher: dispatcher,
            childrenFactory: { [first] }, autoConstructOnAdd: true
        )
        return Harness(
            hub: hub, dispatcher: dispatcher, root: root,
            add: { child in
                if case .success = root.addResult(child) { return true }
                return false
            },
            contains: { child in root.snapshot().contains { $0 === child } },
            setProbe: { root.lateChildProbeForTesting = $0 },
            log: log, subscription: subscription
        )
    }

    private func lateChild(
        _ harness: Harness,
        runs: Recorder,
        failing: Bool = false,
        during: @escaping () -> Void = {}
    ) throws -> ComponentVM {
        try ComponentVM.builder()
            .name("late")
            .services(hub: harness.hub, dispatcher: harness.dispatcher)
            .onConstruct {
                runs.increment()
                during()
                if failing { throw Boom() }
            }
            .build()
    }

    /// Spins until `condition` holds or the bound elapses; returns whether it held.
    private func waitUntil(_ condition: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(bound)
        while !condition() {
            if Date() >= deadline { return false }
            usleep(1_000)
        }
        return true
    }

    /// Runs background hooks and their foreground completions until quiescent.
    private func pump(_ harness: Harness) {
        for _ in 0..<10 {
            harness.dispatcher.flushBackground()
            harness.dispatcher.flushForeground()
        }
    }

    /// Adds `late` on another thread and pauses that add at `pauseAt`, after
    /// it attached the Destructed child and before it started it, until
    /// `resume` holds or the root left Constructing. Settles the original
    /// child meanwhile, so the construct walk pulls `late` in that gap.
    /// Returns whether the add succeeded, or `nil` when it did not finish.
    private func addPausedWhileWalkPulls(
        _ harness: Harness,
        _ late: ComponentVM,
        pauseAt: LateChildStage,
        onProbe: ((ComponentVMBase, LateChildStage) -> Void)? = nil,
        resume: @escaping () -> Bool,
        _ kind: String
    ) -> Bool? {
        let paused = DispatchSemaphore(value: 0)
        let finished = DispatchSemaphore(value: 0)
        let bound = self.bound
        let root = harness.root
        var pausedStatuses: (root: ConstructionStatus, late: ConstructionStatus)?
        var added: Bool?
        harness.setProbe { child, stage in
            onProbe?(child, stage)
            guard child === late, stage == pauseAt else { return }
            pausedStatuses = (root.status, late.status)
            paused.signal()
            let deadline = Date().addingTimeInterval(bound)
            while !resume() && root.status == .constructing && Date() < deadline {
                usleep(1_000)
            }
        }
        defer { harness.setProbe(nil) }
        let adder = Thread {
            added = harness.add(late)
            finished.signal()
        }
        adder.start()
        XCTAssertEqual(paused.wait(timeout: .now() + bound), .success, "\(kind): add paused")
        XCTAssertEqual(pausedStatuses?.root, .constructing, kind)
        XCTAssertEqual(pausedStatuses?.late, .destructed, kind)

        pump(harness) // the original child settles; the walk pulls `late`
        guard finished.wait(timeout: .now() + bound) == .success else {
            XCTFail("\(kind): the paused add did not finish")
            return nil
        }
        pump(harness)
        return added
    }

    private func assertConstructedAfterLate(
        _ harness: Harness,
        _ late: ComponentVM,
        _ kind: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertEqual(harness.root.status, .constructed, kind, file: file, line: line)
        XCTAssertEqual(late.status, .constructed, kind, file: file, line: line)
        let log = harness.log.snapshot
        guard let lateConstructed = log.firstIndex(of: "late:constructed") else {
            return XCTFail("\(kind): late never published constructed", file: file, line: line)
        }
        let rootConstructed = log.firstIndex(of: "root:constructed") ?? -1
        XCTAssertGreaterThan(rootConstructed, lateConstructed, kind, file: file, line: line)
        XCTAssertEqual(
            log.filter { $0 == "late:constructing" }.count, 1, kind, file: file, line: line
        )
    }


    /// Walk first: the walk pulls a late child whose add is paused before its
    /// start attempt. The walk does not start the child: it waits for the
    /// add's attempt, then joins the child.
    func testWalkWaitsForAddsStartAttemptThenJoins() throws {
        for kind in ["composite", "group"] {
            let harness = try makeHarness(kind)
            try harness.root.construct()
            XCTAssertEqual(harness.root.status, .constructing, kind)
            let runs = Recorder()
            let late = try lateChild(harness, runs: runs)
            let walkWaiting = Flag()

            let added = addPausedWhileWalkPulls(
                harness, late, pauseAt: .attached,
                onProbe: { child, stage in
                    if child === late && stage == .walkWaitingOnAdd { walkWaiting.set() }
                },
                resume: { walkWaiting.isSet }, kind
            )

            XCTAssertEqual(added, true, kind)
            assertConstructedAfterLate(harness, late, kind)
            XCTAssertTrue(walkWaiting.isSet, "\(kind): the walk waited for the add")
            XCTAssertEqual(runs.runs, 1, kind)
        }
    }

    /// Add first: the add's start attempt is in flight (the late construct
    /// hook blocks on the add thread) when the walk pulls the child. The walk
    /// waits for that attempt, then joins the child. This also holds before
    /// the fix, where the walk joined the in-flight child directly.
    func testWalkJoinsLateChildWhoseAddIsStartingIt() throws {
        for kind in ["composite", "group"] {
            let harness = try makeHarness(kind)
            try harness.root.construct()
            let runs = Recorder()
            let inHook = DispatchSemaphore(value: 0)
            let releaseHook = DispatchSemaphore(value: 0)
            let bound = self.bound
            let late = try lateChild(harness, runs: runs, during: {
                inHook.signal()
                _ = releaseHook.wait(timeout: .now() + bound)
            })
            let walkWaiting = Flag()
            harness.setProbe { child, stage in
                if child === late && stage == .walkWaitingOnAdd { walkWaiting.set() }
            }
            defer { harness.setProbe(nil) }
            let finished = DispatchSemaphore(value: 0)
            var added: Bool?
            let adder = Thread {
                added = harness.add(late)
                finished.signal()
            }
            adder.start()
            XCTAssertEqual(inHook.wait(timeout: .now() + bound), .success, kind)
            XCTAssertEqual(late.status, .constructing, kind)

            pump(harness) // the original child settles; the walk pulls `late`
            _ = waitUntil { walkWaiting.isSet }
            XCTAssertEqual(harness.root.status, .constructing, kind)
            releaseHook.signal()
            XCTAssertEqual(finished.wait(timeout: .now() + bound), .success, kind)
            pump(harness)

            XCTAssertEqual(added, true, kind)
            assertConstructedAfterLate(harness, late, kind)
            XCTAssertEqual(runs.runs, 1, kind)
        }
    }

    /// A late child whose add-started construct fails while the walk waits on
    /// it: the add fails and is undone, and the container rolls back.
    func testFailedAddStartedLateChildFailsAddAndRollsBack() throws {
        for kind in ["composite", "group"] {
            let harness = try makeHarness(kind)
            try harness.root.construct()
            let runs = Recorder()
            let late = try lateChild(harness, runs: runs, failing: true)
            let walkWaiting = Flag()

            let added = addPausedWhileWalkPulls(
                harness, late, pauseAt: .attached,
                onProbe: { child, stage in
                    if child === late && stage == .walkWaitingOnAdd { walkWaiting.set() }
                },
                resume: { walkWaiting.isSet }, kind
            )

            XCTAssertEqual(added, false, "\(kind): the add fails")
            XCTAssertFalse(harness.contains(late), "\(kind): the add is undone")
            XCTAssertEqual(late.status, .destructed, kind)
            XCTAssertEqual(harness.root.status, .destructed, kind)
            XCTAssertEqual(runs.runs, 1, kind)
        }
    }

    /// A composite whose construct hook runs `afterWalk` after the child walk,
    /// while the composite is still Constructing.
    private final class AfterWalkComposite: CompositeVM<ComponentVM> {
        var afterWalk: (() -> Void)?
        override func _onConstruct() throws {
            try super._onConstruct()
            afterWalk?()
        }
    }

    /// A group whose construct hook runs `afterWalk` after the child walk,
    /// while the group is still Constructing.
    private final class AfterWalkGroup: GroupVM<ComponentVM> {
        var afterWalk: (() -> Void)?
        override func _onConstruct() throws {
            try super._onConstruct()
            afterWalk?()
        }
    }

    /// An add that attaches a child after the walk's last late pull, while
    /// the container is still Constructing, keeps no start record: the walk's
    /// records ended with it. The add still constructs the child.
    func testAddAfterTheWalksLastPullKeepsNoStartRecord() throws {
        for kind in ["composite", "group"] {
            let hub = MessageHub()
            let dispatcher = ManualDispatcher()
            let first = try ComponentVM.builder()
                .name("first").services(hub: hub, dispatcher: dispatcher).build()
            let late = try ComponentVM.builder()
                .name("late").services(hub: hub, dispatcher: dispatcher).build()
            let root: ComponentVMBase
            let records: () -> Int
            var statusAtAdd: ConstructionStatus?
            var added = false
            if kind == "composite" {
                let composite = AfterWalkComposite(
                    name: "root", hub: hub, dispatcher: dispatcher,
                    childrenFactory: { [first] }, autoConstructOnAdd: true
                )
                composite.afterWalk = { [unowned composite] in
                    statusAtAdd = composite.status
                    if case .success = composite.addResult(late) { added = true }
                }
                root = composite
                records = { composite.lateStartRecordCountForTesting }
            } else {
                let group = AfterWalkGroup(
                    name: "root", hub: hub, dispatcher: dispatcher,
                    childrenFactory: { [first] }, autoConstructOnAdd: true
                )
                group.afterWalk = { [unowned group] in
                    statusAtAdd = group.status
                    if case .success = group.addResult(late) { added = true }
                }
                root = group
                records = { group.lateStartRecordCountForTesting }
            }

            try root.construct()

            XCTAssertEqual(statusAtAdd, .constructing, "\(kind): the add ran after the walk")
            XCTAssertTrue(added, kind)
            XCTAssertEqual(late.status, .constructed, "\(kind): the add constructs the child")
            XCTAssertEqual(root.status, .constructed, kind)
            XCTAssertEqual(records(), 0, "\(kind): no start record outlives its walk")
        }
    }
}
