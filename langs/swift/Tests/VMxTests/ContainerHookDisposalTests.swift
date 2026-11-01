//
// ContainerHookDisposalTests.swift — #1062 regression tests.
//
// A container's child cascade runs at the same admitted-hook boundary as its
// own `dispose()` (LIFE-015). A `dispose()` from another thread disposes no
// child while the container's admitted construct hook runs. With no hook
// running, the children are still disposed before the container publishes
// `.disposed` (LIFE-013). Every wait is bounded, so a regression fails instead
// of hanging the suite.
//

import Combine
import Foundation
import XCTest
@testable import VMx

private let hookTimeout: TimeInterval = 5

/// An ordered log shared with the test threads.
private final class EventLog: @unchecked Sendable {
    private let lock = NSLock()
    private var entries: [String] = []
    func add(_ entry: String) { lock.withLock { entries.append(entry) } }
    var all: [String] { lock.withLock { entries } }
    func index(_ entry: String) -> Int? { all.firstIndex(of: entry) }
}

/// A child that logs `cleanup:<name>` from `_onDispose()`.
private final class CleanupProbe: ComponentVM {
    let log: EventLog
    private let lock = NSLock()
    private var disposals = 0
    private var cleanupAction: (() -> Void)?
    var cleanups: Int { lock.withLock { disposals } }
    /// Runs inside `_onDispose()`, after the log entry.
    var onCleanup: (() -> Void)? {
        get { lock.withLock { cleanupAction } }
        set { lock.withLock { cleanupAction = newValue } }
    }

    init(_ name: String, hub: MessageHubProtocol, log: EventLog) {
        self.log = log
        super.init(name: name, hub: hub, dispatcher: NullDispatcher.INSTANCE)
    }

    override func _onDispose() {
        lock.withLock { disposals += 1 }
        log.add("cleanup:\(name)")
        onCleanup?()
        super._onDispose()
    }
}

/// The operations the tests need from a composite or a group.
private struct Container {
    let vm: ComponentVMBase
    let add: (CleanupProbe) -> Void

    static func make(
        _ kind: String,
        hub: MessageHubProtocol,
        factory: Bool,
        hook: @escaping () throws -> Void
    ) -> Container {
        if kind == "composite" {
            let vm = CompositeVM<CleanupProbe>(
                name: kind, hub: hub, dispatcher: NullDispatcher.INSTANCE,
                childrenFactory: factory ? { [] } : nil, onConstruct: hook)
            return Container(vm: vm, add: { vm.add($0) })
        }
        let vm = GroupVM<CleanupProbe>(
            name: kind, hub: hub, dispatcher: NullDispatcher.INSTANCE,
            childrenFactory: factory ? { [] } : nil, onConstruct: hook)
        return Container(vm: vm, add: { vm.add($0) })
    }
}

final class ContainerHookDisposalTests: XCTestCase {
    /// A `dispose()` on another thread while the container's construct hook
    /// blocks: no child is disposed until the hook returns.
    private func assertChildCascadeWaitsForTheHook(
        _ kind: String, factory: Bool, reconstructFirst: Bool
    ) {
        let label = "\(kind) factory=\(factory) reconstructFirst=\(reconstructFirst)"
        let hub = MessageHub()
        let log = EventLog()
        let entered = DispatchSemaphore(value: 0)
        let release = DispatchSemaphore(value: 0)
        let gate = NSLock()
        var blocking = false
        let container = Container.make(kind, hub: hub, factory: factory) {
            guard gate.withLock({ blocking }) else { return }
            log.add("hook-enter")
            entered.signal()
            _ = release.wait(timeout: .now() + hookTimeout)
            log.add("hook-exit")
        }
        let first = CleanupProbe("first", hub: hub, log: log)
        let second = CleanupProbe("second", hub: hub, log: log)
        container.add(first)
        container.add(second)
        if reconstructFirst {
            try? container.vm.construct()
            try? container.vm.destruct()
        }
        let transitions = EventLog()
        let subscription = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .filter { $0.status == .constructing || $0.status == .constructed }
            .sink { transitions.add("\($0.senderName):\($0.status)") }
        defer { subscription.cancel() }
        gate.withLock { blocking = true }

        let constructed = DispatchSemaphore(value: 0)
        let disposed = DispatchSemaphore(value: 0)
        // A factory container may refuse population after supersession, so
        // the construct result is not asserted.
        DispatchQueue.global().async {
            try? container.vm.construct()
            constructed.signal()
        }
        XCTAssertEqual(entered.wait(timeout: .now() + hookTimeout), .success, label)
        DispatchQueue.global().async {
            container.vm.dispose()
            disposed.signal()
        }
        XCTAssertEqual(
            disposed.wait(timeout: .now() + 0.2), .timedOut,
            "\(label): the dispose waits for the admitted hook")
        XCTAssertNotEqual(first.status, .disposed, label)
        XCTAssertNotEqual(second.status, .disposed, label)
        XCTAssertFalse(log.all.contains { $0.hasPrefix("cleanup:") }, label)

        release.signal()
        XCTAssertEqual(constructed.wait(timeout: .now() + hookTimeout), .success, label)
        XCTAssertEqual(disposed.wait(timeout: .now() + hookTimeout), .success, label)
        container.vm.dispose()

        let hookExit = log.index("hook-exit") ?? Int.max
        XCTAssertGreaterThan(log.index("cleanup:first") ?? -1, hookExit, label)
        XCTAssertGreaterThan(log.index("cleanup:second") ?? -1, hookExit, label)
        XCTAssertEqual(first.cleanups, 1, label)
        XCTAssertEqual(second.cleanups, 1, label)
        XCTAssertEqual(container.vm.status, .disposed, label)
        XCTAssertEqual(first.status, .disposed, label)
        XCTAssertEqual(second.status, .disposed, label)
        XCTAssertEqual(
            transitions.all, ["\(kind):constructing"],
            "\(label): nothing publishes Constructed, and no child Constructing")
    }

    /// LIFE-015 — a foreign `dispose()` of a `CompositeVM` or `GroupVM` waits
    /// for the admitted construct hook before its child cascade (#1062). The
    /// variants without a factory and after a reconstruct also run the
    /// post-hook child walk, which a disposed container must stop.
    func testForeignDisposeWaitsForAdmittedConstructHookBeforeChildCascade() {
        for kind in ["composite", "group"] {
            assertChildCascadeWaitsForTheHook(kind, factory: true, reconstructFirst: false)
            assertChildCascadeWaitsForTheHook(kind, factory: false, reconstructFirst: false)
            assertChildCascadeWaitsForTheHook(kind, factory: true, reconstructFirst: true)
        }
    }

    /// LIFE-015 — two containers whose construct hooks dispose each other
    /// finish without deadlock, and each child cascade follows its own
    /// container's hook.
    func testOpposingContainerHooksDeferTheChildCascade() {
        for kind in ["composite", "group"] {
            let log = EventLog()
            let rendezvous = DispatchGroup()
            rendezvous.enter()
            rendezvous.enter()
            var containers: [Container] = []
            var children: [[CleanupProbe]] = []
            let constructed = EventLog()
            var subscriptions: [AnyCancellable] = []
            for index in 0..<2 {
                let hub = MessageHub()
                let container = Container.make(kind, hub: hub, factory: true) {
                    rendezvous.leave()
                    _ = rendezvous.wait(timeout: .now() + hookTimeout)
                    containers[1 - index].vm.dispose()
                    log.add("hook-exit:\(index)")
                }
                let pair = [
                    CleanupProbe("\(index)a", hub: hub, log: log),
                    CleanupProbe("\(index)b", hub: hub, log: log),
                ]
                pair.forEach(container.add)
                subscriptions.append(
                    hub.messages
                        .compactMap { $0 as? ConstructionStatusChangedMessage }
                        .filter { $0.status == .constructed }
                        .sink { constructed.add($0.senderName) })
                containers.append(container)
                children.append(pair)
            }
            defer { subscriptions.forEach { $0.cancel() } }
            let done = DispatchGroup()
            for container in containers {
                done.enter()
                DispatchQueue.global().async {
                    try? container.vm.construct()
                    done.leave()
                }
            }

            XCTAssertEqual(done.wait(timeout: .now() + hookTimeout), .success, "\(kind): no deadlock")
            for index in 0..<2 {
                let hookExit = log.index("hook-exit:\(index)") ?? Int.max
                for child in children[index] {
                    XCTAssertGreaterThan(log.index("cleanup:\(child.name)") ?? -1, hookExit, kind)
                    XCTAssertEqual(child.cleanups, 1, kind)
                    XCTAssertEqual(child.status, .disposed, kind)
                }
                XCTAssertEqual(containers[index].vm.status, .disposed, kind)
            }
            XCTAssertEqual(constructed.all, [], kind)
        }
    }

    /// LIFE-015 — a `dispose()` from the container's own construct hook
    /// disposes the children at once.
    func testSameThreadDisposeInsideOwnHookCascadesImmediately() {
        for kind in ["composite", "group"] {
            let hub = MessageHub()
            let log = EventLog()
            var owner: ComponentVMBase?
            let container = Container.make(kind, hub: hub, factory: true) {
                log.add("hook-enter")
                owner?.dispose()
                log.add("dispose-returned")
            }
            owner = container.vm
            let first = CleanupProbe("first", hub: hub, log: log)
            let second = CleanupProbe("second", hub: hub, log: log)
            container.add(first)
            container.add(second)

            try? container.vm.construct()

            XCTAssertEqual(
                Array(log.all.prefix(4)),
                ["hook-enter", "cleanup:first", "cleanup:second", "dispose-returned"], kind)
            XCTAssertEqual(container.vm.status, .disposed, kind)
            XCTAssertEqual(first.cleanups, 1, kind)
            XCTAssertEqual(second.cleanups, 1, kind)
            owner = nil
        }
    }

    /// LIFE-015 — no hook of the container is admitted while its child cascade
    /// runs. A `construct()` from a child's `_onDispose()` runs no
    /// `onConstruct`, and the container ends `.disposed`.
    func testNoContainerHookIsAdmittedDuringItsChildCascade() {
        for kind in ["composite", "group"] {
            let hub = MessageHub()
            let log = EventLog()
            let hookRuns = EventLog()
            let container = Container.make(kind, hub: hub, factory: false) {
                hookRuns.add("onConstruct")
            }
            let first = CleanupProbe("first", hub: hub, log: log)
            let second = CleanupProbe("second", hub: hub, log: log)
            container.add(first)
            container.add(second)
            weak var owner = container.vm
            first.onCleanup = { try? owner?.construct() }

            container.vm.dispose()

            XCTAssertEqual(hookRuns.all, [], kind)
            XCTAssertEqual(container.vm.status, .disposed, kind)
            XCTAssertEqual(first.cleanups, 1, kind)
            XCTAssertEqual(second.cleanups, 1, kind)
            first.onCleanup = nil
        }
    }

    /// LIFE-015 — the members a leaf registered with `ownMember` also wait for
    /// its admitted construct hook (spec/02 §7.1).
    func testMemberCascadeWaitsForAdmittedForeignHook() throws {
        let hub = MessageHub()
        let log = EventLog()
        let entered = DispatchSemaphore(value: 0)
        let release = DispatchSemaphore(value: 0)
        let parent = try ComponentVM.builder()
            .name("parent")
            .services(hub: hub, dispatcher: NullDispatcher.INSTANCE)
            .onConstruct {
                log.add("hook-enter")
                entered.signal()
                _ = release.wait(timeout: .now() + hookTimeout)
                log.add("hook-exit")
            }
            .build()
        let member = parent.ownMember(CleanupProbe("member", hub: hub, log: log))
        let constructed = DispatchSemaphore(value: 0)
        let disposed = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            try? parent.construct()
            constructed.signal()
        }
        XCTAssertEqual(entered.wait(timeout: .now() + hookTimeout), .success)
        DispatchQueue.global().async {
            parent.dispose()
            disposed.signal()
        }

        XCTAssertEqual(disposed.wait(timeout: .now() + 0.2), .timedOut)
        XCTAssertNotEqual(member.status, .disposed)
        release.signal()
        XCTAssertEqual(constructed.wait(timeout: .now() + hookTimeout), .success)
        XCTAssertEqual(disposed.wait(timeout: .now() + hookTimeout), .success)
        XCTAssertGreaterThan(log.index("cleanup:member") ?? -1, log.index("hook-exit") ?? Int.max)
        XCTAssertEqual(member.cleanups, 1)
        XCTAssertEqual(parent.status, .disposed)
    }
}
