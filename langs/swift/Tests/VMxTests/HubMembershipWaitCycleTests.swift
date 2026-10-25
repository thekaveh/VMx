//
// HubMembershipWaitCycleTests.swift — a hub drain and a container membership
// transaction that wait for each other must not deadlock (#703).
//
// Thread B sends a trigger message and holds the drain in its subscriber.
// Thread A opens a membership transaction and waits in `hub.send` for B's
// drain. B's subscriber then calls back into the same container. Every wait
// below is bounded, so a regression fails instead of hanging the suite.
//
import Combine
import XCTest
@testable import VMx

private final class Box<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: Value

    init(_ value: Value) { storage = value }

    var value: Value {
        get { lock.withLock { storage } }
        set { lock.withLock { storage = newValue } }
    }
}

/// A flag that only the first `take()` sees set.
private final class OneShot: @unchecked Sendable {
    private let lock = NSLock()
    private var armed = true

    func take() -> Bool {
        lock.withLock {
            defer { armed = false }
            return armed
        }
    }
}

private struct CycleOutcome {
    let stepTwoFinished: Bool
    let stepThreeFinished: Bool
    let stepThreeRan: Bool
}

final class HubMembershipWaitCycleTests: XCTestCase {

    private let timeout: TimeInterval = 5

    // ── Harness ──────────────────────────────────────────────────────────

    private func leaf(_ hub: MessageHubProtocol, _ name: String) -> ComponentVM {
        ComponentVM(name: name, hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
    }

    private func constructedComposite(
        _ hub: MessageHub,
        members: [ComponentVM] = [],
        autoConstructOnAdd: Bool = false
    ) throws -> CompositeVM<ComponentVM> {
        let composite = CompositeVM<ComponentVM>(
            name: "composite",
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            autoConstructOnAdd: autoConstructOnAdd
        )
        for member in members { try composite.addResult(member).get() }
        try composite.construct()
        return composite
    }

    private func constructedGroup(_ hub: MessageHub) throws -> GroupVM<ComponentVM> {
        let group = GroupVM<ComponentVM>(
            name: "group",
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
        try group.construct()
        return group
    }

    /// Runs `stepTwo` on thread A after thread B holds the drain of `hub`, and
    /// `stepThree` in B's subscriber once A has registered its hub wait.
    private func runCycle(
        hub: MessageHub,
        stepTwo: @escaping () -> Void,
        stepThree: @escaping () -> Void
    ) -> CycleOutcome {
        let trigger = NSObject()
        let subscriberEntered = DispatchSemaphore(value: 0)
        let stepTwoWaiting = DispatchSemaphore(value: 0)
        let stepTwoDone = DispatchSemaphore(value: 0)
        let stepThreeDone = DispatchSemaphore(value: 0)
        let stepThreeRan = Box(false)
        let waitTimeout = timeout

        hub.onWaitRegisteredForTesting = { stepTwoWaiting.signal() }
        defer { hub.onWaitRegisteredForTesting = nil }
        let subscription = hub.messages.sink { message in
            guard let changed = message as? PropertyChangedMessage,
                  changed.sender === trigger else { return }
            subscriberEntered.signal()
            guard stepTwoWaiting.wait(timeout: .now() + waitTimeout) == .success else { return }
            stepThreeRan.value = true
            stepThree()
        }
        defer { subscription.cancel() }

        Thread.detachNewThread {
            hub.send(PropertyChangedMessage(
                sender: trigger, senderName: "trigger", propertyName: "trigger"
            ))
            stepThreeDone.signal()
        }
        XCTAssertEqual(subscriberEntered.wait(timeout: .now() + timeout), .success)
        Thread.detachNewThread {
            stepTwo()
            stepTwoDone.signal()
        }
        let stepThreeFinished = stepThreeDone.wait(timeout: .now() + timeout) == .success
        let stepTwoFinished = stepTwoDone.wait(timeout: .now() + timeout) == .success
        return CycleOutcome(
            stepTwoFinished: stepTwoFinished,
            stepThreeFinished: stepThreeFinished,
            stepThreeRan: stepThreeRan.value
        )
    }

    private func assertFinished(
        _ outcome: CycleOutcome,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertTrue(outcome.stepThreeRan, "thread A never waited in hub.send", file: file, line: line)
        XCTAssertTrue(outcome.stepTwoFinished, "thread A (transaction owner) hung", file: file, line: line)
        XCTAssertTrue(outcome.stepThreeFinished, "thread B (hub drainer) hung", file: file, line: line)
    }

    private func recordCollectionMessages(_ hub: MessageHub) -> (Box<Int>, AnyCancellable) {
        let count = Box(0)
        let subscription = hub.messages.sink { message in
            if message is CollectionChangedMessage<ComponentVMBase> { count.value += 1 }
        }
        return (count, subscription)
    }

    // ── Step 3 adds to the same container ────────────────────────────────

    func testCompositeAddResultFromDrainingSubscriberDoesNotDeadlock() throws {
        let hub = MessageHub()
        let composite = try constructedComposite(hub)
        let first = leaf(hub, "first"), second = leaf(hub, "second")
        let ownerResult = Box<Result<Void, ContainerOwnershipError>?>(nil)
        let drainerResult = Box<Result<Void, ContainerOwnershipError>?>(nil)

        let outcome = runCycle(
            hub: hub,
            stepTwo: { ownerResult.value = composite.addResult(first) },
            stepThree: { drainerResult.value = composite.addResult(second) }
        )

        assertFinished(outcome)
        guard outcome.stepTwoFinished && outcome.stepThreeFinished else { return }
        XCTAssertNoThrow(try ownerResult.value?.get())
        guard case .failure(.attachmentFailed) = drainerResult.value else {
            return XCTFail("the edge that closes the cycle must fail: \(String(describing: drainerResult.value))")
        }
        XCTAssertEqual(composite.snapshot().map(\.name), ["first"])
    }

    func testGroupAddResultFromDrainingSubscriberDoesNotDeadlock() throws {
        let hub = MessageHub()
        let group = try constructedGroup(hub)
        let first = leaf(hub, "first"), second = leaf(hub, "second")
        let ownerResult = Box<Result<Void, ContainerOwnershipError>?>(nil)
        let drainerResult = Box<Result<Void, ContainerOwnershipError>?>(nil)

        let outcome = runCycle(
            hub: hub,
            stepTwo: { ownerResult.value = group.addResult(first) },
            stepThree: { drainerResult.value = group.addResult(second) }
        )

        assertFinished(outcome)
        guard outcome.stepTwoFinished && outcome.stepThreeFinished else { return }
        XCTAssertNoThrow(try ownerResult.value?.get())
        guard case .failure(.attachmentFailed) = drainerResult.value else {
            return XCTFail("the edge that closes the cycle must fail: \(String(describing: drainerResult.value))")
        }
        XCTAssertEqual(group.snapshot().map(\.name), ["first"])
    }

    // ── Step 3 selects, removes, or disposes ─────────────────────────────

    func testCompositeSelectChildFromDrainingSubscriberDoesNotDeadlock() throws {
        let hub = MessageHub()
        let member = leaf(hub, "member")
        let composite = try constructedComposite(hub, members: [member])
        let added = leaf(hub, "added")

        let outcome = runCycle(
            hub: hub,
            stepTwo: { _ = composite.addResult(added) },
            stepThree: { composite.selectChild(member) }
        )

        assertFinished(outcome)
        guard outcome.stepTwoFinished && outcome.stepThreeFinished else { return }
        XCTAssertNil(composite.current, "a selection that closes the cycle is dropped")
        XCTAssertEqual(composite.count, 2)
    }

    func testCompositeSetCurrentFromDrainingSubscriberDoesNotDeadlock() throws {
        let hub = MessageHub()
        let member = leaf(hub, "member")
        let composite = try constructedComposite(hub, members: [member])
        let added = leaf(hub, "added")
        let thrown = Box<Error?>(nil)

        let outcome = runCycle(
            hub: hub,
            stepTwo: { _ = composite.addResult(added) },
            stepThree: {
                do { try composite.setCurrent(member) } catch { thrown.value = error }
            }
        )

        assertFinished(outcome)
        guard outcome.stepTwoFinished && outcome.stepThreeFinished else { return }
        XCTAssertNil(thrown.value)
        XCTAssertNil(composite.current, "a selection that closes the cycle is dropped")
        XCTAssertEqual(composite.count, 2)
    }

    func testCompositeRemoveFromDrainingSubscriberDoesNotDeadlock() throws {
        let hub = MessageHub()
        let member = leaf(hub, "member")
        let composite = try constructedComposite(hub, members: [member])
        let added = leaf(hub, "added")
        let removed = Box<Bool?>(nil)

        let outcome = runCycle(
            hub: hub,
            stepTwo: { _ = composite.addResult(added) },
            stepThree: { removed.value = composite.remove(member) }
        )

        assertFinished(outcome)
        guard outcome.stepTwoFinished && outcome.stepThreeFinished else { return }
        XCTAssertEqual(removed.value, false)
        XCTAssertEqual(composite.snapshot().map(\.name), ["member", "added"])
    }

    func testCompositeDisposeFromDrainingSubscriberDefersToTransactionOwner() throws {
        let hub = MessageHub()
        let member = leaf(hub, "member")
        let composite = try constructedComposite(hub, members: [member])
        let added = leaf(hub, "added")

        let outcome = runCycle(
            hub: hub,
            stepTwo: { _ = composite.addResult(added) },
            stepThree: { composite.dispose() }
        )

        assertFinished(outcome)
        guard outcome.stepTwoFinished && outcome.stepThreeFinished else { return }
        XCTAssertEqual(composite.status, .disposed, "the transaction owner finishes the disposal")
        XCTAssertEqual(member.status, .disposed)
    }

    func testGroupDisposeFromDrainingSubscriberDefersToTransactionOwner() throws {
        let hub = MessageHub()
        let group = try constructedGroup(hub)
        let added = leaf(hub, "added")

        let outcome = runCycle(
            hub: hub,
            stepTwo: { _ = group.addResult(added) },
            stepThree: { group.dispose() }
        )

        assertFinished(outcome)
        guard outcome.stepTwoFinished && outcome.stepThreeFinished else { return }
        XCTAssertEqual(group.status, .disposed, "the transaction owner finishes the disposal")
    }

    // ── Collection messages batched: a different in-transaction send ─────

    func testAutoConstructStatusMessageInTransactionDoesNotDeadlock() throws {
        let hub = MessageHub()
        let composite = try constructedComposite(hub, autoConstructOnAdd: true)
        let first = leaf(hub, "first"), second = leaf(hub, "second")
        let ownerResult = Box<Result<Void, ContainerOwnershipError>?>(nil)
        let drainerResult = Box<Result<Void, ContainerOwnershipError>?>(nil)
        let batch = composite.batchUpdate()
        let (collectionMessages, recording) = recordCollectionMessages(hub)
        defer { recording.cancel() }

        let outcome = runCycle(
            hub: hub,
            stepTwo: { ownerResult.value = composite.addResult(first) },
            stepThree: { drainerResult.value = composite.addResult(second) }
        )

        assertFinished(outcome)
        guard outcome.stepTwoFinished && outcome.stepThreeFinished else { return }
        XCTAssertEqual(collectionMessages.value, 0, "the waiting send was a status message")
        XCTAssertNoThrow(try ownerResult.value?.get())
        guard case .failure = drainerResult.value else {
            return XCTFail("the edge that closes the cycle must fail")
        }
        XCTAssertEqual(first.status, .constructed)
        batch.dispose()
    }

    func testRemovingCurrentChildPublishesInTransactionWithoutDeadlock() throws {
        let hub = MessageHub()
        let member = leaf(hub, "member")
        let composite = try constructedComposite(hub, members: [member])
        try composite.setCurrent(member)
        let other = leaf(hub, "other")
        let removed = Box<Bool?>(nil)
        let drainerResult = Box<Result<Void, ContainerOwnershipError>?>(nil)
        let batch = composite.batchUpdate()
        let (collectionMessages, recording) = recordCollectionMessages(hub)
        defer { recording.cancel() }

        let outcome = runCycle(
            hub: hub,
            stepTwo: { removed.value = composite.remove(member) },
            stepThree: { drainerResult.value = composite.addResult(other) }
        )

        assertFinished(outcome)
        guard outcome.stepTwoFinished && outcome.stepThreeFinished else { return }
        XCTAssertEqual(collectionMessages.value, 0, "the waiting send was a property message")
        XCTAssertEqual(removed.value, true)
        XCTAssertNil(composite.current)
        guard case .failure = drainerResult.value else {
            return XCTFail("the edge that closes the cycle must fail")
        }
        batch.dispose()
    }

    // ── Opposite order: the drainer waits first ──────────────────────────

    func testOwnerSendDoesNotWaitForDrainerBlockedOnItsTransaction() throws {
        let hub = MessageHub()
        let composite = try constructedComposite(hub, autoConstructOnAdd: true)
        let transactionOpen = DispatchSemaphore(value: 0)
        let drainerCalling = DispatchSemaphore(value: 0)
        let waitTimeout = timeout
        // The first child publishes its lifecycle on another hub, so the owner's
        // only send on `hub` is the composite's add, after the drainer waits.
        let first = ComponentVM(
            name: "first",
            hub: NullMessageHub.INSTANCE,
            dispatcher: ImmediateDispatcher.INSTANCE,
            onConstruct: {
                transactionOpen.signal()
                _ = drainerCalling.wait(timeout: .now() + waitTimeout)
                Thread.sleep(forTimeInterval: 0.1)
            }
        )
        let second = leaf(hub, "second")
        let trigger = NSObject()
        let ownerResult = Box<Result<Void, ContainerOwnershipError>?>(nil)
        let drainerResult = Box<Result<Void, ContainerOwnershipError>?>(nil)
        let subscriberEntered = DispatchSemaphore(value: 0)
        let ownerDone = DispatchSemaphore(value: 0)
        let drainerDone = DispatchSemaphore(value: 0)
        let subscription = hub.messages.sink { message in
            guard let changed = message as? PropertyChangedMessage,
                  changed.sender === trigger else { return }
            subscriberEntered.signal()
            guard transactionOpen.wait(timeout: .now() + waitTimeout) == .success else { return }
            drainerCalling.signal()
            drainerResult.value = composite.addResult(second)
        }
        defer { subscription.cancel() }

        Thread.detachNewThread {
            hub.send(PropertyChangedMessage(
                sender: trigger, senderName: "trigger", propertyName: "trigger"
            ))
            drainerDone.signal()
        }
        XCTAssertEqual(subscriberEntered.wait(timeout: .now() + timeout), .success)
        Thread.detachNewThread {
            ownerResult.value = composite.addResult(first)
            ownerDone.signal()
        }

        XCTAssertEqual(ownerDone.wait(timeout: .now() + timeout), .success, "transaction owner hung")
        XCTAssertEqual(drainerDone.wait(timeout: .now() + timeout), .success, "hub drainer hung")
        XCTAssertNoThrow(try ownerResult.value?.get())
        XCTAssertNotNil(drainerResult.value)
    }

    // ── No cycle: a released drain leaves no edge behind ─────────────────

    /// Thread A waits in `hub.send` inside `ownerStep` while thread B holds
    /// the drain. B's drain then ends and B runs `operation`. The hub seam
    /// keeps A between its wake-up and its first step until B's graph wait
    /// is decided, so a stale A -> B edge would refuse B's wait every time.
    private func runAfterReleasedDrain(
        hub: MessageHub,
        ownerStep: @escaping () -> Void,
        operation: @escaping () -> Void
    ) -> (ownerFinished: Bool, callerFinished: Bool) {
        let trigger = NSObject()
        let subscriberEntered = DispatchSemaphore(value: 0)
        let ownerWaiting = DispatchSemaphore(value: 0)
        let callerDecided = DispatchSemaphore(value: 0)
        let ownerDone = DispatchSemaphore(value: 0)
        let callerDone = DispatchSemaphore(value: 0)
        let callerThread = Box<UInt64>(0)
        let window = OneShot()
        let waitTimeout = timeout

        hub.onWaitRegisteredForTesting = { ownerWaiting.signal() }
        hub.onWaitEndedForTesting = {
            guard window.take() else { return }
            _ = callerDecided.wait(timeout: .now() + waitTimeout)
        }
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, _ in
            if caller == callerThread.value { callerDecided.signal() }
        }
        defer {
            hub.onWaitRegisteredForTesting = nil
            hub.onWaitEndedForTesting = nil
            ThreadWaitGraph.shared.onWaitDecidedForTesting = nil
        }
        let subscription = hub.messages.sink { message in
            guard let changed = message as? PropertyChangedMessage,
                  changed.sender === trigger else { return }
            subscriberEntered.signal()
            _ = ownerWaiting.wait(timeout: .now() + waitTimeout)
        }
        defer { subscription.cancel() }

        Thread.detachNewThread {
            callerThread.value = ThreadWaitGraph.currentThread
            hub.send(PropertyChangedMessage(
                sender: trigger, senderName: "trigger", propertyName: "trigger"
            ))
            operation()
            callerDone.signal()
        }
        XCTAssertEqual(subscriberEntered.wait(timeout: .now() + timeout), .success)
        Thread.detachNewThread {
            ownerStep()
            ownerDone.signal()
        }
        let callerFinished = callerDone.wait(timeout: .now() + timeout) == .success
        let ownerFinished = ownerDone.wait(timeout: .now() + timeout) == .success
        return (ownerFinished, callerFinished)
    }

    func testAddResultAfterReleasedDrainWaitsInsteadOfFailing() throws {
        let hub = MessageHub()
        let composite = try constructedComposite(hub)
        let first = leaf(hub, "first"), second = leaf(hub, "second")
        let result = Box<Result<Void, ContainerOwnershipError>?>(nil)

        let outcome = runAfterReleasedDrain(
            hub: hub,
            ownerStep: { _ = composite.addResult(first) },
            operation: { result.value = composite.addResult(second) }
        )

        XCTAssertTrue(outcome.ownerFinished && outcome.callerFinished)
        XCTAssertNoThrow(try result.value?.get(), "no cycle exists, so the add must wait")
        XCTAssertEqual(composite.snapshot().map(\.name), ["first", "second"])
    }

    func testSetCurrentAfterReleasedDrainWaitsInsteadOfDropping() throws {
        let hub = MessageHub()
        let member = leaf(hub, "member")
        let composite = try constructedComposite(hub, members: [member])
        let added = leaf(hub, "added")
        let thrown = Box<Error?>(nil)

        let outcome = runAfterReleasedDrain(
            hub: hub,
            ownerStep: { _ = composite.addResult(added) },
            operation: {
                do { try composite.setCurrent(member) } catch { thrown.value = error }
            }
        )

        XCTAssertTrue(outcome.ownerFinished && outcome.callerFinished)
        XCTAssertNil(thrown.value)
        XCTAssertTrue(composite.current === member, "no cycle exists, so the selection must apply")
    }

    func testRemoveAfterReleasedDrainWaitsInsteadOfRefusing() throws {
        let hub = MessageHub()
        let member = leaf(hub, "member")
        let composite = try constructedComposite(hub, members: [member])
        let added = leaf(hub, "added")
        let removed = Box<Bool?>(nil)

        let outcome = runAfterReleasedDrain(
            hub: hub,
            ownerStep: { _ = composite.addResult(added) },
            operation: { removed.value = composite.remove(member) }
        )

        XCTAssertTrue(outcome.ownerFinished && outcome.callerFinished)
        XCTAssertEqual(removed.value, true, "no cycle exists, so the removal must wait")
        XCTAssertEqual(composite.snapshot().map(\.name), ["added"])
    }

    func testDisposeAfterReleasedDrainWaitsAndDisposesBeforeReturning() throws {
        let hub = MessageHub()
        let member = leaf(hub, "member")
        let composite = try constructedComposite(hub, members: [member])
        let added = leaf(hub, "added")
        let statusOnReturn = Box<ConstructionStatus?>(nil)

        let outcome = runAfterReleasedDrain(
            hub: hub,
            ownerStep: { _ = composite.addResult(added) },
            operation: {
                composite.dispose()
                statusOnReturn.value = composite.status
            }
        )

        XCTAssertTrue(outcome.ownerFinished && outcome.callerFinished)
        XCTAssertEqual(statusOnReturn.value, .disposed, "no cycle exists, so dispose must wait")
    }

    /// Thread D drains `vm`'s lifecycle and hands the turn to thread W, which
    /// waited for it. W then delivers in a hub subscriber. W's lifecycle edge
    /// must be gone by then, so D's send on the hub still waits for W's drain
    /// and delivers synchronously instead of taking the cycle escape.
    func testLifecycleTurnEdgeEndsBeforeTheWaiterDelivers() throws {
        let hub = MessageHub()
        let vm = leaf(hub, "vm")
        let probe = NSObject()
        let drainerThread = Box<UInt64>(0), waiterThread = Box<UInt64>(0)
        let drainerEntered = DispatchSemaphore(value: 0)
        let waiterDecided = DispatchSemaphore(value: 0)
        let waiterDelivering = DispatchSemaphore(value: 0)
        let probeDecided = DispatchSemaphore(value: 0)
        let drainerDone = DispatchSemaphore(value: 0)
        let waiterDone = DispatchSemaphore(value: 0)
        let probeDelivered = Box(false)
        let probeDeliveredOnReturn = Box<Bool?>(nil)
        let waitTimeout = timeout

        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, _ in
            if caller == waiterThread.value { waiterDecided.signal() }
            if caller == drainerThread.value { probeDecided.signal() }
        }
        defer { ThreadWaitGraph.shared.onWaitDecidedForTesting = nil }
        let subscription = hub.messages.sink { message in
            if let changed = message as? PropertyChangedMessage, changed.sender === probe {
                probeDelivered.value = true
            }
            guard let status = message as? ConstructionStatusChangedMessage,
                  status.sender === vm else { return }
            if status.status == .constructing {
                drainerEntered.signal()
                _ = waiterDecided.wait(timeout: .now() + waitTimeout)
            } else if status.status == .disposed {
                waiterDelivering.signal()
                _ = probeDecided.wait(timeout: .now() + waitTimeout)
            }
        }
        defer { subscription.cancel() }

        Thread.detachNewThread {
            drainerThread.value = ThreadWaitGraph.currentThread
            try? vm.construct()
            _ = waiterDelivering.wait(timeout: .now() + waitTimeout)
            hub.send(PropertyChangedMessage(
                sender: probe, senderName: "probe", propertyName: "probe"
            ))
            probeDeliveredOnReturn.value = probeDelivered.value
            drainerDone.signal()
        }
        XCTAssertEqual(drainerEntered.wait(timeout: .now() + timeout), .success)
        Thread.detachNewThread {
            waiterThread.value = ThreadWaitGraph.currentThread
            vm.dispose()
            waiterDone.signal()
        }

        XCTAssertEqual(drainerDone.wait(timeout: .now() + timeout), .success)
        XCTAssertEqual(waiterDone.wait(timeout: .now() + timeout), .success)
        XCTAssertEqual(
            probeDeliveredOnReturn.value, true,
            "no cycle exists, so the send must wait and deliver synchronously"
        )
        XCTAssertEqual(vm.status, .disposed)
    }

    // ── Guard: no cycle, no refusal ──────────────────────────────────────

    func testSubscriberChangingAnUnrelatedContainerCompletesNormally() throws {
        let hub = MessageHub()
        let composite = try constructedComposite(hub)
        let unrelated = try constructedComposite(hub)
        let first = leaf(hub, "first"), second = leaf(hub, "second")
        let ownerResult = Box<Result<Void, ContainerOwnershipError>?>(nil)
        let drainerResult = Box<Result<Void, ContainerOwnershipError>?>(nil)

        let outcome = runCycle(
            hub: hub,
            stepTwo: { ownerResult.value = composite.addResult(first) },
            stepThree: { drainerResult.value = unrelated.addResult(second) }
        )

        assertFinished(outcome)
        guard outcome.stepTwoFinished && outcome.stepThreeFinished else { return }
        XCTAssertNoThrow(try ownerResult.value?.get())
        XCTAssertNoThrow(try drainerResult.value?.get())
        XCTAssertEqual(composite.snapshot().map(\.name), ["first"])
        XCTAssertEqual(unrelated.snapshot().map(\.name), ["second"])
    }
}
