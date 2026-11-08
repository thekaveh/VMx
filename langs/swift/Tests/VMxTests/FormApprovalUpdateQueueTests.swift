//
// FormApprovalUpdateQueueTests.swift — FORM-039..040 conformance tests.
//
// `FormVM` queues a `setModel` or deny that the approving thread makes during
// the pre-publication window and replays it after `onApproved`. See
// spec/20-form-vm.md §5.1, §5.3 and §5.4, and ADR-0174.
//
// Swift validators, `equals`, the snapshotter, and sinks cannot throw, so the
// FORM-040 test covers only the call-time preparation, equality, staleness,
// and replay-order clauses. The failure-isolation and failure-channel clauses
// have no Swift equivalent.
//

import Combine
import Foundation
import XCTest
@testable import VMx

/// Thread-safe event log shared by sinks, the hub, and callbacks.
private final class QueueEventLog: @unchecked Sendable {
    private let lock = NSLock()
    private var entries: [String] = []

    func append(_ entry: String) {
        lock.lock()
        entries.append(entry)
        lock.unlock()
    }

    var events: [String] {
        lock.lock()
        defer { lock.unlock() }
        return entries
    }

    /// The events logged after `marker`, or all events when it is absent.
    func events(after marker: String) -> [String] {
        let all = events
        guard let index = all.firstIndex(of: marker) else { return all }
        return Array(all[(index + 1)...])
    }

    /// The events logged before `marker`, or all events when it is absent.
    func events(before marker: String) -> [String] {
        let all = events
        guard let index = all.firstIndex(of: marker) else { return all }
        return Array(all[..<index])
    }
}

/// A hub that logs each form message with the model the form holds when the
/// message is sent.
private final class QueueLogHub<Model>: MessageHubProtocol {
    private let subject = PassthroughSubject<any Message, Never>()
    private let log: QueueEventLog
    weak var form: FormVM<Model>?

    init(_ log: QueueEventLog) { self.log = log }

    var messages: AnyPublisher<any Message, Never> { subject.eraseToAnyPublisher() }

    func send(_ message: any Message) {
        if message is FormRevertedMessage {
            log.append("reverted")
        } else if let changed = message as? PropertyChangedMessage, changed.propertyName == "model" {
            log.append("model=\(form.map { "\($0.model)" } ?? "?")")
        }
        subject.send(message)
    }
}

/// Lets a sink act once.
private final class Once: @unchecked Sendable {
    private let lock = NSLock()
    private var armed: Bool

    init(armed: Bool = true) { self.armed = armed }

    func arm() {
        lock.lock()
        armed = true
        lock.unlock()
    }

    func claim() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard armed else { return false }
        armed = false
        return true
    }
}

/// Bound for each approval, so a deadlock fails the test instead of hanging
/// the run.
private let approvalTimeout: TimeInterval = 10

/// Thrown when an approval does not return within `approvalTimeout`.
private struct ApprovalStalled: Error {}

/// The error an approval threw, set once on the approving task.
private final class ApprovalOutcome: @unchecked Sendable {
    private let lock = NSLock()
    private var thrown: Error?

    func record(_ error: Error) {
        lock.lock()
        thrown = error
        lock.unlock()
    }

    var error: Error? {
        lock.lock()
        defer { lock.unlock() }
        return thrown
    }
}

final class FormApprovalUpdateQueueTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    /// Runs `approveAsync()` on a detached task and waits at most
    /// `approvalTimeout` for it. A stalled approval throws `ApprovalStalled`
    /// before the test reads the form, whose state lock it may hold; its task
    /// is left behind rather than hanging the run.
    private func approve<Model>(
        _ form: FormVM<Model>,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async throws {
        let returned = expectation(description: "approveAsync returned")
        let outcome = ApprovalOutcome()
        let boxedForm = UncheckedSendableBox(form)
        Task.detached {
            do {
                try await boxedForm.value.approveAsync()
            } catch {
                outcome.record(error)
            }
            returned.fulfill()
        }
        let waited = await XCTWaiter().fulfillment(of: [returned], timeout: approvalTimeout)
        guard waited == .completed else {
            XCTFail("the approval stalled", file: file, line: line)
            throw ApprovalStalled()
        }
        if let error = outcome.error { throw error }
    }

    /// Logs the form's `errorsChanged`, `canExecuteChanged`, and `onApproved`
    /// events. `approved` records what an `onApproved` observer sees.
    private func observe<Model>(
        _ form: FormVM<Model>,
        _ log: QueueEventLog,
        approved: @escaping (FormVM<Model>) -> Void = { _ in }
    ) {
        form.errorsChanged
            .sink { errors in log.append("errors=\(errors.keys.sorted())") }
            .store(in: &cancellables)
        form.approveCommand.canExecuteChanged
            .sink { _ in log.append("canExecute") }
            .store(in: &cancellables)
        form.onApproved
            .sink { [weak form] _ in
                if let form { approved(form) }
                log.append("approved")
            }
            .store(in: &cancellables)
    }

    /// FORM-039 — a `setModel` from `resetOnApproved` replays after `onApproved`.
    func testResetSetModelReplaysAfterOnApproved() async throws {
        let log = QueueEventLog()
        let hub = QueueLogHub<String>(log)
        weak var weakForm: FormVM<String>?
        let form = FormVM<String>(
            initial: "saved",
            persister: { _ in log.append("persisted") },
            hub: hub,
            validators: ["value": { $0 == "x" ? "rejected" : nil }],
            resetOnApproved: { _ in
                weakForm?.setModel("x")
                log.append("reset returned")
                return "pristine"
            }
        )
        weakForm = form
        hub.form = form
        var lastErrors: [String: String]?
        form.errorsChanged.sink { lastErrors = $0 }.store(in: &cancellables)
        var seen: (model: String, dirty: Bool, valid: Bool)?
        observe(form, log) { form in seen = (form.model, form.isDirty, form.isValid) }

        try await approve(form)

        // The nested call published nothing before `onApproved`: after the
        // admission's `canExecuteChanged` and persistence, the only event is
        // the settlement's single `canExecuteChanged`.
        XCTAssertEqual(
            log.events(before: "approved"),
            ["canExecute", "persisted", "reset returned", "canExecute"]
        )
        XCTAssertEqual(seen?.model, "pristine")
        XCTAssertEqual(seen?.dirty, false)
        XCTAssertEqual(seen?.valid, true)
        // The replay publishes its own notifications after `onApproved`.
        XCTAssertEqual(log.events(after: "approved"), ["errors=[\"value\"]", "canExecute", "model=x"])
        XCTAssertEqual(form.model, "x")
        XCTAssertEqual(form.errors, ["value": "rejected"])
        XCTAssertEqual(lastErrors, form.errors)
    }

    /// FORM-039 — a deny from a settlement `canExecuteChanged` observer replays after `onApproved`.
    func testSettlementObserverDenyReplaysAfterOnApproved() async throws {
        let log = QueueEventLog()
        let hub = QueueLogHub<String>(log)
        let armed = Once(armed: false)
        weak var weakForm: FormVM<String>?
        let form = FormVM<String>(
            initial: "initial",
            persister: { _ in
                // An edit that races persistence; the approval keeps `saved`.
                weakForm?.setModel("newer")
                armed.arm()
            },
            hub: hub
        )
        weakForm = form
        hub.form = form
        form.setModel("saved")
        form.approveCommand.canExecuteChanged
            .sink { [weak form] _ in
                guard armed.claim() else { return }
                form?.denyCommand.execute()
                log.append("deny returned")
            }
            .store(in: &cancellables)
        var seen: (model: String, dirty: Bool)?
        observe(form, log) { form in seen = (form.model, form.isDirty) }

        try await approve(form)

        XCTAssertEqual(seen?.model, "newer", "onApproved observers never see a queued revert")
        XCTAssertEqual(seen?.dirty, true)
        XCTAssertFalse(log.events(before: "approved").contains("reverted"))
        XCTAssertTrue(log.events(before: "approved").contains("deny returned"))
        XCTAssertEqual(log.events(after: "approved"), ["reverted", "model=saved"])
        XCTAssertEqual(form.model, "saved")
        XCTAssertFalse(form.isDirty)
    }

    /// FORM-039 — calls from `resetOnApproved` replay in call order.
    func testResetSetModelThenDenyReplayInCallOrder() async throws {
        let log = QueueEventLog()
        let hub = QueueLogHub<String>(log)
        weak var weakForm: FormVM<String>?
        let form = FormVM<String>(
            initial: "saved",
            persister: { _ in log.append("persisted") },
            hub: hub,
            resetOnApproved: { _ in
                weakForm?.setModel("a")
                weakForm?.denyCommand.execute()
                return "pristine"
            }
        )
        weakForm = form
        hub.form = form
        var seen: String?
        observe(form, log) { form in seen = form.model }

        try await approve(form)

        XCTAssertEqual(seen, "pristine")
        XCTAssertEqual(log.events(before: "approved"), ["canExecute", "persisted", "canExecute"])
        XCTAssertEqual(log.events(after: "approved"), ["model=a", "reverted", "model=pristine"])
        XCTAssertEqual(form.model, "pristine")
        XCTAssertFalse(form.isDirty)
    }

    /// FORM-040 — a queued update prepares at call time; equality never skips the enqueue.
    func testQueuedUpdatePreparesAtCallTimeAndReplaysInOrder() async throws {
        let log = QueueEventLog()
        let hub = QueueLogHub<Int>(log)
        let armed = Once(armed: false)
        let form = FormVM<Int>(
            initial: 1,
            persister: { _ in
                log.append("persisted")
                armed.arm()
            },
            hub: hub,
            validators: ["value": { candidate in
                log.append("validate=\(candidate)")
                return nil
            }]
        )
        hub.form = form
        form.setModel(2)
        form.approveCommand.canExecuteChanged
            .sink { [weak form] _ in
                guard armed.claim() else { return }
                form?.setModel(5)
                form?.setModel(2)
                log.append("observer returned")
            }
            .store(in: &cancellables)
        var seen: Int?
        observe(form, log) { form in seen = form.model }

        try await approve(form)

        // Both calls ran their preparation when they were called, including
        // the one equal to the live model, and changed nothing yet.
        let before = log.events(before: "approved")
        let window = before.drop { $0 != "persisted" }
        XCTAssertEqual(
            window.filter { $0.hasPrefix("validate=") || $0 == "observer returned" },
            ["validate=5", "validate=2", "observer returned"]
        )
        XCTAssertFalse(window.contains { $0.hasPrefix("model=") })
        XCTAssertEqual(seen, 2)
        // Both replay in call order, each as a new update.
        XCTAssertEqual(
            log.events(after: "approved").filter { $0.hasPrefix("model=") },
            ["model=5", "model=2"]
        )
        XCTAssertEqual(form.model, 2)
        XCTAssertFalse(form.isDirty)
    }

    /// FORM-040 — a nested update made during call-time preparation makes the outer call stale.
    func testNestedUpdateDuringCallTimePreparationWinsOverTheOuterCall() async throws {
        let log = QueueEventLog()
        let hub = QueueLogHub<Int>(log)
        let reenter = Once()
        weak var weakForm: FormVM<Int>?
        let form = FormVM<Int>(
            initial: 1,
            persister: { _ in },
            hub: hub,
            validators: ["value": { candidate in
                if candidate == 7, reenter.claim() { weakForm?.setModel(8) }
                return nil
            }],
            resetOnApproved: { _ in
                weakForm?.setModel(7)
                return 0
            }
        )
        weakForm = form
        hub.form = form
        observe(form, log)

        try await approve(form)

        XCTAssertEqual(log.events(after: "approved").filter { $0.hasPrefix("model=") }, ["model=8"])
        XCTAssertEqual(form.model, 8)
    }
}
