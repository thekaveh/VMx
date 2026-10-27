/**
 * A small notebook built from VMx primitives.
 *
 * - Each note is a `ComponentVMOf<NoteModel>` leaf.
 * - The notebook is a `CompositeVM` that owns the notes and tracks `current`.
 * - `saveCurrent` is an `AsyncRelayCommand` that writes the current note to a
 *   store. Store failures from fire-and-forget `execute()` arrive on `errors`.
 *
 * Replace `InMemoryNoteStore` with your own persistence adapter.
 */
import {
  AsyncRelayCommand,
  ComponentVMOf,
  CompositeVM,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
} from "@thekaveh/vmx";
import { filter, type Subscription } from "rxjs";

export interface NoteModel {
  readonly id: string;
  readonly title: string;
  readonly body: string;
}

export type NoteVM = ComponentVMOf<NoteModel>;

/** The store rejects a save when another note already uses the title. */
export class NoteConflictError extends Error {
  readonly title: string;

  constructor(title: string) {
    super(`another note already uses the title "${title}"`);
    this.name = "NoteConflictError";
    this.title = title;
  }
}

export class InMemoryNoteStore {
  readonly #notes = new Map<string, NoteModel>();

  async save(note: NoteModel): Promise<void> {
    for (const other of this.#notes.values()) {
      if (other.id !== note.id && other.title === note.title) {
        throw new NoteConflictError(note.title);
      }
    }
    this.#notes.set(note.id, note);
  }

  get(id: string): NoteModel | undefined {
    return this.#notes.get(id);
  }

  get size(): number {
    return this.#notes.size;
  }
}

export class NotebookApp {
  readonly hub = new MessageHub();
  readonly notebook: CompositeVM<NoteVM>;
  readonly saveCurrent: AsyncRelayCommand;
  readonly errors: unknown[] = [];
  readonly #subscriptions: Subscription[] = [];
  #disposed = false;

  constructor(store: InMemoryNoteStore, seed: readonly NoteModel[]) {
    // `immediate()` runs foreground and background work synchronously. A UI
    // host passes its own scheduler pair to `new RxDispatcher(...)` instead.
    const dispatcher = RxDispatcher.immediate();
    const notes = seed.map((model) =>
      ComponentVMOf.builder<NoteModel>()
        .name(`note-${model.id}`)
        .model(model)
        .modeledHinter((m) => m.title)
        .services(this.hub, dispatcher)
        .build(),
    );
    this.notebook = CompositeVM.builder<NoteVM>()
      .name("notebook")
      .services(this.hub, dispatcher)
      .children(() => notes)
      .build();

    // Re-evaluate `canExecute` whenever any VM on this hub reports a change.
    const changes = this.hub.messages.pipe(
      filter((message) => message instanceof PropertyChangedMessage),
    );
    this.saveCurrent = AsyncRelayCommand.builder()
      .predicate(() => {
        const current = this.notebook.current;
        return this.notebook.isConstructed && current !== null && current.model.title.trim() !== "";
      })
      .task(async () => {
        const current = this.notebook.current;
        if (current !== null) await store.save(current.model);
      })
      .triggers(changes)
      .build();
    this.#subscriptions.push(this.saveCurrent.errors.subscribe((error) => this.errors.push(error)));
  }

  /** Construct the notebook (and its notes) and select the first note. */
  start(): void {
    this.notebook.construct();
    this.notebook.current = [...this.notebook][0] ?? null;
  }

  /** Replace the current note's title. Models are immutable records. */
  renameCurrent(title: string): void {
    const current = this.notebook.current;
    if (current === null) throw new Error("no note is selected");
    current.model = { ...current.model, title };
  }

  select(id: string): void {
    const note = [...this.notebook].find((vm) => vm.model.id === id);
    if (note === undefined) throw new Error(`unknown note ${id}`);
    this.notebook.current = note;
  }

  /** Dispose commands and subscriptions first, then the VMs, then the hub. */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    for (const subscription of this.#subscriptions) subscription.unsubscribe();
    this.saveCurrent.dispose();
    this.notebook.dispose();
    this.hub.dispose();
  }
}
