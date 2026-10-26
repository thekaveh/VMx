//
// Final late-child tests (spec/06 §5.1, spec/02 §6).
//
// With auto-construct-on-add, a child added while the container is still
// `.constructing` is started, and the container reaches `.constructed` only
// after that child does. These tests add a background child after the
// construct walk's last late pull and before the container's commit: from
// the composite's current selector, or, for a group, from the test-only
// `.lastScanDone` probe. They add both on the walk's own thread and from
// another thread, and check that the container publishes `.constructed`
// only once the late child is `.constructed`. Every wait is bounded, so a
// regression fails instead of hanging.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
import Foundation
@testable import VMx

final class FinalLateChildTests: XCTestCase {
    /// The bound on every wait in these tests, in seconds.
    private let bound: TimeInterval = 5

    /// Runs foreground work inline and queues background work, so a test
    /// decides when each background hook runs.
    private final class StepDispatcher: Dispatcher {
        private let lock = NSLock()
        private var background: [() -> Void] = []

        func scheduleForeground(_ work: @escaping () -> Void) { work() }

        func scheduleBackground(_ work: @escaping () -> Void) {
            lock.withLock { background.append(work) }
        }

        var pendingBackground: Int { lock.withLock { background.count } }

        /// Runs the oldest queued background item; returns whether one ran.
        @discardableResult
        func runNextBackground() -> Bool {
            let work: (() -> Void)? = lock.withLock {
                background.isEmpty ? nil : background.removeFirst()
            }
            work?()
            return work != nil
        }
    }

    /// A thread-safe counter and value box.
    private final class Box<Value> {
        private let lock = NSLock()
        private var stored: Value
        init(_ value: Value) { stored = value }
        var value: Value {
            get { lock.withLock { stored } }
            set { lock.withLock { stored = newValue } }
        }
    }

    private struct Scenario {
        let root: ComponentVMBase
        let late: ComponentVM
        let dispatcher: StepDispatcher
        let lateRuns: Box<Int>
        let pullRuns: Box<Int>
        let added: Box<Bool?>
        let addTimedOut: Box<Bool>
        /// The late child's status each time the root publishes `.constructed`.
        let lateAtRootConstructed: Box<[ConstructionStatus]>
        let subscription: AnyCancellable
    }

    /// Builds a container (one background factory child, auto-construct on)
    /// that adds a background `late` child once, after the walk's last late
    /// pull: from the selector (composite) or the `.lastScanDone` probe
    /// (group); on the walk's thread or from another thread.
    private func makeScenario(kind: String, crossThread: Bool) throws -> Scenario {
        let hub = MessageHub()
        let dispatcher = StepDispatcher()
        let first = try ComponentVM.builder()
            .name("first").services(hub: hub, dispatcher: dispatcher)
            .background(true).build()
        let lateRuns = Box(0)
        let late = try ComponentVM.builder()
            .name("late").services(hub: hub, dispatcher: dispatcher)
            .background(true)
            .onConstruct { lateRuns.value += 1 }
            .build()
        let pullRuns = Box(0)
        let added = Box<Bool?>(nil)
        let addTimedOut = Box(false)
        let bound = self.bound

        var addToRoot: (() -> Bool)!
        let addLate: () -> Void = {
            guard added.value == nil else { return }
            added.value = false
            if crossThread {
                let done = DispatchSemaphore(value: 0)
                let result = Box(false)
                Thread {
                    result.value = addToRoot()
                    done.signal()
                }.start()
                if done.wait(timeout: .now() + bound) == .timedOut {
                    addTimedOut.value = true
                    return
                }
                added.value = result.value
            } else {
                added.value = addToRoot()
            }
        }

        let root: ComponentVMBase
        if kind == "composite" {
            var composite: CompositeVM<ComponentVM>!
            composite = CompositeVM<ComponentVM>(
                name: "root", hub: hub, dispatcher: dispatcher,
                childrenFactory: { [first] },
                currentSelector: { _ in
                    pullRuns.value += 1
                    addLate()
                    return nil
                },
                autoConstructOnAdd: true
            )
            addToRoot = { [unowned composite] in
                if case .success = composite!.addResult(late) { return true }
                return false
            }
            root = composite
        } else {
            let group = GroupVM<ComponentVM>(
                name: "root", hub: hub, dispatcher: dispatcher,
                childrenFactory: { [first] }, autoConstructOnAdd: true
            )
            addToRoot = { [unowned group] in
                if case .success = group.addResult(late) { return true }
                return false
            }
            group.lateChildProbeForTesting = { child, stage in
                // Every empty late pull fires the probe; only the first adds.
                guard stage == .lastScanDone, child === group,
                      added.value == nil else { return }
                pullRuns.value += 1
                addLate()
            }
            root = group
        }

        let lateAtRootConstructed = Box<[ConstructionStatus]>([])
        let subscription = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .filter { $0.senderName == "root" && $0.status == .constructed }
            .sink { _ in lateAtRootConstructed.value.append(late.status) }
        return Scenario(
            root: root, late: late, dispatcher: dispatcher,
            lateRuns: lateRuns, pullRuns: pullRuns, added: added,
            addTimedOut: addTimedOut,
            lateAtRootConstructed: lateAtRootConstructed,
            subscription: subscription
        )
    }

    private func assertRootWaitsForFinalLateChild(kind: String, crossThread: Bool) throws {
        let label = "\(kind), \(crossThread ? "cross-thread" : "same-thread")"
        let scenario = try makeScenario(kind: kind, crossThread: crossThread)
        try scenario.root.construct()
        XCTAssertEqual(scenario.root.status, .constructing, label)

        // The original child settles; the walk's last pull finds nothing and
        // the late child is added before the commit.
        XCTAssertTrue(scenario.dispatcher.runNextBackground(), label)
        XCTAssertFalse(scenario.addTimedOut.value, "\(label): the add completes")
        XCTAssertEqual(scenario.added.value, true, "\(label): the add succeeds")
        XCTAssertEqual(scenario.late.status, .constructing, "\(label): the add started it")
        XCTAssertEqual(
            scenario.root.status, .constructing,
            "\(label): the root waits for the late child"
        )
        XCTAssertEqual(scenario.lateAtRootConstructed.value, [], label)

        // The late child settles; only then does the root commit.
        XCTAssertTrue(scenario.dispatcher.runNextBackground(), label)
        XCTAssertEqual(scenario.late.status, .constructed, label)
        XCTAssertEqual(scenario.root.status, .constructed, label)
        XCTAssertEqual(
            scenario.lateAtRootConstructed.value, [.constructed],
            "\(label): the root publishes .constructed once, after the late child"
        )
        XCTAssertEqual(scenario.lateRuns.value, 1, "\(label): the late hook runs once")
        XCTAssertEqual(scenario.pullRuns.value, 1, "\(label): the selector (or the adding probe) runs once")
        XCTAssertEqual(scenario.dispatcher.pendingBackground, 0, label)
    }

    func testCompositeWaitsForChildAddedFromSelectorOnWalkThread() throws {
        try assertRootWaitsForFinalLateChild(kind: "composite", crossThread: false)
    }

    func testCompositeWaitsForChildAddedFromAnotherThreadDuringSelector() throws {
        try assertRootWaitsForFinalLateChild(kind: "composite", crossThread: true)
    }

    func testGroupWaitsForChildAddedAfterLastPullOnWalkThread() throws {
        try assertRootWaitsForFinalLateChild(kind: "group", crossThread: false)
    }

    func testGroupWaitsForChildAddedFromAnotherThreadAfterLastPull() throws {
        try assertRootWaitsForFinalLateChild(kind: "group", crossThread: true)
    }

    /// An add after the root published `.constructed` follows the
    /// add-after-Constructed rule: the child is constructed before the add's
    /// collection change, and the root stays `.constructed`.
    func testAddAfterConstructedConstructsBeforeCollectionChange() throws {
        for kind in ["composite", "group"] {
            let hub = MessageHub()
            let dispatcher = StepDispatcher()
            let late = try ComponentVM.builder()
                .name("late").services(hub: hub, dispatcher: dispatcher).build()
            let statusAtChange = Box<ConstructionStatus?>(nil)
            let root: ComponentVMBase
            let add: () -> Bool
            var cancellables: [AnyCancellable] = []
            if kind == "composite" {
                let composite = CompositeVM<ComponentVM>(
                    name: "root", hub: hub, dispatcher: dispatcher, autoConstructOnAdd: true
                )
                composite.collectionChanged
                    .sink { _ in statusAtChange.value = late.status }
                    .store(in: &cancellables)
                add = {
                    if case .success = composite.addResult(late) { return true }
                    return false
                }
                root = composite
            } else {
                let group = GroupVM<ComponentVM>(
                    name: "root", hub: hub, dispatcher: dispatcher, autoConstructOnAdd: true
                )
                group.collectionChanged
                    .sink { _ in statusAtChange.value = late.status }
                    .store(in: &cancellables)
                add = {
                    if case .success = group.addResult(late) { return true }
                    return false
                }
                root = group
            }
            try root.construct()
            XCTAssertEqual(root.status, .constructed, kind)
            XCTAssertTrue(add(), kind)
            XCTAssertEqual(statusAtChange.value, .constructed, kind)
            XCTAssertEqual(root.status, .constructed, kind)
        }
    }
}
