/**
 * HierarchicalVM<TModel, TVM> — first-class recursive tree ViewModel.
 *
 * Each node carries a typed TModel and may contain children of the same
 * concrete type TVM. Children are lazy by default; eager materialization is
 * opt-in via the eagerChildren constructor option.
 *
 * See spec/18-hierarchical-vm.md and ADR-0028.
 */
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
