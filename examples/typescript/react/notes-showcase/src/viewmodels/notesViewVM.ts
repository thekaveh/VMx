/**
 * NotesViewVM — centre pane: paged, searchable, filterable list of notes.
 *
 * VMx-API adaptation (mirrors C# / Python flavors): `PagedComposition` is a
 * sealed read-only decorator, so we compose rather than subclass. Internal
 * pipeline:
 *   inner storage   = plain `NoteVM[]` (lifecycle owned by this VM)
 *   filtered view   = recomputed on every collection / filter / search change
 *   paged view      = `PagedComposition<NoteVM>` over a lazy factory of the
 *                     filtered list
 *   search          = `SearchableState<NoteVM>` (debounced 150 ms)
 *
 * `bindToAsync(notebookId)` cancels any prior fetch by ignoring its result
 * (in-flight fetches finish but become no-ops if a newer call superseded them).
 */
import {
  asyncScheduler,
  BehaviorSubject,
  map,
  type SchedulerLike,
} from "rxjs";
import {
  ComponentVMBase,
  ConstructionStatus,
  declareCapabilities,
  DerivedProperty,
  PagedComposition,
  PropertyChangedMessage,
  RelayCommand,
  SearchableState,
  ViewModelType,
  type ICommand,
  type IDispatcher,
  type IMessageHub,
} from "@thekaveh/vmx";
import { type INotificationHub } from "@thekaveh/vmx/notifications";

import type { NoteModel } from "../models/noteModel.js";
import type { INoteRepository } from "../models/noteRepository.js";
import { type IDialogService } from "./dialogService.js";
import { NoteVM } from "./noteVM.js";

const SENTINEL = Symbol("not-set");

export class NotesViewVM extends ComponentVMBase {
  readonly #repo: INoteRepository;
  readonly #dialogService: IDialogService | null;
  readonly #notificationHub: INotificationHub | null;
  readonly #inner: NoteVM[] = [];
  readonly #filtered: NoteVM[] = [];
  readonly #paged: PagedComposition<NoteVM>;
  readonly #search: SearchableState<NoteVM>;
  readonly #moveFirst: RelayCommand;
  readonly #movePrev: RelayCommand;
  readonly #moveNext: RelayCommand;
  readonly #moveLast: RelayCommand;
  readonly #stateSubject: BehaviorSubject<void> = new BehaviorSubject<void>(undefined);
  readonly #isEmptyDerived: DerivedProperty<boolean>;
  readonly #pageLabelDerived: DerivedProperty<string>;

  #showStarredOnly = false;
  #filter: ((vm: NoteVM) => boolean) | null = null;
  #current: NoteVM | null = null;
  #activeBindingToken = 0;
  #boundNotebookId: string | null = null;
  // Edge-case backfill (readonly notebook gating): mirrors the readonly
  // flag of the currently-bound notebook. The host (`WorkspaceVM`) sets
  // this when the user changes notebook selection; `CapabilityActionsVM`
  // consults it to gate `addNoteCommand.canExecute`.
  #currentNotebookIsReadonly = false;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    repository: INoteRepository;
    pageSize: number;
    searchDebounceMs: number;
    searchScheduler?: SchedulerLike;
    dialogService?: IDialogService | null;
    notificationHub?: INotificationHub | null;
  }) {
    super({
      name: opts.name,
      hint: opts.hint,
      hub: opts.hub,
      dispatcher: opts.dispatcher,
    });
    this.#repo = opts.repository;
    this.#dialogService = opts.dialogService ?? null;
    this.#notificationHub = opts.notificationHub ?? null;
    declareCapabilities(
      this,
      "IPageable",
      "IFilterable",
      "ISearchable",
      "IReconstructable",
    );

    this.#paged = new PagedComposition<NoteVM>(
      () => this.#filtered.slice(),
      opts.pageSize,
    );
    this.#paged.propertyChanged.subscribe((name) => {
      this._raisePropertyChanged(name);
      this._hub.send(
        PropertyChangedMessage.create(this, this._name, name),
      );
      if (name === "currentPageIndex" || name === "pageCount" || name === "pageSize") {
        this._raisePropertyChanged("pageLabel");
        this._hub.send(
          PropertyChangedMessage.create(this, this._name, "pageLabel"),
        );
        this._raisePropertyChanged("visibleItems");
        this._hub.send(
          PropertyChangedMessage.create(this, this._name, "visibleItems"),
        );
      }
    });

    this.#search = new SearchableState<NoteVM>({
      items: () => this.#inner.slice(),
      // Predicate is unused — we re-run #recomputeFiltered ourselves on every
      // debounced term emission below, blending starred + arbitrary filters.
      predicate: () => true,
      debounceMs: opts.searchDebounceMs,
      scheduler: opts.searchScheduler ?? asyncScheduler,
    });
    this.#search.filtered.subscribe(() => this.#recomputeFiltered());

    this.#isEmptyDerived = new DerivedProperty<boolean>(
      this.#stateSubject.asObservable().pipe(map(() => this.#filtered.length === 0)),
      null,
      null,
    );
    this.#pageLabelDerived = new DerivedProperty<string>(
      this.#stateSubject.asObservable().pipe(
        map(() => {
          const count = Math.max(1, this.pageCount);
          return `Page ${this.currentPageIndex + 1} of ${count}`;
        }),
      ),
      null,
      null,
    );
    // DerivedProperty caches first value; ensure subscribers see initial state.
    this.#stateSubject.next();

    // Predicates + triggers (real-wiring audit, pass 6): without them
    // canExecute() was always true and canExecuteChanged never fired, so
    // the pagination buttons' disabled mirror was vacuous.
    this.#moveFirst = RelayCommand.builder()
      .predicate(() => this.currentPageIndex > 0)
      .task(() => this.#paged.moveToFirstPage())
      .triggers(this.#stateSubject)
      .build();
    this.#movePrev = RelayCommand.builder()
      .predicate(() => this.currentPageIndex > 0)
      .task(() => this.#paged.moveToPreviousPage())
      .triggers(this.#stateSubject)
      .build();
    this.#moveNext = RelayCommand.builder()
      .predicate(() => this.currentPageIndex < this.pageCount - 1)
      .task(() => this.#paged.moveToNextPage())
      .triggers(this.#stateSubject)
      .build();
    this.#moveLast = RelayCommand.builder()
      .predicate(() => this.currentPageIndex < this.pageCount - 1)
      .task(() => this.#paged.moveToLastPage())
      .triggers(this.#stateSubject)
      .build();
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get hub(): IMessageHub {
    return this._hub;
  }

  get inner(): readonly NoteVM[] {
    return this.#inner;
  }

  get filteredItems(): readonly NoteVM[] {
    return this.#filtered;
  }

  get visibleItems(): readonly NoteVM[] {
    return this.#paged.items;
  }

  get count(): number {
    return this.#filtered.length;
  }

  // ── ISearchable ──────────────────────────────────────────────────────────

  get searchTerm(): string {
    return this.#search.searchTerm;
  }

  set searchTerm(value: string) {
    if (this.#search.searchTerm === value) return;
    this.#search.searchTerm = value;
    this._hub.send(
      PropertyChangedMessage.create(this, this._name, "searchTerm"),
    );
    this._raisePropertyChanged("searchTerm");
  }

  canSearch(): boolean {
    return this.#search.canSearch();
  }

  search(): void {
    this.#search.search();
  }

  get isEmpty(): boolean {
    return this.#filtered.length === 0;
  }

  get pageLabel(): string {
    const count = Math.max(1, this.pageCount);
    return `Page ${this.currentPageIndex + 1} of ${count}`;
  }

  get isEmptyDerived(): DerivedProperty<boolean> {
    return this.#isEmptyDerived;
  }

  get pageLabelDerived(): DerivedProperty<string> {
    return this.#pageLabelDerived;
  }

  // ── IFilterable ──────────────────────────────────────────────────────────

  get filter(): ((vm: NoteVM) => boolean) | null {
    return this.#filter;
  }

  set filter(value: ((vm: NoteVM) => boolean) | null) {
    if (this.#filter === value) return;
    this.#filter = value;
    this.#recomputeFiltered();
  }

  canFilter(): boolean {
    return this.status === ConstructionStatus.Constructed;
  }

  get showStarredOnly(): boolean {
    return this.#showStarredOnly;
  }

  set showStarredOnly(value: boolean) {
    if (this.#showStarredOnly === value) return;
    this.#showStarredOnly = value;
    this._hub.send(
      PropertyChangedMessage.create(this, this._name, "showStarredOnly"),
    );
    this._raisePropertyChanged("showStarredOnly");
    this.#recomputeFiltered();
  }

  // ── IPageable ────────────────────────────────────────────────────────────

  get pageSize(): number {
    return this.#paged.pageSize;
  }

  set pageSize(value: number) {
    this.#paged.pageSize = value;
  }

  get currentPageIndex(): number {
    return this.#paged.currentPageIndex;
  }

  set currentPageIndex(value: number) {
    this.#paged.currentPageIndex = value;
  }

  get pageCount(): number {
    return this.#paged.pageCount;
  }

  get isPagingEnabled(): boolean {
    return this.#paged.isPagingEnabled;
  }

  moveToFirstPage(): void {
    this.#paged.moveToFirstPage();
  }

  moveToPreviousPage(): void {
    this.#paged.moveToPreviousPage();
  }

  moveToNextPage(): void {
    this.#paged.moveToNextPage();
  }

  moveToLastPage(): void {
    this.#paged.moveToLastPage();
  }

  get moveToFirstPageCommand(): ICommand {
    return this.#moveFirst;
  }

  get moveToPreviousPageCommand(): ICommand {
    return this.#movePrev;
  }

  get moveToNextPageCommand(): ICommand {
    return this.#moveNext;
  }

  get moveToLastPageCommand(): ICommand {
    return this.#moveLast;
  }

  // ── Current ─────────────────────────────────────────────────────────────

  get current(): NoteVM | null {
    return this.#current;
  }

  set current(value: NoteVM | null) {
    if (this.#current === value) return;
    this.#current = value;
    this._hub.send(
      PropertyChangedMessage.create(this, this._name, "current"),
    );
    this._raisePropertyChanged("current");
  }

  get boundNotebookId(): string | null {
    return this.#boundNotebookId;
  }

  /**
   * Readonly flag of the currently-bound notebook.
   *
   * Edge-case backfill: set by the host (e.g. `WorkspaceVM`) on notebook
   * selection. `CapabilityActionsVM.addNoteCommand` consults this so the
   * bar disables *Add Note* for readonly notebooks.
   */
  get currentNotebookIsReadonly(): boolean {
    return this.#currentNotebookIsReadonly;
  }

  set currentNotebookIsReadonly(value: boolean) {
    if (this.#currentNotebookIsReadonly === value) return;
    this.#currentNotebookIsReadonly = value;
    this._hub.send(
      PropertyChangedMessage.create(
        this,
        this._name,
        "currentNotebookIsReadonly",
      ),
    );
    this._raisePropertyChanged("currentNotebookIsReadonly");
  }

  // ── Binding ──────────────────────────────────────────────────────────────

  /**
   * Cancels any in-flight fetch, loads notes for the given notebook, and
   * replaces the inner items. Resets `current` and the page.
   */
  /** Refresh the list row for *note* after an external update (save):
   * re-seats the persisted model into the matching NoteVM and re-runs the
   * combined filter so row labels, the star marker, the starred filter,
   * and search results reflect the saved values. */
  refreshNote(note: NoteModel): void {
    const vm = this.#inner.find((n) => n.model.id === note.id);
    if (vm === undefined) return;
    vm.model = note;
    this.#recomputeFiltered();
  }

  async bindToAsync(notebookId: string): Promise<void> {
    this.#activeBindingToken += 1;
    const myToken = this.#activeBindingToken;
    const notes = await this.#repo.loadNotes(notebookId);
    if (myToken !== this.#activeBindingToken) return;
    this.#boundNotebookId = notebookId;
    this.#replaceItems(notes);
  }

  #replaceItems(notes: readonly NoteModel[]): void {
    for (const prev of this.#inner) prev.dispose();
    this.#inner.length = 0;
    for (const m of notes) {
      let builder = NoteVM.builder()
        .name(`note:${m.id}`)
        .model(m)
        .services(this._hub, this._dispatcher)
        .onDelete((vm) => this.#deleteNote(vm))
        // Real-wiring audit, pass 6: the capability bar projects
        // note.saveCommand/closeCommand, but nothing wired the handlers —
        // both actions were silent no-ops.
        .onClose((vm) => {
          if (this.#current === vm) this.current = null;
        })
        .onSave((vm) => {
          void this.#repo.saveNote(vm.model);
        });
      if (this.#dialogService !== null) {
        const dialog = this.#dialogService;
        builder = builder.confirmDelete((vm) =>
          dialog.confirm(`Delete “${vm.title}”?`, "Delete note"),
        );
      }
      if (this.#notificationHub !== null) {
        builder = builder.notificationHub(this.#notificationHub);
      }
      const vm = builder.build();
      vm.construct();
      this.#inner.push(vm);
    }
    this.#current = null;
    this._hub.send(
      PropertyChangedMessage.create(this, this._name, "current"),
    );
    this._raisePropertyChanged("current");
    this.#recomputeFiltered();
    this.#paged.moveToFirstPage();
  }

  #deleteNote(note: NoteVM): void {
    // Fire-and-forget: persist via the repo, then remove from the inner
    // collection. The "Note deleted" notification is posted by the NoteVM
    // itself (after the confirm gate, if any).
    void this.#deleteNoteAsync(note);
  }

  async #deleteNoteAsync(note: NoteVM): Promise<void> {
    try {
      await this.#repo.deleteNote(note.model.id);
    } catch {
      return;
    }
    const idx = this.#inner.indexOf(note);
    if (idx < 0) return;
    this.#inner.splice(idx, 1);
    if (this.#current === note) {
      this.#current = null;
      this._hub.send(
        PropertyChangedMessage.create(this, this._name, "current"),
      );
      this._raisePropertyChanged("current");
    }
    this.#recomputeFiltered();
    note.dispose();
  }

  #recomputeFiltered(): void {
    const term = this.#search.searchTerm.trim().toLowerCase();
    this.#filtered.length = 0;
    for (const n of this.#inner) {
      if (this.#showStarredOnly && !n.model.starred) continue;
      if (this.#filter !== null && !this.#filter(n)) continue;
      if (term.length > 0) {
        const haystack =
          (n.title + " " + n.body + " " + n.tags.join(" ")).toLowerCase();
        if (!haystack.includes(term)) continue;
      }
      this.#filtered.push(n);
    }
    for (const name of ["filteredItems", "isEmpty", "visibleItems", "pageLabel", "count"]) {
      this._hub.send(
        PropertyChangedMessage.create(this, this._name, name),
      );
      this._raisePropertyChanged(name);
    }
    this.#stateSubject.next();
  }

  protected override _onDestruct(): void {
    for (const prev of this.#inner) prev.dispose();
    this.#inner.length = 0;
    this.#filtered.length = 0;
    super._onDestruct();
  }

  protected override _onDispose(): void {
    this.#paged.dispose();
    this.#search.dispose();
    this.#stateSubject.complete();
    this.#isEmptyDerived.dispose();
    this.#pageLabelDerived.dispose();
    this.#moveFirst.dispose();
    this.#movePrev.dispose();
    this.#moveNext.dispose();
    this.#moveLast.dispose();
    super._onDispose();
  }

  static builder(): NotesViewVMBuilder {
    return new NotesViewVMBuilder();
  }
}

export class NotesViewVMBuilder {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #repo: INoteRepository | typeof SENTINEL = SENTINEL;
  #pageSize = 5;
  #searchDebounceMs = 150;
  #searchScheduler: SchedulerLike | null = null;
  #dialogService: IDialogService | null = null;
  #notificationHub: INotificationHub | null = null;

  constructor(from?: NotesViewVMBuilder) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#repo = from.#repo;
      this.#pageSize = from.#pageSize;
      this.#searchDebounceMs = from.#searchDebounceMs;
      this.#searchScheduler = from.#searchScheduler;
      this.#dialogService = from.#dialogService;
      this.#notificationHub = from.#notificationHub;
    }
  }

  name(value: string): NotesViewVMBuilder {
    const b = new NotesViewVMBuilder(this);
    b.#name = value;
    return b;
  }

  hint(value: string): NotesViewVMBuilder {
    const b = new NotesViewVMBuilder(this);
    b.#hint = value;
    return b;
  }

  services(hub: IMessageHub, dispatcher: IDispatcher): NotesViewVMBuilder {
    const b = new NotesViewVMBuilder(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  repository(repo: INoteRepository): NotesViewVMBuilder {
    const b = new NotesViewVMBuilder(this);
    b.#repo = repo;
    return b;
  }

  pageSize(value: number): NotesViewVMBuilder {
    const b = new NotesViewVMBuilder(this);
    b.#pageSize = value;
    return b;
  }

  searchDebounceMs(value: number): NotesViewVMBuilder {
    const b = new NotesViewVMBuilder(this);
    b.#searchDebounceMs = value;
    return b;
  }

  searchScheduler(scheduler: SchedulerLike): NotesViewVMBuilder {
    const b = new NotesViewVMBuilder(this);
    b.#searchScheduler = scheduler;
    return b;
  }

  dialogService(service: IDialogService): NotesViewVMBuilder {
    const b = new NotesViewVMBuilder(this);
    b.#dialogService = service;
    return b;
  }

  notificationHub(hub: INotificationHub): NotesViewVMBuilder {
    const b = new NotesViewVMBuilder(this);
    b.#notificationHub = hub;
    return b;
  }

  build(): NotesViewVM {
    if (this.#name === null) throw new Error("name is required");
    if (this.#hub === null || this.#dispatcher === null)
      throw new Error("services (hub + dispatcher) are required");
    if (this.#repo === SENTINEL) throw new Error("repository is required");
    return new NotesViewVM({
      name: this.#name,
      hint: this.#hint,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      repository: this.#repo,
      pageSize: this.#pageSize,
      searchDebounceMs: this.#searchDebounceMs,
      ...(this.#searchScheduler !== null
        ? { searchScheduler: this.#searchScheduler }
        : {}),
      dialogService: this.#dialogService,
      notificationHub: this.#notificationHub,
    });
  }
}
