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
import { BehaviorSubject, filter, type Subscription } from "rxjs";
import {
  AggregateVM6,
  DerivedProperty,
  MessageHub,
  PropertyChangedMessage,
  RelayCommand,
  RxDispatcher,
  type ICommand,
  type IDispatcher,
  type IMessageHub,
} from "vmx";
import {
  type INotificationHub,
  NotificationHub,
} from "vmx/notifications";

import type { NoteModel } from "../models/noteModel.js";
import type { INoteRepository } from "../models/noteRepository.js";
import { CapabilityActionsVM } from "./capabilityActionsVM.js";
import { type IDialogService, NullDialogService } from "./dialogService.js";
import { NoteFormVM } from "./noteFormVM.js";
import { NotebooksRootVM } from "./notebooksRootVM.js";
import { NotesViewVM } from "./notesViewVM.js";
import { NotificationsVM } from "./notificationsVM.js";
import { StatusBarVM } from "./statusBarVM.js";

const SENTINEL = Symbol("not-set");

let noteCounter = 0;
function newNoteId(): string {
  noteCounter += 1;
  return `note-new-${Date.now().toString(36)}-${noteCounter}`;
}

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
  // changes. The React `NotesList` view also calls `noteForm.bindTo`
  // directly on select; the VM-level subscription ensures behavior parity
  // with the C# / Python flavors and survives any host that does not
  // re-implement that bridging step.
  readonly #currentNoteSubscription: Subscription;

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
    const notesViewRef = this.#notesView;
    const noteFormRef = this.#noteForm;
    this.#currentNoteSubscription = notesViewRef.hub.messages
      .pipe(
        filter(
          (m): m is PropertyChangedMessage<unknown> =>
            m instanceof PropertyChangedMessage &&
            m.sender === notesViewRef &&
            m.propertyName === "current",
        ),
      )
      .subscribe(() => {
        const current = notesViewRef.current;
        if (current !== null) {
          noteFormRef.bindTo(current.model);
        }
      });

    this.#newNotebookCommand = RelayCommand.builder()
      .predicate(() => this.isConstructed)
      .task(() => {
        void this.#notebooks.addNotebookAsync(null, "New Notebook");
      })
      .build();
    this.#newNoteCommand = RelayCommand.builder()
      .predicate(() => this.isConstructed && this.#notebooks.current !== null)
      .task(() => {
        void this.#addNewNoteToCurrentAsync();
      })
      .build();
    this.#exportCommand = RelayCommand.builder()
      .predicate(() => this.isConstructed)
      .task(() => {
        void this.#exportInternalAsync();
      })
      .build();
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
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  construct(): void {
    this.#aggregate.construct();
  }

  /**
   * Async construct: builds the aggregate, populates notebooks, sets the
   * first root as current, and binds the notes view to it.
   */
  async constructAsync(): Promise<void> {
    this.#aggregate.construct();
    await this.#notebooks.populateAsync();
    const [first] = this.#notebooks.roots;
    if (first !== undefined) {
      this.#notebooks.current = first;
      this.setFocus(first);
      await this.#notesView.bindToAsync(first.model.id);
    }
  }

  destruct(): void {
    this.#aggregate.destruct();
  }

  dispose(): void {
    this.#currentNoteSubscription.unsubscribe();
    this.#focusedVMDerived.dispose();
    this.#focusSubject.complete();
    this.#newNotebookCommand.dispose();
    this.#newNoteCommand.dispose();
    this.#exportCommand.dispose();
    this.#aggregate.dispose();
  }

  // ── Internal command implementations ──────────────────────────────────────

  async #addNewNoteToCurrentAsync(): Promise<void> {
    const nb = this.#notebooks.current;
    if (nb === null) return;
    const now = new Date().toISOString();
    const note: NoteModel = {
      id: newNoteId(),
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
