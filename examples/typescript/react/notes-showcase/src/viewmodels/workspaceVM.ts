/**
 * WorkspaceVM — root VM for the Notes Workspace.
 *
 * VMx-API adaptation (mirrors C# / Python flavors): instead of subclassing
 * `AggregateVM6`, this VM composes one and exposes `notebooksRoot`,
 * `notesView`, `noteForm`, `statusBar`, `notifications`, and
 * `capabilityActions` as direct accessors. Lifecycle delegates to the inner
 * aggregate — the cascade rules of ADR-0034 still apply, via composition.
 *
 * Adds the toolbar commands (`newNotebookCommand`, `newNoteCommand`,
 * `exportCommand`) and the `focusedVM` derivation (which feeds
 * `CapabilityActionsVM`).
 */
import { BehaviorSubject, Subject, observeOn, type Subscription } from "rxjs";
import {
  AggregateVM6,
  DerivedProperty,
  MessageHub,
  RelayCommand,
  RxDispatcher,
  whenPropertyChanged,
  type ICommand,
  type IDispatcher,
  type IMessageHub,
} from "@thekaveh/vmx";
import {
  type INotificationHub,
  NotificationHub,
} from "@thekaveh/vmx/notifications";

import type { NoteModel } from "../models/noteModel.js";
import type { NotebookVM } from "./notebookVM.js";
import type { INoteRepository } from "../models/noteRepository.js";
import { CapabilityActionsVM } from "./capabilityActionsVM.js";
import { type IDialogService, NullDialogService } from "./dialogService.js";
import { NoteFormVM } from "./noteFormVM.js";
import { NotebooksRootVM } from "./notebooksRootVM.js";
import { NotesViewVM } from "./notesViewVM.js";
import { NotificationsVM } from "./notificationsVM.js";
import { StatusBarVM } from "./statusBarVM.js";
import { ThemeVM } from "./themeVM.js";

const SENTINEL = Symbol("not-set");

export class WorkspaceVM {
  readonly #repo: INoteRepository;
  readonly #dialogService: IDialogService;
  readonly #hub: IMessageHub;
  readonly #notebooks: NotebooksRootVM;
  readonly #notesView: NotesViewVM;
  readonly #noteForm: NoteFormVM;
  readonly #statusBar: StatusBarVM;
  readonly #notifications: NotificationsVM;
  readonly #capabilityActions: CapabilityActionsVM;
  // VMX-129: the theme seam is a workspace-owned sibling of the six aggregate
  // children (an AggregateVM7 was declined in ADR-0058). Lifecycle is driven
  // alongside the aggregate; the React `useThemeAdapter` hook binds to it.
  readonly #theme: ThemeVM;
  #noteCounter = 0;
  readonly #aggregate: AggregateVM6<
    NotebooksRootVM,
    NotesViewVM,
    NoteFormVM,
    StatusBarVM,
    NotificationsVM,
    CapabilityActionsVM
  >;

  readonly #newNotebookCommand: RelayCommand;
  readonly #newNoteCommand: RelayCommand;
  readonly #exportCommand: RelayCommand;

  // Round-3 Critical-2 parity: rebind noteForm whenever notesView.current
  // changes. The VM-level subscription is the single bridge — views set
  // `notesView.current` and everything downstream flows from here.
  readonly #currentNoteSubscription: Subscription;
  readonly #savedNoteSubscription: Subscription;
  // Pushed whenever toolbar-command predicates may have flipped
  // (construct completes, notebook selection changes) — without a trigger
  // the commands' canExecuteChanged never fires and useCommand's disabled
  // mirror stays frozen at first render (real-wiring audit, pass 6).
  readonly #commandTrigger = new Subject<void>();

  readonly #focusSubject: BehaviorSubject<object | null>;
  readonly #focusedVMDerived: DerivedProperty<object | null>;
  #focused: object | null = null;

  constructor(opts: {
    name: string;
    hint: string;
    repository: INoteRepository;
    dialogService: IDialogService;
    notificationHub: INotificationHub;
    hub: IMessageHub;
    dispatcher: IDispatcher;
  }) {
    this.#repo = opts.repository;
    this.#dialogService = opts.dialogService;
    this.#hub = opts.hub;

    this.#notebooks = NotebooksRootVM.builder()
      .name("notebooks")
      .services(opts.hub, opts.dispatcher)
      .repository(opts.repository)
      .notificationHub(opts.notificationHub)
      .build();
    this.#notesView = NotesViewVM.builder()
      .name("notes")
      .services(opts.hub, opts.dispatcher)
      .repository(opts.repository)
      .pageSize(5)
      .searchDebounceMs(150)
      .dialogService(opts.dialogService)
      .notificationHub(opts.notificationHub)
      .build();
    this.#noteForm = NoteFormVM.builder()
      .name("form")
      .services(opts.hub, opts.dispatcher)
      .repository(opts.repository)
      .notificationHub(opts.notificationHub)
      .build();
    this.#statusBar = StatusBarVM.builder()
      .name("status")
      .services(opts.hub, opts.dispatcher)
      .notesView(this.#notesView)
      .notebooks(this.#notebooks)
      .noteForm(this.#noteForm)
      .build();
    this.#notifications = NotificationsVM.builder()
      .name("notifications")
      .services(opts.hub, opts.dispatcher)
      .notificationHub(opts.notificationHub)
      .build();
    this.#capabilityActions = CapabilityActionsVM.builder()
      .name("capabilities")
      .services(opts.hub, opts.dispatcher)
      .focusedGetter(() => this.#focused)
      // Edge-case backfill (readonly notebook gating): the bar's *Add Note*
      // command is gated on the currently-bound notebook's readonly flag
      // (mirrored into notesView by this VM on selection change), and on
      // the workspace being constructed with a current notebook.
      .canAddNote(
        () =>
          this.isConstructed &&
          this.#notebooks.current !== null &&
          !this.#notesView.currentNotebookIsReadonly,
      )
      .addNoteAction(() => {
        void this.#addNewNoteToCurrentAsync();
      })
      .build();

    this.#aggregate = AggregateVM6.builder<
      NotebooksRootVM,
      NotesViewVM,
      NoteFormVM,
      StatusBarVM,
      NotificationsVM,
      CapabilityActionsVM
    >()
      .name(opts.name)
      .hint(opts.hint)
      .services(opts.hub, opts.dispatcher)
      .component1(() => this.#notebooks)
      .component2(() => this.#notesView)
      .component3(() => this.#noteForm)
      .component4(() => this.#statusBar)
      .component5(() => this.#notifications)
      .component6(() => this.#capabilityActions)
      .build();

    // VMX-129: build the workspace-owned theme seam on the shared services.
    this.#theme = new ThemeVM({
      name: "theme",
      hint: "",
      hub: opts.hub,
      dispatcher: opts.dispatcher,
    });

    this.#focusSubject = new BehaviorSubject<object | null>(null);
    this.#focusedVMDerived = new DerivedProperty<object | null>(
      this.#focusSubject.asObservable(),
      null,
      null,
    );

    // Round-3 Critical-2: subscribe to notesView "current" PropertyChanged
    // and rebind the note form. Captures locals so we don't reference
    // `this.#notesView` / `this.#noteForm` before they're assigned during
    // the rest of the constructor.
    //
    // Round-4 Important-1: when current transitions to null (e.g. the
    // selected note is deleted in NotesViewVM.#deleteNoteAsync) the form
    // must be unbound — otherwise the right pane keeps the deleted note's
    // title/body and approve would persist a ghost.
    //
    // Round-4 Important-2: marshal delivery onto the foreground scheduler
    // so bindTo / unbind (which raise PropertyChanged for React subscribers
    // via useSyncExternalStore) always run on the rendering thread. Today
    // current is set from React click handlers (already main-thread) so
    // this is defensive, but matches the foreground-marshal contract the
    // spec requires for PropertyChanged delivery (THR-001 parity).
    const notesViewRef = this.#notesView;
    const noteFormRef = this.#noteForm;
    // VMX-017: the typed `whenPropertyChanged` hub helper replaces the
    // hand-rolled `filter(instanceof + sender === + propertyName)` filter.
    this.#currentNoteSubscription = whenPropertyChanged(
      notesViewRef.hub,
      notesViewRef,
      "current",
    )
      .pipe(observeOn(opts.dispatcher.foreground))
      .subscribe(() => {
        const current = notesViewRef.current;
        if (current !== null) {
          noteFormRef.bindTo(current.model);
        } else {
          noteFormRef.unbind();
        }
      });

    // Real-wiring audit, pass 6: refresh the saved note's list row (title /
    // star were construction-time snapshots and went stale after every
    // save). Mirrors the Python flagship's on_saved → refresh_note wiring.
    this.#savedNoteSubscription = this.#noteForm.onSaved
      .pipe(observeOn(opts.dispatcher.foreground))
      .subscribe((saved) => {
        notesViewRef.refreshNote(saved);
      });

    this.#newNotebookCommand = RelayCommand.builder()
      .predicate(() => this.isConstructed)
      .task(() => {
        void this.#notebooks.addNotebookAsync(null, "New Notebook");
      })
      .triggers(this.#commandTrigger)
      .build();
    this.#newNoteCommand = RelayCommand.builder()
      .predicate(() => this.isConstructed && this.#notebooks.current !== null)
      .task(() => {
        void this.#addNewNoteToCurrentAsync();
      })
      .triggers(this.#commandTrigger)
      .build();
    this.#exportCommand = RelayCommand.builder()
      .predicate(() => this.isConstructed)
      .task(() => {
        void this.#exportInternalAsync();
      })
      .triggers(this.#commandTrigger)
      .build();
  }

  /**
   * Selects *nb* as the current notebook: updates the tree selection,
   * focus, the readonly mirror the capability bar gates on, and rebinds
   * the notes view. The single entry the tree view calls — the readonly
   * mirror was previously set only at construct time, so capability
   * gating went stale on every selection change (real-wiring audit,
   * pass 6).
   */
  selectNotebook(nb: NotebookVM): void {
    this.#notebooks.current = nb;
    this.setFocus(nb);
    this.#notesView.currentNotebookIsReadonly = nb.model.isReadonly ?? false;
    void this.#notesView.bindToAsync(nb.model.id);
  }

  // ── Component accessors ───────────────────────────────────────────────────

  get notebooksRoot(): NotebooksRootVM {
    return this.#notebooks;
  }

  get notesView(): NotesViewVM {
    return this.#notesView;
  }

  get noteForm(): NoteFormVM {
    return this.#noteForm;
  }

  get statusBar(): StatusBarVM {
    return this.#statusBar;
  }

  get notifications(): NotificationsVM {
    return this.#notifications;
  }

  get capabilityActions(): CapabilityActionsVM {
    return this.#capabilityActions;
  }

  /**
   * Theme seam (THEME-001..005). Workspace-owned, not an aggregate child —
   * the React `useThemeAdapter` hook binds to it so the scenario is exercised
   * in the running app (VMX-129).
   */
  get theme(): ThemeVM {
    return this.#theme;
  }

  get hub(): IMessageHub {
    return this.#hub;
  }

  get isConstructed(): boolean {
    return this.#aggregate.isConstructed;
  }

  get newNotebookCommand(): ICommand {
    return this.#newNotebookCommand;
  }

  get newNoteCommand(): ICommand {
    return this.#newNoteCommand;
  }

  get exportCommand(): ICommand {
    return this.#exportCommand;
  }

  get focusedVM(): DerivedProperty<object | null> {
    return this.#focusedVMDerived;
  }

  // ── Focus tracking ────────────────────────────────────────────────────────

  setFocus(focused: object | null): void {
    if (this.#focused === focused) return;
    this.#focused = focused;
    this.#focusSubject.next(focused);
    this.#capabilityActions.recomputeActions();
    this.#commandTrigger.next();
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  construct(): void {
    this.#aggregate.construct();
    this.#theme.construct();
  }

  /**
   * Async construct: builds the aggregate, populates notebooks, sets the
   * first root as current, and binds the notes view to it.
   */
  async constructAsync(): Promise<void> {
    this.#aggregate.construct();
    this.#theme.construct();
    await this.#notebooks.populateAsync();
    const [first] = this.#notebooks.roots;
    if (first !== undefined) {
      this.#notebooks.current = first;
      this.setFocus(first);
      // Edge-case backfill (readonly notebook gating): mirror the
      // notebook's readonly flag into notesView so
      // CapabilityActionsVM.addNoteCommand observes it.
      this.#notesView.currentNotebookIsReadonly =
        first.model.isReadonly ?? false;
      await this.#notesView.bindToAsync(first.model.id);
    }
    this.#commandTrigger.next();
  }

  destruct(): void {
    this.#theme.destruct();
    this.#aggregate.destruct();
  }

  dispose(): void {
    this.#currentNoteSubscription.unsubscribe();
    this.#savedNoteSubscription.unsubscribe();
    this.#commandTrigger.complete();
    this.#focusedVMDerived.dispose();
    this.#focusSubject.complete();
    this.#newNotebookCommand.dispose();
    this.#newNoteCommand.dispose();
    this.#exportCommand.dispose();
    this.#theme.dispose();
    this.#aggregate.dispose();
  }

  // ── Internal command implementations ──────────────────────────────────────

  #newNoteId(): string {
    this.#noteCounter += 1;
    return `note-new-${Date.now().toString(36)}-${this.#noteCounter}`;
  }

  async #addNewNoteToCurrentAsync(): Promise<void> {
    const nb = this.#notebooks.current;
    if (nb === null) return;
    const now = new Date().toISOString();
    const note: NoteModel = {
      id: this.#newNoteId(),
      notebookId: nb.model.id,
      title: "Untitled",
      tags: [],
      body: "",
      starred: false,
      createdAt: now,
      updatedAt: now,
    };
    await this.#repo.saveNote(note);
    await this.#notesView.bindToAsync(nb.model.id);
  }

  async #exportInternalAsync(): Promise<void> {
    const path = await this.#dialogService.pickFileToSave(
      null,
      "Export workspace",
      "notes-export.json",
    );
    if (path === null || path.length === 0) return;
    const { notebooks, notes } = await this.#repo.loadAll();
    await this.#repo.export(notebooks, notes, path);
  }

  static builder(): WorkspaceVMBuilder {
    return new WorkspaceVMBuilder();
  }
}

export class WorkspaceVMBuilder {
  #name = "workspace";
  #hint = "";
  #repo: INoteRepository | typeof SENTINEL = SENTINEL;
  #dialogService: IDialogService | null = null;
  #notificationHub: INotificationHub | null = null;
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;

  constructor(from?: WorkspaceVMBuilder) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#repo = from.#repo;
      this.#dialogService = from.#dialogService;
      this.#notificationHub = from.#notificationHub;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
    }
  }

  name(value: string): WorkspaceVMBuilder {
    const b = new WorkspaceVMBuilder(this);
    b.#name = value;
    return b;
  }

  hint(value: string): WorkspaceVMBuilder {
    const b = new WorkspaceVMBuilder(this);
    b.#hint = value;
    return b;
  }

  repository(repo: INoteRepository): WorkspaceVMBuilder {
    const b = new WorkspaceVMBuilder(this);
    b.#repo = repo;
    return b;
  }

  dialogService(service: IDialogService): WorkspaceVMBuilder {
    const b = new WorkspaceVMBuilder(this);
    b.#dialogService = service;
    return b;
  }

  notificationHub(hub: INotificationHub): WorkspaceVMBuilder {
    const b = new WorkspaceVMBuilder(this);
    b.#notificationHub = hub;
    return b;
  }

  messageHub(hub: IMessageHub): WorkspaceVMBuilder {
    const b = new WorkspaceVMBuilder(this);
    b.#hub = hub;
    return b;
  }

  dispatcher(dispatcher: IDispatcher): WorkspaceVMBuilder {
    const b = new WorkspaceVMBuilder(this);
    b.#dispatcher = dispatcher;
    return b;
  }

  build(): WorkspaceVM {
    if (this.#repo === SENTINEL) throw new Error("repository is required");
    return new WorkspaceVM({
      name: this.#name,
      hint: this.#hint,
      repository: this.#repo,
      dialogService: this.#dialogService ?? NullDialogService.INSTANCE,
      notificationHub: this.#notificationHub ?? new NotificationHub(),
      hub: this.#hub ?? new MessageHub(),
      dispatcher: this.#dispatcher ?? RxDispatcher.immediate(),
    });
  }
}
