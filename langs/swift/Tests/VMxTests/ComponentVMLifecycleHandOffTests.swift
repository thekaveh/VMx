//
// ComponentVMLifecycleHandOffTests.swift — #1056 regression tests.
//
// A lifecycle publication that queues behind another thread's drain waits on
// that drainer in the shared wait-for graph. When the drainer hands the turn
// to the next waiter, every later waiter must wait on the new drainer. A
// stale edge to the old drainer hides a real cycle. A hub wait that closes it
// then does not take its escape, and two threads deadlock.
//
// The in-flight guard (LIFE-008) keeps the public API from queuing two
// foreign waiters on one VM, so the tests use the internal
// `commitInFlightStatusForTesting(_:)` seam. Every wait is bounded, so a
// regression fails instead of hanging the suite.
//
import Combine
import Foundation
import XCTest
@testable import VMx

private final class Locked<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: Value

    init(_ value: Value) { storage = value }

    var value: Value {
        get { lock.withLock { storage } }
        set { lock.withLock { storage = newValue } }
    }

    func mutate(_ body: (inout Value) -> Void) { lock.withLock { body(&storage) } }
}

/// Parks background work, so a background `construct()` stays in flight.
private final class ParkedDispatcher: Dispatcher, @unchecked Sendable {
    private let lock = NSLock()
    private var parked: [() -> Void] = []

    func scheduleForeground(_ work: @escaping () -> Void) { work() }
    func scheduleBackground(_ work: @escaping () -> Void) {
        lock.withLock { parked.append(work) }
    }
}

final class ComponentVMLifecycleHandOffTests: XCTestCase {

    /// The hang guard for one scenario.
    private let hangGuard: TimeInterval = 10

    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        ThreadWaitGraph.shared.onWaitDecidedForTesting = nil
        cancellables.removeAll()
        super.tearDown()
    }

    /// A VM whose background construct parks its hook, so the transition
    /// stays in flight once `construct()` publishes `.constructing`.
    private func parkedVM(_ hub: MessageHubProtocol) -> ComponentVM {
        ComponentVM(name: "v", hub: hub, dispatcher: ParkedDispatcher(), background: true)
    }

    /// Records each status that `vm` delivers, on the hub and on its local
    /// `status` property, in delivery order.
    private func recordDeliveries(
        of vm: ComponentVM,
        hub: MessageHub
    ) -> (hub: Locked<[ConstructionStatus]>, local: Locked<[ConstructionStatus]>) {
        let hubStatuses = Locked<[ConstructionStatus]>([])
        let localStatuses = Locked<[ConstructionStatus]>([])
        hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .filter { $0.sender === vm }
            .sink { message in hubStatuses.mutate { $0.append(message.status) } }
            .store(in: &cancellables)
        vm.propertyChanged
            .filter { $0 == "status" }
            .sink { _ in
                let status = vm.status
                localStatuses.mutate { $0.append(status) }
            }
            .store(in: &cancellables)
        return (hubStatuses, localStatuses)
    }

    /// The six steps of #1056, with two foreign waiters and a hub subscriber:
    ///
    /// 1. Thread D drains a publication of `v`; it is held after its hub send.
    /// 2. Thread W1 queues a publication of `v` and waits with `W1 -> D`.
    /// 3. Thread W2, in a hub subscriber that holds the hub drain, queues a
    ///    publication of `v` and waits with `W2 -> D`.
    /// 4. D hands the turn to W1.
    /// 5. W1 delivers through `hub.send`, which waits for W2's drain unless
    ///    W2's edge now names W1 and the wait closes a cycle.
    /// 6. W2 waits for W1's hand-off.
    ///
    /// With the stale `W2 -> D` edge, step 5 waits and both threads stop.
    func testHandOffRedirectsQueuedWaitsToTheNewDrainer() throws {
        let hub = MessageHub()
        let vm = parkedVM(hub)
        let deliveries = recordDeliveries(of: vm, hub: hub)
        try vm.construct()
        XCTAssertEqual(vm.status, .constructing)
        let trigger = NSObject()
        let deadline = DispatchTime.now() + hangGuard

        let drainer = Locked<UInt64>(0), first = Locked<UInt64>(0), second = Locked<UInt64>(0)
        let drainerHeld = DispatchSemaphore(value: 0)
        let firstWaiting = DispatchSemaphore(value: 0)
        let secondWaiting = DispatchSemaphore(value: 0)
        let drainerDone = DispatchSemaphore(value: 0)
        let firstDone = DispatchSemaphore(value: 0)
        let secondDone = DispatchSemaphore(value: 0)
        let held = Locked(false)
        let firstDecisions = Locked<[Bool]>([])

        // Runs under `lifecycleLock` for a lifecycle wait: it only signals.
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            if caller == first.value { firstDecisions.mutate { $0.append(accepted) } }
            guard accepted else { return }
            if caller == first.value { firstWaiting.signal() }
            if caller == second.value { secondWaiting.signal() }
        }
        // Step 1: hold D in its local delivery, after its hub drain ended.
        vm.propertyChanged
            .filter { $0 == "status" }
            .sink { _ in
                guard ThreadWaitGraph.currentThread == drainer.value else { return }
                var shouldHold = false
                held.mutate { if !$0 { $0 = true; shouldHold = true } }
                guard shouldHold else { return }
                drainerHeld.signal()
                _ = secondWaiting.wait(timeout: deadline)
            }
            .store(in: &cancellables)
        // Step 3: W2's subscriber queues while W2 holds the hub drain.
        hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.sender === trigger }
            .sink { _ in vm.commitInFlightStatusForTesting(.destructed) }
            .store(in: &cancellables)

        Thread.detachNewThread {
            drainer.value = ThreadWaitGraph.currentThread
            vm.commitInFlightStatusForTesting(.constructed)
            drainerDone.signal()
        }
        XCTAssertEqual(drainerHeld.wait(timeout: deadline), .success, "D never drained")
        // Step 2.
        Thread.detachNewThread {
            first.value = ThreadWaitGraph.currentThread
            vm.commitInFlightStatusForTesting(.destructing)
            firstDone.signal()
        }
        XCTAssertEqual(firstWaiting.wait(timeout: deadline), .success, "W1 never queued")
        Thread.detachNewThread {
            second.value = ThreadWaitGraph.currentThread
            hub.send(PropertyChangedMessage(
                sender: trigger, senderName: "trigger", propertyName: "trigger"
            ))
            secondDone.signal()
        }
        // Steps 4-6 run once W2 waits, which releases D.

        XCTAssertEqual(drainerDone.wait(timeout: deadline), .success, "D hung")
        XCTAssertEqual(firstDone.wait(timeout: deadline), .success, "W1 hung")
        XCTAssertEqual(secondDone.wait(timeout: deadline), .success, "W2 hung")
        XCTAssertEqual(
            deliveries.hub.value, [.constructing, .constructed, .destructing, .destructed],
            "each publication reaches the hub once, in FIFO order"
        )
        XCTAssertEqual(
            deliveries.local.value, [.constructing, .constructed, .destructing, .destructed],
            "each publication is delivered locally once, in FIFO order"
        )
        XCTAssertEqual(vm.status, .destructed)
        XCTAssertEqual(
            firstDecisions.value, [true, false],
            "W1 waits for its turn, then its hub wait closes the cycle and enqueues"
        )
    }

    /// A redirected edge that would close a cycle must not leave its waiter
    /// blocked. The hand-off wakes it without the turn, and the new drainer
    /// delivers its publication in FIFO order. No public path builds this
    /// state today, so the test primes the graph. Once W1 and W2 wait on D,
    /// it records that W1 waits on W2. This is as if the new drainer already
    /// waited on the second waiter. W1 is then held in its own delivery until
    /// W2 returns. W2 can return only when the hand-off adopts its publication.
    func testRedirectThatWouldCloseACycleLetsTheNewDrainerAdopt() throws {
        let hub = MessageHub()
        let vm = parkedVM(hub)
        let deliveries = recordDeliveries(of: vm, hub: hub)
        try vm.construct()
        let deadline = DispatchTime.now() + hangGuard
        let marker = NSObject()

        let drainer = Locked<UInt64>(0), first = Locked<UInt64>(0), second = Locked<UInt64>(0)
        let drainerHeld = DispatchSemaphore(value: 0)
        let firstWaiting = DispatchSemaphore(value: 0)
        let secondWaiting = DispatchSemaphore(value: 0)
        let graphPrimed = DispatchSemaphore(value: 0)
        let drainerDone = DispatchSemaphore(value: 0)
        let firstDone = DispatchSemaphore(value: 0)
        let secondDone = DispatchSemaphore(value: 0)
        let secondReturnedFirst = Locked<Bool?>(nil)
        let deliveringThreads = Locked<[ConstructionStatus: UInt64]>([:])

        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            guard accepted else { return }
            if caller == first.value { firstWaiting.signal() }
            if caller == second.value { secondWaiting.signal() }
        }
        vm.propertyChanged
            .filter { $0 == "status" }
            .sink { _ in
                let thread = ThreadWaitGraph.currentThread
                let status = vm.status
                deliveringThreads.mutate { $0[status] = thread }
                if thread == drainer.value && status == .constructed {
                    drainerHeld.signal()
                    _ = graphPrimed.wait(timeout: deadline)
                } else if thread == first.value && status == .destructing {
                    secondReturnedFirst.value = secondDone.wait(timeout: deadline) == .success
                }
            }
            .store(in: &cancellables)

        Thread.detachNewThread {
            drainer.value = ThreadWaitGraph.currentThread
            vm.commitInFlightStatusForTesting(.constructed)
            drainerDone.signal()
        }
        XCTAssertEqual(drainerHeld.wait(timeout: deadline), .success, "D never drained")
        Thread.detachNewThread {
            first.value = ThreadWaitGraph.currentThread
            vm.commitInFlightStatusForTesting(.destructing)
            firstDone.signal()
        }
        XCTAssertEqual(firstWaiting.wait(timeout: deadline), .success, "W1 never queued")
        Thread.detachNewThread {
            second.value = ThreadWaitGraph.currentThread
            vm.commitInFlightStatusForTesting(.destructed)
            secondDone.signal()
        }
        XCTAssertEqual(secondWaiting.wait(timeout: deadline), .success, "W2 never queued")
        XCTAssertTrue(ThreadWaitGraph.shared.beginWait(
            caller: first.value, owner: second.value, resource: ObjectIdentifier(marker)
        ))
        defer { ThreadWaitGraph.shared.endWait(caller: first.value) }
        graphPrimed.signal()

        XCTAssertEqual(drainerDone.wait(timeout: deadline), .success, "D hung")
        XCTAssertEqual(firstDone.wait(timeout: deadline), .success, "W1 hung")
        XCTAssertEqual(secondReturnedFirst.value, true, "W2 stayed blocked on a cycle")
        XCTAssertEqual(
            deliveries.hub.value, [.constructing, .constructed, .destructing, .destructed],
            "each publication reaches the hub once, in FIFO order"
        )
        XCTAssertEqual(
            deliveries.local.value, [.constructing, .constructed, .destructing, .destructed],
            "each publication is delivered locally once, in FIFO order"
        )
        XCTAssertEqual(
            deliveringThreads.value[.destructed], first.value,
            "the new drainer delivers the adopted publication"
        )
        XCTAssertEqual(vm.status, .destructed)
    }

    /// `redirectWait` moves an edge to its new owner. It refuses and removes
    /// an edge that would close a cycle. It ignores a caller with no edge on
    /// the resource.
    func testRedirectWaitMovesAnEdgeOrRefusesACycle() {
        let graph = ThreadWaitGraph()
        let resources = (NSObject(), NSObject(), NSObject())
        let onA = ObjectIdentifier(resources.0)
        let onB = ObjectIdentifier(resources.1)
        let onC = ObjectIdentifier(resources.2)
        let a: UInt64 = 1, b: UInt64 = 2, c: UInt64 = 3

        XCTAssertTrue(graph.beginWait(caller: a, owner: b, resource: onA))
        XCTAssertTrue(graph.beginWait(caller: c, owner: b, resource: onC))
        XCTAssertTrue(graph.redirectWait(caller: a, resource: onA, to: c), "a -> c closes no cycle")
        XCTAssertFalse(graph.beginWait(caller: c, owner: a, resource: onC), "the moved edge is live")
        XCTAssertFalse(graph.redirectWait(caller: c, resource: onC, to: a), "c -> a closes a -> c -> a")
        XCTAssertTrue(graph.beginWait(caller: b, owner: c, resource: onB), "the refused edge is gone")
        XCTAssertTrue(graph.redirectWait(caller: c, resource: onA, to: a), "c has no edge on onA")
        XCTAssertTrue(graph.beginWait(caller: a, owner: c, resource: onA), "nothing was recorded for c")
        withExtendedLifetime(resources) {}
    }
}
