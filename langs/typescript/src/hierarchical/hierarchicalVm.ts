/**
 * HierarchicalVM<TModel, TVM> — first-class recursive tree ViewModel.
 *
 * Each node carries a typed TModel and may contain children of the same
 * concrete type TVM. Children are lazy by default; eager materialization is
 * opt-in via the eagerChildren constructor option.
 *
 * See spec/18-hierarchical-vm.md and ADR-0028.
 */
import { BuilderValidationError } from "../builders/exceptions.js";
import { ComponentVMBase } from "../components/componentVMBase.js";
import { ViewModelType } from "../components/types.js";
import { PropertyChangedMessage } from "../messages/propertyChanged.js";
import {
  TreeStructureChangedMessage,
  type TreeStructureChange,
} from "../messages/treeStructureChanged.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
import { MessageHub } from "../services/messageHub.js";
import { RxDispatcher } from "../services/dispatcher.js";

/** Options for constructing a HierarchicalVM node. */
export interface HierarchicalVMOptions<TModel, TVM> {
  model: TModel;
  childrenFactory: (parent: TVM) => Iterable<TVM>;
  hub?: IMessageHub;
  dispatcher?: IDispatcher;
  name?: string;
  hint?: string;
  /** When true, the full subtree is materialized at construct() time (depth-first). */
  eagerChildren?: boolean;
}

/** Missing-parent retention policy for {@link HierarchicalVM.attachMany}. */
export enum MissingParentPolicy {
  Park = "park",
  Reject = "reject",
}

/** Typed reason why one batch item was not attached. */
export enum BatchAttachRejectionReason {
  DuplicateExistingKey = "duplicate_existing_key",
  DuplicateBatchKey = "duplicate_batch_key",
  AlreadyAttached = "already_attached",
  MissingParent = "missing_parent",
  Cycle = "cycle",
  SelectorFailed = "selector_failed",
  AttachmentFailed = "attachment_failed",
}

export interface BatchAttachOptions<TVM, TKey> {
  keyOf: (item: TVM) => TKey;
  /** A null parent key attaches the item directly beneath the structural root. */
  parentKeyOf: (item: TVM) => TKey | null;
  onMissingParent?: MissingParentPolicy;
}

export interface BatchAttachRejection<TVM> {
  item: TVM;
  reason: BatchAttachRejectionReason;
  detail?: string;
}

export interface BatchAttachResult<TVM> {
  added: readonly TVM[];
  duplicates: readonly TVM[];
  orphans: readonly TVM[];
  rejections: readonly BatchAttachRejection<TVM>[];
}

interface BatchAttachCandidate<TVM, TKey> {
  item: TVM;
  key: TKey;
  parentKey: TKey | null;
  retainIfMissing: boolean;
}

/**
 * Abstract recursive tree ViewModel. Concrete subclasses must satisfy the
 * recursive generic constraint: `class MyNode extends HierarchicalVM<MyModel, MyNode>`.
 *
 * @typeParam TModel - Domain model type for each node.
 * @typeParam TVM - Concrete subclass type (recursive constraint per ADR-0028 §3.2).
 */
export abstract class HierarchicalVM<
  TModel,
  TVM extends HierarchicalVM<TModel, TVM>,
> extends ComponentVMBase {
  readonly #childrenFactory: (parent: TVM) => Iterable<TVM>;
  readonly #eagerChildren: boolean;

  #hierarchicalParent: TVM | null = null;
  #children: TVM[] | null = null;
  #pathCache: readonly TVM[] | null = null;
  #parkedAttachItems: TVM[] = [];

  readonly #model: TModel;

  constructor(opts: HierarchicalVMOptions<TModel, TVM>) {
    const hub = opts.hub ?? new MessageHub();
    const dispatcher = opts.dispatcher ?? RxDispatcher.immediate();
    super({
      name: opts.name ?? new.target.name,
      hint: opts.hint ?? "",
      hub,
      dispatcher,
    });
    this.#model = opts.model;
    this.#childrenFactory = opts.childrenFactory;
    this.#eagerChildren = opts.eagerChildren ?? false;
  }

  // ── ViewModelType ────────────────────────────────────────────────────────

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  // ── Model ────────────────────────────────────────────────────────────────

  /** The domain model carried by this tree node. */
  get model(): TModel {
    return this.#model;
  }

  // ── CRTP self-reference ──────────────────────────────────────────────────

  /**
   * VMX-084: the concrete-subclass (CRTP) view of `this`. The recursive
   * constraint `TVM extends HierarchicalVM<TModel, TVM>` guarantees `this` IS a
   * TVM at runtime, but TypeScript cannot prove it through the abstract base —
   * so the one unavoidable `as unknown as TVM` lives here, instead of being
   * scattered across every self-reference (sibling checks, structural-mutation
   * messages, the children factory, path building). See ADR-0028 §3.2.
   */
  get #self(): TVM {
    return this as unknown as TVM;
  }

  // ── Tree identity ────────────────────────────────────────────────────────

  /** The parent node; null when this node is the root. */
  get parent(): TVM | null {
    return this.#hierarchicalParent;
  }

  /** true when parent is null. */
  get isRoot(): boolean {
    return this.#hierarchicalParent === null;
  }

  /** Distance from the root. Root is 0; child of root is 1; etc. */
  get depth(): number {
    return this.#hierarchicalParent === null
      ? 0
      : this.#hierarchicalParent.depth + 1;
  }

  /**
   * true when this node has no children.
   * Note: accessing this property materializes children if not yet done.
   */
  get isLeaf(): boolean {
    return this.children.length === 0;
  }

  /** true when this is the first child in its parent's children list. */
  get isFirst(): boolean {
    if (this.#hierarchicalParent === null) return false;
    const sibs = this.#hierarchicalParent.children;
    return sibs.length > 0 && sibs[0] === (this.#self);
  }

  /** true when this is the last child in its parent's children list. */
  get isLast(): boolean {
    if (this.#hierarchicalParent === null) return false;
    const sibs = this.#hierarchicalParent.children;
    return (
      sibs.length > 0 &&
      sibs[sibs.length - 1] === (this.#self)
    );
  }

  // ── Children ─────────────────────────────────────────────────────────────

  /** The ordered list of child nodes (lazily materialized by default). */
  get children(): readonly TVM[] {
    if (this.#children === null) {
      this.#children = this.#materializeChildren();
    }
    return this.#children;
  }

  // ── Path ─────────────────────────────────────────────────────────────────

  /**
   * Materialized, cached path from the root to this node (inclusive).
   * Invalidated when parent changes.
   */
  get path(): readonly TVM[] {
    if (this.#pathCache === null) {
      this.#pathCache = this.#buildPath();
    }
    return this.#pathCache;
  }

  // ── Symbol.iterator — supports walk / walkExpanded ───────────────────────

  [Symbol.iterator](): Iterator<TVM> {
    return this.children[Symbol.iterator]();
  }

  // ── Lifecycle override — eager construction ───────────────────────────────

  protected override _onConstruct(): void {
    super._onConstruct();
    if (this.#eagerChildren) {
      // Depth-first: materialize and construct children before returning.
      for (const child of this.children) {
        child.construct();
      }
    }
  }

  // ── Structural mutation ──────────────────────────────────────────────────

  /**
   * Adds child to this node's children list, sets its parent, and publishes
   * a TreeStructureChangedMessage(Added) on the hub.
   */
  addChild(child: TVM): void {
    // Runtime guard: callers may pass null/undefined from untyped contexts.
    if ((child as unknown) == null) throw new Error("child must not be null");
    this.#attachChild(child, false);
  }

  /**
   * Removes child from this node's children list and publishes
   * a TreeStructureChangedMessage(Removed) on the hub.
   */
  removeChild(child: TVM): void {
    // Runtime guard: callers may pass null/undefined from untyped contexts.
    if ((child as unknown) == null) throw new Error("child must not be null");
    const list = this.#requireChildren();
    const index = list.indexOf(child);
    if (index < 0) return; // not a child — no-op
    list.splice(index, 1);
    child.#setHierarchicalParent(null);
    this._hub.send(
      new TreeStructureChangedMessage(
        this.#self,
        this._name,
        "removed" satisfies TreeStructureChange,
        child,
        index,
      ),
    );
  }

  /**
   * Moves child from its current parent to this node and publishes
   * a TreeStructureChangedMessage(Reparented) on the hub.
   */
  reparentChild(child: TVM): void {
    // Runtime guard: callers may pass null/undefined from untyped contexts.
    if ((child as unknown) == null) throw new Error("child must not be null");
    this.#attachChild(child, true);
  }

  #attachChild(child: TVM, explicitReparent: boolean): void {
    if (child.#hierarchicalParent === this.#self) return;

    // HIER-018: reparenting this node or one of its ancestors under
    // itself would create a parent cycle and corrupt depth/path/walk.
    if (this.path.includes(child)) {
      throw new Error(
        `Cannot reparent '${child.name}' under '${this.name}': ` +
          `it is this node or one of its ancestors (HIER-018).`,
      );
    }

    // Materialize both lists before mutation so a factory failure cannot
    // detach the child from its original parent.
    const list = this.#requireChildren();
    const oldParent = child.#hierarchicalParent;
    let oldList: TVM[] | null = null;
    let oldIndex = -1;
    if (oldParent !== null) {
      oldList = oldParent.#requireChildren();
      oldIndex = oldList.indexOf(child);
    }

    const newIndex = list.length;
    if (oldList !== null && oldIndex >= 0) oldList.splice(oldIndex, 1);
    try {
      list.push(child);
      child.#setHierarchicalParent(this.#self);
    } catch (error) {
      const inserted = list.indexOf(child);
      if (inserted >= 0) list.splice(inserted, 1);
      if (oldList !== null && oldIndex >= 0) oldList.splice(oldIndex, 0, child);
      if (child.#hierarchicalParent !== oldParent) {
        child.#setHierarchicalParent(oldParent);
      }
      throw error;
    }

    const reparented = explicitReparent || oldParent !== null;
    this._hub.send(
      new TreeStructureChangedMessage(
        this.#self,
        this._name,
        (reparented ? "reparented" : "added") satisfies TreeStructureChange,
        child,
        reparented ? -1 : newIndex,
      ),
    );
  }

  /** Number of missing-parent items retained on this node's structural root. */
  get parkedAttachCount(): number {
    return this.#treeRoot().#parkedAttachItems.length;
  }

  /**
   * Attach an out-of-order, consumer-keyed batch beneath the structural root.
   * Ordinary ingestion anomalies are returned as typed rejections and never
   * replace an already-materialized node with the same key.
   */
  attachMany<TKey>(
    items: Iterable<TVM>,
    options: BatchAttachOptions<TVM, TKey>,
  ): BatchAttachResult<TVM> {
    const root = this.#treeRoot();
    const incoming = Array.from(items);
    const parked = [...root.#parkedAttachItems];
    root.#parkedAttachItems = [];
    const added: TVM[] = [];
    const duplicates: TVM[] = [];
    const orphans: TVM[] = [];
    const rejections: BatchAttachRejection<TVM>[] = [];
    const policy = options.onMissingParent ?? MissingParentPolicy.Park;

    const existing = new Map<TKey, TVM>();
    try {
      for (const node of root.#materializedSubtree()) {
        const key = options.keyOf(node);
        this.#validateBatchKey(key);
        if (!existing.has(key)) existing.set(key, node);
      }
    } catch (error) {
      root.#parkedAttachItems.push(...parked);
      for (const item of [...parked, ...incoming]) {
        rejections.push(this.#rejection(
          item,
          BatchAttachRejectionReason.SelectorFailed,
          error,
        ));
      }
      return { added, duplicates, orphans, rejections };
    }

    const candidates: BatchAttachCandidate<TVM, TKey>[] = [];
    const candidateKeys = new Set<TKey>();
    const activeItems: Array<readonly [TVM, boolean]> = [
      ...parked.map((item) => [item, true] as const),
      ...incoming.map((item) => [item, false] as const),
    ];
    for (const [item, wasParked] of activeItems) {
      let key: TKey;
      let parentKey: TKey | null;
      try {
        key = options.keyOf(item);
        this.#validateBatchKey(key);
        parentKey = options.parentKeyOf(item);
        if (parentKey !== null) this.#validateBatchKey(parentKey);
      } catch (error) {
        if (wasParked) root.#parkedAttachItems.push(item);
        rejections.push(this.#rejection(
          item,
          BatchAttachRejectionReason.SelectorFailed,
          error,
        ));
        continue;
      }

      if (existing.has(key)) {
        duplicates.push(item);
        rejections.push({ item, reason: BatchAttachRejectionReason.DuplicateExistingKey });
        continue;
      }
      if (candidateKeys.has(key)) {
        duplicates.push(item);
        rejections.push({ item, reason: BatchAttachRejectionReason.DuplicateBatchKey });
        continue;
      }
      if (item.#hierarchicalParent !== null) {
        rejections.push({ item, reason: BatchAttachRejectionReason.AlreadyAttached });
        continue;
      }

      candidateKeys.add(key);
      candidates.push({
        item,
        key,
        parentKey,
        retainIfMissing: wasParked || policy === MissingParentPolicy.Park,
      });
    }

    let unresolved = candidates;
    while (unresolved.length > 0) {
      const next: BatchAttachCandidate<TVM, TKey>[] = [];
      let progressed = false;
      for (const candidate of unresolved) {
        const parent = candidate.parentKey === null
          ? root
          : existing.get(candidate.parentKey);
        if (parent === undefined) {
          next.push(candidate);
          continue;
        }
        try {
          parent.addChild(candidate.item);
        } catch (error) {
          this.#rollbackBatchAttach(parent, candidate.item);
          rejections.push(this.#rejection(
            candidate.item,
            BatchAttachRejectionReason.AttachmentFailed,
            error,
          ));
          continue;
        }
        existing.set(candidate.key, candidate.item);
        added.push(candidate.item);
        progressed = true;
      }
      unresolved = next;
      if (!progressed) break;
    }

    const unresolvedByKey = new Map(unresolved.map((candidate) => [candidate.key, candidate]));
    for (const candidate of unresolved) {
      const isCycle = this.#batchParentChainCycles(candidate, unresolvedByKey);
      const reason = isCycle
        ? BatchAttachRejectionReason.Cycle
        : BatchAttachRejectionReason.MissingParent;
      rejections.push({ item: candidate.item, reason });
      if (!isCycle) {
        orphans.push(candidate.item);
        if (candidate.retainIfMissing) root.#parkedAttachItems.push(candidate.item);
      }
    }

    return { added, duplicates, orphans, rejections };
  }

  /**
   * Drops this node's materialized child cache. The next `children` access
   * invokes `childrenFactory` again. Invalidating an unmaterialized node is a
   * no-op.
   */
  invalidateChildren(): void {
    if (this.#children === null) return;
    this.#children = null;
    this._hub.send(
      PropertyChangedMessage.create(
        this.#self,
        this._name,
        "children",
      ),
    );
  }

  /** Drops cached children for this node and all materialized descendants. */
  invalidateSubtree(): void {
    if (this.#children === null) return;
    for (const child of [...this.#children]) {
      child.invalidateSubtree();
    }
    this.invalidateChildren();
  }

  protected override _onDispose(): void {
    this.#parkedAttachItems = [];
    super._onDispose();
  }

  // ── Private helpers ──────────────────────────────────────────────────────

  #materializeChildren(): TVM[] {
    const children = Array.from(
      this.#childrenFactory(this.#self),
    );
    for (const child of children) {
      child.#hierarchicalParent = this.#self;
    }
    return children;
  }

  #treeRoot(): TVM {
    let node = this.#self;
    while (node.#hierarchicalParent !== null) node = node.#hierarchicalParent;
    return node;
  }

  #materializedSubtree(): TVM[] {
    const nodes: TVM[] = [];
    const stack: TVM[] = [this.#self];
    while (stack.length > 0) {
      const node = stack.pop() as TVM;
      nodes.push(node);
      if (node.#children !== null) stack.push(...[...node.#children].reverse());
    }
    return nodes;
  }

  #validateBatchKey(key: unknown): void {
    if (key == null) throw new Error("keyOf must not return null or undefined");
  }

  #batchParentChainCycles<TKey>(
    candidate: BatchAttachCandidate<TVM, TKey>,
    unresolved: Map<TKey, BatchAttachCandidate<TVM, TKey>>,
  ): boolean {
    const seen = new Set<TKey>();
    let current: BatchAttachCandidate<TVM, TKey> | undefined = candidate;
    while (current !== undefined) {
      if (seen.has(current.key)) return true;
      seen.add(current.key);
      if (current.parentKey === null) return false;
      current = unresolved.get(current.parentKey);
    }
    return false;
  }

  #rollbackBatchAttach(parent: TVM, child: TVM): void {
    if (parent.#children !== null) {
      const index = parent.#children.indexOf(child);
      if (index >= 0) parent.#children.splice(index, 1);
    }
    child.#hierarchicalParent = null;
    child.#pathCache = null;
    child.#invalidatePathCacheDescendants();
  }

  #rejection(
    item: TVM,
    reason: BatchAttachRejectionReason,
    error: unknown,
  ): BatchAttachRejection<TVM> {
    const detail = error instanceof Error ? error.message : String(error);
    return { item, reason, detail };
  }

  #ensureChildrenMaterialized(): void {
    if (this.#children === null) {
      this.#children = this.#materializeChildren();
    }
  }

  /** Materialize if needed and return the non-null children list. */
  #requireChildren(): TVM[] {
    this.#ensureChildrenMaterialized();
    // Safe: #ensureChildrenMaterialized guarantees #children is non-null.
    return this.#children as TVM[];
  }

  #buildPath(): readonly TVM[] {
    const chain: TVM[] = [];
    let node: TVM | null = this.#self;
    while (node !== null) {
      chain.push(node);
      node = node.#hierarchicalParent;
    }
    chain.reverse();
    return chain;
  }

  #setHierarchicalParent(parent: TVM | null): void {
    if (this.#hierarchicalParent === parent) return;
    this.#hierarchicalParent = parent;
    this.#pathCache = null; // Invalidate path cache.
    this.#invalidatePathCacheDescendants();
    this._hub.send(
      PropertyChangedMessage.create(
        this.#self,
        this._name,
        "parent",
      ),
    );
  }

  #invalidatePathCacheDescendants(): void {
    if (this.#children === null) return;
    for (const child of this.#children) {
      child.#pathCache = null;
      child.#invalidatePathCacheDescendants();
    }
  }
}

// ---------------------------------------------------------------------------
// Builder (colocated per the canonical TS builder pattern; see
// `componentVM.ts` for the reference structure). Per ADR-0035 §2 H1 / H2.
// ---------------------------------------------------------------------------

/**
 * Context object passed to a {@link HierarchicalVMBuilder}'s `vmFactory`
 * callable. Carries the settled, validated construction options so the
 * factory can instantiate the concrete TVM subclass.
 *
 * This is a TS type alias for the canonical {@link HierarchicalVMOptions}.
 * It exists as a distinct exported name so consumers can spell the factory
 * signature without importing the broader options type.
 */
export type HierarchicalVMConstructionContext<TModel, TVM> =
  HierarchicalVMOptions<TModel, TVM>;

/**
 * Immutable fluent builder for {@link HierarchicalVM}.
 *
 * Required setters: {@link model}, {@link childrenFactory}, {@link services},
 * {@link vmFactory}.
 *
 * Optional setters: {@link name}, {@link hint}, {@link eagerChildren}.
 *
 * Withers: {@link withDefaultServices} — explicit opt-in to default
 * `MessageHub` + `RxDispatcher.immediate()` wiring (mirrors Python's
 * `with_default_services()`; ADR-0035 §2 H2).
 *
 * `vmFactory` is required because TS classes erase their generic-type
 * identity at runtime: the builder cannot itself instantiate a concrete TVM
 * subclass. Consumers supply a factory `(ctx) => new MyNode(ctx)` instead.
 *
 * Each setter returns a NEW builder instance (BLD-001). `build()` validates
 * each required field and throws {@link BuilderValidationError} on the first
 * missing one (BLD-002).
 */
export class HierarchicalVMBuilder<
  TModel,
  TVM extends HierarchicalVM<TModel, TVM>,
> {
  #model: TModel | undefined = undefined;
  #modelSet = false;
  #childrenFactory: ((parent: TVM) => Iterable<TVM>) | null = null;
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #name: string | null = null;
  #hint = "";
  #eagerChildren = false;
  #vmFactory:
    | ((ctx: HierarchicalVMConstructionContext<TModel, TVM>) => TVM)
    | null = null;

  constructor(from?: HierarchicalVMBuilder<TModel, TVM>) {
    if (from) {
      this.#model = from.#model;
      this.#modelSet = from.#modelSet;
      this.#childrenFactory = from.#childrenFactory;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#eagerChildren = from.#eagerChildren;
      this.#vmFactory = from.#vmFactory;
    }
  }

  /** Set the required domain model carried by the node. */
  model(value: TModel): HierarchicalVMBuilder<TModel, TVM> {
    const b = new HierarchicalVMBuilder<TModel, TVM>(this);
    b.#model = value;
    b.#modelSet = true;
    return b;
  }

  /** Set the required children factory `(parent) => Iterable<TVM>`. */
  childrenFactory(
    fn: (parent: TVM) => Iterable<TVM>,
  ): HierarchicalVMBuilder<TModel, TVM> {
    const b = new HierarchicalVMBuilder<TModel, TVM>(this);
    b.#childrenFactory = fn;
    return b;
  }

  /** Set the required message hub + dispatcher pair. */
  services(
    hub: IMessageHub,
    dispatcher: IDispatcher,
  ): HierarchicalVMBuilder<TModel, TVM> {
    const b = new HierarchicalVMBuilder<TModel, TVM>(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  /** Set the optional `name` (default: concrete class name). */
  name(value: string): HierarchicalVMBuilder<TModel, TVM> {
    const b = new HierarchicalVMBuilder<TModel, TVM>(this);
    b.#name = value;
    return b;
  }

  /** Set the optional `hint` (default: empty string). */
  hint(value: string): HierarchicalVMBuilder<TModel, TVM> {
    const b = new HierarchicalVMBuilder<TModel, TVM>(this);
    b.#hint = value;
    return b;
  }

  /**
   * When `true`, the full subtree is materialized at construct() time
   * (depth-first). Default: `false`.
   */
  eagerChildren(value: boolean): HierarchicalVMBuilder<TModel, TVM> {
    const b = new HierarchicalVMBuilder<TModel, TVM>(this);
    b.#eagerChildren = value;
    return b;
  }

  /**
   * Set the required factory that instantiates the concrete TVM subclass.
   *
   * TS erases generic-type identity at runtime, so the builder cannot
   * instantiate a concrete TVM directly — consumers wire a factory:
   *
   * ```ts
   * .vmFactory((ctx) => new MyNode(ctx))
   * ```
   */
  vmFactory(
    fn: (ctx: HierarchicalVMConstructionContext<TModel, TVM>) => TVM,
  ): HierarchicalVMBuilder<TModel, TVM> {
    const b = new HierarchicalVMBuilder<TModel, TVM>(this);
    b.#vmFactory = fn;
    return b;
  }

  /**
   * Chainable Wither that wires a fresh {@link MessageHub} +
   * {@link RxDispatcher.immediate} pair in a single call. Mirrors Python's
   * `with_default_services()` per ADR-0035 §2 H2 — makes the implicit-default
   * behavior of {@link HierarchicalVM}'s constructor visible at the call site.
   */
  withDefaultServices(): HierarchicalVMBuilder<TModel, TVM> {
    return this.services(new MessageHub(), RxDispatcher.immediate());
  }

  /**
   * Validate required fields and construct the concrete TVM by invoking
   * `vmFactory` with the settled options.
   *
   * @throws {BuilderValidationError} If `model`, `childrenFactory`,
   *   `services`, or `vmFactory` is not set.
   */
  build(): TVM {
    if (!this.#modelSet) throw new BuilderValidationError("model");
    if (this.#childrenFactory === null)
      throw new BuilderValidationError("childrenFactory");
    if (this.#hub === null || this.#dispatcher === null)
      throw new BuilderValidationError("services");
    if (this.#vmFactory === null) throw new BuilderValidationError("vmFactory");

    const ctx: HierarchicalVMConstructionContext<TModel, TVM> = {
      model: this.#model as TModel,
      childrenFactory: this.#childrenFactory,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      eagerChildren: this.#eagerChildren,
      hint: this.#hint,
    };
    if (this.#name !== null) ctx.name = this.#name;

    return this.#vmFactory(ctx);
  }
}
