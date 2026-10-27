/**
 * Internal: the collection-change delivery, auto-construct-on-add and
 * construct walk shared by CompositeVMBase and GroupVM. Internal; not
 * exported from the package.
 */
import type { Subject } from "rxjs";
import type { ComponentVMBase } from "./componentVMBase.js";
import { ConstructionStatus } from "../lifecycle/status.js";
import { collectionChangedMessageFor } from "../collections/vmCollectionHubMessage.js";
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
