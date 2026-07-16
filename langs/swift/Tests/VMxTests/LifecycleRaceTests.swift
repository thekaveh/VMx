//
// VMX-002 regression — background construct/destruct vs dispose lifecycle race.
//
// Swift parity of the C# fix (commit 4afc9b6, VMX-001/054) and the Python fix
// (commit fd4423b, VMX-004). With a *real-thread* background dispatcher a
// background `construct()` completion can interleave with a concurrent
// foreground `dispose()`. Before the fix, the plain-`var` `_status` / `inFlight`
// / `triggersDisposed` were touched from both threads with no synchronization —
// an unsynchronized data race (undefined behaviour, ThreadSanitizer-flaggable):
// the background thread could write `_status = .constructed` *after* the VM was
// disposed (resurrection) and publish a post-dispose status message. The fix
// serializes status admission and ordered publication, so a background
// completion either wins before disposal or observes the terminal `.disposed`
// generation and aborts.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is exercised by CI (`swift.yml` on macos-latest). The
// assertions encode the *correct* (locked) behaviour — final status `.disposed`
// (no resurrection) and no post-dispose `.constructed` hub message — which the
// fixed code satisfies deterministically regardless of timing.
//
import XCTest
import Combine
import Foundation
@testable import VMx

final class LifecycleRaceTests: XCTestCase {

    // MARK: - Test dispatchers

    /// Background work is parked until `flush()` is called on the calling
    /// thread, mirroring the C# `TestScheduler.AdvanceBy(...)` cases: it lets a
    /// test interleave a foreground `dispose()` *between* scheduling the
    /// background completion and running it, deterministically (no real race).
    private final class DeferredDispatcher: Dispatcher {
        private var pending: [() -> Void] = []

        func scheduleForeground(_ work: @escaping () -> Void) { work() }
        func scheduleBackground(_ work: @escaping () -> Void) { pending.append(work) }

        func flush() {
            let work = pending
            pending = []
            for run in work { run() }
        }
    }

    /// Foreground is inline; background work runs on a real concurrent queue so a
    /// background completion genuinely races a foreground `dispose()`. An
    /// optional `gate` semaphore parks the worker so a test can release it in
    /// lock-step with the concurrent dispose, widening the interleaving window.
    private final class RealThreadDispatcher: Dispatcher {
        private let queue = DispatchQueue(
            label: "vmx.test.lifecycle-race", attributes: .concurrent
        )
        private let group = DispatchGroup()
        private let gate: DispatchSemaphore?

        init(gate: DispatchSemaphore? = nil) { self.gate = gate }

        func scheduleForeground(_ work: @escaping () -> Void) { work() }

        func scheduleBackground(_ work: @escaping () -> Void) {
            let gate = self.gate
            let group = self.group
            group.enter()
            queue.async {
                gate?.wait()
                work()
                group.leave()
            }
        }

        /// Block until every scheduled background closure has finished.
        func waitForCompletion() { group.wait() }
    }

    // MARK: - Deterministic abort-on-disposed

    func testConstructingSubscriberDisposePreventsForegroundHook() throws {
        let hub = MessageHub()
        var constructCalls = 0
        let vm = try ComponentVM.builder()
            .name("vm")
            .services(hub: hub, dispatcher: NullDispatcher.INSTANCE)
            .onConstruct { constructCalls += 1 }
            .build()
        var statuses: [ConstructionStatus] = []
        var propertyChanges: [String] = []
        var propertyCompleted = false
        var cleanupCalls = 0
        var statusAfterDisposeReturn: ConstructionStatus?
        var cleanupAfterDisposeReturn = -1
        var completionAfterDisposeReturn = false
        vm.own { cleanupCalls += 1 }
        let propertyCancel = vm.propertyChanged.sink(
            receiveCompletion: { _ in propertyCompleted = true },
            receiveValue: { propertyChanges.append($0) }
        )
        let cancel = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .filter { $0.sender === vm }
            .sink { message in
                statuses.append(message.status)
                if message.status == .constructing {
                    vm.dispose()
                    statusAfterDisposeReturn = vm.status
                    cleanupAfterDisposeReturn = cleanupCalls
                    completionAfterDisposeReturn = propertyCompleted
                }
            }

        try vm.construct()

        XCTAssertEqual(vm.status, .disposed)
        XCTAssertEqual(statusAfterDisposeReturn, .disposed)
        XCTAssertEqual(cleanupAfterDisposeReturn, 1)
        XCTAssertTrue(completionAfterDisposeReturn)
        XCTAssertEqual(constructCalls, 0,
                       "a hook must not start after transient publication disposed the VM")
        XCTAssertEqual(statuses, [.constructing, .disposed])
        XCTAssertEqual(
            propertyChanges,
            ["status", "isConstructed"],
            "the superseded transient status must not publish stale local changes"
        )
        XCTAssertEqual(cleanupCalls, 1)
        XCTAssertTrue(propertyCompleted)
        cancel.cancel()
        propertyCancel.cancel()
    }

    func testReentrantConstructDuringTerminalPublicationRaises() throws {
        let hub = MessageHub()
        let vm = try ComponentVM.builder()
            .name("vm")
            .services(hub: hub, dispatcher: NullDispatcher.INSTANCE)
            .build()
        var reentrantError: Error?
        let cancel = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .filter { $0.sender === vm && $0.status == .constructed }
            .sink { _ in
                do {
                    try vm.construct()
                } catch {
                    reentrantError = error
                }
            }

        try vm.construct()

        XCTAssertTrue(reentrantError is StatusTransitionError,
                      "LIFE-008 applies until terminal publication has completed")
        cancel.cancel()
    }

    func testDisposeDuringReconstructDestructHookSkipsConstructPhase() throws {
        let hub = MessageHub()
        let destructEntered = DispatchSemaphore(value: 0)
        let releaseDestruct = DispatchSemaphore(value: 0)
        let reconstructDone = DispatchSemaphore(value: 0)
        let counterLock = NSLock()
        var constructCalls = 0
        let vm = try ComponentVM.builder()
            .name("vm")
            .services(hub: hub, dispatcher: NullDispatcher.INSTANCE)
            .onConstruct {
                counterLock.lock()
                constructCalls += 1
                counterLock.unlock()
            }
            .onDestruct {
                destructEntered.signal()
                releaseDestruct.wait()
            }
            .build()
        try vm.construct()

        DispatchQueue.global().async {
            try? vm.reconstruct()
            reconstructDone.signal()
        }
        XCTAssertEqual(destructEntered.wait(timeout: .now() + 1), .success)
        let disposeDone = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            vm.dispose()
            disposeDone.signal()
        }
        XCTAssertEqual(
            disposeDone.wait(timeout: .now() + 0.05),
            .timedOut,
            "dispose must wait for an admitted lifecycle hook before returning"
        )
        releaseDestruct.signal()
        XCTAssertEqual(disposeDone.wait(timeout: .now() + 1), .success)
        XCTAssertEqual(reconstructDone.wait(timeout: .now() + 1), .success)

        counterLock.lock()
        let calls = constructCalls
        counterLock.unlock()
        XCTAssertEqual(calls, 1,
                       "a disposed reconstruct must not enter its second construct phase")
        XCTAssertEqual(vm.status, .disposed)
    }

    /// A `dispose()` that lands while a background `construct()` is in flight
    /// must abort the completion: no resurrection, no post-dispose `.constructed`
    /// hub message. Deterministic — the deferred dispatcher holds the background
    /// work until after dispose has run (mirrors the C#
    /// `Dispose_During_InFlight_Background_Construct_Does_Not_Resurrect`).
    func testDisposeDuringInFlightBackgroundConstructDoesNotResurrect() throws {
        let hub = MessageHub()
        let dispatcher = DeferredDispatcher()
        let vm = try! ComponentVM.builder()
            .name("vm")
            .services(hub: hub, dispatcher: dispatcher)
            .background(true)
            .build()

        var statuses: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage) }
            .filter { $0.sender === vm }
            .sink { statuses.append($0.status) }

        try vm.construct()   // emits .constructing; background completion parked
        vm.dispose()     // terminal before the parked work runs
        dispatcher.flush()  // background closure must now no-op (abort)

        XCTAssertEqual(vm.status, .disposed)
        XCTAssertFalse(
            statuses.contains(.constructed),
            "a disposed VM must not complete the Constructed transition (spec/02 invariant 3)"
        )
        XCTAssertEqual(
            statuses.last, .disposed,
            "the last status published must be Disposed"
        )
        cancel.cancel()
    }

    /// Symmetric case for the background `destruct()` path.
    func testDisposeDuringInFlightBackgroundDestructDoesNotResurrect() throws {
        let hub = MessageHub()
        let dispatcher = DeferredDispatcher()
        let vm = try! ComponentVM.builder()
            .name("vm")
            .services(hub: hub, dispatcher: dispatcher)
            .background(true)
            .build()

        try vm.construct()
        dispatcher.flush()  // complete construction synchronously
        XCTAssertEqual(vm.status, .constructed)

        var statuses: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage) }
            .filter { $0.sender === vm }
            .sink { statuses.append($0.status) }

        try vm.destruct()    // emits .destructing; background completion parked
        vm.dispose()     // terminal before the parked work runs
        dispatcher.flush()

        XCTAssertEqual(vm.status, .disposed)
        XCTAssertFalse(
            statuses.contains(.destructed),
            "a disposed VM must not complete the Destructed transition (spec/02 invariant 3)"
        )
        XCTAssertEqual(statuses.last, .disposed)
        cancel.cancel()
    }

    // MARK: - LIFE-008 — concurrent re-invocation while transitioning raises

    /// LIFE-008 — a second `construct()` invoked while the VM is mid-transition
    /// (`.constructing`, with its background completion still parked) raises a
    /// catchable `StatusTransitionError`. v3 converges Swift to the throwing
    /// contract (ADR-0053, superseding ADR-0037 §2.5, under which the in-flight
    /// guard trapped and LIFE-008 was therefore unclaimable). The
    /// `DeferredDispatcher` holds the VM deterministically in `.constructing`, so
    /// the re-invocation is observed without a real race.
    func testLife008ConcurrentConstructWhileTransitioningRaises() throws {
        let hub = MessageHub()
        let dispatcher = DeferredDispatcher()
        let vm = try ComponentVM.builder()
            .name("vm")
            .services(hub: hub, dispatcher: dispatcher)
            .background(true)
            .build()

        try vm.construct()            // emits .constructing; completion parked
        XCTAssertEqual(vm.status, .constructing)

        // Second invocation while in flight MUST raise (spec/12 LIFE-008).
        XCTAssertThrowsError(try vm.construct()) { error in
            guard let e = error as? StatusTransitionError else {
                return XCTFail("expected StatusTransitionError, got \(error)")
            }
            XCTAssertEqual(e.attemptedOperation, "construct")
            XCTAssertEqual(e.currentStatus, .constructing)
        }

        // The original transition still completes cleanly once flushed.
        dispatcher.flush()
        XCTAssertEqual(vm.status, .constructed)
    }

    // MARK: - Real-thread stress

    /// VMX-002 regression: a background `construct()` whose `_setStatus(.constructed)`
    /// runs on a real queue thread must never race a foreground `dispose()` into
    /// (a) resurrection of the VM (final status flipping back to Constructed
    /// after Disposed) or (b) a post-dispose `ConstructionStatusChangedMessage(.constructed)`.
    ///
    /// Unlike the deterministic deferred-dispatcher cases above (single-threaded,
    /// where the in-flight guard is trivially consistent), this exercises the
    /// genuine multi-threaded race the audit flags. With the unsynchronized
    /// plain-`var` state this is undefined behaviour (torn `_status`); once the
    /// transition + dispose are serialized under one lock it is impossible, so
    /// the assertions hold deterministically (zero violations) for the fixed code.
    func testBackgroundConstructRacingDisposeNeverResurrectsOrPublishesPostDispose() throws {
        // The locked code admits zero violations regardless of count, so the test
        // is deterministic; a high count stresses the interleaving window.
        let iterations = 5_000

        var resurrections = 0
        var postDisposeMessages = 0
        var firstViolation = -1

        for i in 0..<iterations {
            let hub = MessageHub()
            let gate = DispatchSemaphore(value: 0)
            let dispatcher = RealThreadDispatcher(gate: gate)
            let vm = try! ComponentVM.builder()
                .name("vm")
                .services(hub: hub, dispatcher: dispatcher)
                .background(true)
                .build()

            // The sink fires from both the foreground (dispose) and background
            // (construct completion) threads, so guard the shared state.
            let stateLock = NSLock()
            var seenDisposed = false
            var constructedAfterDispose = false
            let cancel = hub.messages
                .compactMap { ($0 as? ConstructionStatusChangedMessage) }
                .filter { $0.sender === vm }
                .sink { msg in
                    stateLock.lock()
                    defer { stateLock.unlock() }
                    if msg.status == .disposed {
                        seenDisposed = true
                    } else if msg.status == .constructed && seenDisposed {
                        // A Constructed message emitted *after* Disposed is a
                        // post-dispose publish (spec/02 invariant 3 violation).
                        constructedAfterDispose = true
                    }
                }

            // construct() schedules the background completion (parked on `gate`)
            // after emitting .constructing on this (foreground) thread.
            try vm.construct()

            // Race the worker's completion against a foreground dispose: park a
            // dispose on another queue, then release both back-to-back.
            let disposeGate = DispatchSemaphore(value: 0)
            let disposeDone = DispatchSemaphore(value: 0)
            DispatchQueue.global().async {
                disposeGate.wait()
                vm.dispose()
                disposeDone.signal()
            }
            disposeGate.signal()  // release the dispose thread
            gate.signal()         // release the background construct completion
            disposeDone.wait()
            dispatcher.waitForCompletion()
            cancel.cancel()

            let resurrected = vm.status == .constructed
            stateLock.lock()
            let postDispose = constructedAfterDispose
            stateLock.unlock()

            if resurrected { resurrections += 1 }
            if postDispose { postDisposeMessages += 1 }
            if firstViolation < 0 && (resurrected || postDispose) {
                firstViolation = i
            }
        }

        XCTAssertEqual(
            resurrections, 0,
            "a disposed VM must never flip back to Constructed (Disposed is terminal)"
        )
        XCTAssertEqual(
            postDisposeMessages, 0,
            "a disposed VM must never publish a post-dispose Constructed status message"
        )
        XCTAssertEqual(
            firstViolation, -1,
            "the background transition and foreground dispose() must be atomic"
        )
    }
}
