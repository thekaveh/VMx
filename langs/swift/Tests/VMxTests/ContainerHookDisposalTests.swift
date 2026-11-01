//
// ContainerHookDisposalTests.swift — #1062 and #1063 regression tests.
//
// A container's child cascade runs at the same admitted-hook boundary as its
// own `dispose()` (LIFE-015). This covers composites, groups and fixed
// aggregates. A `dispose()` from another thread disposes no child while the
// container's admitted construct or destruct hook runs. With no hook
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

// ── Fixed aggregates (#1063) ────────────────────────────────────────────

/// Blocks one phase of a fixed aggregate's lifecycle hook until released.
private final class AggregateHookGate: @unchecked Sendable {
    let log: EventLog
    let phase: String
    let entered = DispatchSemaphore(value: 0)
    let release = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var isBlocking = false

    init(log: EventLog, phase: String) {
        self.log = log
        self.phase = phase
    }

    func startBlocking() { lock.withLock { isBlocking = true } }

    /// Runs the base hook `body`; in the blocking phase, waits before it and
    /// logs `hook-returned` after it.
    func run(_ phase: String, _ body: () throws -> Void) rethrows {
        let blocks = lock.withLock { isBlocking } && phase == self.phase
        if blocks {
            log.add("hook-enter")
            entered.signal()
            _ = release.wait(timeout: .now() + hookTimeout)
            log.add("hook-exit")
        }
        try body()
        if blocks { log.add("hook-returned") }
    }
}

/// Runs a base hook through `gate`, or directly when there is no gate.
private func runGated(
    _ gate: AggregateHookGate?, _ phase: String, _ body: () throws -> Void
) rethrows {
    if let gate { try gate.run(phase, body) } else { try body() }
}

/// Creates the slots: `c<N>` first, then `c<N>-candidate` on a later construct.
private final class AggregateSlotFactory: @unchecked Sendable {
    private let hub: MessageHubProtocol
    private let log: EventLog
    private let lock = NSLock()
    private var made: [CleanupProbe] = []
    var created: [CleanupProbe] { lock.withLock { made } }

    init(hub: MessageHubProtocol, log: EventLog) {
        self.hub = hub
        self.log = log
    }

    func slot(_ index: Int) -> () -> CleanupProbe {
        { [self] in
            lock.withLock {
                let first = !made.contains { $0.name.hasPrefix("c\(index)") }
                let probe = CleanupProbe(
                    first ? "c\(index)" : "c\(index)-candidate", hub: hub, log: log)
                made.append(probe)
                return probe
            }
        }
    }
}

private final class GatedAggregateVM1: AggregateVM1<CleanupProbe> {
    var gate: AggregateHookGate?
    override func _onConstruct() throws { try runGated(gate, "construct") { try super._onConstruct() } }
    override func _onDestruct() throws { try runGated(gate, "destruct") { try super._onDestruct() } }
}

private final class GatedAggregateVM2: AggregateVM2<CleanupProbe, CleanupProbe> {
    var gate: AggregateHookGate?
    override func _onConstruct() throws { try runGated(gate, "construct") { try super._onConstruct() } }
    override func _onDestruct() throws { try runGated(gate, "destruct") { try super._onDestruct() } }
}

private final class GatedAggregateVM3: AggregateVM3<CleanupProbe, CleanupProbe, CleanupProbe> {
    var gate: AggregateHookGate?
    override func _onConstruct() throws { try runGated(gate, "construct") { try super._onConstruct() } }
    override func _onDestruct() throws { try runGated(gate, "destruct") { try super._onDestruct() } }
}

private final class GatedAggregateVM4: AggregateVM4<
    CleanupProbe, CleanupProbe, CleanupProbe, CleanupProbe
> {
    var gate: AggregateHookGate?
    override func _onConstruct() throws { try runGated(gate, "construct") { try super._onConstruct() } }
    override func _onDestruct() throws { try runGated(gate, "destruct") { try super._onDestruct() } }
}

private final class GatedAggregateVM5: AggregateVM5<
    CleanupProbe, CleanupProbe, CleanupProbe, CleanupProbe, CleanupProbe
> {
    var gate: AggregateHookGate?
    override func _onConstruct() throws { try runGated(gate, "construct") { try super._onConstruct() } }
    override func _onDestruct() throws { try runGated(gate, "destruct") { try super._onDestruct() } }
}

private final class GatedAggregateVM6: AggregateVM6<
    CleanupProbe, CleanupProbe, CleanupProbe, CleanupProbe, CleanupProbe, CleanupProbe
> {
    var gate: AggregateHookGate?
    override func _onConstruct() throws { try runGated(gate, "construct") { try super._onConstruct() } }
    override func _onDestruct() throws { try runGated(gate, "destruct") { try super._onDestruct() } }
}

/// The aggregate under test and its current slots, in slot order.
private struct GatedAggregate {
    let vm: ComponentVMBase
    let slots: () -> [ComponentVMBase]

    static func make(
        arity: Int, hub: MessageHubProtocol, gate: AggregateHookGate?,
        factory: AggregateSlotFactory
    ) -> GatedAggregate {
        let d = NullDispatcher.INSTANCE
        let f = factory.slot
        switch arity {
        case 1:
            let vm = GatedAggregateVM1(name: "agg1", hub: hub, dispatcher: d, factory1: f(1))
            vm.gate = gate
            return GatedAggregate(vm: vm, slots: { vm.childComponents })
        case 2:
            let vm = GatedAggregateVM2(
                name: "agg2", hub: hub, dispatcher: d, factory1: f(1), factory2: f(2))
            vm.gate = gate
            return GatedAggregate(vm: vm, slots: { vm.childComponents })
        case 3:
            let vm = GatedAggregateVM3(
                name: "agg3", hub: hub, dispatcher: d,
                factory1: f(1), factory2: f(2), factory3: f(3))
            vm.gate = gate
            return GatedAggregate(vm: vm, slots: { vm.childComponents })
        case 4:
            let vm = GatedAggregateVM4(
                name: "agg4", hub: hub, dispatcher: d,
                factory1: f(1), factory2: f(2), factory3: f(3), factory4: f(4))
            vm.gate = gate
            return GatedAggregate(vm: vm, slots: { vm.childComponents })
        case 5:
            let vm = GatedAggregateVM5(
                name: "agg5", hub: hub, dispatcher: d,
                factory1: f(1), factory2: f(2), factory3: f(3), factory4: f(4), factory5: f(5))
            vm.gate = gate
            return GatedAggregate(vm: vm, slots: { vm.childComponents })
        default:
            let vm = GatedAggregateVM6(
                name: "agg6", hub: hub, dispatcher: d,
                factory1: f(1), factory2: f(2), factory3: f(3),
                factory4: f(4), factory5: f(5), factory6: f(6))
            vm.gate = gate
            return GatedAggregate(vm: vm, slots: { vm.childComponents })
        }
    }
}

final class AggregateHookDisposalTests: XCTestCase {
    /// A `dispose()` on another thread while the aggregate's construct or
    /// destruct hook blocks: no slot is disposed until the hook returns.
    private func assertSlotCascadeWaitsForTheHook(arity: Int, phase: String) {
        let label = "AggregateVM\(arity) \(phase)"
        let hub = MessageHub()
        let log = EventLog()
        let gate = AggregateHookGate(log: log, phase: phase)
        let factory = AggregateSlotFactory(hub: hub, log: log)
        let aggregate = GatedAggregate.make(arity: arity, hub: hub, gate: gate, factory: factory)
        XCTAssertNoThrow(try aggregate.vm.construct(), label)
        if phase == "construct" { XCTAssertNoThrow(try aggregate.vm.destruct(), label) }
        let slots = aggregate.slots().compactMap { $0 as? CleanupProbe }
        XCTAssertEqual(slots.count, arity, label)
        gate.startBlocking()

        let errors = EventLog()
        let operated = DispatchSemaphore(value: 0)
        let disposed = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            do {
                if phase == "construct" {
                    try aggregate.vm.construct()
                } else {
                    try aggregate.vm.destruct()
                }
            } catch {
                errors.add("\(error)")
            }
            operated.signal()
        }
        XCTAssertEqual(gate.entered.wait(timeout: .now() + hookTimeout), .success, label)
        DispatchQueue.global().async {
            aggregate.vm.dispose()
            disposed.signal()
        }
        XCTAssertEqual(
            disposed.wait(timeout: .now() + 0.2), .timedOut,
            "\(label): the dispose waits for the admitted hook")
        XCTAssertFalse(log.all.contains { $0.hasPrefix("cleanup:") }, label)
        for slot in slots { XCTAssertNotEqual(slot.status, .disposed, label) }

        gate.release.signal()
        XCTAssertEqual(
            operated.wait(timeout: .now() + hookTimeout), .success, "\(label): no deadlock")
        XCTAssertEqual(
            disposed.wait(timeout: .now() + hookTimeout), .success, "\(label): no deadlock")

        XCTAssertEqual(errors.all, [], label)
        let hookReturned = log.index("hook-returned") ?? Int.max
        for slot in slots {
            XCTAssertGreaterThan(log.index("cleanup:\(slot.name)") ?? -1, hookReturned, label)
            XCTAssertEqual(slot.cleanups, 1, "\(label): \(slot.name)")
            XCTAssertEqual(slot.status, .disposed, label)
        }
        // A construct after the dispose request disposes its candidates at
        // once and commits none (spec/08 §4).
        for probe in factory.created {
            XCTAssertEqual(probe.cleanups, 1, "\(label): \(probe.name)")
        }
        XCTAssertEqual(
            aggregate.slots().map(ObjectIdentifier.init), slots.map(ObjectIdentifier.init), label)
        XCTAssertEqual(aggregate.vm.status, .disposed, label)
    }

    /// LIFE-015 — a foreign `dispose()` of an `AggregateVM1` waits for the
    /// admitted construct hook before its slot cascade, and neither thread
    /// deadlocks (#1063).
    func testForeignDisposeWaitsForAdmittedAggregateVM1ConstructHook() {
        assertSlotCascadeWaitsForTheHook(arity: 1, phase: "construct")
    }

    /// LIFE-015 — the same for `AggregateVM2`…`AggregateVM6` (#1063).
    func testForeignDisposeWaitsForAdmittedAggregateConstructHookAtEveryArity() {
        for arity in 2...6 { assertSlotCascadeWaitsForTheHook(arity: arity, phase: "construct") }
    }

    /// LIFE-015 — a foreign `dispose()` waits for the admitted destruct hook
    /// before the slot cascade, at every arity (#1063).
    func testForeignDisposeWaitsForAdmittedAggregateDestructHookAtEveryArity() {
        for arity in 1...6 { assertSlotCascadeWaitsForTheHook(arity: arity, phase: "destruct") }
    }

    /// LIFE-015 — no hook of the aggregate is admitted while its slot cascade
    /// runs. A `construct()` from a slot's `_onDispose()` creates no slot, and
    /// the aggregate ends `.disposed`.
    func testNoAggregateHookIsAdmittedDuringItsSlotCascade() {
        for arity in 1...6 {
            let label = "AggregateVM\(arity)"
            let hub = MessageHub()
            let log = EventLog()
            let factory = AggregateSlotFactory(hub: hub, log: log)
            let aggregate = GatedAggregate.make(arity: arity, hub: hub, gate: nil, factory: factory)
            XCTAssertNoThrow(try aggregate.vm.construct(), label)
            XCTAssertNoThrow(try aggregate.vm.destruct(), label)
            let slots = aggregate.slots().compactMap { $0 as? CleanupProbe }
            weak var owner = aggregate.vm
            slots[0].onCleanup = { try? owner?.construct() }

            aggregate.vm.dispose()

            XCTAssertEqual(factory.created.count, arity, "\(label): no candidate is created")
            XCTAssertEqual(aggregate.vm.status, .disposed, label)
            for slot in slots { XCTAssertEqual(slot.cleanups, 1, label) }
            slots[0].onCleanup = nil
        }
    }

    /// LIFE-013 — with no hook running, every slot is disposed in slot order
    /// before the aggregate publishes `.disposed`.
    func testSlotsAreDisposedInSlotOrderBeforeTheAggregate() {
        for arity in 1...6 {
            let label = "AggregateVM\(arity)"
            let hub = MessageHub()
            let log = EventLog()
            let disposedSenders = EventLog()
            let subscription = hub.messages
                .compactMap { $0 as? ConstructionStatusChangedMessage }
                .filter { $0.status == .disposed }
                .sink { disposedSenders.add($0.senderName) }
            defer { subscription.cancel() }
            let factory = AggregateSlotFactory(hub: hub, log: log)
            let aggregate = GatedAggregate.make(arity: arity, hub: hub, gate: nil, factory: factory)
            XCTAssertNoThrow(try aggregate.vm.construct(), label)

            aggregate.vm.dispose()

            XCTAssertEqual(
                disposedSenders.all, (1...arity).map { "c\($0)" } + ["agg\(arity)"], label)
        }
    }

    /// LIFE-015 — two aggregates whose slot factories each dispose the other
    /// aggregate, from inside their admitted construct hooks, both finish.
    /// Each ends `.disposed`, and every slot is disposed (#1063).
    func testOpposingAggregateFactoriesDisposeEachOtherWithoutDeadlock() {
        let hub = MessageHub()
        let log = EventLog()
        let rendezvous = DispatchGroup()
        rendezvous.enter()
        rendezvous.enter()
        let createdLock = NSLock()
        var created: [CleanupProbe] = []
        var aggregates: [AggregateVM1<CleanupProbe>] = []
        for index in 0..<2 {
            aggregates.append(AggregateVM1<CleanupProbe>(
                name: "agg\(index)", hub: hub, dispatcher: NullDispatcher.INSTANCE,
                factory1: {
                    rendezvous.leave()
                    _ = rendezvous.wait(timeout: .now() + hookTimeout)
                    aggregates[1 - index].dispose()
                    let slot = CleanupProbe("slot\(index)", hub: hub, log: log)
                    createdLock.withLock { created.append(slot) }
                    return slot
                }))
        }
        let done = DispatchGroup()
        for aggregate in aggregates {
            done.enter()
            DispatchQueue.global().async {
                try? aggregate.construct()
                done.leave()
            }
        }

        XCTAssertEqual(done.wait(timeout: .now() + hookTimeout), .success, "no deadlock")
        for aggregate in aggregates { XCTAssertEqual(aggregate.status, .disposed) }
        let slots = createdLock.withLock { created }
        XCTAssertEqual(slots.count, 2)
        for slot in slots { XCTAssertEqual(slot.status, .disposed, slot.name) }
        aggregates.removeAll()
    }
}
