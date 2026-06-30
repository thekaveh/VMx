import XCTest
@testable import NotesShowcaseCore

/// Repository tests — port of C# `InMemoryNoteRepositoryTests.cs`.
///
/// All tests use zero delays (not under test here). The repo is an actor,
/// so every call is `await`.
final class InMemoryNoteRepositoryTests: XCTestCase {

    // MARK: - Helpers

    private func makeSeed() -> (notebooks: [NotebookModel], notes: [NoteModel]) {
        SeedData.build()
    }

    private func makeRepo(
        loadAllDelay: TimeInterval = 0,
        loadNotesDelay: TimeInterval = 0,
        saveNoteDelay: TimeInterval = 0,
        deleteNoteDelay: TimeInterval = 0,
        addNotebookDelay: TimeInterval = 0,
        exportDelay: TimeInterval = 0
    ) -> InMemoryNoteRepository {
        InMemoryNoteRepository(
            seed: makeSeed(),
            loadAllDelay: loadAllDelay,
            loadNotesDelay: loadNotesDelay,
            saveNoteDelay: saveNoteDelay,
            deleteNoteDelay: deleteNoteDelay,
            addNotebookDelay: addNotebookDelay,
            exportDelay: exportDelay
        )
    }

    // MARK: - Tests

    func testLoadAllReturnsSeed() async throws {
        let repo = makeRepo()
        let (notebooks, notes) = try await repo.loadAll()
        XCTAssertFalse(notebooks.isEmpty, "expected non-empty notebooks from seed")
        XCTAssertFalse(notes.isEmpty, "expected non-empty notes from seed")
    }

    func testLoadNotesFiltersByNotebook() async throws {
        let repo = makeRepo()
        let notes = try await repo.loadNotes(notebookId: "nb-reviews")
        XCTAssertFalse(notes.isEmpty, "nb-reviews should have notes in seed")
        XCTAssertTrue(
            notes.allSatisfy { $0.notebookId == "nb-reviews" },
            "all returned notes should belong to nb-reviews"
        )
    }

    func testSaveNoteUpdatesExisting() async throws {
        let repo = makeRepo()
        let notes = try await repo.loadNotes(notebookId: "nb-reviews")
        let first = notes[0].with(title: "Updated")
        try await repo.saveNote(first)
        let after = try await repo.loadNotes(notebookId: "nb-reviews")
        let found = after.first(where: { $0.id == first.id })
        XCTAssertEqual(found?.title, "Updated")
    }

    func testSaveNoteInsertsWhenIdIsNew() async throws {
        let repo = makeRepo()
        let fresh = NoteModel(
            id: "note-99",
            notebookId: "nb-work",
            title: "Brand new",
            tags: [],
            body: "...",
            starred: false,
            createdAt: Date(),
            updatedAt: Date()
        )
        try await repo.saveNote(fresh)
        let notes = try await repo.loadNotes(notebookId: "nb-work")
        XCTAssertTrue(notes.contains { $0.id == "note-99" }, "inserted note should appear")
    }

    func testDeleteNoteRemovesIt() async throws {
        let repo = makeRepo()
        let before = try await repo.loadNotes(notebookId: "nb-reviews")
        let toDelete = before[0]
        try await repo.deleteNote(id: toDelete.id)
        let after = try await repo.loadNotes(notebookId: "nb-reviews")
        XCTAssertFalse(after.contains { $0.id == toDelete.id }, "deleted note should not appear")
    }

    func testAddNotebookAppendsAndAppearsInLoadAll() async throws {
        let repo = makeRepo()
        try await repo.addNotebook(NotebookModel(id: "nb-inbox", name: "Inbox", parentId: nil))
        let (notebooks, _) = try await repo.loadAll()
        XCTAssertTrue(notebooks.contains { $0.id == "nb-inbox" }, "added notebook should appear")
    }

    func testExportWritesJsonWithExpectedFields() async throws {
        let repo = makeRepo()
        let (nbs, notes) = try await repo.loadAll()
        let path = NSTemporaryDirectory() + "notes-showcase-export-\(UUID().uuidString).json"
        defer { try? FileManager.default.removeItem(atPath: path) }
        try await repo.export(notebooks: nbs, notes: notes, path: path)
        let content = try String(contentsOfFile: path, encoding: .utf8)
        XCTAssertTrue(content.contains("notebooks"), "export JSON should contain 'notebooks' key")
        XCTAssertTrue(content.contains("notes"), "export JSON should contain 'notes' key")
        XCTAssertTrue(content.contains("nb-reviews"), "export JSON should contain seed notebook id")
    }
}
