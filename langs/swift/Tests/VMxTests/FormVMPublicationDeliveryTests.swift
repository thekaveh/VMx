//
// FormVMPublicationDeliveryTests.swift — #1168 regression tests.
//
// Case 1: a `canExecuteChanged` sink on another thread updates the form while
// a successful approval is published. Combine's `PassthroughSubject` held a
// delivery lock while that sink waited for the publication scope, and the
// publishing thread waited for the same lock. `FormVM` now delivers its
// events through `VMxConcurrentSubject`, which holds no lock while a sink
// runs (ADR-0174 §2.1, question 1).
//
// Case 2: a `setModel` called from `resetOnApproved` delivered its
// notifications while the commit held the form's state lock. It is now queued
// and replays after `onApproved` (ADR-0174, question 2; spec/20 §5.3).
//
// Every wait is bounded by `deliveryTimeout`, so a stall fails the test
// instead of hanging the run.
//

import Combine
import Foundation
import XCTest
@testable import VMx

/// Bound for every wait in these tests; a stall shows up as a timeout.
private let deliveryTimeout: TimeInterval = 10
/// How long the stress loops run.
private let stressDuration: TimeInterval = 3.0
/// Marks the thread whose `canExecuteChanged` sink acts (thread Y or Z).
private let actingSinkThread = "FormVMPublicationDeliveryTests.actingSink"

/// Thread-safe ordered log.
private final class DeliveryLog: @unchecked Sendable {
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
}

/// Lets a callback act once.
private final class OnceGate: @unchecked Sendable {
    private let lock = NSLock()
    private var open = true

    func claim() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard open else { return false }
        open = false
        return true
    }
}

private enum SinkCall {
    case setModel
    case deny
    case dispose
}

private var isActingThread: Bool {
    Thread.current.threadDictionary[actingSinkThread] as? Bool == true
}

/// Marks a thread that is inside the stress test's mutating sink.
private let insideMutatingSink = "FormVMPublicationDeliveryTests.insideSink"

/// Runs `body` unless this thread is already inside the mutating sink. The
/// sink's update sends `canExecuteChanged` again on this thread, and with
/// thread X editing in between, an unguarded sink would recurse without
/// bound now that no delivery lock blocks thread X.
private func withoutSinkReentry(_ body: () -> Void) {
    let dictionary = Thread.current.threadDictionary
    guard dictionary[insideMutatingSink] as? Bool != true else { return }
    dictionary[insideMutatingSink] = true
    defer { dictionary[insideMutatingSink] = false }
    body()
}

final class FormVMPublicationDeliveryTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func wait(
        _ semaphore: DispatchSemaphore,
        _ message: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertEqual(
            semaphore.wait(timeout: .now() + deliveryTimeout), .success, message,
            file: file, line: line
        )
    }

    // ── Case 1 ────────────────────────────────────────────────────────────────

    /// The #1168 case 1 deterministic probe. Approval P publishes; inside P's
    /// `errorsChanged` sink, thread Y admits a second approval, and Y's
    /// `canExecuteChanged` sink makes `call`. Y's call waits for P's
    /// publication scope (#533); P must not wait for Y's sink.
    private func runCaseOneProbe(_ call: SinkCall, file: StaticString = #filePath, line: UInt = #line) {
        let log = DeliveryLog()
        let persistOnce = OnceGate()
        weak var weakForm: FormVM<String>?
        let form = FormVM<String>(
            initial: "valid",
            persister: { _ in
                // During P's persistence, make the reset change the error map.
                if persistOnce.claim() { weakForm?.setModel("") }
            },
            validators: ["value": { $0.isEmpty ? "required" : nil }],
            resetOnApproved: { _ in "reset" }
        )
        weakForm = form

        let pInErrorsSink = DispatchSemaphore(value: 0)
        let ySinkStarted = DispatchSemaphore(value: 0)
        let pDone = DispatchSemaphore(value: 0)
        let yDone = DispatchSemaphore(value: 0)
        let approvals = DispatchSemaphore(value: 0)
        let errorsOnce = OnceGate()
        let ySinkOnce = OnceGate()

        form.errorsChanged
            .sink { errors in
                guard errors.isEmpty, errorsOnce.claim() else { return }
                pInErrorsSink.signal()
                _ = ySinkStarted.wait(timeout: .now() + deliveryTimeout)
            }
            .store(in: &cancellables)
        form.approveCommand.canExecuteChanged
            .sink { [weak form] _ in
                guard isActingThread, ySinkOnce.claim(), let form else { return }
                ySinkStarted.signal()
                switch call {
                case .setModel: form.setModel("sink")
                case .deny: form.denyCommand.execute()
                case .dispose: form.dispose()
                }
                log.append("y call returned: \(form.model)")
            }
            .store(in: &cancellables)
        form.onApproved
            .sink { _ in
                log.append("approved")
                approvals.signal()
            }
            .store(in: &cancellables)

        let boxedForm = UncheckedSendableBox(form)
        Task.detached {
            try? await boxedForm.value.approveAsync()
            pDone.signal()
        }
        wait(pInErrorsSink, "P never reached its errorsChanged sink", file: file, line: line)
        Thread {
            Thread.current.threadDictionary[actingSinkThread] = true
            boxedForm.value.approveCommand.execute()
            yDone.signal()
        }.start()

        wait(pDone, "approval P stalled", file: file, line: line)
        wait(yDone, "thread Y stalled", file: file, line: line)

        // Y's call waited until P's `onApproved` was delivered (#533).
        let events = log.events
        XCTAssertEqual(events.first, "approved", file: file, line: line)
        switch call {
        case .setModel:
            XCTAssertEqual(events.dropFirst().first, "y call returned: sink", file: file, line: line)
        case .deny:
            XCTAssertEqual(events.dropFirst().first, "y call returned: reset", file: file, line: line)
        case .dispose:
            XCTAssertEqual(events.dropFirst().first, "y call returned: reset", file: file, line: line)
            XCTAssertFalse(form.approveCommand.canExecute(), file: file, line: line)
        }
        if call != .dispose {
            // Y's own approval settles too.
            wait(approvals, "first onApproved", file: file, line: line)
            wait(approvals, "Y's approval stalled", file: file, line: line)
        }
    }

    func testCanExecuteSinkSetModelDuringPublicationDoesNotStall() {
        runCaseOneProbe(.setModel)
    }

    func testCanExecuteSinkDenyDuringPublicationDoesNotStall() {
        runCaseOneProbe(.deny)
    }

    func testCanExecuteSinkDisposeDuringPublicationDoesNotStall() {
        runCaseOneProbe(.dispose)
    }

    /// The #1168 case 1 `onApproved` shape: P's `onApproved` sink waits for
    /// Y's admission sink and then updates the form, which sends
    /// `canExecuteChanged` while P's scope is open.
    func testOnApprovedSinkUpdateWhileAnotherThreadsSinkWaitsDoesNotStall() {
        let log = DeliveryLog()
        let form = FormVM<String>(
            initial: "valid",
            persister: { _ in },
            validators: ["value": { $0.isEmpty ? "required" : nil }]
        )
        let pInApproved = DispatchSemaphore(value: 0)
        let ySinkStarted = DispatchSemaphore(value: 0)
        let pDone = DispatchSemaphore(value: 0)
        let yDone = DispatchSemaphore(value: 0)
        let approvals = DispatchSemaphore(value: 0)
        let approvedOnce = OnceGate()
        let ySinkOnce = OnceGate()

        form.onApproved
            .sink { [weak form] _ in
                defer { approvals.signal() }
                guard approvedOnce.claim() else { return }
                pInApproved.signal()
                _ = ySinkStarted.wait(timeout: .now() + deliveryTimeout)
                form?.setModel("")
                log.append("p set")
            }
            .store(in: &cancellables)
        form.approveCommand.canExecuteChanged
            .sink { [weak form] _ in
                guard isActingThread, ySinkOnce.claim() else { return }
                ySinkStarted.signal()
                form?.setModel("sink")
                log.append("y set")
            }
            .store(in: &cancellables)

        let boxedForm = UncheckedSendableBox(form)
        Task.detached {
            try? await boxedForm.value.approveAsync()
            pDone.signal()
        }
        wait(pInApproved, "P never reached its onApproved sink")
        Thread {
            Thread.current.threadDictionary[actingSinkThread] = true
            boxedForm.value.approveCommand.execute()
            yDone.signal()
        }.start()

        wait(pDone, "approval P stalled")
        wait(yDone, "thread Y stalled")
        wait(approvals, "first onApproved")
        wait(approvals, "Y's approval stalled")
        XCTAssertEqual(log.events, ["p set", "y set"])
        XCTAssertEqual(form.model, "sink")
    }

    /// The #1168 case 1 stress shape: thread Y admits approvals with a
    /// succeeding persister, and its `canExecuteChanged` sink updates the
    /// form, while thread X edits the form.
    func testMutatingCanExecuteSinkWithSucceedingPersisterDoesNotStall() {
        let form = FormVM<String>(
            initial: "valid",
            persister: { _ in },
            validators: ["value": { $0.isEmpty ? "required" : nil }]
        )
        form.approveCommand.canExecuteChanged
            .sink { [weak form] _ in
                guard isActingThread else { return }
                withoutSinkReentry { form?.setModel("sink") }
            }
            .store(in: &cancellables)

        let deadline = Date().addingTimeInterval(stressDuration)
        let done = DispatchGroup()
        let boxedForm = UncheckedSendableBox(form)
        done.enter()
        Thread {
            Thread.current.threadDictionary[actingSinkThread] = true
            while Date() < deadline { boxedForm.value.approveCommand.execute() }
            done.leave()
        }.start()
        done.enter()
        Thread {
            var iteration = 0
            while Date() < deadline {
                boxedForm.value.setModel(iteration.isMultiple(of: 3) ? "" : "value \(iteration)")
                iteration += 1
            }
            done.leave()
        }.start()

        XCTAssertEqual(
            done.wait(timeout: .now() + stressDuration + deliveryTimeout), .success,
            "a thread stalled: publication deadlock"
        )
    }

    // ── Case 2 ────────────────────────────────────────────────────────────────

    /// The #1168 case 2 probe: `resetOnApproved` calls `setModel("")` while
    /// thread Z's `canExecuteChanged` sink waits to read the form. The call is
    /// queued, so the commit sends nothing under the state lock, and it
    /// replays after `onApproved`.
    func testResetSetModelWhileAnotherThreadsSinkReadsTheFormDoesNotStall() {
        let resetEntered = DispatchSemaphore(value: 0)
        let zSinkStarted = DispatchSemaphore(value: 0)
        let approvalDone = DispatchSemaphore(value: 0)
        let zDone = DispatchSemaphore(value: 0)
        let zSinkOnce = OnceGate()
        weak var weakForm: FormVM<String>?
        let form = FormVM<String>(
            initial: "saved",
            persister: { _ in },
            validators: ["value": { $0.isEmpty ? "required" : nil }],
            resetOnApproved: { _ in
                resetEntered.signal()
                _ = zSinkStarted.wait(timeout: .now() + deliveryTimeout)
                weakForm?.setModel("")
                return "pristine"
            }
        )
        weakForm = form
        let lock = NSLock()
        var lastErrors: [String: String]?
        var seen: (model: String, valid: Bool)?
        form.errorsChanged
            .sink { errors in
                lock.lock()
                lastErrors = errors
                lock.unlock()
            }
            .store(in: &cancellables)
        form.onApproved
            .sink { [weak form] _ in
                guard let form else { return }
                seen = (form.model, form.isValid)
            }
            .store(in: &cancellables)
        form.approveCommand.canExecuteChanged
            .sink { [weak form] _ in
                guard isActingThread, zSinkOnce.claim() else { return }
                zSinkStarted.signal()
                _ = form?.approveCommand.canExecute()
            }
            .store(in: &cancellables)

        let boxedForm = UncheckedSendableBox(form)
        Task.detached {
            try? await boxedForm.value.approveAsync()
            approvalDone.signal()
        }
        wait(resetEntered, "the reset never ran")
        Thread {
            Thread.current.threadDictionary[actingSinkThread] = true
            boxedForm.value.approveCommand.raiseCanExecuteChanged()
            zDone.signal()
        }.start()

        wait(approvalDone, "the approving thread stalled")
        wait(zDone, "thread Z stalled")
        XCTAssertEqual(seen?.model, "pristine", "onApproved observers see the reset state")
        XCTAssertEqual(seen?.valid, true)
        XCTAssertEqual(form.model, "")
        XCTAssertEqual(form.snapshot, "pristine")
        lock.lock()
        let last = lastErrors
        lock.unlock()
        XCTAssertEqual(last, form.errors, "the last delivered error map matches errors")
        XCTAssertEqual(form.errors, ["value": "required"])
    }

    /// #1168 case 2 without a second thread: a `setModel("")` from
    /// `resetOnApproved` on a form that rejects `""` leaves the last delivered
    /// error map equal to `errors`.
    func testResetSetModelLeavesTheLastErrorMapEqualToErrors() async throws {
        weak var weakForm: FormVM<String>?
        let form = FormVM<String>(
            initial: "saved",
            persister: { _ in },
            validators: ["value": { $0.isEmpty ? "required" : nil }],
            resetOnApproved: { _ in
                weakForm?.setModel("")
                return "pristine"
            }
        )
        weakForm = form
        var maps: [[String: String]] = []
        form.errorsChanged.sink { maps.append($0) }.store(in: &cancellables)

        try await form.approveAsync()

        XCTAssertEqual(maps.last, form.errors)
        XCTAssertEqual(form.errors, ["value": "required"])
        XCTAssertEqual(form.model, "")
        XCTAssertEqual(form.snapshot, "pristine")
    }
}
