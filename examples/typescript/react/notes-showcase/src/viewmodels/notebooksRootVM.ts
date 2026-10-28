/**
 * NotebooksRootVM — root of the notebooks tree.
 *
 * The notebooks form a `HierarchicalVM<NotebookModel, NotebookVM>` tree under
 * a hidden root node, whose children are the top-level notebooks. Each
 * node's children factory reads the repository models by `parentId`. A
 * `TreeSelection` on the hidden root holds the current notebook (spec/18
 * §10): it rejects a notebook outside the tree and clears itself when the
 * current notebook leaves it. `addNotebookAsync` persists via the repo,
 * attaches the node with `addChild`, and also publishes a root-level
 * `TreeStructureChangedMessage`.
 */
import {
  AsyncRelayCommand,
  ComponentVMBase,
  ConstructionStatus,
  declareCapabilities,
  TreeSelection,
  TreeStructureChangedMessage,
  ViewModelType,
  type ICommand,
  type IDispatcher,
  type IMessageHub,
} from "@thekaveh/vmx";
import type { Subscription } from "rxjs";
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
  readonly #addNotebookCommand: AsyncRelayCommand;
  /** Repository models; the children factory reads them by `parentId`. */
  #models: readonly NotebookModel[] = [];
  /** Hidden root node; its children are the top-level notebooks. */
  readonly #tree: NotebookVM;
  readonly #selection: TreeSelection<NotebookVM>;
  readonly #currentForwarding: Subscription;

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

    this.#tree = this.#buildNode({ id: "", name: "", parentId: null });
    this.#selection = new TreeSelection<NotebookVM>(this.#tree);
    // The helper publishes nothing to the hub; this VM forwards its changes
    // (spec/14 rule 6).
    this.#currentForwarding = this.#selection.currentChanged.subscribe(() => {
      this._notifyPropertyChanged("current");
    });

    this.#addNotebookCommand = AsyncRelayCommand.builder()
      .predicate(() => this.canCreateNew())
      .task(async () => { await this.addNotebookAsync(null, "New Notebook"); })
      .build();
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get hub(): IMessageHub {
    return this._hub;
  }

  /**
   * All notebooks, depth first (parents before children). `populateAsync`
   * already loads every level, and a node caches its children, so a later
   * call walks cached lists; only a node added since then runs its children
   * factory, once.
   */
  get all(): readonly NotebookVM[] {
    const nodes: NotebookVM[] = [];
    const visit = (parent: NotebookVM): void => {
      for (const child of parent.children) {
        nodes.push(child);
        visit(child);
      }
    };
    visit(this.#tree);
    return nodes;
  }

  /** Root notebooks (children of the hidden root node). */
  get roots(): NotebookVM[] {
    return [...this.#tree.children];
  }

  /** Iterates every notebook, depth first. */
  walk(): Iterable<NotebookVM> {
    return this.all;
  }

  /** Returns the children of the given notebook. */
  childrenOf(parent: NotebookVM): NotebookVM[] {
    return [...parent.children];
  }

  /**
   * Currently selected notebook (two-way bindable). Setting a notebook that
   * is not in the tree throws, and the value becomes null by itself when the
   * current notebook leaves the tree.
   */
  get current(): NotebookVM | null {
    return this.#selection.current;
  }

  set current(value: NotebookVM | null) {
    if (value === null) {
      this.#selection.clear();
      return;
    }
    if (value === this.#tree) throw new Error("The hidden tree root is not a notebook");
    this.#selection.select(value);
  }

  /**
   * True when `nb` is a notebook of the current tree: not the hidden root, not
   * a node dropped by `populateAsync`, and not disposed.
   */
  canSelectNotebook(nb: NotebookVM): boolean {
    return nb !== this.#tree && this.#selection.canSelect(nb);
  }

  /** True when `nb` is a strict ancestor of the current notebook. */
  isAncestorOfCurrent(nb: NotebookVM): boolean {
    const current = this.#selection.current;
    return current !== null && current !== nb && current.path.includes(nb);
  }

  // ── INewCreatable ─────────────────────────────────────────────────────────

  canCreateNew(): boolean {
    return this.status === ConstructionStatus.Constructed;
  }

  createNew(): void {
    this.#addNotebookCommand.execute();
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
    const parent = parentId === null
      ? this.#tree
      : this.all.find((nb) => nb.model.id === parentId);
    if (parent === undefined) throw new Error(`Unknown parent notebook '${parentId ?? ""}'`);
    const vm = this.#buildNode(model);
    vm.construct();
    // Attach before recording the model: `addChild` materializes the parent's
    // children from `#models` first, which must not yet contain this model.
    parent.addChild(vm);
    this.#models = [...this.#models, model];
    // Live-binding invariant: useVm re-renders only on
    // PropertyChangedMessage — TreeStructureChangedMessage alone left the
    // new notebook invisible until the next unrelated re-render.
    this._notifyPropertyChanged("roots");
    this._hub.send(
      new TreeStructureChangedMessage(
        this,
        this._name,
        "added",
        vm,
        parent.children.length - 1,
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
    const previous = this.all;
    this.#models = notebooks;
    // Dropping the cache detaches the old nodes, so the selection clears.
    this.#tree.invalidateChildren();
    for (const prev of previous) prev.dispose();
    for (const nb of this.all) nb.construct();

    this._hub.send(
      new TreeStructureChangedMessage(this, this._name, "added", this, -1),
    );
  }

  protected override _onDestruct(): void {
    for (const nb of this.all) nb.destruct();
    super._onDestruct();
  }

  protected override _onDispose(): void {
    this.#currentForwarding.unsubscribe();
    this.#selection.dispose();
    // Node disposal does not cascade (spec/18 §3), so dispose every node.
    for (const nb of this.all) nb.dispose();
    this.#tree.dispose();
    this.#addNotebookCommand.dispose();
    super._onDispose();
  }

  #buildNode(model: NotebookModel): NotebookVM {
    return NotebookVM.builder()
      .name(model.id === "" ? "nb:root" : `nb:${model.id}`)
      .model(model)
      .services(this._hub, this._dispatcher)
      .childrenFactory((parent) => this.#models
        .filter((nb) => nb.parentId === (parent === this.#tree ? null : parent.model.id))
        .map((nb) => this.#buildNode(nb)))
      .build();
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
