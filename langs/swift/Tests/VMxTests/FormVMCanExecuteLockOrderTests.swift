//
// FormVMCanExecuteLockOrderTests.swift — #704 and #1057 regression tests.
//
// A `canExecuteChanged` sink that calls `canExecute()` reads the form under
// its state gate. Every `canExecuteChanged` and `errorsChanged` send must
// therefore run after the gate is released (ADR-0143), or a send under the
// gate and a send outside it can wait for each other forever. Each stress
// test runs for a fixed time and fails, instead of hanging, if the threads
// stall.
//

import Combine
import Foundation
import XCTest
@testable import VMx

private enum LockOrderTestError: Error {
    case persist
}

/// Bound for each stress run to finish; a stall shows up as a timeout.
private let lockOrderTimeout: TimeInterval = 10
/// How long each stress loop runs.
private let stressDuration: TimeInterval = 1.0
/// How long each re-entrant stress loop runs (#1057).
private let reentrantStressDuration: TimeInterval = 3.0
/// Marks the thread whose `canExecuteChanged` sink updates the form.
private let mutatingSinkThread = "FormVMCanExecuteLockOrderTests.mutatingSink"
/// Marks the thread whose `errorsChanged` sink updates the form.
private let errorsSinkThread = "FormVMCanExecuteLockOrderTests.errorsSink"

final class FormVMCanExecuteLockOrderTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    /// A form whose persister always fails, so every approval settles through
    /// the failed path, and whose `canExecuteChanged` sink reads `canExecute()`.
    private func makeForm() -> FormVM<String> {
        let form = FormVM(
            initial: "valid",
            persister: { (_: String) in throw LockOrderTestError.persist },
            validators: ["value": { $0.isEmpty ? "required" : nil }],
            equals: ==
        )
        observe(form)
        return form
    }

    /// Like `makeForm`, but a second validator calls `reenter` on the
    /// preparing thread whenever it sees the candidate `"trigger"`.
    private func makeReentrantForm(
        strict: Bool = false,
        reenter: @escaping (FormVM<String>) -> Void
    ) -> FormVM<String> {
        weak var weakForm: FormVM<String>?
        let form = FormVM(
            initial: "valid",
            persister: { (_: String) in throw LockOrderTestError.persist },
            strict: strict,
            validators: [
                "value": { $0.isEmpty ? "required" : nil },
                "trigger": { candidate in
                    if candidate == "trigger", let form = weakForm { reenter(form) }
                    return nil
                },
            ],
            equals: ==
        )
        weakForm = form
        observe(form)
        return form
    }

    /// Adds the sinks that read `canExecute()` on every notification.
    private func observe(_ form: FormVM<String>) {
        let command = form.approveCommand
        command.canExecuteChanged
            .sink { _ = command.canExecute() }
            .store(in: &cancellables)
        form.errorsChanged
            .sink { _ in _ = command.canExecute() }
            .store(in: &cancellables)
    }

    /// Runs each loop on its own thread until `duration` elapses and fails
    /// if any thread has not finished within `lockOrderTimeout`.
    private func race(
        _ loops: [(Int) -> Void],
        duration: TimeInterval = stressDuration,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let deadline = Date().addingTimeInterval(duration)
        let done = DispatchGroup()
        for loop in loops {
            done.enter()
            Thread {
                var iteration = 0
                while Date() < deadline {
                    loop(iteration)
                    iteration += 1
                }
                done.leave()
            }.start()
        }
        let result = done.wait(timeout: .now() + lockOrderTimeout)
        XCTAssertEqual(result, .success, "a thread stalled: lock-order deadlock", file: file, line: line)
    }

    func testSingleThreadApproveAndSetModelLoopDoesNotStall() {
        let form = makeForm()
        race([{ iteration in
            form.approveCommand.execute()
            form.setModel(iteration.isMultiple(of: 2) ? "" : "value \(iteration)")
        }])
    }

    func testApprovalAdmissionRacingSetModelDoesNotStall() {
        let form = makeForm()
        race([
            { _ in form.approveCommand.execute() },
            { iteration in form.setModel(iteration.isMultiple(of: 3) ? "" : "value \(iteration)") },
        ])
    }

    func testApprovalAdmissionRacingDenyDoesNotStall() {
        let form = makeForm()
        race([
            { _ in form.approveCommand.execute() },
            { iteration in
                form.setModel(iteration.isMultiple(of: 2) ? "" : "edit \(iteration)")
                form.denyCommand.execute()
            },
        ])
    }

    func testErrorsChangedKeepsCommitOrderAcrossThreads() {
        // Each delivered map differs from the committed map before it, so
        // two equal maps in a row mean deliveries left commit order.
        let form = makeForm()
        let lock = NSLock()
        var delivered: [[String: String]] = []
        form.errorsChanged
            .sink { errors in
                lock.lock()
                delivered.append(errors)
                lock.unlock()
            }
            .store(in: &cancellables)
        let edit: (Int) -> Void = { iteration in
            form.setModel(iteration.isMultiple(of: 2) ? "" : "value \(iteration)")
        }
        race([edit, edit])

        lock.lock()
        let maps = delivered
        lock.unlock()
        XCTAssertGreaterThan(maps.count, 1)
        let repeats = zip(maps, maps.dropFirst()).filter { $0 == $1 }.count
        XCTAssertEqual(repeats, 0, "errorsChanged values arrived out of commit order")
        XCTAssertEqual(maps.last, form.errors)
    }

    func testStrictEqualsThatUpdatesTheFormDoesNotStall() {
        // The strict approval predicate calls `equals`; here `equals` updates
        // the form once per `canExecute()` call on the reading thread.
        let reenter = "FormVMCanExecuteLockOrderTests.reenter"
        weak var weakForm: FormVM<String>?
        let form = FormVM(
            initial: "valid",
            persister: { (_: String) in },
            strict: true,
            validators: ["value": { $0.isEmpty ? "required" : nil }],
            equals: { lhs, rhs in
                let thread = Thread.current
                if thread.threadDictionary[reenter] as? Bool == true {
                    thread.threadDictionary[reenter] = false
                    weakForm?.setModel(lhs == "y" ? "z" : "y")
                }
                return lhs == rhs
            }
        )
        weakForm = form
        race([
            { _ in
                Thread.current.threadDictionary[reenter] = true
                _ = form.approveCommand.canExecute()
            },
            { iteration in form.setModel(iteration.isMultiple(of: 2) ? "" : "value \(iteration)") },
        ])
    }

    func testFailedSettlementRacingSetModelDoesNotStall() {
        let form = makeForm()
        race([
            { _ in
                let settled = DispatchSemaphore(value: 0)
                Task {
                    try? await form.approveAsync()
                    settled.signal()
                }
                _ = settled.wait(timeout: .now() + lockOrderTimeout)
            },
            { iteration in form.setModel(iteration.isMultiple(of: 2) ? "" : "value \(iteration)") },
        ])
    }

    // ── Re-entrant updates (#1057) ────────────────────────────────────────────
    //
    // An update nested in another update's preparation runs while the outer
    // call holds the state gate. It must not send while that gate is held. An
    // approval admission on another thread holds Combine's delivery lock while
    // its sink waits for the gate. A sink that updates the form waits for the
    // publication scope, so an update sends `canExecuteChanged` only after its
    // scope closes.

    func testValidatorReenteringSetModelRacingApprovalAdmissionDoesNotStall() {
        let form = makeReentrantForm { $0.setModel("") }
        race([
            { _ in form.approveCommand.execute() },
            { iteration in form.setModel(iteration.isMultiple(of: 2) ? "trigger" : "value \(iteration)") },
        ], duration: reentrantStressDuration)
    }

    func testStrictValidatorReenteringDenyRacingApprovalAdmissionDoesNotStall() {
        let form = makeReentrantForm(strict: true) { $0.denyCommand.execute() }
        race([
            { _ in form.approveCommand.execute() },
            { iteration in form.setModel(iteration.isMultiple(of: 2) ? "trigger" : "value \(iteration)") },
        ], duration: reentrantStressDuration)
    }

    func testStrictValidatorReenteringApproveRacingApprovalAdmissionDoesNotStall() {
        let form = makeReentrantForm(strict: true) { $0.approveCommand.execute() }
        race([
            { _ in form.approveCommand.execute() },
            { iteration in form.setModel(iteration.isMultiple(of: 2) ? "trigger" : "value \(iteration)") },
        ], duration: reentrantStressDuration)
    }

    func testCanExecuteSinkThatUpdatesTheFormRacingSetModelDoesNotStall() {
        let form = makeForm()
        form.approveCommand.canExecuteChanged
            .sink { [weak form] _ in
                guard Thread.current.threadDictionary[mutatingSinkThread] as? Bool == true else { return }
                form?.setModel("sink")
            }
            .store(in: &cancellables)
        race([
            { _ in
                Thread.current.threadDictionary[mutatingSinkThread] = true
                form.approveCommand.execute()
            },
            { iteration in form.setModel(iteration.isMultiple(of: 3) ? "" : "value \(iteration)") },
        ], duration: reentrantStressDuration)
    }

    func testErrorsChangedSinkThatUpdatesTheFormRacingAMutatingCanExecuteSinkDoesNotStall() {
        // An update made from an `errorsChanged` sink runs while that
        // delivery's scope is open. Its `canExecuteChanged` must wait until
        // that scope closes, because the other sink waits for the scope.
        let form = makeForm()
        form.errorsChanged
            .sink { [weak form] errors in
                guard Thread.current.threadDictionary[errorsSinkThread] as? Bool == true,
                      !errors.isEmpty else { return }
                form?.setModel("fixed")
            }
            .store(in: &cancellables)
        form.approveCommand.canExecuteChanged
            .sink { [weak form] _ in
                guard Thread.current.threadDictionary[mutatingSinkThread] as? Bool == true else { return }
                form?.setModel("sink")
            }
            .store(in: &cancellables)
        race([
            { _ in
                Thread.current.threadDictionary[mutatingSinkThread] = true
                form.approveCommand.execute()
            },
            { iteration in
                Thread.current.threadDictionary[errorsSinkThread] = true
                form.setModel(iteration.isMultiple(of: 2) ? "" : "value \(iteration)")
            },
        ], duration: reentrantStressDuration)
    }

    func testValidatorReenteringSetModelRacingAHubDrainThatReadsTheFormDoesNotStall() {
        // The nested call's model message must not be sent under the gate
        // either. `MessageHub.send` waits for another thread's drain, and that
        // drain's subscriber reads the form.
        let hub = MessageHub()
        weak var weakForm: FormVM<String>?
        let form = FormVM(
            initial: "valid",
            persister: { (_: String) in },
            hub: hub,
            validators: [
                "value": { $0.isEmpty ? "required" : nil },
                "trigger": { candidate in
                    if candidate == "trigger" { weakForm?.setModel("") }
                    return nil
                },
            ],
            equals: ==
        )
        weakForm = form
        hub.messages
            .sink { [weak form] _ in _ = form?.model }
            .store(in: &cancellables)
        race([
            { iteration in form.setModel(iteration.isMultiple(of: 2) ? "trigger" : "value \(iteration)") },
            { iteration in form.setModel(iteration.isMultiple(of: 2) ? "other \(iteration)" : "") },
        ], duration: reentrantStressDuration)
    }

    func testApprovalAdmittedFromAValidatorNotifiesBeforeThePersisterRuns() {
        // The admission's `canExecuteChanged` waits for the outer update to
        // release the gate; the persister starts only after it (§5.3). The
        // first sink call waits briefly, so a persister started too early
        // records first.
        let lock = NSLock()
        var events: [String] = []
        var firstNotice = true
        func record(_ event: String) {
            lock.lock()
            events.append(event)
            lock.unlock()
        }
        let persisterStarted = DispatchSemaphore(value: 0)
        let persisted = expectation(description: "the persister ran")
        weak var weakForm: FormVM<String>?
        let form = FormVM(
            initial: "valid",
            persister: { (_: String) in
                record("persister")
                persisterStarted.signal()
                persisted.fulfill()
            },
            strict: true,
            validators: ["trigger": { candidate in
                if candidate == "trigger", let form = weakForm {
                    form.approveCommand.execute()
                }
                return nil
            }],
            equals: ==
        )
        weakForm = form
        form.setModel("edited")
        form.approveCommand.canExecuteChanged
            .sink { _ in
                lock.lock()
                let isFirst = firstNotice
                firstNotice = false
                lock.unlock()
                if isFirst { _ = persisterStarted.wait(timeout: .now() + 0.2) }
                record("canExecuteChanged")
            }
            .store(in: &cancellables)

        form.setModel("trigger")

        wait(for: [persisted], timeout: lockOrderTimeout)
        lock.lock()
        let observed = events
        lock.unlock()
        XCTAssertEqual(Array(observed.prefix(2)), ["canExecuteChanged", "persister"])
    }
}
