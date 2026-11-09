//
// ConstructStartRaceTests.swift — #1370 and #1375 regression tests.
//
// A walk and an auto-construct add each read a child's status and then start
// the child. When the other side starts the child between the two steps,
// the walk joins that transition and the add leaves it to the walk (spec/02
// §6, spec/06 §5.1, ADR-0218 rule 6). Neither fails when no child
// construction failed. Test-only seams hold each side between its status
// read and its start call. Every wait is bounded, so a regression fails
// instead of hanging.
//
import Combine
import Foundation
import XCTest
@testable import VMx

final class ConstructStartRaceTests: XCTestCase {
    /// A thread-safe counter.
    private final class Counter: @unchecked Sendable {
        private let lock = NSLock()
        private var count = 0
        func increment() { lock.withLock { count += 1 } }
        var value: Int { lock.withLock { count } }
    }

    /// The operations the tests need from a composite or a group.
    private struct Container {
        let vm: ComponentVMBase
        let add: (ComponentVM) -> Bool
        let contains: (ComponentVM) -> Bool
        let setProbe: (((ComponentVMBase, LateChildStage) -> Void)?) -> Void
    }

    private func makeContainer(
        _ kind: String,
        hub: MessageHub,
        dispatcher: Dispatcher,
        hook: (() -> Void)? = nil
    ) -> Container {
        if kind == "composite" {
            let vm = CompositeVM<ComponentVM>(
                name: kind, hub: hub, dispatcher: dispatcher,
                onConstruct: hook, autoConstructOnAdd: true
            )
            return Container(
                vm: vm,
                add: { if case .success = vm.addResult($0) { return true } else { return false } },
                contains: { child in vm.snapshot().contains { $0 === child } },
                setProbe: { vm.lateChildProbeForTesting = $0 }
            )
        }
        let vm = GroupVM<ComponentVM>(
            name: kind, hub: hub, dispatcher: dispatcher,
            onConstruct: hook, autoConstructOnAdd: true
        )
        return Container(
            vm: vm,
            add: { if case .success = vm.addResult($0) { return true } else { return false } },
            contains: { child in vm.snapshot().contains { $0 === child } },
            setProbe: { vm.lateChildProbeForTesting = $0 }
        )
    }

    private func backgroundChild(
        hub: MessageHub,
        dispatcher: Dispatcher,
        constructs: Counter,
        destructs: Counter = Counter()
    ) throws -> ComponentVM {
        try ComponentVM.builder()
            .name("x").services(hub: hub, dispatcher: dispatcher).background(true)
            .onConstruct { constructs.increment() }
            .onDestruct { destructs.increment() }
            .build()
    }

    private func waitUntil(_ condition: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(hangGuard)
        while !condition() {
            if Date() >= deadline { return false }
            usleep(1_000)
        }
        return true
    }

    private func pump(_ dispatcher: ManualDispatcher) {
        for _ in 0..<10 {
            dispatcher.flushBackground()
            dispatcher.flushForeground()
        }
    }

    /// The add loses: the add read `x` as `Destructed`, and the walk starts
    /// `x` before the add calls `construct()`. The add leaves the construct
    /// to the walk and succeeds; the container constructs.
    func testAddThatLosesTheStartLeavesItToTheWalk() throws {
        for kind in ["composite", "group"] {
            let hub = MessageHub()
            let dispatcher = ManualDispatcher()
            let attached = DispatchSemaphore(value: 0)
            let hookEntered = DispatchSemaphore(value: 0)
            let container = makeContainer(kind, hub: hub, dispatcher: dispatcher) {
                hookEntered.signal()
                _ = attached.wait(timeout: .now() + hangGuard)
            }
            let constructs = Counter()
            let x = try backgroundChild(hub: hub, dispatcher: dispatcher, constructs: constructs)
            container.setProbe { child, stage in
                guard child === x else { return }
                if stage == .attached { attached.signal() }
                if stage == .starting { _ = self.waitUntil { x.status == .constructing } }
            }
            defer { container.setProbe(nil) }

            let constructed = DispatchSemaphore(value: 0)
            var constructError: Error?
            DispatchQueue.global().async {
                do { try container.vm.construct() } catch { constructError = error }
                constructed.signal()
            }
            // Add while the container's construct hook runs, before its walk
            // takes the snapshot.
            XCTAssertEqual(hookEntered.wait(timeout: .now() + hangGuard), .success, kind)
            let added = container.add(x)
            XCTAssertEqual(constructed.wait(timeout: .now() + hangGuard), .success, kind)
            pump(dispatcher)

            XCTAssertNil(constructError, kind)
            XCTAssertTrue(added, "\(kind): the add succeeds")
            XCTAssertTrue(container.contains(x), kind)
            XCTAssertEqual(x.status, .constructed, kind)
            XCTAssertEqual(container.vm.status, .constructed, kind)
            XCTAssertEqual(constructs.value, 1, kind)
        }
    }

    /// The walk loses: the walk read `x` as `Destructed`, and the add starts
    /// `x` before the walk calls `construct()`. The walk joins that construct
    /// and the container constructs.
    func testWalkThatLosesTheStartJoinsTheChild() throws {
        for kind in ["composite", "group"] {
            let hub = MessageHub()
            let dispatcher = ManualDispatcher()
            let attached = DispatchSemaphore(value: 0)
            let walkRead = DispatchSemaphore(value: 0)
            let hookEntered = DispatchSemaphore(value: 0)
            let container = makeContainer(kind, hub: hub, dispatcher: dispatcher) {
                hookEntered.signal()
                _ = attached.wait(timeout: .now() + hangGuard)
            }
            let constructs = Counter()
            let x = try backgroundChild(hub: hub, dispatcher: dispatcher, constructs: constructs)
            container.setProbe { child, stage in
                guard child === x, stage == .attached else { return }
                attached.signal()
                _ = walkRead.wait(timeout: .now() + hangGuard)
            }
            container.vm.childStartProbeForTesting = { child in
                guard child === x else { return }
                walkRead.signal()
                _ = self.waitUntil { x.status == .constructing }
            }
            defer {
                container.setProbe(nil)
                container.vm.childStartProbeForTesting = nil
            }

            let constructed = DispatchSemaphore(value: 0)
            var constructError: Error?
            DispatchQueue.global().async {
                do { try container.vm.construct() } catch { constructError = error }
                constructed.signal()
            }
            // Add while the container's construct hook runs, before its walk
            // takes the snapshot.
            XCTAssertEqual(hookEntered.wait(timeout: .now() + hangGuard), .success, kind)
            let added = container.add(x)
            XCTAssertEqual(constructed.wait(timeout: .now() + hangGuard), .success, kind)
            pump(dispatcher)

            XCTAssertNil(constructError, "\(kind): the container construct does not fail")
            XCTAssertTrue(added, kind)
            XCTAssertTrue(container.contains(x), kind)
            XCTAssertEqual(x.status, .constructed, kind)
            XCTAssertEqual(container.vm.status, .constructed, kind)
            XCTAssertEqual(constructs.value, 1, kind)
        }
    }

    /// #1375 — the destruct walk read `x` as `Constructed`, and another
    /// thread starts `x`'s destruct before the walk calls `destruct()`. The
    /// walk joins that destruct; both reach `Destructed`.
    func testDestructWalkThatLosesTheStartJoinsTheChild() throws {
        for kind in ["composite", "group"] {
            let hub = MessageHub()
            let dispatcher = ManualDispatcher()
            let container = makeContainer(kind, hub: hub, dispatcher: dispatcher)
            let constructs = Counter()
            let destructs = Counter()
            let x = try backgroundChild(
                hub: hub, dispatcher: dispatcher, constructs: constructs, destructs: destructs
            )
            try container.vm.construct()
            XCTAssertTrue(container.add(x), kind)
            pump(dispatcher)
            XCTAssertEqual(x.status, .constructed, kind)
            container.vm.childStartProbeForTesting = { child in
                guard child === x else { return }
                let started = DispatchSemaphore(value: 0)
                DispatchQueue.global().async {
                    try? x.destruct()
                    started.signal()
                }
                _ = started.wait(timeout: .now() + hangGuard)
            }
            defer { container.vm.childStartProbeForTesting = nil }

            XCTAssertNoThrow(try container.vm.destruct(), kind)
            pump(dispatcher)

            XCTAssertEqual(x.status, .destructed, kind)
            XCTAssertEqual(container.vm.status, .destructed, kind)
            XCTAssertEqual(destructs.value, 1, kind)
        }
    }
}
