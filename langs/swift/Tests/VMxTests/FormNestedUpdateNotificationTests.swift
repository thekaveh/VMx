//
// FormNestedUpdateNotificationTests.swift — FORM-041..042 conformance tests.
//
// A `setModel`, deny, or approve call nested in a preparation callback or an
// `errorsChanged` sink of `setModel` or deny returns before its
// notifications. The outermost update sends them before it returns, error
// maps first, then starts the persister of a nested approval. Once the form
// is disposed, the queued notifications of nested calls are dropped, and a
// disposal before the persister starts prevents the persister call. See
// spec/20-form-vm.md §5.3, §5.4 and §10, and ADR-0180.
//

import Combine
import Foundation
import XCTest
@testable import VMx

/// Thread-safe event log shared by sinks, the hub, callbacks, and the persister.
private final class NestedEventLog: @unchecked Sendable {
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

    func count(of entry: String) -> Int {
        events.filter { $0 == entry }.count
    }

    func clear() {
        lock.lock()
        entries.removeAll()
        lock.unlock()
    }
}

/// Logs every notification of `form`: `errorsChanged`, the approve command's
/// `canExecuteChanged`, the form's hub messages, `onApproved`, and
/// `approveErrors`.
private func logNotifications(
    of form: FormVM<String>,
    hub: MessageHub,
    into log: NestedEventLog,
    _ cancellables: inout Set<AnyCancellable>
) {
    form.errorsChanged
        .sink { _ in log.append("ErrorsChanged") }
        .store(in: &cancellables)
    form.approveCommand.canExecuteChanged
        .sink { _ in log.append("CanExecuteChanged") }
        .store(in: &cancellables)
    hub.messages
        .sink { [weak form] message in
            guard let form, message.senderObject === form else { return }
            if message is FormRevertedMessage {
                log.append("FormRevertedMessage")
            } else if let changed = message as? PropertyChangedMessage, changed.propertyName == "model" {
                log.append("model message")
            }
        }
        .store(in: &cancellables)
    form.onApproved
        .sink { _ in log.append("OnApproved") }
        .store(in: &cancellables)
    form.approveErrors
        .sink { _ in log.append("ApproveErrors") }
        .store(in: &cancellables)
}

/// The notifications that disposing an idle form publishes on its own (§10).
private func eventsOfPlainDisposal() -> [String] {
    let hub = MessageHub()
    let form = FormVM(initial: "initial", persister: { (_: String) in }, hub: hub)
    let log = NestedEventLog()
    var cancellables = Set<AnyCancellable>()
    logNotifications(of: form, hub: hub, into: log, &cancellables)
    form.dispose()
    return log.events
}

/// A bounded wait that lets a scheduled persister task run.
private let settleDelayNanoseconds: UInt64 = 100_000_000

final class FormNestedUpdateNotificationTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    // ── FORM-041 ──────────────────────────────────────────────────────────────

    /// FORM-041 — a validator that calls setModel(b) while setModel(a) prepares: the nested
    /// call returns before its notifications, and all of them arrive before the outer call
    /// returns.
    func testForm041_nestedSetModelFromAValidatorNotifiesAfterItReturns() {
        let hub = MessageHub()
        let log = NestedEventLog()
        weak var weakForm: FormVM<String>?
        var reenter = true
        let form = FormVM(
            initial: "initial",
            persister: { (_: String) in },
            hub: hub,
            validators: ["name": { candidate in
                if candidate == "a", reenter, let form = weakForm {
                    reenter = false
                    form.setModel("b")
                    log.append("nested returned")
                }
                return candidate == "b" ? "b-error" : nil
            }]
        )
        weakForm = form
        logNotifications(of: form, hub: hub, into: log, &cancellables)

        form.setModel("a")
        log.append("outer returned")

        XCTAssertEqual(
            log.events,
            ["nested returned", "ErrorsChanged", "CanExecuteChanged", "model message", "outer returned"]
        )
        XCTAssertEqual(form.model, "b")
        XCTAssertEqual(form.errors, ["name": "b-error"])
    }

    /// FORM-041 — a validator that runs deny while setModel(a) prepares on a dirty, invalid
    /// form: the revert notifies after the nested call returns and before the outer call
    /// returns.
    func testForm041_nestedDenyFromAValidatorNotifiesAfterItReturns() {
        let hub = MessageHub()
        let log = NestedEventLog()
        weak var weakForm: FormVM<String>?
        var reenter = true
        let form = FormVM(
            initial: "initial",
            persister: { (_: String) in },
            hub: hub,
            validators: ["name": { candidate in
                if candidate == "a", reenter, let form = weakForm {
                    reenter = false
                    form.denyCommand.execute()
                    log.append("nested returned")
                }
                return candidate == "x" ? "x-error" : nil
            }]
        )
        weakForm = form
        form.setModel("x")
        XCTAssertTrue(form.isDirty)
        XCTAssertFalse(form.isValid)
        logNotifications(of: form, hub: hub, into: log, &cancellables)

        form.setModel("a")
        log.append("outer returned")

        XCTAssertEqual(
            log.events,
            [
                "nested returned",
                "ErrorsChanged",
                "FormRevertedMessage",
                "model message",
                "CanExecuteChanged",
                "outer returned",
            ]
        )
        XCTAssertEqual(form.model, form.snapshot)
        XCTAssertTrue(form.isValid)
    }

    /// FORM-041 — an errorsChanged sink that calls setModel(c) on the first map: the nested
    /// update's error map goes out inside the outer delivery, and its other notifications
    /// follow the outer update's own, before the outer call returns.
    func testForm041_setModelFromAnErrorsChangedSinkNotifiesAfterItReturns() {
        let hub = MessageHub()
        let log = NestedEventLog()
        let form = FormVM(
            initial: "initial",
            persister: { (_: String) in },
            hub: hub,
            validators: ["name": { $0 == "a" ? "a-error" : nil }]
        )
        logNotifications(of: form, hub: hub, into: log, &cancellables)
        var maps: [[String: String]] = []
        form.errorsChanged
            .sink { [weak form] errors in
                maps.append(errors)
                guard maps.count == 1, let form else { return }
                form.setModel("c")
                log.append("nested returned")
            }
            .store(in: &cancellables)

        form.setModel("a")
        log.append("outer returned")

        XCTAssertEqual(
            log.events,
            [
                "ErrorsChanged",
                "nested returned",
                "ErrorsChanged",
                "CanExecuteChanged",
                "model message",
                "CanExecuteChanged",
                "model message",
                "outer returned",
            ]
        )
        XCTAssertEqual(maps, [["name": "a-error"], [:]])
        XCTAssertEqual(form.model, "c")
    }

    /// ADR-0180 rule 5 — an approval admitted from a validator starts its persister task
    /// after the outer update sends every queued notification, its own included.
    func testNestedApprovalStartsItsPersisterAfterTheOuterUpdatesNotifications() {
        let hub = MessageHub()
        let log = NestedEventLog()
        weak var weakForm: FormVM<String>?
        var reenter = true
        let form = FormVM(
            initial: "initial",
            persister: { (_: String) in },
            hub: hub,
            validators: ["name": { candidate in
                if candidate == "a", reenter, let form = weakForm {
                    reenter = false
                    form.approveCommand.execute()
                    log.append("nested returned")
                }
                return nil
            }]
        )
        weakForm = form
        var held: [@Sendable () async -> Void] = []
        form.commandApprovalTaskStarter = { operation in
            log.append("persister task started")
            held.append(operation)
        }
        logNotifications(of: form, hub: hub, into: log, &cancellables)

        form.setModel("a")
        log.append("outer returned")

        XCTAssertEqual(
            log.events,
            [
                "nested returned",
                "CanExecuteChanged",
                "model message",
                "persister task started",
                "outer returned",
            ]
        )
        XCTAssertEqual(held.count, 1)
        XCTAssertEqual(form.model, "a", "the outer assignment commits")
    }

    // ── FORM-042 ──────────────────────────────────────────────────────────────

    /// FORM-042 — a validator that runs the approve command and then disposes the form: the
    /// persister is never called, and the nested approval's notifications are dropped.
    func testForm042_nestedApprovalThenDisposalNeverCallsThePersister() async throws {
        let hub = MessageHub()
        let log = NestedEventLog()
        weak var weakForm: FormVM<String>?
        var reenter = true
        let form = FormVM(
            initial: "initial",
            persister: { (_: String) in log.append("persister") },
            hub: hub,
            validators: ["name": { candidate in
                if candidate == "trigger", reenter, let form = weakForm {
                    reenter = false
                    form.approveCommand.execute()
                    form.dispose()
                }
                return nil
            }]
        )
        weakForm = form
        logNotifications(of: form, hub: hub, into: log, &cancellables)

        form.setModel("trigger")
        try await Task.sleep(nanoseconds: settleDelayNanoseconds)

        XCTAssertFalse(reenter, "the validator ran the approve command")
        XCTAssertEqual(log.count(of: "persister"), 0, "the persister was never called")
        XCTAssertEqual(log.events, eventsOfPlainDisposal(), "only the disposal's own notifications")
    }

    /// FORM-042 — a validator that calls setModel(b) and then disposes the form: the nested
    /// update's queued notifications are dropped.
    func testForm042_nestedSetModelThenDisposalDropsItsNotifications() {
        let hub = MessageHub()
        let log = NestedEventLog()
        weak var weakForm: FormVM<String>?
        var reenter = true
        let form = FormVM(
            initial: "initial",
            persister: { (_: String) in },
            hub: hub,
            validators: ["name": { candidate in
                if candidate == "a", reenter, let form = weakForm {
                    reenter = false
                    form.setModel("b")
                    form.dispose()
                }
                return candidate == "b" ? "b-error" : nil
            }]
        )
        weakForm = form
        logNotifications(of: form, hub: hub, into: log, &cancellables)

        form.setModel("a")

        XCTAssertFalse(reenter, "the validator re-entered setModel")
        XCTAssertEqual(log.count(of: "ErrorsChanged"), 0)
        XCTAssertEqual(log.count(of: "model message"), 0)
        XCTAssertEqual(log.events, eventsOfPlainDisposal(), "only the disposal's own notifications")
    }

    /// FORM-042 — a disposal after approveCommand.execute() returns, but before the
    /// persister task starts, prevents the persister call. The test holds the task start
    /// back until dispose() returns.
    func testForm042_disposalBeforeTheScheduledPersisterStartsPreventsTheCall() async {
        let hub = MessageHub()
        let log = NestedEventLog()
        let form = FormVM(
            initial: "initial",
            persister: { (_: String) in log.append("persister") },
            hub: hub
        )
        var held: [@Sendable () async -> Void] = []
        form.commandApprovalTaskStarter = { operation in held.append(operation) }
        logNotifications(of: form, hub: hub, into: log, &cancellables)

        form.approveCommand.execute()
        let calls = log.count(of: "persister")
        form.dispose()
        log.clear()
        for operation in held { await operation() }

        XCTAssertEqual(held.count, 1, "execute() scheduled one persister task")
        XCTAssertEqual(calls, 0, "Swift starts the persister in a scheduled task")
        XCTAssertEqual(log.count(of: "persister"), calls, "the persister call count is unchanged")
        XCTAssertEqual(log.events, [], "the approval settles silently")
    }
}
