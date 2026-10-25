//
// FormApprovalAdmissionTests.swift — FORM-031..034 conformance tests.
//
// A form admits one approval at a time. Each persister call parks on a
// continuation until the test releases it, so every "in flight" assertion
// runs while the persister is provably blocked, and every wait is bounded.
// See spec/20-form-vm.md §5.3 and ADR-0143.
//

import Combine
import Foundation
import XCTest
@testable import VMx

private enum ApprovalTestError: Error, Equatable {
    case persist
    case reset
}

/// Hang guard for every wait. Tests resume as soon as the awaited event
/// happens; the bound only turns a missing event into a failure.
private let admissionTimeout: TimeInterval = 10

/// Thread-safe ordered record of observed events.
private final class ApprovalEventLog: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: [String] = []

    func append(_ event: String) {
        lock.lock()
        storage.append(event)
        lock.unlock()
    }

    var events: [String] {
        lock.lock()
        defer { lock.unlock() }
        return storage
    }
}

/// Thread-safe counter.
private final class ApprovalCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var storage = 0

    func increment() {
        lock.lock()
        storage += 1
        lock.unlock()
    }

    var value: Int {
        lock.lock()
        defer { lock.unlock() }
        return storage
    }
}

/// A flag consumed by its first `take()`, so an observer acts once.
private final class ApprovalOneShot: @unchecked Sendable {
    private let lock = NSLock()
    private var armed = true

    func take() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        let wasArmed = armed
        armed = false
        return wasArmed
    }
}

/// Late-bound reference for a persister created before its form.
private final class ApprovalFormRef: @unchecked Sendable {
    weak var form: FormVM<String>?
}

/// Persister that records each call and parks it until the test releases it.
private final class GatedPersister: @unchecked Sendable {
    private let lock = NSLock()
    private var models: [String] = []
    private var parked: [CheckedContinuation<Error?, Never>] = []
    private var waiters: [(count: Int, expectation: XCTestExpectation)] = []

    /// Models passed to the persister, in call order.
    var calls: [String] {
        lock.lock()
        defer { lock.unlock() }
        return models
    }

    func persist(_ model: String) async throws {
        let failure = await withCheckedContinuation { (continuation: CheckedContinuation<Error?, Never>) in
            lock.lock()
            models.append(model)
            parked.append(continuation)
            let count = models.count
            let reached = waiters.filter { $0.count <= count }.map { $0.expectation }
            waiters.removeAll { $0.count <= count }
            lock.unlock()
            reached.forEach { $0.fulfill() }
        }
        if let failure { throw failure }
    }

    /// Fulfilled once `count` calls have parked, including earlier calls.
    func arrivals(_ count: Int) -> XCTestExpectation {
        let expectation = XCTestExpectation(description: "\(count) persister call(s) parked")
        lock.lock()
        let reached = models.count >= count
        if !reached { waiters.append((count: count, expectation: expectation)) }
        lock.unlock()
        if reached { expectation.fulfill() }
        return expectation
    }

    /// Resumes the oldest parked call with success, or with a throw of `failure`.
    func release(throwing failure: Error? = nil) {
        lock.lock()
        let continuation = parked.isEmpty ? nil : parked.removeFirst()
        lock.unlock()
        XCTAssertNotNil(continuation, "release() needs a parked persister call")
        continuation?.resume(returning: failure)
    }
}

/// Runs `approveAsync()` in an unstructured task and records how it ended.
private final class ApprovalRun: @unchecked Sendable {
    let finished: XCTestExpectation
    private let lock = NSLock()
    private var failure: Error?

    init(_ form: FormVM<String>, _ description: String) {
        finished = XCTestExpectation(description: description)
        let box = UncheckedSendableBox(form)
        Task { [self, box] in
            do {
                try await box.value.approveAsync()
            } catch {
                self.record(error)
            }
            self.finished.fulfill()
        }
    }

    private func record(_ error: Error) {
        lock.lock()
        failure = error
        lock.unlock()
    }

    /// The error the run threw, or `nil` when it returned normally.
    var error: Error? {
        lock.lock()
        defer { lock.unlock() }
        return failure
    }
}

final class FormApprovalAdmissionTests: XCTestCase {
    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    // ── FORM-031 ──────────────────────────────────────────────────────────────

    /// FORM-031 — a second approval during an in-flight approval is refused: calls from the
    /// awaiter, the command, the persister, and a canExecuteChanged handler persist nothing.
    func testForm031_secondApprovalDuringAnInFlightApprovalIsRefused() async throws {
        let probe = GatedPersister()
        let ref = ApprovalFormRef()
        let log = ApprovalEventLog()
        let fromPersister = ApprovalOneShot()
        let form = FormVM(
            initial: "initial",
            persister: { (model: String) in
                if fromPersister.take() {
                    // Called inside the admitted approval: refused at once.
                    do {
                        try await ref.form?.approveAsync()
                        log.append("persister approval returned")
                    } catch {
                        log.append("persister approval threw")
                    }
                }
                try await probe.persist(model)
            }
        )
        ref.form = form
        form.setModel("first")

        let approved = ApprovalEventLog()
        let failures = ApprovalEventLog()
        form.onApproved.sink { approved.append($0) }.store(in: &cancellables)
        form.approveErrors.sink { failures.append("\($0)") }.store(in: &cancellables)

        // The first notification is the admission, raised while in flight.
        let fromHandler = ApprovalOneShot()
        let handlerApproval = XCTestExpectation(description: "handler approval finished")
        let boxed = UncheckedSendableBox(form)
        form.approveCommand.canExecuteChanged.sink {
            guard fromHandler.take() else { return }
            Task {
                do {
                    try await boxed.value.approveAsync()
                    log.append("handler approval returned")
                } catch {
                    log.append("handler approval threw")
                }
                handlerApproval.fulfill()
            }
        }.store(in: &cancellables)

        let first = ApprovalRun(form, "first approval")
        await fulfillment(of: [probe.arrivals(1), handlerApproval], timeout: admissionTimeout)

        // A direct call and a command execution while the persister is blocked.
        let refused = ApprovalRun(form, "refused approval")
        await fulfillment(of: [refused.finished], timeout: admissionTimeout)
        XCTAssertNil(refused.error, "a refused call returns normally")
        form.approveCommand.execute()

        XCTAssertEqual(
            Set(log.events), ["persister approval returned", "handler approval returned"],
            "refused calls return normally"
        )
        XCTAssertEqual(probe.calls, ["first"], "only the admitted approval reaches the persister")
        XCTAssertEqual(form.model, "first")
        XCTAssertEqual(form.snapshot, "initial")
        XCTAssertEqual(form.errors, [:])
        XCTAssertTrue(form.isDirty)
        XCTAssertEqual(approved.events, [])
        XCTAssertEqual(failures.events, [])

        probe.release()
        await fulfillment(of: [first.finished], timeout: admissionTimeout)
        XCTAssertNil(first.error)
        XCTAssertEqual(form.snapshot, "first", "the snapshot is the first approval's capture")
        XCTAssertEqual(approved.events, ["first"])

        // After settlement the next approval is admitted and persists its own capture.
        form.setModel("second")
        let second = ApprovalRun(form, "second approval")
        await fulfillment(of: [probe.arrivals(2)], timeout: admissionTimeout)
        probe.release()
        await fulfillment(of: [second.finished], timeout: admissionTimeout)
        XCTAssertNil(second.error)
        XCTAssertEqual(probe.calls, ["first", "second"])
        XCTAssertEqual(form.snapshot, "second")
        XCTAssertFalse(form.isDirty)
        XCTAssertEqual(approved.events, ["first", "second"])
        XCTAssertEqual(failures.events, [])
    }

    // ── FORM-032 ──────────────────────────────────────────────────────────────

    /// FORM-032 — the approve command is disabled while an approval is in flight;
    /// canExecuteChanged fires once on admission and once on each settlement.
    func testForm032_approveCommandIsDisabledWhileAnApprovalIsInFlight() async throws {
        let probe = GatedPersister()
        let ref = ApprovalFormRef()
        let changes = ApprovalCounter()
        let atEntry = ApprovalEventLog()
        let form = FormVM(
            initial: "initial",
            persister: { (model: String) in
                let canExecute = ref.form?.approveCommand.canExecute() ?? true
                atEntry.append("\(changes.value) change(s), canExecute \(canExecute)")
                try await probe.persist(model)
            }
        )
        ref.form = form
        form.approveCommand.canExecuteChanged.sink { changes.increment() }.store(in: &cancellables)
        XCTAssertTrue(form.approveCommand.canExecute())

        // Success.
        form.setModel("saved")
        let success = ApprovalRun(form, "successful approval")
        await fulfillment(of: [probe.arrivals(1)], timeout: admissionTimeout)
        XCTAssertEqual(atEntry.events, ["1 change(s), canExecute false"],
                       "admission notifies exactly once before the persister runs")
        XCTAssertFalse(form.approveCommand.canExecute())
        probe.release()
        await fulfillment(of: [success.finished], timeout: admissionTimeout)
        XCTAssertNil(success.error)
        XCTAssertEqual(changes.value, 2, "a successful settlement notifies exactly once")
        XCTAssertTrue(form.approveCommand.canExecute())

        // Persister failure.
        form.setModel("rejected")
        let failure = ApprovalRun(form, "failed approval")
        await fulfillment(of: [probe.arrivals(2)], timeout: admissionTimeout)
        XCTAssertEqual(atEntry.events.last, "3 change(s), canExecute false")
        XCTAssertFalse(form.approveCommand.canExecute())
        probe.release(throwing: ApprovalTestError.persist)
        await fulfillment(of: [failure.finished], timeout: admissionTimeout)
        XCTAssertEqual(failure.error as? ApprovalTestError, ApprovalTestError.persist)
        XCTAssertEqual(changes.value, 4, "a failed settlement notifies exactly once")
        XCTAssertTrue(form.approveCommand.canExecute())

        // A reset that throws after a successful persist.
        let resetProbe = GatedPersister()
        let resetChanges = ApprovalCounter()
        let resetting = FormVM(
            initial: "initial",
            persister: { (model: String) in try await resetProbe.persist(model) },
            resetOnApproved: { _ in throw ApprovalTestError.reset }
        )
        resetting.approveCommand.canExecuteChanged
            .sink { resetChanges.increment() }
            .store(in: &cancellables)
        resetting.setModel("saved")
        let resetRun = ApprovalRun(resetting, "approval whose reset fails")
        await fulfillment(of: [resetProbe.arrivals(1)], timeout: admissionTimeout)
        XCTAssertEqual(resetChanges.value, 1)
        XCTAssertFalse(resetting.approveCommand.canExecute())
        resetProbe.release()
        await fulfillment(of: [resetRun.finished], timeout: admissionTimeout)
        XCTAssertEqual(resetRun.error as? ApprovalTestError, ApprovalTestError.reset)
        XCTAssertEqual(resetChanges.value, 2, "a failed reset settles with exactly one notification")
        XCTAssertTrue(resetting.approveCommand.canExecute())
        XCTAssertEqual(resetting.snapshot, "initial")

        // Strict mode, through the command path: execute() admits before it
        // returns, and the dirty-to-pristine change shares the one settlement
        // notification.
        let strictProbe = GatedPersister()
        let strictChanges = ApprovalCounter()
        let strictForm = FormVM(
            initial: "initial",
            persister: { (model: String) in try await strictProbe.persist(model) },
            strict: true
        )
        strictForm.approveCommand.canExecuteChanged
            .sink { strictChanges.increment() }
            .store(in: &cancellables)
        let strictSettled = XCTestExpectation(description: "strict approval settled")
        strictForm.onApproved.sink { _ in strictSettled.fulfill() }.store(in: &cancellables)
        XCTAssertFalse(strictForm.approveCommand.canExecute())
        strictForm.setModel("edited")
        XCTAssertEqual(strictChanges.value, 1)
        XCTAssertTrue(strictForm.approveCommand.canExecute())

        strictForm.approveCommand.execute()
        XCTAssertEqual(strictChanges.value, 2, "execute() raises the admission notification")
        XCTAssertFalse(strictForm.approveCommand.canExecute(), "execute() admits before returning")
        strictForm.approveCommand.execute()
        await fulfillment(of: [strictProbe.arrivals(1)], timeout: admissionTimeout)
        strictProbe.release()
        await fulfillment(of: [strictSettled], timeout: admissionTimeout)
        XCTAssertEqual(strictChanges.value, 3)
        XCTAssertEqual(strictProbe.calls, ["edited"], "the second execute() was refused")
        XCTAssertFalse(strictForm.approveCommand.canExecute(), "a pristine strict form stays disabled")
        strictForm.setModel("next")
        XCTAssertTrue(strictForm.approveCommand.canExecute())
    }

    // ── FORM-033 ──────────────────────────────────────────────────────────────

    /// FORM-033 — settlement publishes errorsChanged, one canExecuteChanged, then onApproved,
    /// each after the in-flight mark is cleared.
    func testForm033_settlementNotificationsFollowTheClearedMark() async throws {
        let probe = GatedPersister()
        let form = FormVM(
            initial: "initial",
            persister: { (model: String) in try await probe.persist(model) },
            validators: ["value": { $0.isEmpty ? "required" : nil }],
            resetOnApproved: { "reset:\($0)" }
        )
        form.setModel("first")
        let log = ApprovalEventLog()
        let boxed = UncheckedSendableBox(form)
        form.errorsChanged.sink { errors in
            let canExecute = boxed.value.approveCommand.canExecute()
            log.append("errors \(errors.isEmpty ? "cleared" : "set"), canExecute \(canExecute)")
        }.store(in: &cancellables)
        form.approveCommand.canExecuteChanged.sink {
            log.append("canExecuteChanged, canExecute \(boxed.value.approveCommand.canExecute())")
        }.store(in: &cancellables)
        form.onApproved.sink { approved in
            log.append("approved \(approved), canExecute \(boxed.value.approveCommand.canExecute())")
        }.store(in: &cancellables)

        let run = ApprovalRun(form, "approval")
        await fulfillment(of: [probe.arrivals(1)], timeout: admissionTimeout)
        // An edit during the persist invalidates the form; the reset repairs it.
        form.setModel("")
        probe.release()
        await fulfillment(of: [run.finished], timeout: admissionTimeout)

        XCTAssertNil(run.error)
        XCTAssertEqual(log.events, [
            "canExecuteChanged, canExecute false",  // admission
            "errors set, canExecute false",         // the racing edit
            "canExecuteChanged, canExecute false",  // its validity change
            "errors cleared, canExecute true",      // settlement: errors
            "canExecuteChanged, canExecute true",   // settlement: exactly one
            "approved first, canExecute true",      // settlement: outcome
        ])
        XCTAssertEqual(form.model, "reset:first")
        XCTAssertEqual(form.snapshot, "reset:first")
        XCTAssertTrue(form.isValid)
    }

    /// FORM-033 — an onApproved subscriber sees an idle form, and its approval is admitted
    /// and captures the settled model.
    func testForm033_approvedObserverStartsTheNextApproval() async throws {
        let probe = GatedPersister()
        let form = FormVM(
            initial: "initial",
            persister: { (model: String) in try await probe.persist(model) },
            resetOnApproved: { "reset:\($0)" }
        )
        form.setModel("first")
        let observed = ApprovalEventLog()
        let fromObserver = ApprovalOneShot()
        let observerApproval = XCTestExpectation(description: "observer approval finished")
        let boxed = UncheckedSendableBox(form)
        form.onApproved.sink { approved in
            guard fromObserver.take() else { return }
            let canExecute = boxed.value.approveCommand.canExecute()
            observed.append("approved \(approved), canExecute \(canExecute)")
            Task {
                do {
                    try await boxed.value.approveAsync()
                    observed.append("observer approval returned")
                } catch {
                    observed.append("observer approval threw")
                }
                observerApproval.fulfill()
            }
        }.store(in: &cancellables)

        let first = ApprovalRun(form, "first approval")
        await fulfillment(of: [probe.arrivals(1)], timeout: admissionTimeout)
        probe.release()
        // The observer's approval is admitted and persists the settled model.
        await fulfillment(of: [first.finished, probe.arrivals(2)], timeout: admissionTimeout)
        XCTAssertNil(first.error)
        XCTAssertEqual(probe.calls, ["first", "reset:first"])
        probe.release()
        await fulfillment(of: [observerApproval], timeout: admissionTimeout)

        XCTAssertEqual(observed.events, [
            "approved first, canExecute true",
            "observer approval returned",
        ])
        XCTAssertEqual(form.model, "reset:reset:first")
        XCTAssertEqual(form.snapshot, "reset:reset:first")
    }

    /// FORM-033 — a failed approval settles before its one failure channel: an approveErrors
    /// subscriber, or the awaiter that catches it, may approve again and is admitted.
    func testForm033_failureObserversStartTheNextApproval() async throws {
        let probe = GatedPersister()
        let form = FormVM(
            initial: "initial",
            persister: { (model: String) in try await probe.persist(model) }
        )
        form.setModel("first")
        let boxed = UncheckedSendableBox(form)
        let failures = ApprovalEventLog()
        let fromObserver = ApprovalOneShot()
        let observerApproval = XCTestExpectation(description: "approveErrors observer approval finished")
        form.approveErrors.sink { error in
            let state = boxed.value
            failures.append(
                "\(error): model \(state.model), snapshot \(state.snapshot), "
                    + "\(state.errors.count) error(s), canExecute \(state.approveCommand.canExecute())"
            )
            guard fromObserver.take() else { return }
            Task {
                do {
                    try await boxed.value.approveAsync()
                    failures.append("observer approval returned")
                } catch {
                    failures.append("observer approval threw")
                }
                observerApproval.fulfill()
            }
        }.store(in: &cancellables)

        // Command path: the failure reaches approveErrors once, after settlement.
        form.approveCommand.execute()
        await fulfillment(of: [probe.arrivals(1)], timeout: admissionTimeout)
        probe.release(throwing: ApprovalTestError.persist)
        await fulfillment(of: [probe.arrivals(2)], timeout: admissionTimeout)
        XCTAssertEqual(probe.calls, ["first", "first"], "the observer's approval was admitted")
        probe.release()
        await fulfillment(of: [observerApproval], timeout: admissionTimeout)
        XCTAssertEqual(failures.events, [
            "persist: model first, snapshot initial, 0 error(s), canExecute true",
            "observer approval returned",
        ])
        XCTAssertEqual(form.snapshot, "first")

        // Awaitable path: only the awaiter observes the failure, and its retry is admitted.
        form.setModel("second")
        let retryLog = ApprovalEventLog()
        let retried = XCTestExpectation(description: "awaiter retried")
        Task {
            do {
                try await boxed.value.approveAsync()
                retryLog.append("no failure")
            } catch {
                let canExecute = boxed.value.approveCommand.canExecute()
                retryLog.append("caught \(error), canExecute \(canExecute)")
                do {
                    try await boxed.value.approveAsync()
                    retryLog.append("retry returned")
                } catch {
                    retryLog.append("retry threw")
                }
            }
            retried.fulfill()
        }
        await fulfillment(of: [probe.arrivals(3)], timeout: admissionTimeout)
        probe.release(throwing: ApprovalTestError.persist)
        await fulfillment(of: [probe.arrivals(4)], timeout: admissionTimeout)
        XCTAssertEqual(probe.calls, ["first", "first", "second", "second"])
        probe.release()
        await fulfillment(of: [retried], timeout: admissionTimeout)

        XCTAssertEqual(retryLog.events, ["caught persist, canExecute true", "retry returned"])
        XCTAssertEqual(failures.events.count, 2, "the awaited failure is not emitted on approveErrors")
        XCTAssertEqual(form.snapshot, "second")
        XCTAssertFalse(form.isDirty)
    }

    // ── FORM-034 ──────────────────────────────────────────────────────────────

    /// FORM-034 — setModel and denyCommand proceed during an in-flight approval, which still
    /// commits its captured value, or its authoritative reset.
    func testForm034_editsAndDenyProceedDuringAnInFlightApproval() async throws {
        let probe = GatedPersister()
        let form = FormVM(
            initial: "initial",
            persister: { (model: String) in try await probe.persist(model) }
        )
        let approved = ApprovalEventLog()
        form.onApproved.sink { approved.append($0) }.store(in: &cancellables)
        form.setModel("captured")

        // An edit during the persist.
        let edited = ApprovalRun(form, "approval racing an edit")
        await fulfillment(of: [probe.arrivals(1)], timeout: admissionTimeout)
        form.setModel("newer")
        XCTAssertEqual(form.model, "newer", "setModel is not blocked")
        probe.release()
        await fulfillment(of: [edited.finished], timeout: admissionTimeout)
        XCTAssertNil(edited.error)
        XCTAssertEqual(form.snapshot, "captured")
        XCTAssertEqual(form.model, "newer")
        XCTAssertTrue(form.isDirty)
        XCTAssertEqual(approved.events, ["captured"])

        // A deny during another persist reverts to the current snapshot.
        let denied = ApprovalRun(form, "approval racing a deny")
        await fulfillment(of: [probe.arrivals(2)], timeout: admissionTimeout)
        XCTAssertTrue(form.denyCommand.canExecute())
        form.denyCommand.execute()
        XCTAssertEqual(form.model, "captured", "deny is not blocked")
        probe.release()
        await fulfillment(of: [denied.finished], timeout: admissionTimeout)
        XCTAssertNil(denied.error)
        XCTAssertEqual(probe.calls, ["captured", "newer"])
        XCTAssertEqual(form.snapshot, "newer", "the approval still commits its capture")
        XCTAssertEqual(form.model, "captured")
        XCTAssertTrue(form.isDirty)
        XCTAssertEqual(approved.events, ["captured", "newer"])

        // With resetOnApproved, the reset replaces the edited or reverted model.
        let resetProbe = GatedPersister()
        let resetting = FormVM(
            initial: "initial",
            persister: { (model: String) in try await resetProbe.persist(model) },
            resetOnApproved: { "reset:\($0)" }
        )
        resetting.setModel("captured")
        let resetEdited = ApprovalRun(resetting, "reset approval racing an edit")
        await fulfillment(of: [resetProbe.arrivals(1)], timeout: admissionTimeout)
        resetting.setModel("newer")
        resetProbe.release()
        await fulfillment(of: [resetEdited.finished], timeout: admissionTimeout)
        XCTAssertNil(resetEdited.error)
        XCTAssertEqual(resetting.model, "reset:captured")
        XCTAssertEqual(resetting.snapshot, "reset:captured")
        XCTAssertFalse(resetting.isDirty)

        resetting.setModel("draft")
        let resetDenied = ApprovalRun(resetting, "reset approval racing a deny")
        await fulfillment(of: [resetProbe.arrivals(2)], timeout: admissionTimeout)
        resetting.denyCommand.execute()
        XCTAssertEqual(resetting.model, "reset:captured")
        resetProbe.release()
        await fulfillment(of: [resetDenied.finished], timeout: admissionTimeout)
        XCTAssertNil(resetDenied.error)
        XCTAssertEqual(resetProbe.calls, ["captured", "draft"])
        XCTAssertEqual(resetting.model, "reset:draft")
        XCTAssertEqual(resetting.snapshot, "reset:draft")
        XCTAssertFalse(resetting.isDirty)
    }

    /// FORM-034 — disposal during an in-flight approval suppresses settlement and every later
    /// approve call does nothing; the test completes within a bounded timeout.
    func testForm034_disposalDuringAnInFlightApprovalSuppressesSettlement() async throws {
        let probe = GatedPersister()
        // A settled commit would publish on every channel: the reset changes the errors.
        let form = FormVM(
            initial: "initial",
            persister: { (model: String) in try await probe.persist(model) },
            validators: ["value": { $0.isEmpty ? "required" : nil }],
            resetOnApproved: { _ in "" }
        )
        form.setModel("captured")
        let events = ApprovalEventLog()
        form.onApproved.sink { events.append("approved \($0)") }.store(in: &cancellables)
        form.approveErrors.sink { events.append("approveErrors \($0)") }.store(in: &cancellables)
        form.errorsChanged.sink { _ in events.append("errorsChanged") }.store(in: &cancellables)
        form.approveCommand.canExecuteChanged
            .sink { events.append("canExecuteChanged") }
            .store(in: &cancellables)

        let awaited = ApprovalRun(form, "approval disposed in flight")
        await fulfillment(of: [probe.arrivals(1)], timeout: admissionTimeout)
        form.dispose()
        let atDisposal = events.events
        probe.release()
        await fulfillment(of: [awaited.finished], timeout: admissionTimeout)

        XCTAssertNil(awaited.error, "the awaiter's outcome is unchanged by disposal")
        XCTAssertEqual(events.events, atDisposal, "nothing is emitted after disposal")
        XCTAssertFalse(atDisposal.contains { $0.hasPrefix("approved") || $0 == "errorsChanged" })
        XCTAssertEqual(form.model, "captured")
        XCTAssertEqual(form.snapshot, "initial")
        XCTAssertEqual(form.errors, [:])

        let afterDisposal = ApprovalRun(form, "approval after disposal")
        await fulfillment(of: [afterDisposal.finished], timeout: admissionTimeout)
        XCTAssertNil(afterDisposal.error)
        form.approveCommand.execute()
        XCTAssertEqual(probe.calls, ["captured"], "a disposed form never invokes the persister again")

        // Command path: a failure that lands after disposal is dropped.
        let commandProbe = GatedPersister()
        let commandForm = FormVM(
            initial: "initial",
            persister: { (model: String) in try await commandProbe.persist(model) }
        )
        commandForm.setModel("captured")
        let lateFailure = XCTestExpectation(description: "approveErrors after disposal")
        lateFailure.isInverted = true
        commandForm.approveErrors.sink { _ in lateFailure.fulfill() }.store(in: &cancellables)
        commandForm.approveCommand.execute()
        await fulfillment(of: [commandProbe.arrivals(1)], timeout: admissionTimeout)
        commandForm.dispose()
        commandProbe.release(throwing: ApprovalTestError.persist)
        await fulfillment(of: [lateFailure], timeout: 0.3)
        let commandAfterDisposal = ApprovalRun(commandForm, "command form approval after disposal")
        await fulfillment(of: [commandAfterDisposal.finished], timeout: admissionTimeout)
        XCTAssertNil(commandAfterDisposal.error)
        XCTAssertEqual(commandProbe.calls, ["captured"])
        XCTAssertEqual(commandForm.snapshot, "initial")
    }
}
