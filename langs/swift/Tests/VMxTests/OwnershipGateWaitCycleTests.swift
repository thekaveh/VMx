//
// OwnershipGateWaitCycleTests.swift — #1154 regression tests.
//
// A transfer holds the child's ownership gate from reservation until commit
// or rollback, and the child's construct hook runs inside that interval. A
// wait for another thread's gate is recorded in the one wait-for graph
// (spec/03 §4.1, ADR-0172), keyed on the gate object. A gate wait that would
// close a cycle fails before mutation with `.attachmentFailed`; a contested
// gate that closes no cycle still blocks. Every wait is bounded, so a
// regression fails instead of hanging the suite.
//

import Combine
import Foundation
import XCTest
@testable import VMx

private let gateTimeout: TimeInterval = 5

private final class SharedValue<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: T
    init(_ value: T) { storage = value }
    var value: T {
        get { lock.withLock { storage } }
        set { lock.withLock { storage = newValue } }
    }
}

private typealias AddResult = Result<Void, ContainerOwnershipError>

final class OwnershipGateWaitCycleTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        ThreadWaitGraph.shared.onWaitDecidedForTesting = nil
        cancellables.removeAll()
        super.tearDown()
    }

    private func child(_ name: String, onConstruct: (() throws -> Void)? = nil) throws -> ComponentVM {
        var builder = ComponentVM.builder()
            .name(name)
            .services(hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
        if let onConstruct { builder = builder.onConstruct(onConstruct) }
        return try builder.build()
    }

    private func group<Child: ComponentVMBase>(_ name: String, construct: Bool = true) throws -> GroupVM<Child> {
        let group = GroupVM<Child>(
            name: name,
            hub: NullMessageHub.INSTANCE,
            dispatcher: ImmediateDispatcher.INSTANCE,
            autoConstructOnAdd: true
        )
        if construct { try group.construct() }
        return group
    }

    /// Starts `body` on a new thread that records its graph key in `id` first.
    private func spawn(_ id: SharedValue<UInt64>, _ body: @escaping () -> Void) -> DispatchSemaphore {
        let done = DispatchSemaphore(value: 0)
        Thread.detachNewThread {
            id.value = ThreadWaitGraph.currentThread
            body()
            done.signal()
        }
        return done
    }

    /// Signals `semaphore` for each accepted wait that `thread` records.
    private func signalAcceptedWaits(_ thread: SharedValue<UInt64>, _ semaphore: DispatchSemaphore) {
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            if accepted, caller == thread.value { semaphore.signal() }
        }
    }

    /// The groups among `groups` that hold `vm`.
    private func holders<Child: ComponentVMBase>(of vm: Child, in groups: [GroupVM<Child>]) -> [GroupVM<Child>] {
        groups.filter { group in group.snapshot().contains { $0 === vm } }
    }

    private func assertSingleMembership<Child: ComponentVMBase>(
        _ vm: Child,
        in groups: [GroupVM<Child>],
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let holding = holders(of: vm, in: groups)
        XCTAssertEqual(holding.count, 1, "\(vm.name) is in \(holding.count) groups", file: file, line: line)
        if let only = holding.first {
            XCTAssertTrue(vm._ownershipParent?.ownershipOwner === only, "\(vm.name) has another parent", file: file, line: line)
        }
    }

    private func assertOnlyAttachmentFailures(
        _ results: [AddResult?],
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        var failures = 0
        for result in results {
            switch result {
            case .success?: break
            case .failure(.attachmentFailed)?: failures += 1
            case .failure(let other)?: XCTFail("unexpected failure \(other)", file: file, line: line)
            case nil: XCTFail("a call did not return", file: file, line: line)
            }
        }
        XCTAssertGreaterThanOrEqual(failures, 1, "no call refused the cyclic wait", file: file, line: line)
    }

    /// #1154 reproduction 1, after ADR-0187. T1 holds the gate of `b` and
    /// tries to detach `b` from g2, whose membership transaction T2 owns. The
    /// detach fails at once, so T1 never waits for g2 and no cycle forms.
    /// T2's hook then moves `b` inside g2's transaction, which ADR-0118
    /// refuses.
    func testDetachDuringAnotherThreadsMembershipTransactionFailsAtOnce() throws {
        let g1: GroupVM<ComponentVM> = try group("g1")
        let g2: GroupVM<ComponentVM> = try group("g2", construct: false)
        let g3: GroupVM<ComponentVM> = try group("g3")
        let b = try child("b")
        try g2.addResult(b).get()
        try g2.construct()

        let t1 = SharedValue<UInt64>(0)
        let t1Finished = DispatchSemaphore(value: 0)
        let hookEntered = DispatchSemaphore(value: 0)
        let hookResult = SharedValue<AddResult?>(nil)
        let firstRun = SharedValue(true)
        let y = try child("y") {
            guard firstRun.value else { return }
            firstRun.value = false
            hookEntered.signal()
            _ = t1Finished.wait(timeout: .now() + gateTimeout)
            hookResult.value = g3.addResult(b)
        }

        let t2 = SharedValue<UInt64>(0)
        let t2Result = SharedValue<AddResult?>(nil)
        let t2Done = spawn(t2) { t2Result.value = g2.addResult(y) }
        XCTAssertEqual(hookEntered.wait(timeout: .now() + gateTimeout), .success)
        let t1Result = SharedValue<AddResult?>(nil)
        let t1Done = spawn(t1) {
            t1Result.value = g1.addResult(b)
            t1Finished.signal()
        }

        XCTAssertEqual(t1Done.wait(timeout: .now() + 1), .success, "T1 waited for g2's transaction")
        XCTAssertEqual(t2Done.wait(timeout: .now() + gateTimeout), .success, "T2 hung")
        guard case .failure(.attachmentFailed(let inner))? = t1Result.value,
              inner is ContainerMembershipTransactionError else {
            return XCTFail("T1: \(String(describing: t1Result.value))")
        }
        guard case .success? = t2Result.value else { return XCTFail("T2: \(String(describing: t2Result.value))") }
        guard case .failure(.attachmentFailed)? = hookResult.value else {
            return XCTFail("hook: \(String(describing: hookResult.value))")
        }
        XCTAssertEqual(holders(of: b, in: [g1, g2, g3]).map(\.name), ["g2"])
        XCTAssertEqual(holders(of: y, in: [g1, g2, g3]).map(\.name), ["g2"])
    }

    /// #1154 reproduction 2. Each hook transfers the other thread's child,
    /// whose gate that thread holds. The second gate wait closes the cycle.
    func testGateWaitThatClosesACycleOfGatesIsRefused() throws {
        let g1: GroupVM<ComponentVM> = try group("g1")
        let g2: GroupVM<ComponentVM> = try group("g2")
        let g3: GroupVM<ComponentVM> = try group("g3")
        let g4: GroupVM<ComponentVM> = try group("g4")

        let t1 = SharedValue<UInt64>(0)
        let t1Waiting = DispatchSemaphore(value: 0)
        signalAcceptedWaits(t1, t1Waiting)
        let aaStarted = DispatchSemaphore(value: 0)
        let bbStarted = DispatchSemaphore(value: 0)
        let aaFirstRun = SharedValue(true)
        let bbFirstRun = SharedValue(true)
        let aaHookResult = SharedValue<AddResult?>(nil)
        let bbHookResult = SharedValue<AddResult?>(nil)
        let bbRef = SharedValue<ComponentVM?>(nil)
        let aaRef = SharedValue<ComponentVM?>(nil)

        let aa = try child("aa") {
            guard aaFirstRun.value else { return }
            aaFirstRun.value = false
            aaStarted.signal()
            _ = bbStarted.wait(timeout: .now() + gateTimeout)
            aaHookResult.value = g3.addResult(bbRef.value!)
        }
        let bb = try child("bb") {
            guard bbFirstRun.value else { return }
            bbFirstRun.value = false
            bbStarted.signal()
            _ = aaStarted.wait(timeout: .now() + gateTimeout)
            // Wait for T1's recorded gate wait instead of a fixed delay.
            _ = t1Waiting.wait(timeout: .now() + gateTimeout)
            bbHookResult.value = g4.addResult(aaRef.value!)
        }
        aaRef.value = aa
        bbRef.value = bb

        let t1Result = SharedValue<AddResult?>(nil)
        let t2Result = SharedValue<AddResult?>(nil)
        let t2 = SharedValue<UInt64>(0)
        let t1Done = spawn(t1) { t1Result.value = g1.addResult(aa) }
        let t2Done = spawn(t2) { t2Result.value = g2.addResult(bb) }

        XCTAssertEqual(t1Done.wait(timeout: .now() + gateTimeout), .success, "T1 hung")
        XCTAssertEqual(t2Done.wait(timeout: .now() + gateTimeout), .success, "T2 hung")
        assertOnlyAttachmentFailures([t1Result.value, t2Result.value, aaHookResult.value, bbHookResult.value])
        assertSingleMembership(aa, in: [g1, g2, g3, g4])
        assertSingleMembership(bb, in: [g1, g2, g3, g4])
    }

    /// A contested gate that closes no cycle still blocks: T2 waits for T1's
    /// transfer of `c` to finish, then moves `c` to g2.
    func testContestedGateWithoutACycleStillBlocks() throws {
        let g1: GroupVM<ComponentVM> = try group("g1")
        let g2: GroupVM<ComponentVM> = try group("g2")
        let t2 = SharedValue<UInt64>(0)
        let t2Waiting = DispatchSemaphore(value: 0)
        signalAcceptedWaits(t2, t2Waiting)
        let hookEntered = DispatchSemaphore(value: 0)
        let releaseHook = DispatchSemaphore(value: 0)
        let firstRun = SharedValue(true)
        let c = try child("c") {
            guard firstRun.value else { return }
            firstRun.value = false
            hookEntered.signal()
            _ = releaseHook.wait(timeout: .now() + gateTimeout)
        }

        let t1 = SharedValue<UInt64>(0)
        let t1Result = SharedValue<AddResult?>(nil)
        let t1Done = spawn(t1) { t1Result.value = g1.addResult(c) }
        XCTAssertEqual(hookEntered.wait(timeout: .now() + gateTimeout), .success)
        let t2Result = SharedValue<AddResult?>(nil)
        let t2Done = spawn(t2) { t2Result.value = g2.addResult(c) }

        XCTAssertEqual(t2Waiting.wait(timeout: .now() + gateTimeout), .success, "T2 never waited for the gate")
        XCTAssertEqual(t2Done.wait(timeout: .now() + 0.2), .timedOut, "T2 returned while the hook held the gate")
        releaseHook.signal()
        XCTAssertEqual(t1Done.wait(timeout: .now() + gateTimeout), .success, "T1 hung")
        XCTAssertEqual(t2Done.wait(timeout: .now() + gateTimeout), .success, "T2 hung")
        guard case .success? = t1Result.value else { return XCTFail("T1: \(String(describing: t1Result.value))") }
        guard case .success? = t2Result.value else { return XCTFail("T2: \(String(describing: t2Result.value))") }
        XCTAssertEqual(holders(of: c, in: [g1, g2]).map(\.name), ["g2"])
        XCTAssertTrue(c._ownershipParent?.ownershipOwner === g2)
    }

    /// A nested container has a membership transaction and an ownership gate,
    /// and they are two resources (spec/03 §4.1 rule 2). T_a transfers `inner`
    /// (a group that is itself a child) and holds its gate in `inner`'s hook.
    /// T_b owns outer3's transaction and waits for that gate. `inner`'s own
    /// membership transaction then ends with a waiter (T_c's disposal; a
    /// membership change never waits, ADR-0187), which releases the waits on
    /// that transaction. T_b's gate wait must survive it, so T_a's disposal
    /// of outer3, which would wait for T_b, is refused instead of hanging.
    func testNestedContainerTransactionEndDoesNotDropAGateWait() throws {
        let outer1: GroupVM<GroupVM<ComponentVM>> = try group("outer1", construct: false)
        let outer2: GroupVM<GroupVM<ComponentVM>> = try group("outer2")
        let outer3: GroupVM<GroupVM<ComponentVM>> = try group("outer3")

        let ta = SharedValue<UInt64>(0)
        let tb = SharedValue<UInt64>(0)
        let tc = SharedValue<UInt64>(0)
        let tbWaiting = DispatchSemaphore(value: 0)
        let tcWaiting = DispatchSemaphore(value: 0)
        let taRefused = SharedValue(false)
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            if !accepted, caller == ta.value { taRefused.value = true }
            guard accepted else { return }
            if caller == tb.value { tbWaiting.signal() }
            if caller == tc.value { tcWaiting.signal() }
        }

        let hookEntered = DispatchSemaphore(value: 0)
        let sinkEntered = DispatchSemaphore(value: 0)
        let firstRun = SharedValue(true)
        let firstSink = SharedValue(true)
        let innerAddResult = SharedValue<AddResult?>(nil)
        let w = try child("w")
        let innerRef = SharedValue<GroupVM<ComponentVM>?>(nil)
        let inner = GroupVM<ComponentVM>(
            name: "inner",
            hub: NullMessageHub.INSTANCE,
            dispatcher: ImmediateDispatcher.INSTANCE,
            onConstruct: {
                guard firstRun.value else { return }
                firstRun.value = false
                hookEntered.signal()
                // T_b now waits for the gate of `inner`, which T_a holds.
                _ = tbWaiting.wait(timeout: .now() + gateTimeout)
                // Open and end inner's own transaction while T_c waits for it.
                innerAddResult.value = innerRef.value!.addResult(w)
                // T_b owns outer3's transaction and waits for T_a: refused.
                outer3.dispose()
            }
        )
        innerRef.value = inner
        inner.collectionChanged.sink { _ in
            guard firstSink.value else { return }
            firstSink.value = false
            sinkEntered.signal()
            _ = tcWaiting.wait(timeout: .now() + gateTimeout)
        }.store(in: &cancellables)
        try outer1.addResult(inner).get()

        let taResult = SharedValue<AddResult?>(nil)
        let taDone = spawn(ta) { taResult.value = outer2.addResult(inner) }
        XCTAssertEqual(hookEntered.wait(timeout: .now() + gateTimeout), .success)
        let tbResult = SharedValue<AddResult?>(nil)
        let tbDone = spawn(tb) { tbResult.value = outer3.addResult(inner) }
        XCTAssertEqual(sinkEntered.wait(timeout: .now() + gateTimeout), .success)
        let tcDone = spawn(tc) { inner.dispose() }

        XCTAssertEqual(taDone.wait(timeout: .now() + gateTimeout), .success, "T_a hung")
        XCTAssertEqual(tbDone.wait(timeout: .now() + gateTimeout), .success, "T_b hung")
        XCTAssertEqual(tcDone.wait(timeout: .now() + gateTimeout), .success, "T_c hung")
        guard case .success? = innerAddResult.value else {
            return XCTFail("inner.addResult(w): \(String(describing: innerAddResult.value))")
        }
        XCTAssertTrue(taRefused.value, "the cyclic disposal wait was not refused")
        guard case .success? = taResult.value else {
            return XCTFail("T_a \(String(describing: taResult.value))")
        }
        // T_b's transfer runs after T_a's and may find outer2's transaction
        // still open (ADR-0187).
        switch tbResult.value {
        case .success?, .failure(.attachmentFailed)?: break
        default: XCTFail("T_b \(String(describing: tbResult.value))")
        }
        XCTAssertEqual(outer3.status, .disposed, "outer3's deferred disposal ran")
        XCTAssertEqual(inner.status, .disposed)
        assertSingleMembership(inner, in: [outer1, outer2, outer3])
    }
}
