/**
 * NotebooksRootVM — root of the notebooks tree.
 *
 * VMx-API adaptation (parity with C# / Python flavors): the plan asked for
 * `HierarchicalVM<NotebookModel, NotebookVM>`, but VMx TS's
 * `HierarchicalVM` sources each node's children from a per-node factory
 * (materialized lazily on first access, not eagerly at construct time) and
 * lacks the "current selection" / "walk" surface the showcase needs.
 * We own a flat collection and expose roots / children-of / walk over it.
 * `addNotebookAsync` persists via the repo and publishes a
 * `TreeStructureChangedMessage` so subscribers observe structural changes
 * the same way they would on a `HierarchicalVM`.
 */
import {
  ComponentVMBase,
  ConstructionStatus,
  declareCapabilities,
  RelayCommand,
  TreeStructureChangedMessage,
  ViewModelType,
  type ICommand,
  type IDispatcher,
  type IMessageHub,
} from "@thekaveh/vmx";
import {
  type INotificationHub,
  Notification,
  NotificationType,
} from "@thekaveh/vmx/notifications";

import type { NotebookModel } from "../models/notebookModel.js";
import type { INoteRepository } from "../models/noteRepository.js";
import { NotebookVM } from "./notebookVM.js";

const SENTINEL = Symbol("not-set");

let counter = 0;
function newNotebookId(): string {
  counter += 1;
  return `nb-new-${Date.now().toString(36)}-${counter}`;
}

export class NotebooksRootVM extends ComponentVMBase {
  readonly #repo: INoteRepository;
  readonly #notificationHub: INotificationHub | null;
  readonly #all: NotebookVM[] = [];
  readonly #addNotebookCommand: RelayCommand;
  #current: NotebookVM | null = null;

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
    declareCapabilities(this, "INewCreatable", "IReconstructable");

    this.#addNotebookCommand = RelayCommand.builder()
      .predicate(() => this.canCreateNew())
      .task(() => {
        void this.addNotebookAsync(null, "New Notebook");
      })
      .build();
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get hub(): IMessageHub {
    return this._hub;
  }

  /** All notebooks (flat, ordered). */
  get all(): readonly NotebookVM[] {
    return this.#all;
  }

  /** Root notebooks (no parent). */
  get roots(): NotebookVM[] {
    return this.#all.filter((nb) => nb.model.parentId === null);
  }

  /** Iterates every notebook in repository order. */
  walk(): Iterable<NotebookVM> {
    return this.#all.slice();
  }

  /** Returns the children of the given notebook (matched by parentId). */
  childrenOf(parent: NotebookVM): NotebookVM[] {
    return this.#all.filter((nb) => nb.model.parentId === parent.model.id);
  }

  /** Currently selected notebook (two-way bindable). */
  get current(): NotebookVM | null {
    return this.#current;
  }

  set current(value: NotebookVM | null) {
    if (this.#current === value) return;
    this.#current = value;
    this._notifyPropertyChanged("current");
  }

  // ── INewCreatable ─────────────────────────────────────────────────────────

  canCreateNew(): boolean {
    return this.status === ConstructionStatus.Constructed;
  }

  createNew(): void {
    void this.addNotebookAsync(null, "New Notebook");
  }

  get addNotebookCommand(): ICommand {
    return this.#addNotebookCommand;
  }

  /**
   * Persists a new notebook via the repo and publishes a
   * `TreeStructureChangedMessage("added")` so subscribers refresh.
   */
  async addNotebookAsync(parentId: string | null, name: string): Promise<void> {
    const model: NotebookModel = { id: newNotebookId(), name, parentId };
    await this.#repo.addNotebook(model);
    const vm = NotebookVM.builder()
      .name(`nb:${model.id}`)
      .model(model)
      .services(this._hub, this._dispatcher)
      .build();
    vm.construct();
    this.#all.push(vm);
    // Real-wiring audit, pass 6: useVm re-renders only on
    // PropertyChangedMessage — TreeStructureChangedMessage alone left the
    // new notebook invisible until the next unrelated re-render.
    this._notifyPropertyChanged("roots");
    this._hub.send(
      new TreeStructureChangedMessage(
        this,
        this._name,
        "added",
        vm,
        this.#all.length - 1,
      ),
    );
    // Spec §6.2: publish a "Notebook added" notification (cross-flavor parity
    // with the C# and Python flavors). No-op when no notification hub is
    // wired (e.g. in unit tests that don't care about toast feedback).
    if (this.#notificationHub !== null) {
      void this.#notificationHub.post(
        new Notification(NotificationType.Notification, `Notebook added: “${name}”`),
      );
    }
  }

  /**
   * Loads notebooks from the repository and constructs each child VM.
   * Called by `WorkspaceVM` during async construct.
   */
  async populateAsync(): Promise<void> {
    const { notebooks } = await this.#repo.loadAll();
    for (const prev of this.#all) prev.dispose();
    this.#all.length = 0;
    this.#current = null;

    for (const nb of notebooks) {
      const vm = NotebookVM.builder()
        .name(`nb:${nb.id}`)
        .model(nb)
        .services(this._hub, this._dispatcher)
        .build();
      vm.construct();
      this.#all.push(vm);
    }

    this._hub.send(
      new TreeStructureChangedMessage(this, this._name, "added", this, -1),
    );
  }

  protected override _onDestruct(): void {
    for (const nb of this.#all) nb.destruct();
    super._onDestruct();
  }

  protected override _onDispose(): void {
    for (const nb of this.#all) nb.dispose();
    this.#addNotebookCommand.dispose();
    super._onDispose();
  }

  static builder(): NotebooksRootVMBuilder {
    return new NotebooksRootVMBuilder();
  }
}

export class NotebooksRootVMBuilder {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #repo: INoteRepository | typeof SENTINEL = SENTINEL;
  #notificationHub: INotificationHub | null = null;

  constructor(from?: NotebooksRootVMBuilder) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#repo = from.#repo;
      this.#notificationHub = from.#notificationHub;
    }
  }

  name(value: string): NotebooksRootVMBuilder {
    const b = new NotebooksRootVMBuilder(this);
    b.#name = value;
    return b;
  }

  hint(value: string): NotebooksRootVMBuilder {
    const b = new NotebooksRootVMBuilder(this);
    b.#hint = value;
    return b;
  }

  services(hub: IMessageHub, dispatcher: IDispatcher): NotebooksRootVMBuilder {
    const b = new NotebooksRootVMBuilder(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  repository(repo: INoteRepository): NotebooksRootVMBuilder {
    const b = new NotebooksRootVMBuilder(this);
    b.#repo = repo;
    return b;
  }

  notificationHub(hub: INotificationHub): NotebooksRootVMBuilder {
    const b = new NotebooksRootVMBuilder(this);
    b.#notificationHub = hub;
    return b;
  }

  build(): NotebooksRootVM {
    if (this.#name === null) throw new Error("name is required");
    if (this.#hub === null || this.#dispatcher === null)
      throw new Error("services (hub + dispatcher) are required");
    if (this.#repo === SENTINEL) throw new Error("repository is required");
    return new NotebooksRootVM({
      name: this.#name,
      hint: this.#hint,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      repository: this.#repo,
      notificationHub: this.#notificationHub,
    });
  }
}
