//
// FormVMApproveTests.swift — FORM-004/005/006/007/008/015 conformance tests.
//
// approve/deny commands, onApproved channel, approveErrors channel, hub messages.
// See spec/20-form-vm.md §6-8 and ADR-0048.
//

import Combine
import XCTest
@testable import VMx

// MARK: - Test model

private struct TestModel: Equatable {
    var name: String
    var value: Int
}

// MARK: - Reference-type recorder (required for @escaping / async capture)

private final class PersistRecorder {
    var calls: [TestModel] = []
    var shouldThrow = false
    var error: Error = NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "persist failed"])

    func persister(_ model: TestModel) async throws {
        calls.append(model)
        if shouldThrow { throw error }
    }
}

// MARK: - Test cases

final class FormVMApproveTests: XCTestCase {

    // ── FORM-004 ──────────────────────────────────────────────────────────────

    /// FORM-004 — denyCommand reverts model to snapshot; isDirty == false after revert.
    func testForm004_denyCommandRevertsModelToSnapshot() {
        let initial = TestModel(name: "Alice", value: 1)
        let sut = FormVM(
            initial: initial,
            persister: { (_: TestModel) in }
        )

        sut.setModel(TestModel(name: "Bob", value: 2))
        XCTAssertTrue(sut.isDirty, "form should be dirty after setModel")

        sut.denyCommand.execute()

        XCTAssertEqual(sut.model, initial, "model should revert to initial snapshot after deny")
        XCTAssertFalse(sut.isDirty, "isDirty should be false after deny")
    }

    // ── FORM-005 ──────────────────────────────────────────────────────────────

    /// FORM-005 — approveAsync() invokes persister with current model; snapshot advances on success; isDirty == false.
    func testForm005_approveAsyncPersistsAndAdvancesSnapshot() async throws {
        let initial = TestModel(name: "Alice", value: 1)
        let recorder = PersistRecorder()
        let sut = FormVM(
            initial: initial,
            persister: recorder.persister
        )

        let updated = TestModel(name: "Bob", value: 2)
        sut.setModel(updated)

        try await sut.approveAsync()

        XCTAssertEqual(recorder.calls.count, 1, "persister should be called exactly once")
        XCTAssertEqual(recorder.calls[0], updated, "persister should receive the updated model")
        XCTAssertEqual(sut.snapshot, updated, "snapshot should advance to the persisted model")
        XCTAssertFalse(sut.isDirty, "isDirty should be false after a successful approve")
    }

    // ── FORM-006 ──────────────────────────────────────────────────────────────

    /// FORM-006 — onApproved fires the captured persisted value exactly once on success; NOT when persister throws.
    func testForm006_onApprovedFiresOnSuccessOnly() async throws {
        let initial = TestModel(name: "Alice", value: 1)
        var approved: [TestModel] = []
        var cancellables = Set<AnyCancellable>()

        let sut = FormVM(
            initial: initial,
            persister: { (_: TestModel) in }
        )
        sut.onApproved.sink { approved.append($0) }.store(in: &cancellables)

        XCTAssertEqual(approved.count, 0, "onApproved should not fire at construction")

        sut.setModel(TestModel(name: "Bob", value: 2))
        try await sut.approveAsync()

        XCTAssertEqual(approved.count, 1, "onApproved should fire exactly once after successful approve")
        XCTAssertEqual(approved[0], TestModel(name: "Bob", value: 2), "onApproved value should match the persisted model")

        cancellables.removeAll()
    }

    // ── FORM-007 ──────────────────────────────────────────────────────────────

    /// FORM-007 — persister throw leaves snapshot and model unchanged; approveAsync() rethrows.
    func testForm007_persisterThrowLeavesStateUnchanged() async {
        let initial = TestModel(name: "Alice", value: 1)
        let updated = TestModel(name: "Bob", value: 2)
        let recorder = PersistRecorder()
        recorder.shouldThrow = true

        var approved: [TestModel] = []
        var cancellables = Set<AnyCancellable>()

        let sut = FormVM(
            initial: initial,
            persister: recorder.persister
        )
        sut.onApproved.sink { approved.append($0) }.store(in: &cancellables)

        sut.setModel(updated)

        do {
            try await sut.approveAsync()
            XCTFail("approveAsync() should rethrow the persister error")
        } catch {
            // expected — rethrow path
        }

        XCTAssertEqual(sut.model, updated, "model should be unchanged after a failed approve")
        XCTAssertEqual(sut.snapshot, initial, "snapshot should be unchanged after a failed approve")
        XCTAssertTrue(sut.isDirty, "isDirty should remain true after a failed approve")
        XCTAssertEqual(approved.count, 0, "onApproved must not fire when the persister throws")

        cancellables.removeAll()
    }

    // ── FORM-008 ──────────────────────────────────────────────────────────────

    /// FORM-008 — denyCommand publishes FormRevertedMessage AND PropertyChangedMessage("model") on hub.
    func testForm008_denyCommandPublishesHubMessages() {
        let hub = MessageHub()
        var received: [any Message] = []
        var cancellables = Set<AnyCancellable>()

        hub.messages.sink { received.append($0) }.store(in: &cancellables)

        let initial = TestModel(name: "Alice", value: 1)
        let sut = FormVM(
            initial: initial,
            persister: { (_: TestModel) in },
            hub: hub
        )

        sut.setModel(TestModel(name: "Bob", value: 2))
        received.removeAll()
        sut.denyCommand.execute()

        cancellables.removeAll()

        XCTAssertEqual(received.count, 2, "deny should publish exactly 2 hub messages")

        let revertMsg = received.first { $0 is FormRevertedMessage } as? FormRevertedMessage
        XCTAssertNotNil(revertMsg, "hub messages should include a FormRevertedMessage")
        XCTAssertTrue(revertMsg?.senderObject === sut, "FormRevertedMessage.senderObject should be the form")
        XCTAssertEqual(revertMsg?.senderName, "FormVM", "FormRevertedMessage.senderName should be 'FormVM'")

        let propMsg = received.first { ($0 as? PropertyChangedMessage)?.propertyName == "model" } as? PropertyChangedMessage
        XCTAssertNotNil(propMsg, "hub messages should include a PropertyChangedMessage with propertyName 'model'")
        XCTAssertTrue(propMsg?.senderObject === sut, "PropertyChangedMessage.senderObject should be the form")
    }

    // ── FORM-015 ──────────────────────────────────────────────────────────────

    /// FORM-015 — approveCommand.execute() surfaces persister failure on approveErrors (fire-and-forget path);
    /// no state mutation, no onApproved.
    func testForm015_approveCommandSurfacesErrorOnApproveErrors() {
        let initial = TestModel(name: "Alice", value: 1)
        let recorder = PersistRecorder()
        recorder.shouldThrow = true

        var errors: [Error] = []
        var approved: [TestModel] = []
        var cancellables = Set<AnyCancellable>()

        let sut = FormVM(
            initial: initial,
            persister: recorder.persister
        )

        sut.approveErrors.sink { errors.append($0) }.store(in: &cancellables)
        sut.onApproved.sink { approved.append($0) }.store(in: &cancellables)

        sut.setModel(TestModel(name: "Bob", value: 2))

        // Drain the fire-and-forget Task via XCTestExpectation.
        let errorExpectation = expectation(description: "approveErrors fires")
        sut.approveErrors.first().sink { _ in errorExpectation.fulfill() }.store(in: &cancellables)

        sut.approveCommand.execute()

        wait(for: [errorExpectation], timeout: 2.0)

        XCTAssertEqual(errors.count, 1, "approveErrors should surface the persister failure exactly once")
        XCTAssertEqual(approved.count, 0, "onApproved must not fire when persist fails via command path")
        XCTAssertTrue(sut.isDirty, "isDirty should remain true after a failed command-path approve")
        XCTAssertEqual(sut.snapshot, initial, "snapshot must not advance when persist fails via command path")

        cancellables.removeAll()
        sut.dispose()
    }
}
