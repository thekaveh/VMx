//
// CapabilityActionsVMTests — scenario tests for CapabilityActionsVM.
//
// Ports NotesShowcase.Tests/ViewModels/CapabilityActionsVMTests.cs (C# Avalonia flavor).
// No conformance-ID markers (scenario IDs live in THEME-00x only).
//
// The Delete-command parity tests verify that the capability bar's "Delete"
// action reuses `NoteVM.deleteCommand` directly (including the
// `ConfirmationDecoratorCommand` wrapper when a confirm delegate is wired),
// so the action bar behaves identically to the in-list delete button.
//
import XCTest
import Combine
import VMx
@testable import NotesShowcaseCore

// MARK: - Recorders

/// Thread-safe recorder for notifications observed on a hub's `pending` stream.
///
/// The `pending` sink fires (via `CurrentValueSubject.send`) on the posting
/// Task's executor, while the test's drain loop reads on the test executor. A
/// lock serialises both sides so the poll never races the in-place snapshot
/// write — the same cross-executor Swift-array hazard behind the NotesView
/// delete crash.
private final class NotificationMessageRecorder {
    private let lock = NSLock()
    private var _messages: [String] = []
    var cancellables = Set<AnyCancellable>()

    /// Replace the recorded messages with the latest `pending` snapshot.
    func record(_ snapshot: [VMx.Notification]) {
        lock.lock(); defer { lock.unlock() }
        _messages = snapshot.map(\.message)
    }

    /// True iff any recorded message satisfies `predicate`.
    func anyMessage(_ predicate: (String) -> Bool) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return _messages.contains(where: predicate)
    }

    /// Snapshot copy of the recorded messages (for failure diagnostics).
    var messages: [String] {
        lock.lock(); defer { lock.unlock() }
        return _messages
    }
}

// MARK: - CapabilityActionsVMTests

final class CapabilityActionsVMTests: XCTestCase {

    // MARK: - Helpers

    private func buildCaps(getter: @escaping () -> AnyObject?) throws -> CapabilityActionsVM {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let vm = try CapabilityActionsVM.builder()
            .name("caps")
            .services(hub: hub, dispatcher: dispatcher)
            .focusedGetter(getter)
            .build()
        try vm.construct()
        return vm
    }

    private func sampleNotebook() throws -> NotebookVM {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let vm = try NotebookVM.builder()
            .name("nb")
            .services(hub: hub, dispatcher: dispatcher)
            .model(NotebookModel(id: "nb-1", name: "Work", parentId: nil))
            .build()
        try vm.construct()
        return vm
    }

    private func sampleNote() throws -> NoteVM {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let model = NoteModel(
            id: "n-1", notebookId: "nb-1", title: "T",
            tags: [], body: "", starred: false,
            createdAt: Date(), updatedAt: Date()
        )
        let vm = try NoteVM.builder()
            .name("note")
            .services(hub: hub, dispatcher: dispatcher)
            .model(model)
            .build()
        try vm.construct()
        return vm
    }

    /// Builds a `NoteVM` with an injected `confirmDelete` gate and optional
    /// notification hub + onDelete callback. Mirrors C# `NoteWithConfirm`.
    private func noteWithConfirm(
        confirmResult: Bool,
        notificationHub: NotificationHubProtocol? = nil,
        onDelete: ((NoteVM) -> Void)? = nil
    ) throws -> NoteVM {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let model = NoteModel(
            id: "n-cap", notebookId: "nb-cap", title: "T",
            tags: [], body: "", starred: false,
            createdAt: Date(), updatedAt: Date()
        )
        var b = NoteVM.builder()
            .name("note:cap")
            .services(hub: hub, dispatcher: dispatcher)
            .model(model)
            .onDelete(onDelete ?? { _ in })
            .confirmDelete({ confirmResult })
        if let nh = notificationHub {
            b = b.notificationHub(nh)
        }
        let vm = try b.build()
        try vm.construct()
        return vm
    }

    // MARK: - Notebook focus

    func testNotebookInFocusYieldsExpandCollapseToggleSelectActions() throws {
        let nb = try sampleNotebook()
        let caps = try buildCaps(getter: { nb })
        let labels = (try caps.actions.value).map(\.label)

        XCTAssertTrue(labels.contains("Expand"),           "Expected 'Expand' in \(labels)")
        XCTAssertTrue(labels.contains("Collapse"),         "Expected 'Collapse' in \(labels)")
        XCTAssertTrue(labels.contains("Toggle Expansion"), "Expected 'Toggle Expansion' in \(labels)")
        XCTAssertTrue(labels.contains("Select"),           "Expected 'Select' in \(labels)")
        // No note-specific actions.
        XCTAssertFalse(labels.contains("Close"),  "Unexpected 'Close' in \(labels)")
        XCTAssertFalse(labels.contains("Delete"), "Unexpected 'Delete' in \(labels)")
    }

    // MARK: - Note focus

    func testNoteInFocusYieldsCloseSaveDeleteSelectActions() throws {
        let note = try sampleNote()
        let caps = try buildCaps(getter: { note })
        let labels = (try caps.actions.value).map(\.label)

        XCTAssertTrue(labels.contains("Close"),  "Expected 'Close' in \(labels)")
        XCTAssertTrue(labels.contains("Save"),   "Expected 'Save' in \(labels)")
        XCTAssertTrue(labels.contains("Delete"), "Expected 'Delete' in \(labels)")
        XCTAssertTrue(labels.contains("Select"), "Expected 'Select' in \(labels)")
        // No notebook expansion actions.
        XCTAssertFalse(labels.contains("Expand"), "Unexpected 'Expand' in \(labels)")
    }

    // MARK: - Nil focus

    func testNilFocusYieldsEmptyActions() throws {
        let caps = try buildCaps(getter: { nil })
        XCTAssertTrue((try caps.actions.value).isEmpty,
                      "Expected empty actions for nil focus")
    }

    func testAddNoteCommandDelegatesToHostPredicateAndAction() async throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        var canAdd = false
        var calls = 0
        let caps = try CapabilityActionsVM.builder()
            .name("caps")
            .services(hub: hub, dispatcher: dispatcher)
            .focusedGetter({ nil })
            .canAddNote({ canAdd })
            .addNoteAction({ calls += 1 })
            .build()
        try caps.construct()

        XCTAssertFalse(caps.addNoteCommand.canExecute())
        try await caps.addNoteCommand.executeAsync()
        XCTAssertEqual(0, calls)

        canAdd = true

        XCTAssertTrue(caps.addNoteCommand.canExecute())
        try await caps.addNoteCommand.executeAsync()
        XCTAssertEqual(1, calls)
    }

    // MARK: - recomputeActions

    func testRecomputeActionsPicksUpFocusChange() throws {
        var focused: AnyObject? = try sampleNotebook()
        let caps = try buildCaps(getter: { focused })

        XCTAssertTrue((try caps.actions.value).map(\.label).contains("Expand"),
                      "Expected 'Expand' for notebook focus")

        focused = try sampleNote()
        caps.recomputeActions()

        let labels = (try caps.actions.value).map(\.label)
        XCTAssertTrue(labels.contains("Close"),   "Expected 'Close' after focus change to note")
        XCTAssertFalse(labels.contains("Expand"), "Unexpected 'Expand' after focus change to note")
    }

    // MARK: - Predicate delegation

    func testEachActionCanExecuteFollowsUnderlyingPredicate() throws {
        let nb = try sampleNotebook() // initially collapsed
        let caps = try buildCaps(getter: { nb })

        let expand  = try (caps.actions.value).first(where: { $0.label == "Expand" })!
        let collapse = try (caps.actions.value).first(where: { $0.label == "Collapse" })!

        XCTAssertTrue(expand.command.canExecute(),
                      "Expected Expand.canExecute() = true when notebook is collapsed")
        XCTAssertFalse(collapse.command.canExecute(),
                       "Expected Collapse.canExecute() = false when notebook is collapsed")

        // Expand the notebook, then reproject to capture the new state.
        nb.expand()
        caps.recomputeActions()

        let collapse2 = try (caps.actions.value).first(where: { $0.label == "Collapse" })!
        XCTAssertTrue(collapse2.command.canExecute(),
                      "Expected Collapse.canExecute() = true after expansion + reproject")
    }

    // MARK: - Delete command parity

    func testCapabilityBarDeleteReusesNoteDeleteCommand() throws {
        // Delete action must hold the SAME command instance as NoteVM.deleteCommand.
        let note = try noteWithConfirm(confirmResult: false)
        let caps = try buildCaps(getter: { note })
        let delete = try (caps.actions.value).first(where: { $0.label == "Delete" })!

        // Identity check: same underlying object reference.
        XCTAssertTrue(
            (delete.command as AnyObject) === (note.deleteCommand as AnyObject),
            "Expected capability-bar Delete to reuse NoteVM.deleteCommand"
        )
        // When a confirmDelete gate is wired, the command is wrapped.
        XCTAssertTrue(delete.command is ConfirmationDecoratorCommand,
                      "Expected ConfirmationDecoratorCommand when confirmDelete is wired")
    }

    func testCapabilityBarDeleteConfirmFalseDoesNotDelete() async throws {
        var deleted: [Bool] = []
        let note = try noteWithConfirm(confirmResult: false, onDelete: { _ in deleted.append(true) })
        let caps = try buildCaps(getter: { note })
        let delete = try (caps.actions.value).first(where: { $0.label == "Delete" })!

        if let confirmCmd = delete.command as? ConfirmationDecoratorCommand {
            try await confirmCmd.executeAsync()
        } else {
            XCTFail("Expected ConfirmationDecoratorCommand")
        }

        XCTAssertTrue(deleted.isEmpty, "Expected onDelete NOT called when confirm returns false")
    }

    func testCapabilityBarDeleteConfirmTrueInvokesOnDeleteAndPublishesNotification() async throws {
        let notifHub = NotificationHub()
        defer { notifHub.dispose() }

        let recorder = NotificationMessageRecorder()
        notifHub.pending
            .sink { [weak recorder] snapshot in recorder?.record(snapshot) }
            .store(in: &recorder.cancellables)

        var deleted: [Bool] = []
        let note = try noteWithConfirm(
            confirmResult: true,
            notificationHub: notifHub,
            onDelete: { _ in deleted.append(true) }
        )
        let caps = try buildCaps(getter: { note })
        let delete = try (caps.actions.value).first(where: { $0.label == "Delete" })!

        if let confirmCmd = delete.command as? ConfirmationDecoratorCommand {
            try await confirmCmd.executeAsync()
        } else {
            XCTFail("Expected ConfirmationDecoratorCommand")
        }

        XCTAssertEqual(1, deleted.count, "Expected onDelete called exactly once")

        XCTAssertTrue(recorder.anyMessage({ $0.contains("Note deleted") }),
                      "Expected 'Note deleted' notification; got \(recorder.messages)")
    }
}
