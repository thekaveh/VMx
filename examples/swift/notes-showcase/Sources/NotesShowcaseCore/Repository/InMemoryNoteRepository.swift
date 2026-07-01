import Foundation

/// Default `NoteRepository`: in-memory store with simulated I/O delays.
///
/// Concurrency-safe: Swift `actor` serialises all mutations, mirroring the
/// C# `SemaphoreSlim(1, 1)` gate. All methods are `async throws` per the
/// protocol; cancellation propagates via structured concurrency / `Task.sleep`.
///
/// Default delays mirror the scenario doc §7: 300 / 150 / 200 / 120 / 120 / 150 ms.
/// Pass zero overrides in tests that don't care about wall-clock timing.
public actor InMemoryNoteRepository: NoteRepository {

    // MARK: - State

    private var notebooks: [NotebookModel]
    private var notes: [NoteModel]

    // MARK: - Delay configuration

    private let loadAllDelay: TimeInterval
    private let loadNotesDelay: TimeInterval
    private let saveNoteDelay: TimeInterval
    private let deleteNoteDelay: TimeInterval
    private let addNotebookDelay: TimeInterval
    private let exportDelay: TimeInterval

    // MARK: - Injectable clock

    /// Returns the current timestamp. Injected for test determinism.
    private let now: () -> Date

    // MARK: - Init

    public init(
        seed: (notebooks: [NotebookModel], notes: [NoteModel]),
        loadAllDelay: TimeInterval = 0.3,
        loadNotesDelay: TimeInterval = 0.15,
        saveNoteDelay: TimeInterval = 0.2,
        deleteNoteDelay: TimeInterval = 0.12,
        addNotebookDelay: TimeInterval = 0.12,
        exportDelay: TimeInterval = 0.15,
        now: @escaping () -> Date = { Date() }
    ) {
        self.notebooks = seed.notebooks
        self.notes = seed.notes
        self.loadAllDelay = loadAllDelay
        self.loadNotesDelay = loadNotesDelay
        self.saveNoteDelay = saveNoteDelay
        self.deleteNoteDelay = deleteNoteDelay
        self.addNotebookDelay = addNotebookDelay
        self.exportDelay = exportDelay
        self.now = now
    }

    // MARK: - NoteRepository

    public func loadAll() async throws -> (notebooks: [NotebookModel], notes: [NoteModel]) {
        try await sleep(loadAllDelay)
        return (notebooks: notebooks, notes: notes)
    }

    public func loadNotes(notebookId: String) async throws -> [NoteModel] {
        try await sleep(loadNotesDelay)
        return notes.filter { $0.notebookId == notebookId }
    }

    public func saveNote(_ note: NoteModel) async throws {
        try await sleep(saveNoteDelay)
        let stamped = note.with(updatedAt: now())
        if let idx = notes.firstIndex(where: { $0.id == note.id }) {
            notes[idx] = stamped
        } else {
            notes.append(stamped)
        }
    }

    public func deleteNote(id: String) async throws {
        try await sleep(deleteNoteDelay)
        notes.removeAll { $0.id == id }
    }

    public func addNotebook(_ notebook: NotebookModel) async throws {
        try await sleep(addNotebookDelay)
        notebooks.append(notebook)
    }

    public func export(
        notebooks: [NotebookModel],
        notes: [NoteModel],
        path: String
    ) async throws {
        try await sleep(exportDelay)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        let payload = ExportPayload(notebooks: notebooks, notes: notes)
        let data = try encoder.encode(payload)
        try data.write(to: URL(fileURLWithPath: path))
    }

    // MARK: - Private helpers

    private func sleep(_ interval: TimeInterval) async throws {
        guard interval > 0 else { return }
        try await Task.sleep(nanoseconds: UInt64(interval * 1_000_000_000))
    }
}

// MARK: - Export payload

private struct ExportPayload: Encodable {
    let notebooks: [NotebookModel]
    let notes: [NoteModel]
}
