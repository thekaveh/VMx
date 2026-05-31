/**
 * InMemoryNoteRepository — default INoteRepository: in-memory store with
 * simulated I/O delays.
 *
 * Mirrors the C# `InMemoryNoteRepository` and Python `InMemoryNoteRepository`
 * (default delays 300/150/200/120/120/150 ms). Mutex-like single-flight lock
 * via a small async queue ensures saveNote / deleteNote / loadAll never
 * interleave half-applied state when called concurrently from VMs.
 */
import type { NotebookModel } from "./notebookModel.js";
import type { NoteModel } from "./noteModel.js";
import type { INoteRepository, RepositorySnapshot } from "./noteRepository.js";

/** Optional per-method delay overrides — useful in tests for zero latency. */
export interface InMemoryRepositoryOptions {
  loadAllDelayMs?: number;
  loadNotesDelayMs?: number;
  saveNoteDelayMs?: number;
  deleteNoteDelayMs?: number;
  addNotebookDelayMs?: number;
  exportDelayMs?: number;
}

/**
 * Minimal mutex: every `run()` chain waits for the previous one. Avoids
 * pulling in `async-mutex` for a one-method dependency.
 */
class AsyncLock {
  #tail: Promise<void> = Promise.resolve();

  async run<T>(work: () => Promise<T> | T): Promise<T> {
    const prior = this.#tail;
    let release!: () => void;
    this.#tail = new Promise<void>((resolve) => {
      release = resolve;
    });
    await prior;
    try {
      return await work();
    } finally {
      release();
    }
  }
}

function delay(ms: number): Promise<void> {
  if (ms <= 0) return Promise.resolve();
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export class InMemoryNoteRepository implements INoteRepository {
  readonly #notebooks: NotebookModel[];
  readonly #notes: NoteModel[];
  readonly #gate = new AsyncLock();
  readonly #loadAllMs: number;
  readonly #loadNotesMs: number;
  readonly #saveNoteMs: number;
  readonly #deleteNoteMs: number;
  readonly #addNotebookMs: number;
  readonly #exportMs: number;
  /**
   * The optional `exporter` lets host code persist exports without depending on
   * Node's `fs` (kept out of the VM layer per Pure-VM contract). Default is a
   * no-op so the repository remains usable in the browser / under jsdom.
   */
  readonly #exporter: ((path: string, payload: string) => Promise<void>) | null;

  constructor(
    seed: {
      notebooks: readonly NotebookModel[];
      notes: readonly NoteModel[];
    },
    opts: InMemoryRepositoryOptions = {},
    exporter: ((path: string, payload: string) => Promise<void>) | null = null,
  ) {
    this.#notebooks = [...seed.notebooks];
    this.#notes = [...seed.notes];
    this.#loadAllMs = opts.loadAllDelayMs ?? 300;
    this.#loadNotesMs = opts.loadNotesDelayMs ?? 150;
    this.#saveNoteMs = opts.saveNoteDelayMs ?? 200;
    this.#deleteNoteMs = opts.deleteNoteDelayMs ?? 120;
    this.#addNotebookMs = opts.addNotebookDelayMs ?? 120;
    this.#exportMs = opts.exportDelayMs ?? 150;
    this.#exporter = exporter;
  }

  async loadAll(): Promise<RepositorySnapshot> {
    await delay(this.#loadAllMs);
    return this.#gate.run(() => ({
      notebooks: [...this.#notebooks],
      notes: [...this.#notes],
    }));
  }

  async loadNotes(notebookId: string): Promise<NoteModel[]> {
    await delay(this.#loadNotesMs);
    return this.#gate.run(() =>
      this.#notes.filter((n) => n.notebookId === notebookId),
    );
  }

  async saveNote(note: NoteModel): Promise<void> {
    await delay(this.#saveNoteMs);
    return this.#gate.run(() => {
      const stamped: NoteModel = {
        ...note,
        updatedAt: new Date().toISOString(),
      };
      const idx = this.#notes.findIndex((n) => n.id === note.id);
      if (idx >= 0) {
        this.#notes[idx] = stamped;
      } else {
        this.#notes.push(stamped);
      }
    });
  }

  async deleteNote(id: string): Promise<void> {
    await delay(this.#deleteNoteMs);
    return this.#gate.run(() => {
      const idx = this.#notes.findIndex((n) => n.id === id);
      if (idx >= 0) this.#notes.splice(idx, 1);
    });
  }

  async addNotebook(notebook: NotebookModel): Promise<void> {
    await delay(this.#addNotebookMs);
    return this.#gate.run(() => {
      this.#notebooks.push(notebook);
    });
  }

  async export(
    notebooks: readonly NotebookModel[],
    notes: readonly NoteModel[],
    path: string,
  ): Promise<void> {
    await delay(this.#exportMs);
    const payload = JSON.stringify(
      {
        notebooks: notebooks.map((n) => ({
          id: n.id,
          name: n.name,
          parentId: n.parentId,
        })),
        notes: notes.map((n) => ({
          id: n.id,
          notebookId: n.notebookId,
          title: n.title,
          tags: [...n.tags],
          body: n.body,
          starred: n.starred,
          createdAt: n.createdAt,
          updatedAt: n.updatedAt,
        })),
      },
      null,
      2,
    );
    if (this.#exporter !== null) {
      await this.#exporter(path, payload);
    }
  }
}
