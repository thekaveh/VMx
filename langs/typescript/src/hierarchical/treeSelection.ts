/**
 * TreeSelection<TVM> — opt-in "one current node per tree" helper.
 *
 * See spec/18-hierarchical-vm.md §10, ADR-0164 and HIER-033..HIER-040.
 */
import { Subject, type Observable, type Subscription } from "rxjs";
import { disposeBestEffort } from "../components/disposal.js";
import { ConstructionStatus } from "../lifecycle/status.js";
import type { IMessage } from "../messages/types.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { HierarchicalVM } from "./hierarchicalVm.js";

/**
 * Tracks one current node of the tree below a {@link HierarchicalVM} root
 * (spec/18 §10). A tree node cannot be the `current` item of a container, so
 * a consumer that needs one current node per tree composes this helper on the
 * root instead.
 *
 * A node is selectable when walking its `parent` links reaches the root (the
 * root itself qualifies) and no node on that path is `Disposed`. The checks
 * read only `parent` and `status`, so they never invoke a children factory.
 *
 * While a node is current, the helper subscribes to the hub of every node on
 * the path from that node to the root (one subscription per distinct hub).
 * On any message whose sender is a path node, it repeats the check: it clears
 * the selection when the node has left the tree, and it watches the new path
 * after a move inside the tree.
 *
 * The helper publishes nothing to a hub and never changes, materializes or
 * disposes a node. The owning VM forwards {@link currentChanged} to its own
 * property notification (spec/14 rule 6). Like the tree, the helper is used
 * from one thread and takes no locks.
 *
 * @typeParam TVM - The concrete tree node type.
 */
export class TreeSelection<TVM extends HierarchicalVM<unknown, TVM>> {
  readonly #root: TVM;
  readonly #changes = new Subject<TVM | null>();
  // Changes made while a value is being delivered wait here, so every
  // subscriber sees the changes in order (spec/18 §10.3).
  #pending: (TVM | null)[] = [];
  #emitting = false;
  readonly #subscriptions = new Map<IMessageHub, Subscription>();
  #pathNodes: ReadonlySet<unknown> = new Set<unknown>();
  #current: TVM | null = null;
  #disposed = false;

  /**
   * Creates a selection over the tree below `root`. The helper does not take
   * ownership of `root`.
   *
   * @throws {TypeError} If `root` is null or undefined.
   */
  constructor(root: TVM) {
    // Runtime guard: callers may pass null/undefined from untyped contexts.
    if ((root as unknown) == null) {
      throw new TypeError("root must not be null or undefined");
    }
    this.#root = root;
  }

  /** The current node, or null when nothing is selected. */
  get current(): TVM | null {
    return this.#current;
  }

  /**
   * Emits the new `current`, or null, once for every effective change. Hot:
   * a new subscriber receives no replayed value. Completes on `dispose()`.
   */
  get currentChanged(): Observable<TVM | null> {
    return this.#changes.asObservable();
  }

  /**
   * True when this helper is not disposed, `node` reaches the root through its
   * `parent` links, and no node on that path is `Disposed`.
   */
  canSelect(node: TVM | null | undefined): boolean {
    if (this.#disposed || node == null) return false;
    let candidate: TVM | null = node;
    while (candidate !== null) {
      if (candidate.status === ConstructionStatus.Disposed) return false;
      if (candidate === this.#root) return true;
      candidate = candidate.parent;
    }
    return false;
  }

  /**
   * Makes `node` current. Selecting the current node again does nothing, and
   * so does any call after `dispose()`.
   *
   * @throws {TypeError} If `node` is null or undefined.
   * @throws {Error} If {@link canSelect} rejects `node`; `current` keeps its
   *   value and nothing is emitted.
   */
  select(node: TVM): void {
    if (this.#disposed) return;
    // Runtime guard: callers may pass null/undefined from untyped contexts.
    if ((node as unknown) == null) {
      throw new TypeError("node must not be null or undefined");
    }
    if (!this.canSelect(node)) {
      throw new Error(
        `Cannot select '${node.name}': it is not a live member of the tree ` +
          `rooted at '${this.#root.name}'.`,
      );
    }
    if (node === this.#current) return;
    this.#current = node;
    this.#watch(node);
    this.#emit(node);
  }

  /** Sets `current` to null. Does nothing when it is already null or after `dispose()`. */
  clear(): void {
    if (this.#disposed || this.#current === null) return;
    this.#current = null;
    this.#releaseWatch();
    this.#emit(null);
  }

  /**
   * Releases the hub subscriptions, sets `current` to null without emitting,
   * and completes {@link currentChanged}. Every step runs; the first failure
   * is rethrown. Idempotent. Never disposes or detaches a node.
   */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#current = null;
    this.#pending = [];
    this.#pathNodes = new Set<unknown>();
    const subscriptions = [...this.#subscriptions.values()];
    this.#subscriptions.clear();
    disposeBestEffort([
      ...subscriptions.map((subscription) => () => subscription.unsubscribe()),
      () => this.#changes.complete(),
    ]);
  }

  // Delivers `value` after the changes already being delivered. A subscriber
  // that selects or clears re-entrantly queues its change behind this one.
  #emit(value: TVM | null): void {
    this.#pending.push(value);
    if (this.#emitting) return;
    this.#emitting = true;
    try {
      while (this.#pending.length > 0 && !this.#disposed) {
        this.#changes.next(this.#pending.shift() as TVM | null);
      }
    } finally {
      this.#emitting = false;
      if (this.#disposed) this.#pending = [];
    }
  }

  // Subscribes to the hub of every node from `node` up to the root, reusing a
  // subscription per distinct hub, and drops hubs no longer on the path.
  #watch(node: TVM): void {
    const pathNodes = new Set<unknown>();
    const hubs = new Set<IMessageHub>();
    let candidate: TVM | null = node;
    while (candidate !== null) {
      pathNodes.add(candidate);
      hubs.add(candidate.hub);
      if (candidate === this.#root) break;
      candidate = candidate.parent;
    }
    this.#pathNodes = pathNodes;
    for (const [hub, subscription] of [...this.#subscriptions]) {
      if (hubs.has(hub)) continue;
      this.#subscriptions.delete(hub);
      subscription.unsubscribe();
    }
    for (const hub of hubs) {
      if (this.#subscriptions.has(hub)) continue;
      this.#subscriptions.set(
        hub,
        hub.messages.subscribe((message) => {
          this.#onMessage(message);
        }),
      );
    }
  }

  #releaseWatch(): void {
    this.#pathNodes = new Set<unknown>();
    const subscriptions = [...this.#subscriptions.values()];
    this.#subscriptions.clear();
    disposeBestEffort(subscriptions.map((subscription) => () => subscription.unsubscribe()));
  }

  // Each leave-tree event is published by a node on the watched path: the
  // moved node's `parent` change, the invalidated node's `children` change, or
  // the disposed node's status change (spec/18 §10.2).
  #onMessage(message: IMessage): void {
    const current = this.#current;
    if (this.#disposed || current === null) return;
    if (!this.#pathNodes.has(message.sender)) return;
    if (this.canSelect(current)) {
      this.#watch(current);
      return;
    }
    this.#current = null;
    this.#releaseWatch();
    this.#emit(null);
  }
}
