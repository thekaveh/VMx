//
// ConstructWalkMembershipTests.swift — the construct walk of a composite or
// group counts members only (spec/06 §5.1, spec/07 §1.1, ADR-0186, #1313).
//
// Claimed IDs: COMP-047, GRP-015.
//
// Each test runs one removal case against a container built with
// auto-construct-on-add. A background anchor child keeps the walk waiting, and
// each child has its own `ManualDispatcher`, so the test decides when each
// background hook runs. A removed child does not change the container.
//
// NOTE: `swift test` needs full Xcode (XCTest); CI runs it on macos-15.
//
import XCTest
import Foundation
@testable import VMx

final class ConstructWalkMembershipTests: XCTestCase {
    private struct Boom: Error {}

    /// Counts construct hook runs.
    private final class Counter {
        private let lock = NSLock()
        private var count = 0
        func increment() { lock.withLock { count += 1 } }
        var value: Int { lock.withLock { count } }
    }

    /// One container under test, seen through closures.
    private struct Container {
        let vm: ComponentVMBase
        let add: (ComponentVM) -> Bool
        let remove: (ComponentVM) -> Bool
        let contains: (ComponentVM) -> Bool
        let setProbe: (((ComponentVMBase, LateChildStage) -> Void)?) -> Void
    }

    private func makeContainer(_ kind: String, children: [ComponentVM]) -> Container {
        if kind == "composite" {
            let composite = CompositeVM<ComponentVM>(
                name: "p", hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE,
                autoConstructOnAdd: true
            )
            for child in children { XCTAssertNoThrow(try composite.addResult(child).get()) }
            return Container(
                vm: composite,
                add: { if case .success = composite.addResult($0) { return true } else { return false } },
                remove: { composite.remove($0) },
                contains: { child in composite.snapshot().contains { $0 === child } },
                setProbe: { composite.lateChildProbeForTesting = $0 }
            )
        }
        let group = GroupVM<ComponentVM>(
            name: "g", hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE,
            autoConstructOnAdd: true
        )
        for child in children { XCTAssertNoThrow(try group.addResult(child).get()) }
        return Container(
            vm: group,
            add: { if case .success = group.addResult($0) { return true } else { return false } },
            remove: { group.remove($0) },
            contains: { child in group.snapshot().contains { $0 === child } },
            setProbe: { group.lateChildProbeForTesting = $0 }
        )
    }

    private func child(
        _ name: String,
        dispatcher: Dispatcher = ImmediateDispatcher.INSTANCE,
        background: Bool = false,
        failing: Bool = false,
        runs: Counter? = nil,
        hold: (entered: DispatchSemaphore, release: DispatchSemaphore)? = nil
    ) throws -> ComponentVM {
        try ComponentVM.builder()
            .name(name)
            .services(hub: NullMessageHub.INSTANCE, dispatcher: dispatcher)
            .background(background)
            .onConstruct {
                runs?.increment()
                if let hold {
                    hold.entered.signal()
                    _ = hold.release.wait(timeout: .now() + 5)
                }
                if failing { throw Boom() }
            }
            .build()
    }

    /// Runs the background hooks of `dispatcher` and their foreground
    /// completions until both queues are empty.
    private func settle(_ dispatcher: ManualDispatcher) {
        for _ in 0..<5 {
            dispatcher.flushBackground()
            dispatcher.flushForeground()
        }
    }

    // ── Shared cases ─────────────────────────────────────────────────────

    /// Case 1: a snapshot child removed before the walk reaches it.
    private func runSnapshotChildRemovedBeforeTheWalkReachesIt(_ kind: String) throws {
        let anchorDispatcher = ManualDispatcher()
        let anchor = try child("a", dispatcher: anchorDispatcher, background: true)
        let runs = Counter()
        let s = try child("s", failing: true, runs: runs)
        let p = makeContainer(kind, children: [anchor, s])

        XCTAssertNoThrow(try p.vm.construct(), kind)
        XCTAssertEqual(p.vm.status, .constructing, "\(kind): the walk waits on the anchor")
        XCTAssertTrue(p.remove(s), kind)
        settle(anchorDispatcher)

        XCTAssertEqual(p.vm.status, .constructed, kind)
        XCTAssertEqual(s.status, .destructed, kind)
        XCTAssertEqual(runs.value, 0, "\(kind): the walk never starts a removed snapshot child")
        XCTAssertFalse(p.contains(s), kind)
    }

    /// Case 2: the snapshot child the walk waits on is removed, then fails.
    private func runSnapshotChildRemovedWhileTheWalkWaitsOnIt(_ kind: String) throws {
        let dispatcher = ManualDispatcher()
        let a = try child("a", dispatcher: dispatcher, background: true, failing: true)
        let p = makeContainer(kind, children: [a])

        XCTAssertNoThrow(try p.vm.construct(), kind)
        XCTAssertEqual(p.vm.status, .constructing, kind)
        XCTAssertTrue(p.remove(a), kind)
        XCTAssertEqual(a.status, .constructing, "\(kind): a removal does not cancel the child")
        settle(dispatcher)

        XCTAssertEqual(p.vm.status, .constructed, kind)
        XCTAssertEqual(a.status, .destructed, kind)
        XCTAssertFalse(p.contains(a), kind)
    }

    /// Case 3: a late child the walk joined is removed, then fails.
    private func runLateChildRemovedWhileTheWalkWaitsOnIt(_ kind: String) throws {
        let anchorDispatcher = ManualDispatcher()
        let lateDispatcher = ManualDispatcher()
        let anchor = try child("a", dispatcher: anchorDispatcher, background: true)
        let p = makeContainer(kind, children: [anchor])
        XCTAssertNoThrow(try p.vm.construct(), kind)
        let late = try child("l", dispatcher: lateDispatcher, background: true, failing: true)
        XCTAssertTrue(p.add(late), kind)
        XCTAssertEqual(late.status, .constructing, "\(kind): the add starts the late child")
        settle(anchorDispatcher)
        XCTAssertEqual(p.vm.status, .constructing, "\(kind): the walk joined the late child")

        XCTAssertTrue(p.remove(late), kind)
        settle(lateDispatcher)

        XCTAssertEqual(p.vm.status, .constructed, kind)
        XCTAssertEqual(late.status, .destructed, kind)
        XCTAssertFalse(p.contains(late), kind)
    }

    /// Case 4: a late child removed before the walk reaches it.
    private func runLateChildRemovedBeforeTheWalkReachesIt(_ kind: String) throws {
        let anchorDispatcher = ManualDispatcher()
        let lateDispatcher = ManualDispatcher()
        let anchor = try child("a", dispatcher: anchorDispatcher, background: true)
        let p = makeContainer(kind, children: [anchor])
        XCTAssertNoThrow(try p.vm.construct(), kind)
        let late = try child("l", dispatcher: lateDispatcher, background: true, failing: true)
        XCTAssertTrue(p.add(late), kind)

        XCTAssertTrue(p.remove(late), kind)
        settle(lateDispatcher)
        settle(anchorDispatcher)

        XCTAssertEqual(p.vm.status, .constructed, kind)
        XCTAssertEqual(late.status, .destructed, kind)
        XCTAssertFalse(p.contains(late), kind)
    }

    /// A late child whose own construct fails during its add: the add fails
    /// and is undone, and the container still reaches Constructed. The walk
    /// waits on the add's start attempt while the child's hook fails.
    private func runLateChildWhoseAddFails(_ kind: String) throws {
        let anchorDispatcher = ManualDispatcher()
        let anchor = try child("a", dispatcher: anchorDispatcher, background: true)
        let p = makeContainer(kind, children: [anchor])
        XCTAssertNoThrow(try p.vm.construct(), kind)
        let runs = Counter()
        let entered = DispatchSemaphore(value: 0)
        let release = DispatchSemaphore(value: 0)
        let late = try child("l", failing: true, runs: runs, hold: (entered, release))
        let walkWaiting = DispatchSemaphore(value: 0)
        p.setProbe { child, stage in
            if child === late && stage == .walkWaitingOnAdd { walkWaiting.signal() }
        }
        defer { p.setProbe(nil) }
        let finished = DispatchSemaphore(value: 0)
        var added: Bool?
        let adder = Thread {
            added = p.add(late)
            finished.signal()
        }
        adder.start()

        XCTAssertEqual(entered.wait(timeout: .now() + 5), .success, "\(kind): the add starts the late child")
        settle(anchorDispatcher) // the anchor settles; the walk reaches the late child
        XCTAssertEqual(
            walkWaiting.wait(timeout: .now() + 5), .success, "\(kind): the walk waits on the add's attempt"
        )
        XCTAssertEqual(p.vm.status, .constructing, kind)
        release.signal() // the late child's hook fails now
        XCTAssertEqual(finished.wait(timeout: .now() + 5), .success, "\(kind): the failed add completes")
        settle(anchorDispatcher)

        XCTAssertEqual(added, false, "\(kind): the add fails")
        XCTAssertFalse(p.contains(late), "\(kind): the add is undone")
        XCTAssertEqual(p.vm.status, .constructed, kind)
        XCTAssertEqual(late.status, .destructed, kind)
        XCTAssertEqual(runs.value, 1, kind)
    }

    // ── COMP-047 ─────────────────────────────────────────────────────────

    /// COMP-047 — a snapshot child removed before the walk reaches it is
    /// never started, and the composite reaches Constructed.
    func testCOMP047SnapshotChildRemovedBeforeTheWalkReachesIt() throws {
        try runSnapshotChildRemovedBeforeTheWalkReachesIt("composite")
    }

    /// COMP-047 — a snapshot child removed while the walk waits on it does
    /// not roll the composite back when it fails.
    func testCOMP047SnapshotChildRemovedWhileTheWalkWaitsOnIt() throws {
        try runSnapshotChildRemovedWhileTheWalkWaitsOnIt("composite")
    }

    /// COMP-047 — a late child removed while the walk waits on it does not
    /// roll the composite back when it fails.
    func testCOMP047LateChildRemovedWhileTheWalkWaitsOnIt() throws {
        try runLateChildRemovedWhileTheWalkWaitsOnIt("composite")
    }

    /// COMP-047 — a late child removed before the walk reaches it is skipped.
    func testCOMP047LateChildRemovedBeforeTheWalkReachesIt() throws {
        try runLateChildRemovedBeforeTheWalkReachesIt("composite")
    }

    /// COMP-047 — a late child whose add fails leaves the composite to reach
    /// Constructed.
    func testCOMP047LateChildWhoseAddFails() throws {
        try runLateChildWhoseAddFails("composite")
    }

    // ── GRP-015 ──────────────────────────────────────────────────────────

    /// GRP-015 — a snapshot child removed before the walk reaches it is
    /// never started, and the group reaches Constructed.
    func testGRP015SnapshotChildRemovedBeforeTheWalkReachesIt() throws {
        try runSnapshotChildRemovedBeforeTheWalkReachesIt("group")
    }

    /// GRP-015 — a snapshot child removed while the walk waits on it does
    /// not roll the group back when it fails.
    func testGRP015SnapshotChildRemovedWhileTheWalkWaitsOnIt() throws {
        try runSnapshotChildRemovedWhileTheWalkWaitsOnIt("group")
    }

    /// GRP-015 — a late child removed while the walk waits on it does not
    /// roll the group back when it fails.
    func testGRP015LateChildRemovedWhileTheWalkWaitsOnIt() throws {
        try runLateChildRemovedWhileTheWalkWaitsOnIt("group")
    }

    /// GRP-015 — a late child removed before the walk reaches it is skipped.
    func testGRP015LateChildRemovedBeforeTheWalkReachesIt() throws {
        try runLateChildRemovedBeforeTheWalkReachesIt("group")
    }

    /// GRP-015 — a late child whose add fails leaves the group to reach
    /// Constructed.
    func testGRP015LateChildWhoseAddFails() throws {
        try runLateChildWhoseAddFails("group")
    }
}
