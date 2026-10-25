//
// FormVMCanExecuteLockOrderTests.swift — #704 regression tests.
//
// A `canExecuteChanged` sink that calls `canExecute()` reads the form under
// its state gate. Every `canExecuteChanged` and `errorsChanged` send must
// therefore run after the gate is released (ADR-0143), or a send under the
// gate and a send outside it can wait for each other forever. Each test runs
// for a fixed time and fails, instead of hanging, if the threads stall.
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
        let command = form.approveCommand
        command.canExecuteChanged
            .sink { _ = command.canExecute() }
            .store(in: &cancellables)
        form.errorsChanged
            .sink { _ in _ = command.canExecute() }
            .store(in: &cancellables)
        return form
    }

    /// Runs each loop on its own thread until `stressDuration` elapses and
    /// fails if any thread has not finished within `lockOrderTimeout`.
    private func race(_ loops: [(Int) -> Void], file: StaticString = #filePath, line: UInt = #line) {
        let deadline = Date().addingTimeInterval(stressDuration)
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
}
