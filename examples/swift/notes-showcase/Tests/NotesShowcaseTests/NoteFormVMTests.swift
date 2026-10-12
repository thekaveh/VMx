//
// NoteFormVMTests — scenario tests for NoteFormVM.
//
// Ports NotesShowcase.Tests/ViewModels/NoteFormVMTests.cs (C# Avalonia flavor).
// No conformance-ID markers (scenario IDs live in THEME-00x only).
//
import XCTest
import Combine
import VMx
@testable import NotesShowcaseCore

// MARK: - Recorders

/// Reference-type recorder for `PropertyChangedMessage`s emitted by a specific sender.
private final class PropertyChangedRecorder {
    var propertyNames: [String] = []
    var cancellables = Set<AnyCancellable>()
}

/// Repository whose first `saveNote` stays pending until the test releases it.
/// Later saves and every read go straight to a zero-delay in-memory store, so
/// an extra save is counted instead of hanging the test.
private actor PendingSaveRepository: NoteRepository {
    private let store = InMemoryNoteRepository(
        seed: SeedData.build(),
        loadAllDelay: 0,
        loadNotesDelay: 0,
        saveNoteDelay: 0
    )
    private(set) var savedTitles: [String] = []
    private var saveStarted = false
    private var startWaiters: [CheckedContinuation<Void, Never>] = []
    private var pendingSave: CheckedContinuation<Void, Never>?

    func waitForPendingSave() async {
        if saveStarted { return }
        await withCheckedContinuation { startWaiters.append($0) }
    }

    func releasePendingSave() {
        pendingSave?.resume()
        pendingSave = nil
    }

    func saveNote(_ note: NoteModel) async throws {
        savedTitles.append(note.title)
        if !saveStarted {
            saveStarted = true
            let waiters = startWaiters
            startWaiters.removeAll()
            waiters.forEach { $0.resume() }
            await withCheckedContinuation { pendingSave = $0 }
        }
        try await store.saveNote(note)
    }

    func loadAll() async throws -> (notebooks: [NotebookModel], notes: [NoteModel]) {
        try await store.loadAll()
    }

    func loadNotes(notebookId: String) async throws -> [NoteModel] {
        try await store.loadNotes(notebookId: notebookId)
    }

    func searchNotes(
        term: String,
        token: String?,
        pageSize: Int
    ) async throws -> (items: [NoteModel], nextToken: String?) {
        try await store.searchNotes(term: term, token: token, pageSize: pageSize)
    }

    func deleteNote(id: String) async throws { try await store.deleteNote(id: id) }
    func addNotebook(_ notebook: NotebookModel) async throws { try await store.addNotebook(notebook) }
    func export(
        notebooks: [NotebookModel],
        notes: [NoteModel],
        path: String
    ) async throws {
        try await store.export(notebooks: notebooks, notes: notes, path: path)
    }
}

// MARK: - NoteFormVMTests

final class NoteFormVMTests: XCTestCase {

    // MARK: - Helpers

    private func build() throws -> (NoteFormVM, InMemoryNoteRepository) {
        let hub = MessageHub()
        let repo = InMemoryNoteRepository(
            seed: SeedData.build(),
            loadAllDelay: 0,
            loadNotesDelay: 0,
            saveNoteDelay: 0
        )
        let form = try NoteFormVM.builder()
            .name("form")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .repository(repo)
            .build()
        try form.construct()
        return (form, repo)
    }

    private func sampleNote(title: String = "Hello") -> NoteModel {
        NoteModel(
            id: "note-01", notebookId: "nb-reviews", title: title,
            tags: [], body: "", starred: false,
            createdAt: Date(), updatedAt: Date()
        )
    }

    /// Subscribes a `PropertyChangedRecorder` to all `PropertyChangedMessage`s
    /// on the form's hub that were sent by `form`.
    private func capture(form: NoteFormVM) -> PropertyChangedRecorder {
        let recorder = PropertyChangedRecorder()
        form.hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { [weak form] msg in
                guard let form else { return false }
                return msg.sender === form
            }
            .sink { [weak recorder] msg in recorder?.propertyNames.append(msg.propertyName) }
            .store(in: &recorder.cancellables)
        return recorder
    }

    // MARK: - Bind / dirty

    func testBindTo_snapshotsAndClearsDirty() throws {
        let (form, _) = try build()
        form.bindTo(sampleNote())
        XCTAssertFalse(form.isDirty)
        XCTAssertEqual("Hello", form.snapshot.title)
    }

    func testMutatingDraft_setsDirtyTrue() throws {
        let (form, _) = try build()
        form.bindTo(sampleNote())
        form.draft = form.draft.with(title: "Edited")
        XCTAssertTrue(form.isDirty)
        XCTAssertEqual("Edited", form.draft.title)
    }

    func testTagSuggestions_deduplicateMixedCaseCatalogEntries() async throws {
        let (form, repo) = try build()
        try await repo.saveNote(NoteModel(
            id: "mixed-tags", notebookId: "nb-work", title: "Tags",
            tags: ["Security", "security"], body: "", starred: false,
            createdAt: Date(), updatedAt: Date()
        ))
        form.bindTo(sampleNote())
        await form.refreshTagSuggestions()

        form.tagDraft = "sec"

        XCTAssertEqual(form.tagSuggestions, ["security"])
    }

    func testALateSearchEmissionCannotReplaceSuggestionsForTheCurrentTerm() async throws {
        // The tag search's debounced emission arrives on the main queue, so one
        // computed for an earlier term can land after the current term's
        // search has applied its result (#550).
        let (form, repo) = try build()
        try await repo.saveNote(NoteModel(
            id: "tagged", notebookId: "nb-work", title: "Tags",
            tags: ["security"], body: "", starred: false,
            createdAt: Date(), updatedAt: Date()
        ))
        form.bindTo(sampleNote())
        await form.refreshTagSuggestions()
        form.tagDraft = "sec"
        XCTAssertEqual(form.tagSuggestions, ["security"])

        form.receiveTagSearchResult([])  // computed for the initial empty term

        XCTAssertEqual(
            form.tagSuggestions, ["security"],
            "suggestions must follow the current tag draft"
        )
    }

    // MARK: - Approve

    func testApprove_persistsClearsDirtyAndResnapshots() async throws {
        let (form, repo) = try build()
        let (_, notes) = try await repo.loadAll()
        let note = try XCTUnwrap(notes.first)
        form.bindTo(note)
        XCTAssertFalse(form.isDirty)
        form.draft = form.draft.with(title: "Edited")
        XCTAssertTrue(form.isDirty)

        try await form.approveAsync()

        XCTAssertFalse(form.isDirty)
        XCTAssertEqual("Edited", form.snapshot.title)
        let reloaded = try await repo.loadNotes(notebookId: note.notebookId)
        XCTAssertEqual(
            "Edited",
            reloaded.first(where: { $0.id == note.id })?.title
        )
    }

    func testDoubleSaveWhileTheRepositorySaveIsPending_persistsOnce() async throws {
        // FormVM admits one approval at a time (spec/20-form-vm.md §5.3).
        let repo = PendingSaveRepository()
        let form = try NoteFormVM.builder()
            .name("form")
            .services(hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
            .repository(repo)
            .build()
        try form.construct()
        form.bindTo(sampleNote(title: "Original"))
        form.title = "Edited"

        let firstSave = Task { try await form.approveCommand.executeAsync() }
        await repo.waitForPendingSave()

        // The busy command drops a second click. A direct save, as a keyboard
        // shortcut would make, reaches the inner FormVM, which refuses it
        // while the first approval is in flight.
        XCTAssertFalse(form.approveCommand.canExecute())
        form.approveCommand.execute()
        try await form.approveAsync()
        let titlesWhilePending = await repo.savedTitles
        XCTAssertEqual(titlesWhilePending, ["Edited"])
        XCTAssertTrue(form.isDirty, "the refused save changed nothing")
        XCTAssertEqual("Original", form.snapshot.title)

        await repo.releasePendingSave()
        try await firstSave.value

        let savedTitles = await repo.savedTitles
        XCTAssertEqual(savedTitles, ["Edited"], "the double save persisted once")
        XCTAssertEqual("Edited", form.snapshot.title)
        XCTAssertFalse(form.isDirty)
    }

    // MARK: - Deny

    func testDeny_revertsDraftToSnapshot() throws {
        let (form, _) = try build()
        form.bindTo(sampleNote(title: "Original"))
        form.draft = form.draft.with(title: "Changed")
        XCTAssertTrue(form.isDirty)

        form.denyCommand.execute()

        XCTAssertFalse(form.isDirty)
        XCTAssertEqual("Original", form.draft.title)
    }

    // MARK: - ApproveCommand CanExecute

    func testApproveCommand_canExecute_requiresDirtyAndValid() throws {
        let (form, _) = try build()
        form.bindTo(sampleNote(title: "Original"))
        // Not dirty → cannot approve.
        XCTAssertFalse(form.approveCommand.canExecute())
        // Dirty + valid → can approve.
        form.draft = form.draft.with(title: "New title")
        XCTAssertTrue(form.approveCommand.canExecute())
        // Dirty but invalid (empty title) → cannot approve.
        form.draft = form.draft.with(title: "")
        XCTAssertFalse(form.isValid)
        XCTAssertFalse(form.approveCommand.canExecute())
    }

    func testEmptyTitle_makesIsValidFalse() throws {
        let (form, _) = try build()
        form.bindTo(sampleNote(title: ""))
        XCTAssertFalse(form.isValid)
        XCTAssertEqual("Title is required.", form.titleError)
        form.title = "Now valid"
        XCTAssertTrue(form.isValid)
        XCTAssertNil(form.titleError)
    }

    // MARK: - Tags

    func testAddTagCommand_appendsUniqueTagAndClearsTagDraft() throws {
        let (form, _) = try build()
        form.bindTo(sampleNote())
        form.tagDraft = "security"
        form.addTagCommand.execute()
        XCTAssertTrue(form.draft.tags.contains("security"))
        XCTAssertEqual("", form.tagDraft)
        // Idempotent: re-adding the same tag is a no-op.
        form.tagDraft = "security"
        form.addTagCommand.execute()
        XCTAssertEqual(1, form.draft.tags.count)
    }

    func testRemoveTagCommand_removesTag() throws {
        let (form, _) = try build()
        form.bindTo(sampleNote().with(tags: ["a", "b"]))
        form.removeTagCommand.execute("a")
        XCTAssertFalse(form.draft.tags.contains("a"))
        XCTAssertTrue(form.draft.tags.contains("b"))
    }

    func testTagSuggestions_filterWorkspaceTagCatalogThroughSearchableState() async throws {
        let (form, _) = try build()
        form.bindTo(sampleNote().with(tags: []))
        await form.refreshTagSuggestions()

        form.tagDraft = "sec"

        XCTAssertEqual(["security"], form.tagSuggestions)
        XCTAssertEqual("security", form.tagSuggestionsText)
    }

    func testTagSuggestions_omitTagsAlreadyOnDraft() async throws {
        let (form, _) = try build()
        form.bindTo(sampleNote().with(tags: ["security"]))
        await form.refreshTagSuggestions()

        form.tagDraft = "sec"

        XCTAssertEqual([], form.tagSuggestions)
        XCTAssertEqual("", form.tagSuggestionsText)
    }

    // MARK: - Editor Mode

    func testEditorMode_defaultsToEditAndSwitchesThroughDiscriminatorVM() throws {
        let (form, _) = try build()
        XCTAssertEqual("edit", form.editorMode)
        XCTAssertTrue(form.isEditMode)
        XCTAssertFalse(form.isPreviewMode)
        XCTAssertFalse(form.showEditModeCommand.canExecute())
        XCTAssertTrue(form.showPreviewModeCommand.canExecute())

        form.showPreviewModeCommand.execute()

        XCTAssertEqual("preview", form.editorMode)
        XCTAssertFalse(form.isEditMode)
        XCTAssertTrue(form.isPreviewMode)
        XCTAssertTrue(form.showEditModeCommand.canExecute())
        XCTAssertFalse(form.showPreviewModeCommand.canExecute())
    }

    // MARK: - Two-way scalar setter parity

    func testSettingTitleScalar_flipsDirtyTrueAndEnablesApproveCommand() throws {
        let (form, _) = try build()
        form.bindTo(sampleNote(title: "Original"))
        XCTAssertFalse(form.isDirty)
        XCTAssertFalse(form.approveCommand.canExecute())

        form.title = "Edited"

        XCTAssertEqual("Edited", form.title)
        XCTAssertEqual("Edited", form.draft.title)
        XCTAssertTrue(form.isDirty)
        XCTAssertTrue(form.approveCommand.canExecute())
    }

    func testSettingTitleBackToSnapshotValue_flipsDirtyFalse() throws {
        let (form, _) = try build()
        form.bindTo(sampleNote(title: "Original"))
        form.title = "Edited"
        XCTAssertTrue(form.isDirty)

        form.title = "Original"

        XCTAssertFalse(form.isDirty)
        XCTAssertFalse(form.approveCommand.canExecute())
    }

    func testSettingBodyAndStarred_roundTripIntoDraft() throws {
        let (form, _) = try build()
        form.bindTo(sampleNote())
        form.body = "New body content"
        form.starred = true
        XCTAssertEqual("New body content", form.draft.body)
        XCTAssertTrue(form.draft.starred)
        XCTAssertTrue(form.isDirty)
    }

    func testSettingTitleToSameValue_isNoOp() throws {
        let (form, _) = try build()
        form.bindTo(sampleNote(title: "Hello"))
        form.title = "Hello"
        XCTAssertFalse(form.isDirty)
    }

    func testScalarSetters_emitPropertyChangedMessageOnHub() throws {
        let (form, _) = try build()
        form.bindTo(sampleNote())
        let recorder = capture(form: form)

        form.title = "T2"
        form.body = "B2"
        form.starred = true

        XCTAssertTrue(
            recorder.propertyNames.contains("title"),
            "Expected 'title' in \(recorder.propertyNames)"
        )
        XCTAssertTrue(
            recorder.propertyNames.contains("body"),
            "Expected 'body' in \(recorder.propertyNames)"
        )
        XCTAssertTrue(
            recorder.propertyNames.contains("starred"),
            "Expected 'starred' in \(recorder.propertyNames)"
        )
    }

    func testScalarSetters_areNoOpsWhenNoNoteIsBound() throws {
        let (form, _) = try build()
        // Pre-bind: no inner FormVM yet — setters must safely no-op.
        form.title = "ignored"
        form.body = "ignored"
        form.starred = true
        XCTAssertFalse(form.isDirty)
    }

    // MARK: - BindTo emits PropertyChanged for command references

    func testBindTo_emitsPropertyChangedForApproveCommandAndDenyCommand() throws {
        let (form, _) = try build()
        let recorder = capture(form: form)

        form.bindTo(sampleNote())

        XCTAssertTrue(
            recorder.propertyNames.contains("approveCommand"),
            "Expected 'approveCommand' in \(recorder.propertyNames)"
        )
        XCTAssertTrue(
            recorder.propertyNames.contains("denyCommand"),
            "Expected 'denyCommand' in \(recorder.propertyNames)"
        )
    }

    // MARK: - TagsText

    func testTagsText_rendersCommaJoinedTagList() throws {
        let (form, _) = try build()
        form.bindTo(sampleNote().with(tags: ["alpha", "beta"]))
        XCTAssertEqual("alpha, beta", form.tagsText)
    }

    // MARK: - Unbind

    func testUnbind_clearsTagDraftBuffer() throws {
        let (form, _) = try build()
        form.bindTo(sampleNote())
        form.tagDraft = "secur"
        XCTAssertEqual("secur", form.tagDraft)

        form.unbind()

        XCTAssertEqual("", form.tagDraft)
        XCTAssertFalse(form.hasBoundNote)
    }

    // MARK: - Notification

    func testApproveAsync_publishesSavedNotification() async throws {
        let hub = MessageHub()
        let repo = InMemoryNoteRepository(
            seed: SeedData.build(),
            loadAllDelay: 0,
            loadNotesDelay: 0,
            saveNoteDelay: 0
        )
        let notificationHub = NotificationHub()
        var observed: [VMx.Notification] = []
        var cancellables = Set<AnyCancellable>()
        notificationHub.pending
            .sink { snapshot in observed = snapshot }
            .store(in: &cancellables)

        let form = try NoteFormVM.builder()
            .name("form")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .repository(repo)
            .notificationHub(notificationHub)
            .build()
        try form.construct()

        let (_, notes) = try await repo.loadAll()
        let note = try XCTUnwrap(notes.first)
        form.bindTo(note)
        form.title = "Edited title"

        try await form.approveAsync()
        // The saved notification posts via a detached Task (awaiting
        // NotificationHub.post would suspend until the toast resolves), so
        // poll briefly for its arrival.
        for _ in 0..<50 where !observed.contains(where: {
            $0.message.contains("Saved") && $0.message.contains("Edited title")
        }) {
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
        XCTAssertTrue(
            observed.contains(where: {
                $0.message.contains("Saved") && $0.message.contains("Edited title")
            }),
            "Expected 'Saved … Edited title' notification; got \(observed.map { $0.message })"
        )
    }
}
