//
// WorkspaceVMTests — scenario tests for WorkspaceVM (composition root).
//
// Ports examples/csharp/avalonia/NotesShowcase.Tests/ViewModels/WorkspaceVMTests.cs.
// No conformance-ID markers (scenario IDs live in THEME-00x only).
//
// Determinism strategy:
//   • Repo delays are zero except where a test proves awaited completion.
//   • ImmediateDispatcher.INSTANCE → scheduleForeground runs inline.
//   • `waitUntil` drains the few intentionally fire-and-forget observation Tasks
//     by yielding until the condition holds or a retry cap is hit.
//
import XCTest
import Combine
import VMx
@testable import NotesShowcaseCore

// MARK: - Test dispatcher

/// Runs foreground work inline like `ImmediateDispatcher`. A test can queue
/// one action that runs right after the `count`-th next foreground work item,
/// before the code that scheduled that item resumes.
private final class InterleavingDispatcher: Dispatcher, @unchecked Sendable {
    private let lock = NSLock()
    private var remaining = 0
    private var pending: (() -> Void)?

    func afterForeground(count: Int, _ action: @escaping () -> Void) {
        lock.withLock { remaining = count; pending = action }
    }

    func scheduleForeground(_ work: @escaping () -> Void) {
        let action = lock.withLock { () -> (() -> Void)? in
            guard pending != nil else { return nil }
            remaining -= 1
            guard remaining == 0 else { return nil }
            defer { pending = nil }
            return pending
        }
        work()
        action?()
    }

    func scheduleBackground(_ work: @escaping () -> Void) {
        work()
    }
}

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

/// Repository whose every call throws `failure`, to drive construction failure.
private struct FailingRepository: NoteRepository {
    let failure: any Error

    func loadAll() async throws -> (notebooks: [NotebookModel], notes: [NoteModel]) { throw failure }
    func loadNotes(notebookId: String) async throws -> [NoteModel] { throw failure }
    func searchNotes(
        term: String,
        token: String?,
        pageSize: Int
    ) async throws -> (items: [NoteModel], nextToken: String?) { throw failure }
    func saveNote(_ note: NoteModel) async throws { throw failure }
    func deleteNote(id: String) async throws { throw failure }
    func addNotebook(_ notebook: NotebookModel) async throws { throw failure }
    func export(notebooks: [NotebookModel], notes: [NoteModel], path: String) async throws { throw failure }
}

private struct RepositoryUnavailable: Error {}

/// Forwards to an in-memory repository and counts the note saves.
private actor CountingRepository: NoteRepository {
    let inner: InMemoryNoteRepository
    private(set) var saveCount = 0

    init(_ inner: InMemoryNoteRepository) { self.inner = inner }

    func loadAll() async throws -> (notebooks: [NotebookModel], notes: [NoteModel]) {
        try await inner.loadAll()
    }
    func loadNotes(notebookId: String) async throws -> [NoteModel] {
        try await inner.loadNotes(notebookId: notebookId)
    }
    func searchNotes(
        term: String,
        token: String?,
        pageSize: Int
    ) async throws -> (items: [NoteModel], nextToken: String?) {
        try await inner.searchNotes(term: term, token: token, pageSize: pageSize)
    }
    func saveNote(_ note: NoteModel) async throws {
        saveCount += 1
        try await inner.saveNote(note)
    }
    func deleteNote(id: String) async throws { try await inner.deleteNote(id: id) }
    func addNotebook(_ notebook: NotebookModel) async throws { try await inner.addNotebook(notebook) }
    func export(notebooks: [NotebookModel], notes: [NoteModel], path: String) async throws {
        try await inner.export(notebooks: notebooks, notes: notes, path: path)
    }
}

// MARK: - WorkspaceVMTests

final class WorkspaceVMTests: XCTestCase {

    // MARK: - Helpers

    /// Builds a zero-delay workspace wired to the standard seed.
    private func buildWorkspace(
        dialogService: (any DialogService)? = nil,
        addNotebookDelay: TimeInterval = 0
    ) throws -> WorkspaceVM {
        let repo = InMemoryNoteRepository(
            seed: SeedData.build(),
            loadAllDelay: 0,
            loadNotesDelay: 0,
            saveNoteDelay: 0,
            deleteNoteDelay: 0,
            addNotebookDelay: addNotebookDelay,
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
        await waitUntil {
            ws.notesView.boundNotebookId == other.model.id
                && ws.notesView.filteredItems.allSatisfy {
                    $0.model.notebookId == other.model.id
                }
        }

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
        // cleared-selection form behavior: when Current becomes nil (e.g. after delete),
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
        // `current` clears before its change message reaches the workspace,
        // which unbinds the form. While another thread drains the hub, that
        // delivery lags, so wait for the unbind itself (#533).
        await waitUntil { ws.notesView.current == nil && !ws.noteForm.hasBoundNote }

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
        let ws = try buildWorkspace(addNotebookDelay: 0.02)
        try await ws.constructAsync()
        defer { ws.dispose() }

        let before = ws.notebooksRoot.all.count
        try await ws.newNotebookCommand.executeAsync()

        XCTAssertGreaterThan(ws.notebooksRoot.all.count, before)
    }

    func testNewNoteCommand_addsNoteInCurrentNotebook() async throws {
        let ws = try buildWorkspace()
        try await ws.constructAsync()
        defer { ws.dispose() }

        let nbId = ws.notebooksRoot.current?.model.id
        XCTAssertNotNil(nbId)
        let before = ws.notesView.filteredItems.count

        try await ws.newNoteCommand.executeAsync()

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

    func testNotebookModel_defaultIsNotReadonly() {
        let nb = NotebookModel(id: "nb", name: "Notebook", parentId: nil)

        XCTAssertFalse(nb.isReadonly)
    }

    func testCapabilityAddNote_isDisabledForReadonlyNotebook() async throws {
        let repo = InMemoryNoteRepository(
            seed: (
                notebooks: [
                    NotebookModel(
                        id: "nb-readonly",
                        name: "Archive",
                        parentId: nil,
                        isReadonly: true
                    )
                ],
                notes: []
            ),
            loadAllDelay: 0,
            loadNotesDelay: 0,
            saveNoteDelay: 0
        )
        let ws = try WorkspaceVM.builder().repository(repo).build()
        try await ws.constructAsync()
        defer { ws.dispose() }

        XCTAssertTrue(ws.notesView.currentNotebookIsReadonly)
        XCTAssertFalse(ws.capabilityActions.addNoteCommand.canExecute())
    }

    func testCapabilityAddNote_isEnabledForWritableNotebook() async throws {
        let repo = InMemoryNoteRepository(
            seed: (
                notebooks: [
                    NotebookModel(id: "nb-rw", name: "Drafts", parentId: nil)
                ],
                notes: []
            ),
            loadAllDelay: 0,
            loadNotesDelay: 0,
            saveNoteDelay: 0
        )
        let ws = try WorkspaceVM.builder().repository(repo).build()
        try await ws.constructAsync()
        defer { ws.dispose() }

        XCTAssertFalse(ws.notesView.currentNotebookIsReadonly)
        XCTAssertTrue(ws.capabilityActions.addNoteCommand.canExecute())
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

    func testSelectingNote_updatesCapabilityFocus() async throws {
        let ws = try buildWorkspace()
        try await ws.constructAsync()
        defer { ws.dispose() }

        guard let noteVM = ws.notesView.filteredItems.first else {
            XCTFail("Expected seeded note")
            return
        }

        ws.notesView.current = noteVM

        var labels = try ws.capabilityActions.actions.value.map(\.label)
        XCTAssertTrue(labels.contains("Close"))
        XCTAssertTrue(labels.contains("Save"))
        XCTAssertFalse(labels.contains("Expand"))

        ws.notesView.current = nil
        labels = try ws.capabilityActions.actions.value.map(\.label)
        XCTAssertTrue(labels.contains("Expand"))
        XCTAssertFalse(labels.contains("Save"))
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

    // MARK: - ADR-0201 interaction policies

    /// A workspace over a repository and notification hub the test can read.
    private struct PolicyFixture {
        let ws: WorkspaceVM
        let repo: CountingRepository
        let pending: () -> [VMx.Notification]
        let subscription: AnyCancellable
    }

    private func buildPolicyFixture(
        dispatcher: Dispatcher = ImmediateDispatcher.INSTANCE
    ) async throws -> PolicyFixture {
        let repo = CountingRepository(InMemoryNoteRepository(
            seed: SeedData.build(),
            loadAllDelay: 0,
            loadNotesDelay: 0,
            saveNoteDelay: 0,
            deleteNoteDelay: 0,
            addNotebookDelay: 0,
            exportDelay: 0
        ))
        let hub = NotificationHub()
        let ws = try WorkspaceVM.builder()
            .repository(repo).notificationHub(hub).dispatcher(dispatcher).build()
        let box = PendingBox()
        let sub = hub.pending.sink { box.items = $0 }
        try await ws.constructAsync()
        return PolicyFixture(ws: ws, repo: repo, pending: { box.items }, subscription: sub)
    }

    private final class PendingBox { var items: [VMx.Notification] = [] }

    private func storedTitle(_ repo: CountingRepository, _ note: NoteVM) async throws -> String? {
        let id = note.model.id
        return try await repo.loadNotes(notebookId: note.model.notebookId).first { $0.id == id }?.title
    }

    /// The action bar's "Save" command for the focused item.
    private func actionBarSave(_ ws: WorkspaceVM) throws -> AsyncRelayCommand {
        let action = try XCTUnwrap(try ws.capabilityActions.actions.value.first { $0.label == "Save" })
        return try XCTUnwrap(action.command as? AsyncRelayCommand)
    }

    /// ADR-0201 §2.1 — a search that hides the current note keeps it current
    /// and keeps the editor draft; clearing the search shows the note again.
    @MainActor
    func testHidingTheSelectedNote_keepsCurrentAndTheDraft() async throws {
        let f = try await buildPolicyFixture()
        defer { f.subscription.cancel(); f.ws.dispose() }
        let ws = f.ws
        let note = try XCTUnwrap(ws.notesView.visibleItems.first { $0.title == "Roadmap snapshot" })
        ws.notesView.current = note
        ws.noteForm.title = "Roadmap draft"

        ws.notesView.searchTerm = "Standup"
        ws.notesView.search()

        XCTAssertFalse(ws.notesView.visibleItems.contains { $0 === note })
        XCTAssertTrue(ws.notesView.current === note)
        XCTAssertEqual("Roadmap draft", ws.noteForm.title)
        XCTAssertTrue(ws.noteForm.isDirty)

        ws.notesView.searchTerm = ""
        ws.notesView.search()

        XCTAssertTrue(ws.notesView.current === note)
        XCTAssertTrue(ws.notesView.visibleItems.contains { $0 === note })
        XCTAssertEqual("Roadmap draft", ws.noteForm.title)
        XCTAssertTrue(ws.noteForm.isDirty)
    }

    /// ADR-0201 §2.2 — selecting another note discards the unsaved draft with
    /// no prompt; the repository keeps the stored title.
    func testSelectingAnotherNote_discardsTheUnsavedDraft() async throws {
        let f = try await buildPolicyFixture()
        defer { f.subscription.cancel(); f.ws.dispose() }
        let ws = f.ws
        let a = ws.notesView.visibleItems[0]
        let b = ws.notesView.visibleItems[1]
        let aTitle = a.model.title
        ws.notesView.current = a
        ws.noteForm.title = "Unsaved draft"
        XCTAssertTrue(ws.noteForm.isDirty)

        ws.notesView.current = b

        XCTAssertEqual(b.model.title, ws.noteForm.title)
        XCTAssertFalse(ws.noteForm.isDirty)

        ws.notesView.current = a

        XCTAssertEqual(aTitle, ws.noteForm.title)
        XCTAssertFalse(ws.noteForm.isDirty)
        let stored = try await storedTitle(f.repo, a)
        XCTAssertEqual(aTitle, stored)
    }

    /// ADR-0201 §2.3 — the action-bar Save on the note in the editor saves the
    /// editor draft and posts the editor's "Saved" notification.
    func testActionBarSave_onTheEditedNote_savesTheDraft() async throws {
        let f = try await buildPolicyFixture()
        defer { f.subscription.cancel(); f.ws.dispose() }
        let ws = f.ws
        let note = ws.notesView.visibleItems[0]
        ws.notesView.current = note
        ws.setFocus(note)
        ws.noteForm.title = "Saved from the action bar"

        try await actionBarSave(ws).executeAsync()

        let stored = try await storedTitle(f.repo, note)
        XCTAssertEqual("Saved from the action bar", stored)
        XCTAssertFalse(ws.noteForm.isDirty)
        let toast = "Saved \u{201C}Saved from the action bar\u{201D}"
        await waitUntil { f.pending().contains { $0.message == toast } }
        XCTAssertTrue(f.pending().contains { $0.message == toast })
    }

    /// ADR-0201 §2.3 — the action-bar Save writes nothing when the editor
    /// draft for that note is not valid.
    func testActionBarSave_withAnInvalidDraft_writesNothing() async throws {
        let f = try await buildPolicyFixture()
        defer { f.subscription.cancel(); f.ws.dispose() }
        let ws = f.ws
        let note = ws.notesView.visibleItems[0]
        let original = note.model.title
        ws.notesView.current = note
        ws.setFocus(note)
        ws.noteForm.title = ""
        XCTAssertFalse(ws.noteForm.isValid)

        try await actionBarSave(ws).executeAsync()

        let stored = try await storedTitle(f.repo, note)
        XCTAssertEqual(original, stored)
        let saves = await f.repo.saveCount
        XCTAssertEqual(0, saves)
        XCTAssertTrue(ws.noteForm.isDirty)
    }

    /// ADR-0201 §2.3 — the action-bar Save writes nothing and posts no
    /// "Saved" notification when the editor draft for that note is clean.
    func testActionBarSave_withACleanDraft_writesNothing() async throws {
        let f = try await buildPolicyFixture()
        defer { f.subscription.cancel(); f.ws.dispose() }
        let ws = f.ws
        let note = ws.notesView.visibleItems[0]
        ws.notesView.current = note
        ws.setFocus(note)
        XCTAssertFalse(ws.noteForm.isDirty)

        try await actionBarSave(ws).executeAsync()

        let saves = await f.repo.saveCount
        XCTAssertEqual(0, saves)
        await waitUntil({ !f.pending().isEmpty }, attempts: 20)
        XCTAssertTrue(f.pending().isEmpty)
    }

    /// ADR-0201 §2.3 — a note switch after the Save decision does not
    /// redirect the Save. The switch binds a clean draft for another note,
    /// and the Save writes nothing and posts no "Saved" notification.
    func testActionBarSave_aNoteSwitchAfterTheDecision_writesNothing() async throws {
        let dispatcher = InterleavingDispatcher()
        let f = try await buildPolicyFixture(dispatcher: dispatcher)
        defer { f.subscription.cancel(); f.ws.dispose() }
        let ws = f.ws
        let edited = ws.notesView.visibleItems[0]
        let other = ws.notesView.visibleItems[1]
        ws.notesView.current = edited
        ws.setFocus(edited)
        ws.noteForm.title = "Draft that the switch discards"
        let save = try actionBarSave(ws)

        // The first foreground item is the NoteVM admission check. The second
        // is the Save's route decision. The switch runs right after it,
        // before the Save resumes.
        dispatcher.afterForeground(count: 2) { ws.notesView.current = other }
        try await save.executeAsync()

        XCTAssertEqual(other.model.id, ws.noteForm.snapshot.id)
        let saves = await f.repo.saveCount
        XCTAssertEqual(0, saves)
        await waitUntil({ f.pending().contains { $0.message.hasPrefix("Saved") } }, attempts: 20)
        XCTAssertFalse(f.pending().contains { $0.message.hasPrefix("Saved") })
    }

    /// ADR-0201 §2.3 — for a focused note that the editor does not hold, the
    /// action-bar Save persists that note's stored model, not the draft.
    func testActionBarSave_onAnotherNote_savesItsStoredModel() async throws {
        let f = try await buildPolicyFixture()
        defer { f.subscription.cancel(); f.ws.dispose() }
        let ws = f.ws
        let edited = ws.notesView.visibleItems[0]
        let other = ws.notesView.visibleItems[1]
        let editedTitle = edited.model.title
        ws.notesView.current = edited
        ws.noteForm.title = "Draft that stays unsaved"
        ws.setFocus(other)

        try await actionBarSave(ws).executeAsync()

        let storedEdited = try await storedTitle(f.repo, edited)
        let storedOther = try await storedTitle(f.repo, other)
        XCTAssertEqual(editedTitle, storedEdited)
        XCTAssertEqual(other.model.title, storedOther)
        let saves = await f.repo.saveCount
        XCTAssertEqual(1, saves)
        XCTAssertEqual("Draft that stays unsaved", ws.noteForm.title)
        XCTAssertTrue(ws.noteForm.isDirty)
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

        try await ws.exportCommand.executeAsync()

        XCTAssertTrue(
            FileManager.default.fileExists(atPath: path),
            "export must write through the picked path"
        )
    }

    // MARK: - Startup failure reporting (#467)

    /// Builds a workspace over `repository` and records its hub's pending list.
    private func startWorkspace(
        over repository: any NoteRepository
    ) throws -> (WorkspaceVM, () -> [VMx.Notification], AnyCancellable) {
        let hub = NotificationHub()
        let ws = try WorkspaceVM.builder().repository(repository).notificationHub(hub).build()
        var pending: [VMx.Notification] = []
        let sub = hub.pending.sink { pending = $0 }
        return (ws, { pending }, sub)
    }

    func testConstructReportingFailure_postsAnErrorNotificationWhenConstructionFails() async throws {
        let (ws, pending, sub) = try startWorkspace(over: FailingRepository(failure: RepositoryUnavailable()))
        defer { sub.cancel(); ws.dispose() }

        await ws.constructReportingFailure()
        await waitUntil { !pending().isEmpty }

        XCTAssertEqual(pending().map(\.type), [.error])
        XCTAssertEqual(pending().first?.message, WorkspaceVM.constructionFailureMessage)
    }

    func testConstructReportingFailure_postsNothingWhenConstructionIsCancelled() async throws {
        let (ws, pending, sub) = try startWorkspace(over: FailingRepository(failure: CancellationError()))
        defer { sub.cancel(); ws.dispose() }

        await ws.constructReportingFailure()
        await waitUntil({ !pending().isEmpty }, attempts: 20)

        XCTAssertTrue(pending().isEmpty, "a cancelled construct is not reported as an error")
    }

    func testConstructReportingFailure_postsNothingWhenConstructionSucceeds() async throws {
        let repo = InMemoryNoteRepository(
            seed: SeedData.build(),
            loadAllDelay: 0,
            loadNotesDelay: 0,
            saveNoteDelay: 0
        )
        let (ws, pending, sub) = try startWorkspace(over: repo)
        defer { sub.cancel(); ws.dispose() }

        await ws.constructReportingFailure()
        await waitUntil({ !pending().isEmpty }, attempts: 20)

        XCTAssertTrue(pending().isEmpty)
        XCTAssertFalse(ws.notesView.filteredItems.isEmpty, "construction still completes")
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
