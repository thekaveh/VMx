/**
 * INoteRepository — persistence port for notebooks and notes.
 *
 * Mirrors the C# / Python `INoteRepository` contract. All methods are async
 * and return Promises so views never block. Simulated I/O delays in
 * `InMemoryNoteRepository` mirror the canonical 300/150/200/120/120/150 ms
 * timings from scenario doc §7.
 */
import type { NotebookModel } from "./notebookModel.js";
import type { NoteModel } from "./noteModel.js";

export interface RepositorySnapshot {
  readonly notebooks: readonly NotebookModel[];
  readonly notes: readonly NoteModel[];
}

export interface INoteRepository {
  /** Loads everything. ~300 ms simulated delay. */
  loadAll(): Promise<RepositorySnapshot>;
  /** Loads notes belonging to a given notebook id. ~150 ms simulated delay. */
  loadNotes(notebookId: string): Promise<NoteModel[]>;
  /** Inserts or updates a note (stamps updatedAt). ~200 ms simulated delay. */
  saveNote(note: NoteModel): Promise<void>;
  /** Removes the note with the given id (no-op if absent). ~120 ms simulated delay. */
  deleteNote(id: string): Promise<void>;
  /** Appends a new notebook to the store. ~120 ms simulated delay. */
  addNotebook(notebook: NotebookModel): Promise<void>;
  /** Writes a JSON snapshot to the given path. ~150 ms simulated delay. */
  export(
    notebooks: readonly NotebookModel[],
    notes: readonly NoteModel[],
    path: string,
  ): Promise<void>;
}
