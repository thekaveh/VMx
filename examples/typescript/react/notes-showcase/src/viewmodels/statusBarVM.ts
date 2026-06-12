/**
 * StatusBarVM — read-only VM driving the three status-bar slots:
 *   * `noteCountText` — "N notes" / "1 note"
 *   * `starredText`   — "K starred"
 *   * `editingText`   — "Editing: TITLE" / "Editing: TITLE *" / "No selection"
 *
 * Each slot is a `DerivedProperty<string>`, recomputed from hub-published
 * PropertyChangedMessages from the upstream `NotesViewVM` / `NoteFormVM`.
 * Equality-guarded internally by DerivedProperty (Object.is on the new value).
 */
import { BehaviorSubject, filter, map, merge, type Subscription } from "rxjs";
import {
  ComponentVMBase,
  DerivedProperty,
  PropertyChangedMessage,
  ViewModelType,
  type IDispatcher,
  type IMessageHub,
} from "@thekaveh/vmx";

import type { NoteFormVM } from "./noteFormVM.js";
import type { NotebooksRootVM } from "./notebooksRootVM.js";
import type { NotesViewVM } from "./notesViewVM.js";

export class StatusBarVM extends ComponentVMBase {
  readonly #notesView: NotesViewVM;
  readonly #noteForm: NoteFormVM;
  readonly #notebooks: NotebooksRootVM;
  readonly #notesViewTick: BehaviorSubject<void>;
  readonly #noteFormTick: BehaviorSubject<void>;
  readonly #hubSubs: Subscription[] = [];
  readonly #noteCountText: DerivedProperty<string>;
  readonly #starredText: DerivedProperty<string>;
  readonly #editingText: DerivedProperty<string>;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    notesView: NotesViewVM;
    notebooks: NotebooksRootVM;
    noteForm: NoteFormVM;
  }) {
    super({
      name: opts.name,
      hint: opts.hint,
      hub: opts.hub,
      dispatcher: opts.dispatcher,
    });
    this.#notesView = opts.notesView;
    this.#notebooks = opts.notebooks;
    this.#noteForm = opts.noteForm;

    this.#notesViewTick = new BehaviorSubject<void>(undefined);
    this.#noteFormTick = new BehaviorSubject<void>(undefined);

    const notesViewMsgs = opts.notesView.hub.messages.pipe(
      filter(
        (m): m is PropertyChangedMessage<unknown> =>
          m instanceof PropertyChangedMessage && m.sender === opts.notesView,
      ),
    );
    this.#hubSubs.push(notesViewMsgs.subscribe(() => this.#notesViewTick.next()));

    const noteFormMsgs = opts.noteForm.hub.messages.pipe(
      filter(
        (m): m is PropertyChangedMessage<unknown> =>
          m instanceof PropertyChangedMessage && m.sender === opts.noteForm,
      ),
    );
    this.#hubSubs.push(noteFormMsgs.subscribe(() => this.#noteFormTick.next()));

    const notesViewStream = merge(this.#notesViewTick).pipe(
      map(() => {
        const n = this.#notesView.filteredItems.length;
        const k = this.#notesView.filteredItems.filter((x) => x.model.starred)
          .length;
        return { n, k };
      }),
    );

    const formStream = merge(this.#noteFormTick).pipe(
      map(() => ({
        bound: this.#noteForm.hasBoundNote,
        title: this.#noteForm.draft.title,
        dirty: this.#noteForm.isDirty,
      })),
    );

    this.#noteCountText = new DerivedProperty<string>(
      notesViewStream.pipe(
        map(({ n }) => `${n} note${n === 1 ? "" : "s"}`),
      ),
      null,
      null,
    );
    this.#starredText = new DerivedProperty<string>(
      notesViewStream.pipe(map(({ k }) => `${k} starred`)),
      null,
      null,
    );
    this.#editingText = new DerivedProperty<string>(
      formStream.pipe(
        map(({ bound, title, dirty }) =>
          bound
            ? `Editing: ${title}${dirty ? " *" : ""}`
            : "No selection",
        ),
      ),
      null,
      null,
    );
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get hub(): IMessageHub {
    return this._hub;
  }

  get notebooks(): NotebooksRootVM {
    return this.#notebooks;
  }

  get noteCountText(): DerivedProperty<string> {
    return this.#noteCountText;
  }

  get starredText(): DerivedProperty<string> {
    return this.#starredText;
  }

  get editingText(): DerivedProperty<string> {
    return this.#editingText;
  }

  protected override _onDispose(): void {
    // The hub outlives this VM — drop our callbacks so a disposed status bar
    // stops ticking (the Python flagship already does this via self._subs).
    for (const sub of this.#hubSubs) sub.unsubscribe();
    this.#noteCountText.dispose();
    this.#starredText.dispose();
    this.#editingText.dispose();
    this.#notesViewTick.complete();
    this.#noteFormTick.complete();
    super._onDispose();
  }

  static builder(): StatusBarVMBuilder {
    return new StatusBarVMBuilder();
  }
}

export class StatusBarVMBuilder {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #notesView: NotesViewVM | null = null;
  #notebooks: NotebooksRootVM | null = null;
  #noteForm: NoteFormVM | null = null;

  constructor(from?: StatusBarVMBuilder) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#notesView = from.#notesView;
      this.#notebooks = from.#notebooks;
      this.#noteForm = from.#noteForm;
    }
  }

  name(value: string): StatusBarVMBuilder {
    const b = new StatusBarVMBuilder(this);
    b.#name = value;
    return b;
  }

  hint(value: string): StatusBarVMBuilder {
    const b = new StatusBarVMBuilder(this);
    b.#hint = value;
    return b;
  }

  services(hub: IMessageHub, dispatcher: IDispatcher): StatusBarVMBuilder {
    const b = new StatusBarVMBuilder(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  notesView(vm: NotesViewVM): StatusBarVMBuilder {
    const b = new StatusBarVMBuilder(this);
    b.#notesView = vm;
    return b;
  }

  notebooks(vm: NotebooksRootVM): StatusBarVMBuilder {
    const b = new StatusBarVMBuilder(this);
    b.#notebooks = vm;
    return b;
  }

  noteForm(vm: NoteFormVM): StatusBarVMBuilder {
    const b = new StatusBarVMBuilder(this);
    b.#noteForm = vm;
    return b;
  }

  build(): StatusBarVM {
    if (this.#name === null) throw new Error("name is required");
    if (this.#hub === null || this.#dispatcher === null)
      throw new Error("services are required");
    if (this.#notesView === null) throw new Error("notesView is required");
    if (this.#notebooks === null) throw new Error("notebooks is required");
    if (this.#noteForm === null) throw new Error("noteForm is required");
    return new StatusBarVM({
      name: this.#name,
      hint: this.#hint,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      notesView: this.#notesView,
      notebooks: this.#notebooks,
      noteForm: this.#noteForm,
    });
  }
}
