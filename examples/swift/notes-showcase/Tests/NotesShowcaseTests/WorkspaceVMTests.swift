//
// WorkspaceVMTests — scenario tests for WorkspaceVM (composition root).
//
// Ports examples/csharp/avalonia/NotesShowcase.Tests/ViewModels/WorkspaceVMTests.cs.
// No conformance-ID markers (scenario IDs live in THEME-00x only).
//
// Determinism strategy:
//   • Zero repo delays → async repo calls return immediately.
//   • ImmediateDispatcher.INSTANCE → scheduleForeground runs inline.
//   • `waitUntil` drains fire-and-forget Tasks (addNotebook, newNote, etc.)
//     by yielding until the condition holds or a retry cap is hit.
//
import XCTest
import Combine
import VMx
@testable import NotesShowcaseCore

// MARK: - Test dialog services

/// Dialog that silently accepts every confirmation and returns `nil` for files.
private final class AlwaysAcceptDialogService: DialogService {
    func pickFileToOpen(filter: FileFilter?, title: String?) async -> String? { nil }
    func pickFileToSave(filter: FileFilter?, title: String?, suggestedName: String?) async -> String? { nil }
    func confirm(_ message: String, title: String?) async -> Bool { true }
    func notify(_ message: String, title: String?, severity: NotificationSeverity) async {}
}

/// Dialog that always returns a pre-configured path from `pickFileToSave`.
private final class SaveDialogService: DialogService {
    private let _path: String
    init(path: String) { _path = path }
    func pickFileToOpen(filter: FileFilter?, title: String?) async -> String? { nil }
    func pickFileToSave(filter: FileFilter?, title: String?, suggestedName: String?) async -> String? { _path }
    func confirm(_ message: String, title: String?) async -> Bool { true }
    func notify(_ message: String, title: String?, severity: NotificationSeverity) async {}
}

// MARK: - WorkspaceVMTests

final class WorkspaceVMTests: XCTestCase {

    // MARK: - Helpers

    /// Builds a zero-delay workspace wired to the standard seed.
    private func buildWorkspace(
        dialogService: (any DialogService)? = nil
    ) throws -> WorkspaceVM {
        let repo = InMemoryNoteRepository(
            seed: SeedData.build(),
            loadAllDelay: 0,
            loadNotesDelay: 0,
            saveNoteDelay: 0,
            deleteNoteDelay: 0,
            addNotebookDelay: 0,
            exportDelay: 0
        )
        var b = WorkspaceVM.builder().repository(repo)
        if let ds = dialogService { b = b.dialogService(ds) }
        return try b.build()
    }

    /// Polls until `condition` returns `true` or the retry cap is reached.
    ///
    /// Uses `Task.sleep(nanoseconds: 1_000_000)` (1 ms) rather than
    /// `Task.yield()` between checks so the cooperative-pool threads have
    /// real wall-clock time to drain nested async chains (outer spawn →
    /// bindNotesObserved → bindTo inner Task → actor hop).  Pure
    /// `Task.yield()` from the main actor only reschedules other
    /// *main-actor* work; cooperative-pool tasks may not advance within
    /// the allowed attempt window on loaded CI runners.
    private func waitUntil(_ condition: @escaping () -> Bool, attempts: Int = 100) async {
        for _ in 0..<attempts {
            if condition() { return }
            try? await Task.sleep(nanoseconds: 1_000_000)   // 1 ms per iteration
        }
    }

    // MARK: - Construction

    func testConstructAsync_loadsNotebooks_selectsFirst_populatesNotes() async throws {
        let ws = try buildWorkspace()
        try await ws.constructAsync()
        defer { ws.dispose() }

        XCTAssertEqual(.constructed, ws.status)
        XCTAssertNotNil(ws.notebooksRoot.current)
        XCTAssertFalse(ws.notesView.visibleItems.isEmpty)
        // First root in seed order is nb-work.
        XCTAssertEqual("nb-work", ws.notebooksRoot.current?.model.id)
        XCTAssertTrue(
            ws.notesView.filteredItems.allSatisfy { $0.model.notebookId == "nb-work" }
        )
    }

    func testAllSixAggregateChildren_areConstructed() async throws {
        let ws = try buildWorkspace()
        try await ws.constructAsync()
        defer { ws.dispose() }

        XCTAssertTrue(ws.notebooksRoot.isConstructed)
        XCTAssertTrue(ws.notesView.isConstructed)
        XCTAssertTrue(ws.noteForm.isConstructed)
        XCTAssertTrue(ws.statusBar.isConstructed)
        XCTAssertTrue(ws.notifications.isConstructed)
        XCTAssertTrue(ws.capabilityActions.isConstructed)
    }

    func testTheme_isConstructedAlongsideAggregate() async throws {
        let ws = try buildWorkspace()
        try await ws.constructAsync()
        defer { ws.dispose() }

        XCTAssertTrue(ws.theme.isConstructed)
    }

    // MARK: - Notebook selection rebinds notes view

    func testSelectingAnotherNotebook_rebindsNotesView() async throws {
        let ws = try buildWorkspace()
        try await ws.constructAsync()
        defer { ws.dispose() }

        let firstId = ws.notesView.boundNotebookId
        // Pick a root different from the currently bound one.
        guard let other = ws.notebooksRoot.roots.first(where: { $0.model.id != firstId }) else {
            XCTFail("Expected at least two root notebooks in seed data")
            return
        }

        ws.notebooksRoot.current = other
        await waitUntil { ws.notesView.boundNotebookId == other.model.id }

        XCTAssertEqual(other.model.id, ws.notesView.boundNotebookId)
        XCTAssertTrue(
            ws.notesView.filteredItems.allSatisfy { $0.model.notebookId == other.model.id }
        )
    }

    // MARK: - Note form wiring

    func testSelectingANote_bindsTheForm() async throws {
        let ws = try buildWorkspace()
        try await ws.constructAsync()
        defer { ws.dispose() }

        let note = ws.notesView.filteredItems.first
        XCTAssertNotNil(note, "Expected notes after constructAsync")
        ws.notesView.current = note

        XCTAssertTrue(ws.noteForm.hasBoundNote)
        XCTAssertEqual(note?.model.title, ws.noteForm.title)
    }

    func testClearingCurrentNote_unbindsTheForm() async throws {
        // Round-4 Important-1: when Current becomes nil (e.g. after delete),
        // the form must be unbound so no ghost data lingers in the right pane.
        let ws = try buildWorkspace(dialogService: AlwaysAcceptDialogService())
        try await ws.constructAsync()
        defer { ws.dispose() }

        let note = ws.notesView.filteredItems.first
        XCTAssertNotNil(note)
        ws.notesView.current = note

        XCTAssertTrue(ws.noteForm.hasBoundNote)

        // Delete the selected note (AlwaysAccept confirms the prompt).
        note?.deleteCommand.execute()
        await waitUntil { ws.notesView.current == nil }

        XCTAssertNil(ws.notesView.current)
        XCTAssertFalse(ws.noteForm.hasBoundNote)
        XCTAssertEqual("", ws.noteForm.title)
        XCTAssertEqual("", ws.noteForm.body)
    }

    // MARK: - onSaved → refreshNote wiring

    func testSave_refreshesListRowTitleAndStar() async throws {
        let ws = try buildWorkspace()
        try await ws.constructAsync()
        defer { ws.dispose() }

        let note = ws.notesView.inner.at(0)
        ws.notesView.current = note
        ws.noteForm.title = "Retitled by test"
        try await ws.noteForm.approveAsync()

        await waitUntil {
            ws.notesView.filteredItems.contains { $0.title == "Retitled by test" }
        }

        XCTAssertEqual("Retitled by test", note.title)
        XCTAssertTrue(
            ws.notesView.filteredItems.contains { $0.title == "Retitled by test" }
        )
    }

    // MARK: - Commands

    func testNewNotebookCommand_appendsANotebook() async throws {
        let ws = try buildWorkspace()
        try await ws.constructAsync()
        defer { ws.dispose() }

        let before = ws.notebooksRoot.all.count
        ws.newNotebookCommand.execute()
        await waitUntil { ws.notebooksRoot.all.count > before }

        XCTAssertGreaterThan(ws.notebooksRoot.all.count, before)
    }

    func testNewNoteCommand_addsNoteInCurrentNotebook() async throws {
        let ws = try buildWorkspace()
        try await ws.constructAsync()
        defer { ws.dispose() }

        let nbId = ws.notebooksRoot.current?.model.id
        XCTAssertNotNil(nbId)
        let before = ws.notesView.filteredItems.count

        ws.newNoteCommand.execute()
        await waitUntil { ws.notesView.filteredItems.count > before }

        XCTAssertGreaterThan(ws.notesView.filteredItems.count, before)
        if let nbId = nbId {
            XCTAssertTrue(
                ws.notesView.filteredItems.allSatisfy { $0.model.notebookId == nbId }
            )
        }
    }

    func testToolbarCommands_fireCanExecuteChanged_afterConstruction() async throws {
        // Avalonia (and SwiftUI) caches CanExecute from before construction;
        // without a command-trigger fire the "+ Note" button stays disabled.
        let ws = try buildWorkspace()
        var changes = 0
        let sub = ws.newNoteCommand.canExecuteChanged.sink { changes += 1 }

        XCTAssertFalse(ws.newNoteCommand.canExecute())  // Before construction: no notebook yet.

        try await ws.constructAsync()
        defer { ws.dispose(); sub.cancel() }

        XCTAssertGreaterThan(changes, 0,
            "canExecuteChanged must fire so bound UI buttons re-evaluate")
        XCTAssertTrue(ws.newNoteCommand.canExecute())
    }

    func testConstruct_withNoNotebooks_stillEnablesNewNotebookButton() async throws {
        let repo = InMemoryNoteRepository(
            seed: (notebooks: [], notes: []),
            loadAllDelay: 0,
            loadNotesDelay: 0,
            saveNoteDelay: 0
        )
        let ws = try WorkspaceVM.builder().repository(repo).build()
        try await ws.constructAsync()
        defer { ws.dispose() }

        XCTAssertTrue(ws.newNotebookCommand.canExecute())
        XCTAssertFalse(ws.newNoteCommand.canExecute(),
            "newNote requires a current notebook — none selected yet")
    }

    // MARK: - setFocus / capability actions

    func testSetFocus_triggersCapabilityActionsRecompute() async throws {
        let ws = try buildWorkspace()
        try await ws.constructAsync()
        defer { ws.dispose() }

        // Focus on a notebook: actions list includes "Expand" (Expandable).
        let nb = ws.notebooksRoot.current
        XCTAssertNotNil(nb)
        ws.setFocus(nb!)
        XCTAssertTrue(
            try ws.capabilityActions.actions.value.contains { $0.label == "Expand" }
        )

        // Focus on a note: actions switch to note-specific actions.
        let noteVM = ws.notesView.filteredItems.first
        XCTAssertNotNil(noteVM)
        ws.setFocus(noteVM!)
        let labels = try ws.capabilityActions.actions.value.map(\.label)
        XCTAssertTrue(labels.contains("Close"))
        XCTAssertFalse(labels.contains("Expand"))
    }

    // MARK: - Deny / revert

    func testDenyCommand_revertsAndRepublishesDraftSurface() async throws {
        let ws = try buildWorkspace()
        try await ws.constructAsync()
        defer { ws.dispose() }

        let note = ws.notesView.inner.at(0)
        ws.notesView.current = note
        let original = ws.noteForm.title
        ws.noteForm.title = original + " (edited)"
        XCTAssertTrue(ws.noteForm.isDirty)

        ws.noteForm.denyCommand.execute()

        XCTAssertFalse(ws.noteForm.isDirty)
        XCTAssertEqual(original, ws.noteForm.title)
    }

    // MARK: - Lifecycle cascade

    func testDestruct_cascadesToAllSixChildren() async throws {
        let ws = try buildWorkspace()
        try await ws.constructAsync()
        try ws.destruct()
        defer { ws.dispose() }

        XCTAssertEqual(.destructed, ws.notebooksRoot.status)
        XCTAssertEqual(.destructed, ws.notesView.status)
        XCTAssertEqual(.destructed, ws.noteForm.status)
        XCTAssertEqual(.destructed, ws.statusBar.status)
        XCTAssertEqual(.destructed, ws.notifications.status)
        XCTAssertEqual(.destructed, ws.capabilityActions.status)
    }

    // MARK: - Export

    func testExportCommand_writesWorkspaceThroughDialogPath() async throws {
        let path = (NSTemporaryDirectory() as NSString)
            .appendingPathComponent("vmx-export-\(UUID().uuidString).json")
        let ws = try WorkspaceVM.builder()
            .repository(InMemoryNoteRepository(
                seed: SeedData.build(),
                loadAllDelay: 0,
                loadNotesDelay: 0,
                saveNoteDelay: 0,
                exportDelay: 0
            ))
            .dialogService(SaveDialogService(path: path))
            .build()
        try await ws.constructAsync()
        defer {
            ws.dispose()
            try? FileManager.default.removeItem(atPath: path)
        }

        ws.exportCommand.execute()
        await waitUntil { FileManager.default.fileExists(atPath: path) }

        XCTAssertTrue(
            FileManager.default.fileExists(atPath: path),
            "export must write through the picked path"
        )
    }

    // MARK: - Builder

    func testBuilder_throwsWhenRepositoryIsMissing() {
        XCTAssertThrowsError(try WorkspaceVM.builder().build())
    }

    func testBuilder_usesDefaultsForOptionalServices() throws {
        let repo = InMemoryNoteRepository(
            seed: (notebooks: [], notes: []),
            loadAllDelay: 0,
            loadNotesDelay: 0,
            saveNoteDelay: 0
        )
        let ws = try WorkspaceVM.builder().repository(repo).build()
        // No crash when built with only the required field.
        XCTAssertNotNil(ws)
        ws.dispose()
    }
}
