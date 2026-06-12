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
    return sibs.length > 0 && sibs[0] === (this as unknown as TVM);
  }

  /** true when this is the last child in its parent's children list. */
  get isLast(): boolean {
    if (this.#hierarchicalParent === null) return false;
    const sibs = this.#hierarchicalParent.children;
    return (
      sibs.length > 0 &&
      sibs[sibs.length - 1] === (this as unknown as TVM)
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
    const list = this.#requireChildren();
    const index = list.length;
    list.push(child);
    child.#setHierarchicalParent(this as unknown as TVM);
    this._hub.send(
      new TreeStructureChangedMessage(
        this as unknown as TVM,
        this._name,
        "added" satisfies TreeStructureChange,
        child,
        index,
      ),
    );
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
        this as unknown as TVM,
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
    if (child.#hierarchicalParent === (this as unknown as TVM)) return; // no-op

    // HIER-018: reparenting this node or one of its ancestors under
    // itself would create a parent cycle and corrupt depth/path/walk.
    if (this.path.includes(child)) {
      throw new Error(
        `Cannot reparent '${child.name}' under '${this.name}': ` +
          `it is this node or one of its ancestors (HIER-018).`,
      );
    }

    // Detach from old parent silently.
    const oldParent = child.#hierarchicalParent;
    if (oldParent !== null) {
      const oldList = oldParent.#requireChildren();
      const idx = oldList.indexOf(child);
      if (idx >= 0) oldList.splice(idx, 1);
    }

    // Attach to new parent.
    const list = this.#requireChildren();
    list.push(child);
    child.#setHierarchicalParent(this as unknown as TVM);
    this._hub.send(
      new TreeStructureChangedMessage(
        this as unknown as TVM,
        this._name,
        "reparented" satisfies TreeStructureChange,
        child,
        -1,
      ),
    );
  }

  // ── Private helpers ──────────────────────────────────────────────────────

  #materializeChildren(): TVM[] {
    const children = Array.from(
      this.#childrenFactory(this as unknown as TVM),
    );
    for (const child of children) {
      child.#hierarchicalParent = this as unknown as TVM;
    }
    return children;
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
    let node: TVM | null = this as unknown as TVM;
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
        this as unknown as TVM,
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
