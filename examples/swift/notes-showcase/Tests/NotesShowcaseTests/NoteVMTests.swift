//
// NoteVMTests — scenario tests for NoteVM.
//
// Ports NotesShowcase.Tests/ViewModels/NoteVMTests.cs (C# Avalonia flavor).
// No conformance-ID markers (scenario IDs live in THEME-00x only).
//
import XCTest
import Combine
import VMx
@testable import NotesShowcaseCore

// MARK: - Recorders

/// Reference-type recorder for `PropertyChangedMessage`s on a hub.
private final class PropertyChangedRecorder {
    var propertyNames: [String] = []
    var cancellables = Set<AnyCancellable>()
}

/// Reference-type recorder for NoteVM callback invocations.
private final class NoteVMCallbackRecorder {
    var deletedItems: [NoteVM] = []
    var savedItems: [NoteVM] = []
    var closedCount: Int = 0
}

/// Thread-safe recorder for notifications observed on a hub's `pending` stream.
///
/// The `pending` sink fires (via `CurrentValueSubject.send`) on the posting
/// Task's executor, while test assertions read on the test executor. A lock
/// serialises both sides so the read never races the snapshot write — the same
/// cross-executor Swift-array hazard behind the NotesView delete crash.
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

// MARK: - NoteVMTests

final class NoteVMTests: XCTestCase {

    // MARK: - Helpers

    private func makeModel(title: String = "Hello", starred: Bool = false) -> NoteModel {
        NoteModel(
            id: "note-01",
            notebookId: "nb-reviews",
            title: title,
            tags: [],
            body: "",
            starred: starred,
            createdAt: Date(),
            updatedAt: Date()
        )
    }

    private func build(
        title: String = "Hello",
        starred: Bool = false
    ) throws -> (NoteVM, MessageHub) {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let vm = try NoteVM.builder()
            .name("note")
            .services(hub: hub, dispatcher: dispatcher)
            .model(makeModel(title: title, starred: starred))
            .build()
        return (vm, hub)
    }

    /// Subscribes a `PropertyChangedRecorder` to all `PropertyChangedMessage`s on `hub`.
    private func capture(_ hub: MessageHub) -> PropertyChangedRecorder {
        let recorder = PropertyChangedRecorder()
        hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .sink { [weak recorder] msg in recorder?.propertyNames.append(msg.propertyName) }
            .store(in: &recorder.cancellables)
        return recorder
    }

    // MARK: - Capability set

    func testCapabilitySetIsCorrect() throws {
        let (vm, _) = try build()
        XCTAssertTrue(vm is Selectable)
        XCTAssertTrue(vm is Deselectable)
        XCTAssertTrue(vm is Closable)
        // `Deletable`/`Savable` DO have an `associatedtype Item`; because `vm`'s
        // static type is the concrete `NoteVM`, the compiler resolves these as
        // compile-time conformance checks (not runtime existential casts).
        XCTAssertTrue(vm is Deletable)
        XCTAssertTrue(vm is Savable)
        XCTAssertTrue(vm is Reconstructable)
        // Capabilities NOT applicable to a note:
        XCTAssertFalse(vm is Expandable)
        XCTAssertFalse(vm is NewCreatable)
    }

    // MARK: - Model setter

    func testModelTitleChange_publishesTitlePropertyChangedMessage() throws {
        let (vm, hub) = try build(title: "Old")
        try vm.construct()
        let recorder = capture(hub)

        vm.model = vm.model.with(title: "New")

        XCTAssertTrue(recorder.propertyNames.contains("title"),
                      "Expected 'title' in \(recorder.propertyNames)")
        XCTAssertTrue(recorder.propertyNames.contains("model"),
                      "Expected 'model' in \(recorder.propertyNames)")
        XCTAssertEqual("New", vm.title)
    }

    func testModelStarredChange_publishesStarredPropertyChangedMessage() throws {
        let (vm, hub) = try build(starred: false)
        try vm.construct()
        let recorder = capture(hub)

        vm.model = vm.model.with(starred: true)

        XCTAssertTrue(recorder.propertyNames.contains("starred"),
                      "Expected 'starred' in \(recorder.propertyNames)")
    }

    // MARK: - Predicates

    func testPredicatesReject_whenNotConstructed() throws {
        let (vm, _) = try build()
        // Pre-construct: isConstructed is false → cannot close/save/delete.
        XCTAssertFalse(vm.canClose())
        XCTAssertFalse(vm.canSave(vm))
        XCTAssertFalse(vm.canDelete(vm))
    }

    // MARK: - CloseCommand

    func testCloseCommand_invokesOnCloseCallback() throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        var closedCount = 0
        let vm = try NoteVM.builder()
            .name("note")
            .services(hub: hub, dispatcher: dispatcher)
            .model(makeModel())
            .onClose({ closedCount += 1 })
            .build()
        try vm.construct()

        vm.closeCommand.execute()

        XCTAssertEqual(1, closedCount)
    }

    // MARK: - SaveCommand

    func testSaveCommand_invokesOnSaveCallback() throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let recorder = NoteVMCallbackRecorder()
        let vm = try NoteVM.builder()
            .name("note")
            .services(hub: hub, dispatcher: dispatcher)
            .model(makeModel())
            .onSave({ [weak recorder] item in recorder?.savedItems.append(item) })
            .build()
        try vm.construct()

        vm.saveCommand.execute()

        XCTAssertEqual(1, recorder.savedItems.count)
        XCTAssertTrue(recorder.savedItems.first === vm)
    }

    // MARK: - DeleteCommand (plain — no confirm delegate)

    func testDeleteCommand_invokesOnDeleteCallback() throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let recorder = NoteVMCallbackRecorder()
        let vm = try NoteVM.builder()
            .name("note")
            .services(hub: hub, dispatcher: dispatcher)
            .model(makeModel())
            .onDelete({ [weak recorder] item in recorder?.deletedItems.append(item) })
            .build()
        try vm.construct()

        vm.deleteCommand.execute()

        XCTAssertEqual(1, recorder.deletedItems.count)
        XCTAssertTrue(recorder.deletedItems.first === vm)
    }

    // MARK: - ConfirmationDecoratorCommand (confirm false)

    func testDeleteCommand_withConfirmFalse_doesNotInvokeOnDelete() async throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let recorder = NoteVMCallbackRecorder()
        let vm = try NoteVM.builder()
            .name("note")
            .services(hub: hub, dispatcher: dispatcher)
            .model(makeModel())
            .onDelete({ [weak recorder] item in recorder?.deletedItems.append(item) })
            .confirmDelete({ false })   // user clicks "No"
            .build()
        try vm.construct()

        let dc = try XCTUnwrap(vm.deleteCommand as? ConfirmationDecoratorCommand,
                               "Expected ConfirmationDecoratorCommand")
        try await dc.executeAsync()

        XCTAssertTrue(recorder.deletedItems.isEmpty,
                      "Delete should be blocked by confirm-false gate")
    }

    // MARK: - ConfirmationDecoratorCommand (confirm true)

    func testDeleteCommand_withConfirmTrue_invokesOnDelete() async throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let recorder = NoteVMCallbackRecorder()
        let vm = try NoteVM.builder()
            .name("note")
            .services(hub: hub, dispatcher: dispatcher)
            .model(makeModel())
            .onDelete({ [weak recorder] item in recorder?.deletedItems.append(item) })
            .confirmDelete({ true })    // user clicks "Yes"
            .build()
        try vm.construct()

        let dc = try XCTUnwrap(vm.deleteCommand as? ConfirmationDecoratorCommand,
                               "Expected ConfirmationDecoratorCommand")
        try await dc.executeAsync()

        XCTAssertEqual(1, recorder.deletedItems.count)
        XCTAssertTrue(recorder.deletedItems.first === vm)
    }

    // MARK: - Notification hub

    func testDeleteCommand_publishesNoteDeletedNotification_onSuccess() async throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let notificationHub = NotificationHub()
        let recorder = NotificationMessageRecorder()
        notificationHub.pending
            .sink { [weak recorder] snapshot in recorder?.record(snapshot) }
            .store(in: &recorder.cancellables)

        let vm = try NoteVM.builder()
            .name("note")
            .services(hub: hub, dispatcher: dispatcher)
            .model(makeModel(title: "Important"))
            .onDelete({ _ in })
            .confirmDelete({ true })
            .notificationHub(notificationHub)
            .build()
        try vm.construct()

        let dc = try XCTUnwrap(vm.deleteCommand as? ConfirmationDecoratorCommand)
        try await dc.executeAsync()

        // The Task inside _performDelete is fire-and-forget; yield so it lands.
        try? await Task.sleep(nanoseconds: 1_000_000)

        XCTAssertTrue(
            recorder.anyMessage { $0.contains("Note deleted") && $0.contains("Important") },
            "Expected 'Note deleted … Important' notification; got \(recorder.messages)"
        )
    }

    func testDeleteCommand_doesNotPublishNotification_whenConfirmFalse() async throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let notificationHub = NotificationHub()
        let recorder = NotificationMessageRecorder()
        notificationHub.pending
            .sink { [weak recorder] snapshot in recorder?.record(snapshot) }
            .store(in: &recorder.cancellables)

        let vm = try NoteVM.builder()
            .name("note")
            .services(hub: hub, dispatcher: dispatcher)
            .model(makeModel())
            .onDelete({ _ in })
            .confirmDelete({ false })
            .notificationHub(notificationHub)
            .build()
        try vm.construct()

        let dc = try XCTUnwrap(vm.deleteCommand as? ConfirmationDecoratorCommand)
        try await dc.executeAsync()
        try? await Task.sleep(nanoseconds: 1_000_000)

        XCTAssertFalse(
            recorder.anyMessage { $0.contains("Note deleted") },
            "Expected no notification when confirm returns false"
        )
    }
}
