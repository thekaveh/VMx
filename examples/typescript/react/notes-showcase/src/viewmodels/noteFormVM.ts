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
import { Subject, Subscription, type Observable } from "rxjs";

import {
  ComponentVMBase,
  declareCapabilities,
  DiscriminatorVM,
  FormVM,
  PropertyChangedMessage,
  RelayCommand,
  RelayCommandOf,
  SearchableState,
  ViewModelType,
  type ICommand,
  type ICommandOf,
  type IDispatcher,
  type IMessageHub,
} from "@thekaveh/vmx";
import {
  Notification,
  NotificationType,
  type INotificationHub,
} from "@thekaveh/vmx/notifications";

import type { NoteModel } from "../models/noteModel.js";
import type { INoteRepository } from "../models/noteRepository.js";

const SENTINEL = Symbol("not-set");
const TITLE_REQUIRED = "Title is required.";
export type EditorMode = "edit" | "preview";

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
  readonly #denyCommand: RelayCommand;
  readonly #showEditModeCommand: RelayCommand;
  readonly #showPreviewModeCommand: RelayCommand;
  readonly #onSaved = new Subject<NoteModel>();
  readonly #editorMode = new DiscriminatorVM<EditorMode>("edit");
  readonly #editorModeSub: Subscription;
  readonly #tagSearch: SearchableState<string>;
  readonly #tagSearchSub: Subscription;
  #form: FormVM<NoteModel> | null = null;
  #bound: NoteModel | null = null;
  #tagDraft = "";
  #tagCatalog: readonly string[] = [];
  #tagSuggestions: readonly string[] = [];

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
    this.#tagSearch = new SearchableState<string>({
      items: () => this.#tagCatalog,
      predicate: (tag, term) => {
        const normalized = term.trim().toLowerCase();
        if (normalized.length === 0) return false;
        if (!tag.toLowerCase().includes(normalized)) return false;
        return !this.draft.tags.some((existing) =>
          existing.toLowerCase() === tag.toLowerCase(),
        );
      },
      debounceMs: 0,
      scheduler: opts.dispatcher.foreground,
    });

    // Stable deny delegate (real-wiring audit, pass 6): the inner FormVM's
    // denyCommand publishes with sender = FormVM, which useVm's sender
    // filter drops — the DOM never re-rendered a revert. One stable command
    // delegates to the live form and re-emits this VM's own draft channels.
    this.#denyCommand = RelayCommand.builder()
      .task(() => {
        this.#form?.denyCommand.execute();
        this.#emitDraftChanges();
      })
      .build();

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
    this.#showEditModeCommand = RelayCommand.builder()
      .predicate(() => this.isPreviewMode)
      .task(() => this.#editorMode.setActiveKey("edit"))
      .triggers(this.#editorMode.activeChanged)
      .build();
    this.#showPreviewModeCommand = RelayCommand.builder()
      .predicate(() => this.isEditMode)
      .task(() => this.#editorMode.setActiveKey("preview"))
      .triggers(this.#editorMode.activeChanged)
      .build();
    this.#editorModeSub = this.#editorMode.activeChanged.subscribe(() => {
      this._hub.send(PropertyChangedMessage.create(this, this._name, "editorMode"));
      this._raisePropertyChanged("editorMode");
      this._hub.send(PropertyChangedMessage.create(this, this._name, "isPreviewMode"));
      this._raisePropertyChanged("isPreviewMode");
      this._hub.send(PropertyChangedMessage.create(this, this._name, "isEditMode"));
      this._raisePropertyChanged("isEditMode");
      this._hub.send(PropertyChangedMessage.create(this, this._name, "showEditModeCommand"));
      this._raisePropertyChanged("showEditModeCommand");
      this._hub.send(PropertyChangedMessage.create(this, this._name, "showPreviewModeCommand"));
      this._raisePropertyChanged("showPreviewModeCommand");
    });
    this.#tagSearchSub = this.#tagSearch.filtered.subscribe((suggestions) => {
      this.#tagSuggestions = suggestions;
      this.#emitTagSuggestionChanges();
    });
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

  get editorMode(): EditorMode {
    return this.#editorMode.activeKey;
  }

  get isPreviewMode(): boolean {
    return this.#editorMode.isActive("preview");
  }

  get isEditMode(): boolean {
    return this.#editorMode.isActive("edit");
  }

  get showEditModeCommand(): ICommand {
    return this.#showEditModeCommand;
  }

  get showPreviewModeCommand(): ICommand {
    return this.#showPreviewModeCommand;
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

  get isValid(): boolean {
    return this.#form?.isValid ?? false;
  }

  get titleError(): string | null {
    return this.#form?.fieldError("title") ?? null;
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
    return this.#denyCommand;
  }

  /** Emits the persisted NoteModel after each successful save — the
   * workspace refreshes the matching list row (row labels / star /
   * filter inputs were construction-time snapshots otherwise). */
  get onSaved(): Observable<NoteModel> {
    return this.#onSaved.asObservable();
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
    this.#tagSearch.searchTerm = value;
    this.#tagSearch.search();
  }

  get addTagCommand(): ICommand {
    return this.#addTagCommand;
  }

  get removeTagCommand(): ICommandOf<string> {
    return this.#removeTagCommand;
  }

  get tagSuggestions(): readonly string[] {
    return this.#tagSuggestions;
  }

  get tagSuggestionsText(): string {
    return this.#tagSuggestions.join(", ");
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
      validators: {
        title: (m) => m.title.trim().length === 0 ? TITLE_REQUIRED : null,
      },
    });
    this.#form.onApproved.subscribe((m) => this.#onSaved.next(m));
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
   *
   * Round-5 Minor: also reset ``tagDraft``. The user-typed tag input
   * buffer is part of the editor state, so a binding transition must
   * clear it too — otherwise the chip input still shows the orphan text
   * after the note disappears. Cross-flavor parity with C# `TagDraft =
   * string.Empty` and Python `self._tag_draft = ""`.
   */
  unbind(): void {
    const hadTagDraft = this.#tagDraft.length > 0;
    if (this.#form === null && this.#bound === null && !hadTagDraft) return;
    this.#form?.dispose();
    this.#form = null;
    this.#bound = null;
    if (hadTagDraft) {
      this.#tagDraft = "";
      this._hub.send(
        PropertyChangedMessage.create(this, this._name, "tagDraft"),
      );
      this._raisePropertyChanged("tagDraft");
    }
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
    await this.refreshTagSuggestionsAsync();
  }

  async refreshTagSuggestionsAsync(): Promise<void> {
    try {
      const snapshot = await this.#repo.loadAll();
      this.#tagCatalog = Array.from(
        new Set(
          snapshot.notes
            .flatMap((note) => note.tags)
            .map((tag) => tag.trim())
            .filter(Boolean),
        ),
      ).sort((left, right) => left.localeCompare(right));
      this.#tagSearch.search();
    } catch {
      this.#tagCatalog = [];
      this.#tagSearch.search();
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
    this.#tagSearch.search();
  }

  #removeTag(tag: string): void {
    if (tag.length === 0) return;
    this.draft = {
      ...this.draft,
      tags: this.draft.tags.filter(
        (t) => t.toLowerCase() !== tag.toLowerCase(),
      ),
    };
    this.#tagSearch.search();
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
      "titleError",
      "tagsText",
      "tagSuggestions",
      "tagSuggestionsText",
      "approveCommand",
      "denyCommand",
    ]) {
      this._hub.send(
        PropertyChangedMessage.create(this, this._name, name),
      );
      this._raisePropertyChanged(name);
    }
  }

  #emitTagSuggestionChanges(): void {
    for (const name of ["tagSuggestions", "tagSuggestionsText"]) {
      this._hub.send(PropertyChangedMessage.create(this, this._name, name));
      this._raisePropertyChanged(name);
    }
  }

  protected override _onDispose(): void {
    this.#form?.dispose();
    this.#approveCommand.dispose();
    this.#addTagCommand.dispose();
    this.#removeTagCommand.dispose();
    this.#denyCommand.dispose();
    this.#showEditModeCommand.dispose();
    this.#showPreviewModeCommand.dispose();
    this.#editorModeSub.unsubscribe();
    this.#editorMode.dispose();
    this.#tagSearchSub.unsubscribe();
    this.#tagSearch.dispose();
    this.#onSaved.complete();
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
