//
// StatusBarVMTests — scenario tests for StatusBarVM.
//
// Ports NotesShowcase.Tests/ViewModels/StatusBarVMTests.cs (C# Avalonia flavor).
// No conformance-ID markers (scenario IDs live in THEME-00x only).
//
// Task-8 note: BindableDerived sidecars are not implemented in Swift yet.
// The two sidecar tests from the C# file are skipped here; they will be
// added in Task 8.
//
import XCTest
import Combine
import VMx
@testable import NotesShowcaseCore

// MARK: - StatusBarVMTests

final class StatusBarVMTests: XCTestCase {

    // MARK: - Shared fixture

    /// All fixtures share a hub so property-changed messages from NotesViewVM /
    /// NoteFormVM reach the StatusBarVM subscription.
    private struct Fixture {
        let hub: MessageHub
        let bar: StatusBarVM
        let notes: NotesViewVM
        let notebooks: NotebooksRootVM
        let form: NoteFormVM
        let repo: InMemoryNoteRepository
    }

    private func build() throws -> Fixture {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let repo = InMemoryNoteRepository(
            seed: SeedData.build(),
            loadAllDelay: 0,
            loadNotesDelay: 0,
            saveNoteDelay: 0
        )
        let notes = try NotesViewVM.builder()
            .name("notes").services(hub: hub, dispatcher: dispatcher)
            .repository(repo).pageSize(5)
            .searchDebounce(.milliseconds(0))
            .build()
        let notebooks = try NotebooksRootVM.builder()
            .name("nbs").services(hub: hub, dispatcher: dispatcher)
            .repository(repo)
            .build()
        let form = try NoteFormVM.builder()
            .name("form").services(hub: hub, dispatcher: dispatcher)
            .repository(repo)
            .build()
        let bar = try StatusBarVM.builder()
            .name("status").services(hub: hub, dispatcher: dispatcher)
            .notesView(notes).notebooks(notebooks).noteForm(form)
            .build()
        try notes.construct()
        try notebooks.construct()
        try form.construct()
        try bar.construct()
        return Fixture(hub: hub, bar: bar, notes: notes, notebooks: notebooks, form: form, repo: repo)
    }

    private func sampleNote(title: String = "Title") -> NoteModel {
        NoteModel(
            id: "n1", notebookId: "nb-reviews", title: title,
            tags: [], body: "", starred: false,
            createdAt: Date(), updatedAt: Date()
        )
    }

    // MARK: - noteCountText

    func testNoteCountText_recomputesWhenNotesViewEmitsPropertyChanged() async throws {
        let f = try build()
        let initial = try f.bar.noteCountText.value
        await f.notes.bindTo(notebookId: "nb-reviews")
        let updated = try f.bar.noteCountText.value
        XCTAssertNotEqual(initial, updated)
        XCTAssertTrue(updated.contains("note"), "Expected 'note' in '\(updated)'")
    }

    // MARK: - starredText

    func testStarredText_reflectsStarredCountInCurrentFilter() async throws {
        let f = try build()
        await f.notes.bindTo(notebookId: "nb-reviews")
        // SeedData: 2 starred notes in nb-reviews.
        XCTAssertEqual("2 starred", try f.bar.starredText.value)
    }

    // MARK: - editingText

    func testEditingText_saysNoSelectionUntilFormIsBound() throws {
        let f = try build()
        XCTAssertEqual("No selection", try f.bar.editingText.value)

        f.form.bindTo(sampleNote(title: "Title"))

        let editing = try f.bar.editingText.value
        XCTAssertTrue(editing.contains("Editing:"), "Expected 'Editing:' in '\(editing)'")
        XCTAssertTrue(editing.contains("Title"),    "Expected 'Title' in '\(editing)'")
    }

    func testEditingText_dirtyMarkerAppearsOnMutation() throws {
        let f = try build()
        f.form.bindTo(sampleNote(title: "Title"))

        XCTAssertFalse((try f.bar.editingText.value).contains(" *"),
                       "Expected no ' *' marker before mutation")

        f.form.draft = f.form.draft.with(title: "Title v2")

        XCTAssertTrue((try f.bar.editingText.value).contains(" *"),
                      "Expected ' *' dirty marker after draft mutation")
    }

    // MARK: - Distinct-until-changed

    func testEqualityGuardNoDuplicateDerivedPropertyEmissionsForSameValue() async throws {
        let f = try build()
        await f.notes.bindTo(notebookId: "nb-reviews")

        var emitCount = 0
        var cancellables = Set<AnyCancellable>()
        f.bar.noteCountText.valueChanged
            .sink { _ in emitCount += 1 }
            .store(in: &cancellables)

        // Same filter = same count = no emission via distinct-until-changed.
        f.notes.filter = nil
        f.notes.filter = nil
        f.notes.showStarredOnly = false

        XCTAssertEqual(0, emitCount,
                       "Expected zero emissions for no-op filter mutations (distinct-until-changed)")
    }
}
