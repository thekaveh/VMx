//
// Inline dispose cascade conformance tests (spec/02-lifecycle.md §7.2,
// ADR-0175).
//
// Claimed IDs: LIFE-021.
//
// A container disposes its children, and a leaf its registered members,
// before it publishes `.disposed`. A `construct()`, `destruct()`, or
// `reconstruct()` call that starts during that inline cascade throws
// `StatusTransitionError(currentStatus: .disposed, …)`, runs no hook, and
// publishes nothing (#1174). Once the cascade has started, no status other
// than `.disposed` commits, so a transition that started earlier publishes
// nothing more (#1167). Every cross-thread wait is bounded, so a regression
// fails instead of hanging the suite.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import Combine
import Foundation
import XCTest
@testable import VMx

private let hangGuard: TimeInterval = 5

/// A child or member whose `_onDispose()` runs a test action.
private final class CascadeProbe: ComponentVM {
    private let lock = NSLock()
    private var action: (() -> Void)?
    var onCleanup: (() -> Void)? {
        get { lock.withLock { action } }
        set { lock.withLock { action = newValue } }
    }

    init(_ name: String, hub: MessageHubProtocol) {
        super.init(name: name, hub: hub, dispatcher: NullDispatcher.INSTANCE)
    }

    override func _onDispose() {
        onCleanup?()
        super._onDispose()
    }
}

/// An `AggregateVM1` that counts its hook bodies and factory calls.
private final class CountingAggregate: AggregateVM1<CascadeProbe> {
    var hookCalls = 0

    override func _onConstruct() throws {
        hookCalls += 1
        try super._onConstruct()
    }

    override func _onDestruct() throws {
        hookCalls += 1
        try super._onDestruct()
    }
}

/// Records the status messages each sender publishes on a hub.
private final class StatusRecorder {
    private let lock = NSLock()
    private var entries: [(sender: String, status: ConstructionStatus)] = []
    private var subscription: AnyCancellable?

    init(_ hub: MessageHubProtocol) {
        subscription = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .sink { [weak self] message in
                guard let self else { return }
                self.lock.withLock {
                    self.entries.append((message.senderName, message.status))
                }
            }
    }

    func statuses(of sender: String) -> [ConstructionStatus] {
        lock.withLock { entries.filter { $0.sender == sender }.map(\.status) }
    }

    func cancel() { subscription?.cancel() }
}

/// The container under test and the counters a LIFE-021 case asserts.
private struct Box {
    let vm: ComponentVMBase
    let hookCalls: () -> Int
    let factoryCalls: () -> Int
    let child: () -> CascadeProbe?
}

private enum Operation: String, CaseIterable {
    case construct
    case destruct
    case reconstruct

    func run(_ vm: ComponentVMBase) throws {
        switch self {
        case .construct: try vm.construct()
        case .destruct: try vm.destruct()
        case .reconstruct: try vm.reconstruct()
        }
    }
}

final class InlineDisposeCascadeConformanceTests: XCTestCase {
    private func makeBox(_ kind: String, hub: MessageHubProtocol) -> Box {
        var hooks = 0
        switch kind {
        case "composite":
            let vm = CompositeVM<CascadeProbe>(
                name: "box", hub: hub, dispatcher: NullDispatcher.INSTANCE,
                onConstruct: { hooks += 1 }, onDestruct: { hooks += 1 })
            let c1 = CascadeProbe("c1", hub: hub)
            vm.add(c1)
            return Box(vm: vm, hookCalls: { hooks }, factoryCalls: { 0 }, child: { c1 })
        case "group":
            let vm = GroupVM<CascadeProbe>(
                name: "box", hub: hub, dispatcher: NullDispatcher.INSTANCE,
                onConstruct: { hooks += 1 }, onDestruct: { hooks += 1 })
            let c1 = CascadeProbe("c1", hub: hub)
            vm.add(c1)
            return Box(vm: vm, hookCalls: { hooks }, factoryCalls: { 0 }, child: { c1 })
        default:
            var factoryCalls = 0
            let vm = CountingAggregate(
                name: "box", hub: hub, dispatcher: NullDispatcher.INSTANCE,
                factory1: {
                    factoryCalls += 1
                    return CascadeProbe("c1", hub: hub)
                })
            return Box(
                vm: vm,
                hookCalls: { vm.hookCalls },
                factoryCalls: { factoryCalls },
                child: { vm.component1 })
        }
    }

    /// One LIFE-021 container case: `c1`'s dispose hook calls `operation` on
    /// `box` while `box` is `start`.
    private func assertCascadeRefuses(
        _ kind: String,
        _ operation: Operation,
        from start: ConstructionStatus,
        file: StaticString = #filePath,
        line: UInt = #line
    ) throws {
        let label = "\(kind) \(operation.rawValue) from \(start.name)"
        let hub = MessageHub()
        let box = makeBox(kind, hub: hub)
        // An aggregate is constructed once first, so that `c1` exists.
        if kind == "aggregate" || start == .constructed {
            try box.vm.construct()
        }
        if start == .destructed, box.vm.status == .constructed {
            try box.vm.destruct()
        }
        XCTAssertEqual(box.vm.status, start, label, file: file, line: line)
        let c1 = try XCTUnwrap(box.child(), label, file: file, line: line)
        let hooksBefore = box.hookCalls()
        let factoryBefore = box.factoryCalls()
        let recorder = StatusRecorder(hub)
        defer { recorder.cancel() }
        var recorded: Error?
        var statusDuringCall: ConstructionStatus?
        c1.onCleanup = {
            statusDuringCall = box.vm.status
            do { try operation.run(box.vm) } catch { recorded = error }
        }

        box.vm.dispose()

        let error = try XCTUnwrap(
            recorded as? StatusTransitionError,
            "\(label): the call fails with the Disposed error", file: file, line: line)
        XCTAssertEqual(error.currentStatus, .disposed, label, file: file, line: line)
        XCTAssertEqual(
            error.attemptedOperation, operation.rawValue, label, file: file, line: line)
        // The error names Disposed although Status has not reached it yet.
        XCTAssertEqual(statusDuringCall, start, label, file: file, line: line)
        XCTAssertEqual(
            box.hookCalls(), hooksBefore, "\(label): no box hook runs",
            file: file, line: line)
        XCTAssertEqual(
            box.factoryCalls(), factoryBefore, "\(label): no slot factory runs",
            file: file, line: line)
        XCTAssertEqual(
            recorder.statuses(of: "box"), [.disposed],
            "\(label): box publishes only Disposed", file: file, line: line)
        XCTAssertEqual(box.vm.status, .disposed, label, file: file, line: line)
        XCTAssertEqual(c1.status, .disposed, label, file: file, line: line)
        XCTAssertEqual(
            recorder.statuses(of: "c1"), [.disposed],
            "\(label): c1 publishes Disposed once", file: file, line: line)
    }

    /// LIFE-021 — `construct()` from `Destructed` and `destruct()` from
    /// `Constructed`, called from a child's dispose hook during the inline
    /// cascade of a `CompositeVM`, `GroupVM`, or `AggregateVM1`, throw the
    /// Disposed error, run no hook, and publish nothing.
    func testLifecycleCallFromChildDisposeHookFailsWithDisposedError() throws {
        for kind in ["composite", "group", "aggregate"] {
            try assertCascadeRefuses(kind, .construct, from: .destructed)
            try assertCascadeRefuses(kind, .destruct, from: .constructed)
        }
    }

    /// LIFE-021 — the refusal runs before the idempotent no-op and the
    /// legality check: `construct()` and `reconstruct()` from `Constructed`
    /// fail in the same way.
    func testIdempotentConstructAndReconstructDuringCascadeFailToo() throws {
        for kind in ["composite", "group", "aggregate"] {
            try assertCascadeRefuses(kind, .construct, from: .constructed)
            try assertCascadeRefuses(kind, .reconstruct, from: .constructed)
        }
    }

    /// LIFE-021 — a member's dispose hook that calls `construct()` on its
    /// leaf gets the Disposed error. No leaf hook runs, and the leaf
    /// publishes only `Disposed` (spec/02 §7.1).
    func testMemberDisposeHookConstructOfLeafFails() throws {
        let hub = MessageHub()
        var hookCalls = 0
        let leaf = ComponentVM(
            name: "leaf", hub: hub, dispatcher: NullDispatcher.INSTANCE,
            onConstruct: { hookCalls += 1 })
        let member = leaf.ownMember(CascadeProbe("member", hub: hub))
        let recorder = StatusRecorder(hub)
        defer { recorder.cancel() }
        var recorded: Error?
        member.onCleanup = {
            do { try leaf.construct() } catch { recorded = error }
        }

        leaf.dispose()

        let error = try XCTUnwrap(recorded as? StatusTransitionError)
        XCTAssertEqual(error.currentStatus, .disposed)
        XCTAssertEqual(error.attemptedOperation, "construct")
        XCTAssertEqual(hookCalls, 0, "no leaf hook runs")
        XCTAssertEqual(recorder.statuses(of: "leaf"), [.disposed])
        XCTAssertEqual(leaf.status, .disposed)
        XCTAssertEqual(member.status, .disposed)
    }

    /// LIFE-021 — a background leaf's `Constructed` commit, queued on a
    /// manual foreground scheduler, is dropped when the member's dispose
    /// hook drains that scheduler during the inline cascade (#1167).
    func testQueuedBackgroundCommitDrainedDuringMemberCascadeIsDropped() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        var hookCalls = 0
        let leaf = ComponentVM(
            name: "leaf", hub: hub, dispatcher: dispatcher,
            onConstruct: { hookCalls += 1 }, background: true)
        let member = leaf.ownMember(CascadeProbe("member", hub: hub))
        let recorder = StatusRecorder(hub)
        defer { recorder.cancel() }

        try leaf.construct()
        dispatcher.flushBackground()
        XCTAssertEqual(hookCalls, 1, "the construct hook ran")
        XCTAssertEqual(leaf.status, .constructing, "the commit is queued")
        member.onCleanup = { dispatcher.flushForeground() }

        leaf.dispose()

        XCTAssertEqual(
            recorder.statuses(of: "leaf"), [.constructing, .disposed],
            "the queued Constructed commit publishes nothing")
        XCTAssertEqual(leaf.status, .disposed)
        XCTAssertEqual(member.status, .disposed)
        dispatcher.flushForeground()
        XCTAssertEqual(recorder.statuses(of: "leaf"), [.constructing, .disposed])
    }

    /// LIFE-021 — a synchronous transition whose hook returned before an
    /// inline cascade began on another thread commits nothing once the
    /// cascade has started (#1167). The call returns without an error.
    func testSettledCommitAfterCascadeStartedIsDropped() throws {
        for kind in ["composite", "group"] {
            for operation in [Operation.construct, .destruct] {
                try assertSettledCommitIsDropped(kind, operation)
            }
        }
    }

    private func assertSettledCommitIsDropped(
        _ kind: String, _ operation: Operation
    ) throws {
        let label = "\(kind) \(operation.rawValue)"
        let hub = MessageHub()
        let box = makeBox(kind, hub: hub)
        if operation == .destruct { try box.vm.construct() }
        let c1 = try XCTUnwrap(box.child(), label)
        let recorder = StatusRecorder(hub)
        defer { recorder.cancel() }

        let hookReturned = DispatchSemaphore(value: 0)
        let resume = DispatchSemaphore(value: 0)
        let callReturned = DispatchSemaphore(value: 0)
        let disposed = DispatchSemaphore(value: 0)
        box.vm.afterHookReleaseForTesting = {
            hookReturned.signal()
            _ = resume.wait(timeout: .now() + hangGuard)
        }
        // The transition commits while the cascade disposes c1.
        var resumedInCascade = DispatchTimeoutResult.timedOut
        c1.onCleanup = {
            resume.signal()
            resumedInCascade = callReturned.wait(timeout: .now() + hangGuard)
        }
        var callError: Error?
        DispatchQueue.global().async {
            do { try operation.run(box.vm) } catch { callError = error }
            callReturned.signal()
        }
        XCTAssertEqual(hookReturned.wait(timeout: .now() + hangGuard), .success, label)
        DispatchQueue.global().async {
            box.vm.dispose()
            disposed.signal()
        }
        XCTAssertEqual(disposed.wait(timeout: .now() + hangGuard), .success, label)
        box.vm.afterHookReleaseForTesting = nil

        XCTAssertEqual(
            resumedInCascade, .success,
            "\(label): the call returned inside the cascade")
        XCTAssertNil(callError, "\(label): the superseded call raises nothing")
        let transient: ConstructionStatus = operation == .construct
            ? .constructing : .destructing
        XCTAssertEqual(
            recorder.statuses(of: "box"), [transient, .disposed],
            "\(label): no settled status commits after the cascade started")
        XCTAssertEqual(box.vm.status, .disposed, label)
        XCTAssertEqual(c1.status, .disposed, label)
    }
}
