//
// FormCrossThreadPreparationTests.swift — #1427, #1452 and #1426 regression
// tests.
//
// A form holds no lock while a consumer callback runs (spec/20 §5.4,
// ADR-0215). Another thread's reads and calls therefore never wait for an
// equality, a validator, the snapshotter or `resetOnApproved`. An update
// that another thread's commit overtakes runs again as a new call. Another
// thread's edit during the post-persist commit commits at once, and a
// configured reset overwrites it (§5.1, §5.3). A refused `dispose()` wakes
// every scope waiter at once, and an update opens a publication scope only
// when its error map changes (§5.5).
//
// Every wait is bounded, so a deadlock fails the test instead of hanging the
// run. No conformance ID: each rule needs a second thread (ADR-0215 §4).
//

import Combine
import Foundation
import XCTest
@testable import VMx

/// Bound for every wait in these tests; a stall shows up as a timeout.
private let crossThreadTimeout: TimeInterval = 5

private struct Ping: Message {
    let senderObject: AnyObject
    let senderName: String
}

/// A thread-safe value shared by callbacks on several threads.
private final class Shared<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: Value

    init(_ value: Value) {
        stored = value
    }

    var value: Value {
        get { lock.lock(); defer { lock.unlock() }; return stored }
        set { lock.lock(); stored = newValue; lock.unlock() }
    }

    /// Sets the value and returns the previous one.
    func exchange(_ value: Value) -> Value {
        lock.lock()
        defer { lock.unlock() }
        let previous = stored
        stored = value
        return previous
    }
}

/// Runs `body` on a new thread and returns a semaphore that it signals when
/// `body` returns.
private func onThread(_ body: @escaping () -> Void) -> DispatchSemaphore {
    let done = DispatchSemaphore(value: 0)
    let boxed = UncheckedSendableBox(body)
    Thread {
        boxed.value()
        done.signal()
    }.start()
    return done
}

final class FormCrossThreadPreparationTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        ThreadWaitGraph.shared.onWaitDecidedForTesting = nil
        cancellables.removeAll()
        super.tearDown()
    }

    @discardableResult
    private func wait(
        _ semaphore: DispatchSemaphore,
        _ message: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> Bool {
        let result = semaphore.wait(timeout: .now() + crossThreadTimeout * 2)
        XCTAssertEqual(result, .success, message, file: file, line: line)
        return result == .success
    }

    // ── #1427: callbacks run with no form lock ────────────────────────────────

    /// A validator that joins another thread's `setModel` completes. That
    /// thread commits first, and the overtaken update then runs again.
    func testValidatorJoiningAnotherThreadsSetModelDoesNotDeadlock() {
        let joined = Shared<Bool?>(nil)
        let armed = Shared(true)
        weak var weakForm: FormVM<Int>?
        let form = FormVM(
            initial: 0,
            persister: { (_: Int) in },
            validators: ["value": { candidate in
                if candidate == 1, armed.exchange(false), let form = weakForm {
                    let boxed = UncheckedSendableBox(form)
                    let done = onThread { boxed.value.setModel(2) }
                    joined.value = done.wait(timeout: .now() + crossThreadTimeout) == .success
                }
                return nil
            }]
        )
        weakForm = form
        let boxed = UncheckedSendableBox(form)

        guard wait(onThread { boxed.value.setModel(1) }, "setModel(1) stalled") else { return }
        XCTAssertEqual(joined.value, true, "the other thread's setModel completed during the validator")
        XCTAssertEqual(form.model, 1, "the overtaken update ran again after the other thread's commit")
    }

    /// Another thread's reads return the committed state while a validator
    /// runs.
    func testAnotherThreadsReadsDoNotWaitForAValidator() {
        let read = Shared<(model: Int, isDirty: Bool, isValid: Bool, canExecute: Bool)?>(nil)
        let armed = Shared(true)
        weak var weakForm: FormVM<Int>?
        let form = FormVM(
            initial: 0,
            persister: { (_: Int) in },
            validators: ["value": { candidate in
                if candidate == 1, armed.exchange(false), let form = weakForm {
                    let boxed = UncheckedSendableBox(form)
                    let done = onThread {
                        let form = boxed.value
                        read.value = (
                            form.model,
                            form.isDirty,
                            form.isValid && form.errors.isEmpty && form.fieldError("value") == nil,
                            form.approveCommand.canExecute()
                        )
                        _ = form.snapshot
                    }
                    _ = done.wait(timeout: .now() + crossThreadTimeout)
                }
                return nil
            }]
        )
        weakForm = form
        let boxed = UncheckedSendableBox(form)

        guard wait(onThread { boxed.value.setModel(1) }, "setModel(1) stalled") else { return }
        let observed = read.value
        XCTAssertNotNil(observed, "the reads completed while the validator ran")
        XCTAssertEqual(observed?.model, 0)
        XCTAssertEqual(observed?.isDirty, false)
        XCTAssertEqual(observed?.isValid, true)
        XCTAssertEqual(observed?.canExecute, true)
        XCTAssertEqual(form.model, 1)
    }

    /// A `dispose()` from another thread during a preparation marks the form
    /// disposed and returns. The preparing call commits nothing, and the
    /// channels complete when it returns (§5.4, §10).
    func testDisposeFromAnotherThreadDuringAPreparationReturnsAtOnce() {
        let validatorEntered = DispatchSemaphore(value: 0)
        let releaseValidator = DispatchSemaphore(value: 0)
        let hub = MessageHub()
        let form = FormVM(
            initial: "initial",
            persister: { (_: String) in },
            hub: hub,
            validators: ["name": { candidate in
                if candidate == "first" {
                    validatorEntered.signal()
                    _ = releaseValidator.wait(timeout: .now() + crossThreadTimeout * 2)
                }
                return nil
            }]
        )
        let finished = Shared(false)
        form.errorsChanged
            .sink(receiveCompletion: { _ in finished.value = true }, receiveValue: { _ in })
            .store(in: &cancellables)
        let published = Shared(0)
        hub.messages
            .sink { _ in published.value += 1 }
            .store(in: &cancellables)
        let boxed = UncheckedSendableBox(form)

        let firstDone = onThread { boxed.value.setModel("first") }
        guard wait(validatorEntered, "the validator never ran") else { return }
        let disposed = onThread { boxed.value.dispose() }
        let disposeReturned = disposed.wait(timeout: .now() + crossThreadTimeout) == .success
        let finishedDuringPreparation = finished.value
        releaseValidator.signal()
        guard wait(firstDone, "setModel(first) stalled") else { return }
        if !disposeReturned { wait(disposed, "dispose() stalled") }

        XCTAssertTrue(disposeReturned, "dispose() returned while the validator ran")
        XCTAssertFalse(finishedDuringPreparation, "the teardown waits for the preparing call")
        XCTAssertTrue(finished.value, "the teardown ran when the preparing call returned")
        XCTAssertEqual(form.model, "initial", "the preparing call committed nothing")
        XCTAssertEqual(published.value, 0)
    }

    // ── #1452: another thread during the post-persist commit ──────────────────

    private enum RacingCall {
        case setModel
        case deny
    }

    /// Runs an approval whose `resetOnApproved` blocks, and makes `call` from
    /// another thread meanwhile. The call commits at once, and the reset then
    /// overwrites it.
    private func runRaceWithReset(_ call: RacingCall, file: StaticString = #filePath, line: UInt = #line) {
        let resetEntered = DispatchSemaphore(value: 0)
        let releaseReset = DispatchSemaphore(value: 0)
        let form = FormVM(
            initial: "saved",
            persister: { (_: String) in },
            resetOnApproved: { _ in
                resetEntered.signal()
                _ = releaseReset.wait(timeout: .now() + crossThreadTimeout * 2)
                return "pristine"
            }
        )
        form.setModel("edited")
        let boxed = UncheckedSendableBox(form)
        let approved = DispatchSemaphore(value: 0)
        Task.detached {
            try? await boxed.value.approveAsync()
            approved.signal()
        }
        guard wait(resetEntered, "the reset never ran", file: file, line: line) else { return }

        let racing = onThread {
            switch call {
            case .setModel: boxed.value.setModel("racing")
            case .deny: boxed.value.denyCommand.execute()
            }
        }
        let committedAtOnce = racing.wait(timeout: .now() + crossThreadTimeout) == .success
        let modelDuringReset = form.model
        releaseReset.signal()
        guard wait(approved, "the approval stalled", file: file, line: line) else { return }
        if !committedAtOnce { wait(racing, "the racing call stalled", file: file, line: line) }

        XCTAssertTrue(committedAtOnce, "the call did not wait for the reset", file: file, line: line)
        XCTAssertEqual(
            modelDuringReset, call == .setModel ? "racing" : "saved",
            "the call committed at once", file: file, line: line
        )
        XCTAssertEqual(form.model, "pristine", "the reset overwrote the call", file: file, line: line)
        XCTAssertEqual(form.snapshot, "pristine", file: file, line: line)
        XCTAssertFalse(form.isDirty, file: file, line: line)
    }

    func testAnotherThreadsSetModelDuringTheResetCommitsAndIsOverwritten() {
        runRaceWithReset(.setModel)
    }

    func testAnotherThreadsDenyDuringTheResetCommitsAndIsOverwritten() {
        runRaceWithReset(.deny)
    }

    /// Without a reset, another thread's `setModel` during the snapshotter
    /// commits at once and stands; the snapshot advances to the captured
    /// value.
    func testAnotherThreadsSetModelDuringTheApprovalSnapshotStands() {
        let snapshotEntered = DispatchSemaphore(value: 0)
        let releaseSnapshot = DispatchSemaphore(value: 0)
        let armed = Shared(false)
        let form = FormVM(
            initial: "saved",
            persister: { (_: String) in },
            snapshotter: { value in
                if value == "edited", armed.exchange(false) {
                    snapshotEntered.signal()
                    _ = releaseSnapshot.wait(timeout: .now() + crossThreadTimeout * 2)
                }
                return value
            }
        )
        form.setModel("edited")
        armed.value = true
        let boxed = UncheckedSendableBox(form)
        let approved = DispatchSemaphore(value: 0)
        Task.detached {
            try? await boxed.value.approveAsync()
            approved.signal()
        }
        guard wait(snapshotEntered, "the snapshotter never ran") else { return }

        let racing = onThread { boxed.value.setModel("racing") }
        let committedAtOnce = racing.wait(timeout: .now() + crossThreadTimeout) == .success
        releaseSnapshot.signal()
        guard wait(approved, "the approval stalled") else { return }
        if !committedAtOnce { wait(racing, "the racing call stalled") }

        XCTAssertTrue(committedAtOnce, "the call did not wait for the snapshotter")
        XCTAssertEqual(form.model, "racing", "without a reset, the call's model stands")
        XCTAssertEqual(form.snapshot, "edited", "the snapshot advanced to the captured value")
        XCTAssertTrue(form.isDirty)
    }

    // ── #1426: publication waits ──────────────────────────────────────────────

    /// A refused `dispose()` wakes another thread's waiting `setModel` at
    /// once, before the publisher's scope ends (§5.5 refused waits rule 4).
    ///
    /// Thread X holds an update scope: its `errorsChanged` sink sends on hub
    /// `H` while thread Y drains `H`. Thread W's `setModel` waits for X's
    /// scope. Y's subscriber then disposes the form; that wait closes a cycle
    /// and is refused.
    func testRefusedDisposeWakesAWaitingSetModelAtOnce() {
        let hub = MessageHub()
        let form = FormVM(
            initial: "saved",
            persister: { (_: String) in },
            validators: ["value": { $0 == "bad" ? "rejected" : nil }]
        )
        let boxedForm = UncheckedSendableBox(form)
        let boxedHub = UncheckedSendableBox(hub)
        let drainerEntered = DispatchSemaphore(value: 0)
        let disposeNow = DispatchSemaphore(value: 0)
        let publisherInScope = DispatchSemaphore(value: 0)
        let publisherSends = DispatchSemaphore(value: 0)
        let publisherWaitsOnHub = DispatchSemaphore(value: 0)
        let releasePublisher = DispatchSemaphore(value: 0)
        let waiterWaits = DispatchSemaphore(value: 0)
        let waiterThread = Shared<UInt64>(0)
        let finished = Shared(false)

        hub.messages
            .sink { message in
                guard message.senderName == "drainer" else { return }
                drainerEntered.signal()
                _ = disposeNow.wait(timeout: .now() + crossThreadTimeout * 2)
                boxedForm.value.dispose()
            }
            .store(in: &cancellables)
        let armed = Shared(true)
        form.errorsChanged
            .sink(receiveCompletion: { _ in finished.value = true }, receiveValue: { _ in
                guard armed.exchange(false) else { return }
                publisherInScope.signal()
                _ = publisherSends.wait(timeout: .now() + crossThreadTimeout * 2)
                boxedHub.value.send(Ping(senderObject: NSObject(), senderName: "publisher"))
                _ = releasePublisher.wait(timeout: .now() + crossThreadTimeout * 2)
            })
            .store(in: &cancellables)

        let drainerDone = onThread {
            boxedHub.value.send(Ping(senderObject: NSObject(), senderName: "drainer"))
        }
        guard wait(drainerEntered, "Y never took the drain") else { return }
        let publisherDone = onThread { boxedForm.value.setModel("bad") }
        guard wait(publisherInScope, "X never opened its scope") else { return }

        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            if accepted, caller == waiterThread.value { waiterWaits.signal() }
        }
        let waiterDone = onThread {
            waiterThread.value = ThreadWaitGraph.currentThread
            boxedForm.value.setModel("w")
        }
        guard wait(waiterWaits, "W never waited for X's scope") else { return }

        hub.onWaitRegisteredForTesting = { publisherWaitsOnHub.signal() }
        publisherSends.signal()
        guard wait(publisherWaitsOnHub, "X never waited for Y's drain") else { return }
        disposeNow.signal()

        let wokeAtOnce = waiterDone.wait(timeout: .now() + crossThreadTimeout) == .success
        let finishedBeforeScopeEnds = finished.value
        releasePublisher.signal()
        guard wait(publisherDone, "thread X stalled"), wait(drainerDone, "thread Y stalled") else { return }
        if !wokeAtOnce { wait(waiterDone, "thread W stalled") }

        XCTAssertTrue(wokeAtOnce, "the refused dispose() woke W before X's scope ended")
        XCTAssertFalse(finishedBeforeScopeEnds, "the teardown waits for X's scope")
        XCTAssertTrue(finished.value, "the teardown ran when X's scope ended")
        XCTAssertEqual(form.model, "bad", "W found the form disposed")
    }

    /// An update opens a publication scope only when its commit changes the
    /// error map (§5.5).
    func testUpdateOpensAScopeOnlyWhenTheErrorMapChanges() {
        let form = FormVM(
            initial: "saved",
            persister: { (_: String) in },
            validators: ["value": { $0 == "bad" ? "rejected" : nil }]
        )
        form.setModel("edited")
        form.denyCommand.execute()
        XCTAssertEqual(form.updateScopesOpenedForTesting, 0, "unchanged error maps open no scope")

        form.setModel("bad")
        XCTAssertEqual(form.updateScopesOpenedForTesting, 1)
        form.denyCommand.execute()
        XCTAssertEqual(form.updateScopesOpenedForTesting, 2)
    }
}
