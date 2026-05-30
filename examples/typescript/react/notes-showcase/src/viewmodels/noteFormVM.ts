/**
 * NoteFormVM — VM for the note editor pane.
 *
 * VMx-API adaptation (mirrors C# / Python flavors): VMx's `FormVM<TM>` is
 * suitable for composition but we layer extra validation, tag mutation
 * commands, and a post-approve notification on top. This VM owns a
 * `FormVM<NoteModel>` in strict mode (so `approveCommand.canExecute` already
 * gates on `isDirty`), and our own predicate additionally gates on `isValid`.
 *
 * `onApproved` persists via the repository (delegated through the FormVM's
 * `persister`) and then publishes a "Saved" notification.
 */
import {
  ComponentVMBase,
  declareCapabilities,
  FormVM,
  PropertyChangedMessage,
  RelayCommand,
  RelayCommandOf,
  ViewModelType,
  type ICommand,
  type ICommandOf,
  type IDispatcher,
  type IMessageHub,
} from "vmx";
import {
  Notification,
  NotificationType,
  type INotificationHub,
} from "vmx/notifications";

import type { NoteModel } from "../models/noteModel.js";
import type { INoteRepository } from "../models/noteRepository.js";

const SENTINEL = Symbol("not-set");

const EMPTY: NoteModel = {
  id: "",
  notebookId: "",
  title: "",
  tags: [],
  body: "",
  starred: false,
  createdAt: new Date(0).toISOString(),
  updatedAt: new Date(0).toISOString(),
};

export class NoteFormVM extends ComponentVMBase {
  readonly #repo: INoteRepository;
  readonly #notificationHub: INotificationHub | null;
  readonly #approveCommand: RelayCommand;
  readonly #addTagCommand: RelayCommand;
  readonly #removeTagCommand: RelayCommandOf<string>;
  readonly #noopCommand: RelayCommand;
  #form: FormVM<NoteModel> | null = null;
  #bound: NoteModel | null = null;
  #tagDraft = "";

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    repository: INoteRepository;
    notificationHub?: INotificationHub | null;
  }) {
    super({
      name: opts.name,
      hint: opts.hint,
      hub: opts.hub,
      dispatcher: opts.dispatcher,
    });
    this.#repo = opts.repository;
    this.#notificationHub = opts.notificationHub ?? null;
    declareCapabilities(this, "IReconstructable");

    this.#noopCommand = RelayCommand.builder().build();

    this.#approveCommand = RelayCommand.builder()
      .predicate(() => this.isDirty && this.isValid)
      .task(() => {
        void this.approveAsync();
      })
      .build();
    this.#addTagCommand = RelayCommand.builder()
      .predicate(
        () => this.hasBoundNote && this.#tagDraft.trim().length > 0,
      )
      .task(() => this.#addTag())
      .build();
    this.#removeTagCommand = RelayCommandOf.builder<string>()
      .predicate((tag) => this.hasBoundNote && tag.length > 0)
      .task((tag) => this.#removeTag(tag))
      .build();
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get hub(): IMessageHub {
    return this._hub;
  }

  get hasBoundNote(): boolean {
    return this.#form !== null;
  }

  /** Live editable draft. Returns EMPTY before `bindTo`. */
  get draft(): NoteModel {
    return this.#form?.model ?? this.#bound ?? EMPTY;
  }

  set draft(value: NoteModel) {
    if (this.#form === null) return;
    this.#form.setModel(value);
    this.#emitDraftChanges();
  }

  /** Snapshot — advances on each successful approve. */
  get snapshot(): NoteModel {
    return this.#form?.snapshot ?? this.#bound ?? EMPTY;
  }

  get isDirty(): boolean {
    return this.#form?.isDirty ?? false;
  }

  /** Validation: non-empty title. */
  get isValid(): boolean {
    return this.draft.title.trim().length > 0;
  }

  /** Comma-joined tag list — bind UI text labels to this so the rendered
   * string is "alpha, beta" instead of an array repr. Mirrors Py
   * ``tags_text`` (Round-3 Important C-I1) and C# ``TagsText``. */
  get tagsText(): string {
    return this.draft.tags.join(", ");
  }

  get approveCommand(): ICommand {
    return this.#approveCommand;
  }

  get denyCommand(): ICommand {
    return this.#form?.denyCommand ?? this.#noopCommand;
  }

  get tagDraft(): string {
    return this.#tagDraft;
  }

  set tagDraft(value: string) {
    if (this.#tagDraft === value) return;
    this.#tagDraft = value;
    this._hub.send(
      PropertyChangedMessage.create(this, this._name, "tagDraft"),
    );
    this._raisePropertyChanged("tagDraft");
  }

  get addTagCommand(): ICommand {
    return this.#addTagCommand;
  }

  get removeTagCommand(): ICommandOf<string> {
    return this.#removeTagCommand;
  }

  /** Binds the form to `note` (creates / replaces the inner FormVM). */
  bindTo(note: NoteModel): void {
    this.#form?.dispose();
    this.#bound = note;
    this.#form = new FormVM<NoteModel>({
      initial: note,
      persister: (m) => this.#persistAsync(m),
      hub: this._hub,
      strict: true,
    });
    this.#emitDraftChanges();
  }

  /**
   * Clears the form back to its initial empty state — disposes the inner
   * FormVM, resets `hasBoundNote` to `false`, and emits PropertyChanged so
   * widgets re-read (draft / snapshot / tagsText flip to EMPTY).
   *
   * Round-4 Important-1: called by `WorkspaceVM` when `notesView.current`
   * transitions to `null` (e.g. the selected note is deleted in
   * `NotesViewVM.#deleteNoteAsync`) so the right-pane editor does not show
   * ghost data from the just-removed note. Mirrors C# `NoteFormVM.Unbind`
   * and Python `NoteFormVM.unbind`.
   */
  unbind(): void {
    if (this.#form === null && this.#bound === null) return;
    this.#form?.dispose();
    this.#form = null;
    this.#bound = null;
    this.#emitDraftChanges();
  }

  /**
   * Awaitable approve cycle — persists via the repo and (on success) publishes
   * a "Saved" notification. Useful in tests.
   */
  async approveAsync(): Promise<void> {
    if (this.#form === null) return;
    await this.#form.approveAsync();
    this.#emitDraftChanges();
    if (this.#notificationHub !== null) {
      void this.#notificationHub.post(
        new Notification(
          NotificationType.Notification,
          `Saved “${this.#form.snapshot.title}”`,
        ),
      );
    }
  }

  async #persistAsync(note: NoteModel): Promise<void> {
    await this.#repo.saveNote(note);
  }

  #addTag(): void {
    const trimmed = this.#tagDraft.trim();
    if (trimmed.length === 0) return;
    if (this.draft.tags.some((t) => t.toLowerCase() === trimmed.toLowerCase()))
      return;
    this.draft = { ...this.draft, tags: [...this.draft.tags, trimmed] };
    this.tagDraft = "";
  }

  #removeTag(tag: string): void {
    if (tag.length === 0) return;
    this.draft = {
      ...this.draft,
      tags: this.draft.tags.filter(
        (t) => t.toLowerCase() !== tag.toLowerCase(),
      ),
    };
  }

  #emitDraftChanges(): void {
    // Round-3 Important B-I2 parity: also fire for ``approveCommand`` /
    // ``denyCommand`` whose getters delegate to the inner ``#form`` (and to
    // ``#noopCommand`` before bindTo). Without this, bindings keep the
    // stale references after the form is rebound.
    //
    // Round-4 Minor-2 (cross-flavor parity): ``tagsText`` is a derived
    // accessor that re-projects on every draft mutation; without firing
    // PropertyChanged here any consumer subscribed specifically to
    // ``tagsText`` (e.g. a chip-strip label) would miss notifications.
    // Mirrors the C# emission list (``TagsText``) and the Python
    // ``tags_text`` DerivedProperty (which re-emits via ``_self_subject``).
    for (const name of [
      "draft",
      "snapshot",
      "isDirty",
      "isValid",
      "tagsText",
      "approveCommand",
      "denyCommand",
    ]) {
      this._hub.send(
        PropertyChangedMessage.create(this, this._name, name),
      );
      this._raisePropertyChanged(name);
    }
  }

  protected override _onDispose(): void {
    this.#form?.dispose();
    this.#approveCommand.dispose();
    this.#addTagCommand.dispose();
    this.#removeTagCommand.dispose();
    this.#noopCommand.dispose();
    super._onDispose();
  }

  static builder(): NoteFormVMBuilder {
    return new NoteFormVMBuilder();
  }
}

export class NoteFormVMBuilder {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #repo: INoteRepository | typeof SENTINEL = SENTINEL;
  #notificationHub: INotificationHub | null = null;

  constructor(from?: NoteFormVMBuilder) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#repo = from.#repo;
      this.#notificationHub = from.#notificationHub;
    }
  }

  name(value: string): NoteFormVMBuilder {
    const b = new NoteFormVMBuilder(this);
    b.#name = value;
    return b;
  }

  hint(value: string): NoteFormVMBuilder {
    const b = new NoteFormVMBuilder(this);
    b.#hint = value;
    return b;
  }

  services(hub: IMessageHub, dispatcher: IDispatcher): NoteFormVMBuilder {
    const b = new NoteFormVMBuilder(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  repository(repo: INoteRepository): NoteFormVMBuilder {
    const b = new NoteFormVMBuilder(this);
    b.#repo = repo;
    return b;
  }

  notificationHub(hub: INotificationHub): NoteFormVMBuilder {
    const b = new NoteFormVMBuilder(this);
    b.#notificationHub = hub;
    return b;
  }

  build(): NoteFormVM {
    if (this.#name === null) throw new Error("name is required");
    if (this.#hub === null || this.#dispatcher === null)
      throw new Error("services (hub + dispatcher) are required");
    if (this.#repo === SENTINEL) throw new Error("repository is required");
    return new NoteFormVM({
      name: this.#name,
      hint: this.#hint,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      repository: this.#repo,
      notificationHub: this.#notificationHub,
    });
  }
}
