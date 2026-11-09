/**
 * Internal: the collection-change delivery, batch, auto-construct-on-add,
 * construct walk and destruct order shared by CompositeVMBase and GroupVM.
 * Internal; not exported from the package.
 */
import type { Subject } from "rxjs";
import type { ComponentVMBase } from "./componentVMBase.js";
import type { ChildOrder } from "./types.js";
import { ConstructionStatus } from "../lifecycle/status.js";
import { collectionChangedMessageFor } from "../collections/vmCollectionHubMessage.js";
import { makeCollectionChangedEvent } from "../collections/collectionChangedEvent.js";
import { BatchUpdateHandle } from "../collections/batchUpdateHandle.js";
import type { IBatchable } from "../collections/batchUpdateHandle.js";
import type { CollectionChangedEvent } from "../collections/index.js";

/**
 * Local subscribers first, then one hub message sent by `container`
 * (spec ch. 01 §1.4, ADR-0142). A disposed container publishes nothing.
 */
export function deliverCollectionChanged(
  container: ComponentVMBase,
  subject: Subject<CollectionChangedEvent>,
  isDisposed: () => boolean,
  event: CollectionChangedEvent,
): void {
  subject.next(event);
  // A completed rxjs Subject is stopped, not closed, so check the
  // container's own disposal: it may have been disposed before a batch
  // closed or by a local subscriber of this very event.
  if (isDisposed()) return;
  container.hub.send(collectionChangedMessageFor(container, event));
}

/**
 * The ref-counted collection-change batch shared by CompositeVMBase and
 * GroupVM (spec v1.1, COMP-013, GRP-006). It owns the batch depth and the
 * dirty flag; each container member only forwards here. A change inside an
 * open batch only marks it dirty; the outermost close delivers one `reset`
 * if any change occurred.
 */
export class ContainerBatch {
  readonly #deliver: (event: CollectionChangedEvent) => void;
  #depth = 0;
  #dirty = false;

  /** @param deliver The container's local-event and hub delivery. */
  constructor(deliver: (event: CollectionChangedEvent) => void) {
    this.#deliver = deliver;
  }

  /** Opens one batch level; the handle closes it once through `owner._exitBatch()`. */
  enter(owner: IBatchable): BatchUpdateHandle {
    this.#depth++;
    return new BatchUpdateHandle(owner);
  }

  /** Closes one batch level; the outermost close delivers the pending `reset`. */
  exit(): void {
    this.#depth--;
    if (this.#depth === 0 && this.#dirty) {
      this.#dirty = false;
      this.#deliver(makeCollectionChangedEvent("reset"));
    }
  }

  /** Delivers `event` now, or marks an open batch dirty. */
  emit(event: CollectionChangedEvent): void {
    if (this.#depth > 0) {
      this.#dirty = true;
      return;
    }
    this.#deliver(event);
  }
}

/** Starts `child` when `container` auto-constructs children on add. */
export function maybeAutoConstruct(
  container: ComponentVMBase,
  autoConstructOnAdd: boolean,
  child: ComponentVMBase,
): void {
  if (!autoConstructOnAdd) return;
  if (container.status === ConstructionStatus.Constructing) {
    // The construct walk joins a child added while it runs (constructWalk).
    if (child.status === ConstructionStatus.Destructed) child.construct();
    return;
  }
  if (container.status !== ConstructionStatus.Constructed) return;
  if (child.status === ConstructionStatus.Constructed) return;
  child.construct();
}

/**
 * The construct walk's children: the membership snapshot, then (with
 * auto-construct-on-add) each child added while the walk runs. A late child
 * was already started by `maybeAutoConstruct`, so it is joined like a
 * population child and never restarted (spec/02 §6, spec/06 §5.1).
 * `children` is read on every step because the container may replace its
 * array while the walk runs.
 */
export function* constructWalk<VM extends ComponentVMBase>(
  children: () => readonly VM[],
  autoConstructOnAdd: boolean,
  joined: Set<ComponentVMBase>,
): Generator<VM> {
  const visited = new Set<VM>(children());
  yield* [...visited];
  if (!autoConstructOnAdd) return;
  for (;;) {
    const late = children().find((child) => !visited.has(child));
    if (late === undefined) return;
    visited.add(late);
    joined.add(late);
    yield late;
  }
}

/**
 * Returns `order`, or throws a `TypeError` when it is not a `ChildOrder`
 * value. `destructWalk` reverses only for `"reverse"`, so an unknown value
 * from an untyped caller, such as `"Reverse"`, would otherwise give
 * insertion order with no error (#1397).
 */
export function requireChildOrder(order: unknown): ChildOrder {
  if (order !== "insertion" && order !== "reverse") {
    throw new TypeError(
      `destructOrder must be "insertion" or "reverse", got "${String(order)}"`,
    );
  }
  return order;
}

/**
 * A snapshot of `children` in the order the container destructs and disposes
 * them (spec/02 §6, ADR-0161): as given for `"insertion"`, last child first
 * for `"reverse"`.
 */
export function destructWalk<VM extends ComponentVMBase>(
  children: readonly VM[],
  order: ChildOrder,
): VM[] {
  const snapshot = [...children];
  return order === "reverse" ? snapshot.reverse() : snapshot;
}
