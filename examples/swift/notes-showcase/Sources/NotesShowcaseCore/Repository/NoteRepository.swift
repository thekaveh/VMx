import Foundation

/// Async persistence port for notebooks and notes.
///
/// Mirrors C# `INoteRepository`. Every example wires its VMs to one
/// implementation; `InMemoryNoteRepository` is the default for the showcase.
///
/// Swift structured concurrency replaces the C# `CancellationToken` parameter:
/// use `Task` cancellation instead.
public protocol NoteRepository: Sendable {
    /// Loads the full seed at startup (notebooks + notes).
    func loadAll() async throws -> (notebooks: [NotebookModel], notes: [NoteModel])

    /// Loads only the notes belonging to `notebookId`.
    func loadNotes(notebookId: String) async throws -> [NoteModel]

    /// Persists `note` (insert-or-update by id), stamping `updatedAt`.
    func saveNote(_ note: NoteModel) async throws

    /// Removes the note identified by `id`.
    func deleteNote(id: String) async throws

    /// Appends a new notebook.
    func addNotebook(_ notebook: NotebookModel) async throws

    /// Serialises the workspace to `path` as indented JSON.
    func export(notebooks: [NotebookModel], notes: [NoteModel], path: String) async throws
}
