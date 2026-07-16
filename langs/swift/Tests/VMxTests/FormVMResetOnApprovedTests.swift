import Combine
import Foundation
import XCTest
@preconcurrency @testable import VMx

private enum ResetTestError: Error { case failed }

private final class ResetBox {
    var values: [Int]
    init(_ values: [Int]) { self.values = values }
}

private struct ResetModel: Equatable {
    let value: String
    let nested: ResetBox

    static func == (lhs: ResetModel, rhs: ResetModel) -> Bool {
        lhs.value == rhs.value && lhs.nested.values == rhs.nested.values
    }
}

private final class AsyncGate: @unchecked Sendable {
    let started: XCTestExpectation
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Void, Never>?

    init(_ started: XCTestExpectation) { self.started = started }

    func wait() async {
        await withCheckedContinuation { continuation in
            lock.lock()
            self.continuation = continuation
            lock.unlock()
            started.fulfill()
        }
    }

    func release() {
        lock.lock()
        let continuation = self.continuation
        self.continuation = nil
        lock.unlock()
        continuation?.resume()
    }
}

final class FormVMResetOnApprovedTests: XCTestCase {
    /// FORM-024 — reset runs after persist and onApproved receives the captured model.
    func testForm024_resetOrderAndApprovedPayload() async throws {
        var order: [String] = []
        let form = try FormVM<String>.builder()
            .initial("initial")
            .persister { model in order.append("persist:\(model)") }
            .resetOnApproved { model in order.append("reset:\(model)"); return "reset" }
            .build()
        var approved: [String] = []
        var cancellables = Set<AnyCancellable>()
        form.onApproved.sink { model in
            order.append("approved:\(model)")
            XCTAssertEqual(form.model, "reset")
            XCTAssertEqual(form.snapshot, "reset")
            XCTAssertFalse(form.isDirty)
            approved.append(model)
        }.store(in: &cancellables)
        form.setModel("saved")

        try await form.approveAsync()

        XCTAssertEqual(order, ["persist:saved", "reset:saved", "approved:saved"])
        XCTAssertEqual(form.model, "reset")
        XCTAssertEqual(form.snapshot, "reset")
        XCTAssertFalse(form.isDirty)
        XCTAssertEqual(approved, ["saved"])
    }

    func testResetErrorObserverMutationRunsAfterPristineApproval() async throws {
        let form = try FormVM<String>.builder()
            .initial("saved")
            .persister { _ in }
            .validator("value") { $0.isEmpty ? "required" : nil }
            .resetOnApproved { _ in "" }
            .build()
        var observed: [(String, String, String, Bool)] = []
        var cancellables = Set<AnyCancellable>()
        form.errorsChanged.sink { _ in
            form.setModel("reentrant")
        }.store(in: &cancellables)
        form.onApproved.sink { approved in
            observed.append((approved, form.model, form.snapshot, form.isDirty))
        }.store(in: &cancellables)

        try await form.approveAsync()

        XCTAssertEqual(observed.count, 1)
        XCTAssertEqual(observed.first?.0, "saved")
        XCTAssertEqual(observed.first?.1, "")
        XCTAssertEqual(observed.first?.2, "")
        XCTAssertEqual(observed.first?.3, false)
        XCTAssertEqual(form.model, "reentrant")
        XCTAssertEqual(form.snapshot, "")
        XCTAssertTrue(form.isDirty)
    }

    /// FORM-025 — reset output is snapshotted twice, independent, revalidated, and strict-clean.
    func testForm025_snapshotValidationAndStrictIntegration() async throws {
        var calls = 0
        let form = try FormVM<ResetModel>.builder()
            .initial(ResetModel(value: "initial", nested: ResetBox([])))
            .persister { _ in }
            .strict(true)
            .snapshotter { model in calls += 1; return ResetModel(value: model.value, nested: ResetBox(model.nested.values)) }
            .validator("value") { $0.value.isEmpty ? "required" : nil }
            .resetOnApproved { _ in ResetModel(value: "", nested: ResetBox([1])) }
            .build()
        calls = 0
        form.setModel(ResetModel(value: "saved", nested: ResetBox([])))

        try await form.approveAsync()

        XCTAssertEqual(calls, 2)
        XCTAssertFalse(form.model.nested === form.snapshot.nested)
        XCTAssertEqual(form.fieldError("value"), "required")
        XCTAssertFalse(form.isValid)
        XCTAssertFalse(form.approveCommand.canExecute())
    }

    /// FORM-026 — post-persist reset failure is atomic and has one observer.
    func testForm026_resetFailureIsAtomicAndSinglyObserved() async throws {
        var persisted = 0
        let direct = try FormVM<String>.builder().initial("initial")
            .persister { _ in persisted += 1 }
            .resetOnApproved { _ in throw ResetTestError.failed }
            .build()
        direct.setModel("saved")
        do {
            try await direct.approveAsync()
            XCTFail("expected reset failure")
        } catch ResetTestError.failed {}
        XCTAssertEqual(persisted, 1)
        XCTAssertEqual(direct.model, "saved")
        XCTAssertEqual(direct.snapshot, "initial")

        let command = try FormVM<String>.builder().initial("initial")
            .persister { _ in }
            .resetOnApproved { _ in throw ResetTestError.failed }
            .build()
        command.setModel("saved")
        let observed = expectation(description: "approveErrors")
        var errors = 0
        var cancellables = Set<AnyCancellable>()
        command.approveErrors.sink { _ in errors += 1; observed.fulfill() }.store(in: &cancellables)
        command.approveCommand.execute()
        await fulfillment(of: [observed], timeout: 2)
        XCTAssertEqual(errors, 1)
    }

    /// FORM-027 — reset is skipped for invalid, failed, cancelled, and denied flows.
    func testForm027_resetSkippedWithoutSuccessfulApproval() async throws {
        var calls = 0
        let reset: (String) throws -> String = { model in calls += 1; return model }
        let invalid = try FormVM<String>.builder().initial("").persister { _ in }
            .validator("value") { $0.isEmpty ? "required" : nil }.resetOnApproved(reset).build()
        try await invalid.approveAsync()
        let failed = try FormVM<String>.builder().initial("initial")
            .persister { _ in throw ResetTestError.failed }.resetOnApproved(reset).build()
        do { try await failed.approveAsync(); XCTFail("expected failure") } catch ResetTestError.failed {}
        let cancelled = try FormVM<String>.builder().initial("initial")
            .persister { _ in throw CancellationError() }.resetOnApproved(reset).build()
        do { try await cancelled.approveAsync(); XCTFail("expected cancellation") } catch is CancellationError {}
        let denied = try FormVM<String>.builder().initial("initial").persister { _ in }
            .resetOnApproved(reset).build()
        denied.setModel("edited")
        denied.denyCommand.execute()
        XCTAssertEqual(calls, 0)
    }

    /// FORM-028 — disposal during persistence suppresses reset and notification.
    func testForm028_disposalDuringPersistenceSuppressesReset() async throws {
        let started = expectation(description: "persist entered")
        let gate = AsyncGate(started)
        var resets = 0
        let form = try FormVM<String>.builder().initial("initial")
            .persister { _ in await gate.wait() }
            .resetOnApproved { model in resets += 1; return model }.build()
        form.setModel("saved")
        let approval = Task { try await form.approveAsync() }
        await fulfillment(of: [started], timeout: 2)
        form.dispose()
        gate.release()
        try await approval.value
        XCTAssertEqual(resets, 0)
        XCTAssertEqual(form.model, "saved")
        XCTAssertEqual(form.snapshot, "initial")
    }

    /// FORM-029 — reset wins over a model mutation racing the persister.
    func testForm029_resetWinsRacingModelMutation() async throws {
        let started = expectation(description: "persist entered")
        let gate = AsyncGate(started)
        var resetInputs: [String] = []
        let form = try FormVM<String>.builder().initial("initial")
            .persister { _ in await gate.wait() }
            .resetOnApproved { model in resetInputs.append(model); return "reset:\(model)" }.build()
        form.setModel("saved")
        let approval = Task { try await form.approveAsync() }
        await fulfillment(of: [started], timeout: 2)
        form.setModel("racing-edit")
        gate.release()
        try await approval.value
        XCTAssertEqual(resetInputs, ["saved"])
        XCTAssertEqual(form.model, "reset:saved")
        XCTAssertEqual(form.snapshot, "reset:saved")
        XCTAssertFalse(form.isDirty)
    }

    func testResetCommitRemainsPristineThroughApprovedPublication() async throws {
        let form = try FormVM<String>.builder().initial("initial")
            .persister { _ in }
            .resetOnApproved { "reset:\($0)" }
            .build()
        form.setModel("saved")
        let setterEntered = DispatchSemaphore(value: 0)
        let setterDone = DispatchSemaphore(value: 0)
        var cancellables = Set<AnyCancellable>()
        form.onApproved.sink { _ in
            DispatchQueue.global().async {
                setterEntered.signal()
                form.setModel("racing")
                setterDone.signal()
            }
            XCTAssertEqual(setterEntered.wait(timeout: .now() + 1), .success)
            XCTAssertEqual(setterDone.wait(timeout: .now()), .timedOut)
            XCTAssertEqual(form.model, "reset:saved")
            XCTAssertEqual(form.snapshot, "reset:saved")
            XCTAssertFalse(form.isDirty)
        }.store(in: &cancellables)

        try await form.approveAsync()

        XCTAssertEqual(setterDone.wait(timeout: .now() + 1), .success)
        XCTAssertEqual(form.model, "racing")
        XCTAssertEqual(form.snapshot, "reset:saved")
        XCTAssertTrue(form.isDirty)
    }

    func testReentrantApprovedMutationRunsAfterPristinePublication() async throws {
        let form = try FormVM<String>.builder().initial("initial")
            .persister { _ in }
            .resetOnApproved { "reset:\($0)" }
            .build()
        form.setModel("saved")
        var observedPristineBeforeMutation = false
        var stateAfterMutation: String?
        var cancellables = Set<AnyCancellable>()
        form.onApproved.sink { _ in
            observedPristineBeforeMutation = form.model == "reset:saved" &&
                form.snapshot == "reset:saved" && !form.isDirty
            form.setModel("reentrant")
            stateAfterMutation = form.model
        }.store(in: &cancellables)

        try await form.approveAsync()

        XCTAssertTrue(observedPristineBeforeMutation)
        XCTAssertEqual(stateAfterMutation, "reentrant")
        XCTAssertEqual(form.model, "reentrant")
        XCTAssertEqual(form.snapshot, "reset:saved")
        XCTAssertTrue(form.isDirty)
    }

    func testInjectedEqualityMayReadFormWithoutDeadlock() async {
        var form: FormVM<String>!
        form = FormVM(
            initial: "initial",
            persister: { _ in },
            equals: { lhs, rhs in
                _ = form?.model
                return lhs == rhs
            }
        )
        let finished = expectation(description: "setModel returned")
        DispatchQueue.global().async {
            form.setModel("next")
            finished.fulfill()
        }

        await fulfillment(of: [finished], timeout: 1)
        XCTAssertEqual(form.model, "next")
    }

    func testAdmittedSetterCompletesBeforeQueuedDisposal() async throws {
        let validatorEntered = DispatchSemaphore(value: 0)
        let releaseValidator = DispatchSemaphore(value: 0)
        let hub = MessageHub()
        let form = try FormVM<String>.builder().initial("initial")
            .persister { _ in }
            .hub(hub)
            .validator("value") { value in
                if value == "accepted" {
                    validatorEntered.signal()
                    releaseValidator.wait()
                }
                return nil
            }
            .build()
        var publishedModels: [String] = []
        var cancellables = Set<AnyCancellable>()
        hub.messages.compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.sender === form && $0.propertyName == "model" }
            .sink { _ in publishedModels.append(form.model) }
            .store(in: &cancellables)

        let setterDone = expectation(description: "setter returned")
        DispatchQueue.global().async {
            form.setModel("accepted")
            setterDone.fulfill()
        }
        XCTAssertEqual(validatorEntered.wait(timeout: .now() + 1), .success)
        let disposeStarted = DispatchSemaphore(value: 0)
        let disposeDone = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            disposeStarted.signal()
            form.dispose()
            disposeDone.signal()
        }
        XCTAssertEqual(disposeStarted.wait(timeout: .now() + 1), .success)
        XCTAssertEqual(disposeDone.wait(timeout: .now()), .timedOut)
        releaseValidator.signal()

        await fulfillment(of: [setterDone], timeout: 1)
        XCTAssertEqual(disposeDone.wait(timeout: .now() + 1), .success)
        XCTAssertEqual(form.model, "accepted")
        XCTAssertEqual(publishedModels, ["accepted"])
    }

    func testEqualityCallbackDisposalDoesNotCancelAdmittedAssignment() {
        var form: FormVM<String>!
        form = FormVM(
            initial: "initial",
            persister: { _ in },
            equals: { lhs, rhs in
                if rhs == "next" { form.dispose() }
                return lhs == rhs
            }
        )

        form.setModel("next")
        form.setModel("late")

        XCTAssertEqual(form.model, "next")
    }

    func testValidatorCallbackDisposalDoesNotCancelAdmittedAssignment() {
        var form: FormVM<String>!
        form = FormVM(
            initial: "initial",
            persister: { _ in },
            validators: ["value": { value in
                if value == "next" { form.dispose() }
                return nil
            }]
        )

        form.setModel("next")
        form.setModel("late")

        XCTAssertEqual(form.model, "next")
    }

    func testValidatorObservesAcceptedLiveModel() {
        var form: FormVM<String>!
        form = FormVM(
            initial: "initial",
            persister: { _ in },
            validators: ["value": { value in
                if value == "next" { XCTAssertEqual(form.model, value) }
                return nil
            }]
        )

        form.setModel("next")

        XCTAssertEqual(form.model, "next")
    }
}
