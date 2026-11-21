/**
 * Announcement nodes and the prototype's stand-in for native nodes (R15.*).
 *
 * An announcement node is a version counter for (source, name). It is bumped, as one write, at every publication of
 * `name` by the source: a view-model's dual-channel helper or local-only raise, a status transition, a command raise,
 * an expansion change, or an emission of a VMx helper's change stream (`isExpandedChanged`, `canExecuteChanged`, ...).
 * Emissions that the graph itself makes for registered names do not bump it. This is prototype behavior: the
 * proposal's R15.3 bumps it (README.md §1.6).
 *
 * Fix round 2 (R15.2): state first, extended to derived values. A library publication commits the
 * announcement nodes it publishes before the library delivers anything (`publication`), so every hub or local
 * observer of the library's own message reads the current values of their dependents. The change-stream emission
 * inside the publication then does not commit them again. A stream that the prototype cannot reach before delivery
 * (DiscriminatorVM, FormVM, DerivedProperty) still commits at its emission (README.md, limit 2).
 *
 * R15.5: on 3.30.0 the prototype implements the built-in native nodes (status, model, state, isExpanded, ...) as
 * announcement nodes. It installs tracking accessors on the instances it touches, so a direct read such as
 * `this.status` or `resource.state` is tracked there. A VMx implementation tracks them natively.
 */
import { ComponentVMBase, DiscriminatorVM, FormVM } from "@thekaveh/vmx";
import { filter, isObservable, type Observable, type Subscription } from "rxjs";
import { reportStreamFed } from "./diagnostics.js";
import { ReactiveWriteError } from "./errors.js";
import {
  bumpVersions,
  inEvaluation,
  isTracking,
  libraryOperation,
  ReactiveNode,
  releaseNode,
  track,
  untracked,
} from "./graph.js";
import { describeObject, findDescriptor, libraryPrototypes } from "./util.js";

// ── The graph's own emissions ────────────────────────────────────────────────────────────────────────────────

let graphEmission: { readonly vm: object; readonly name: string } | null = null;

/**
 * Runs `fn` while the graph announces `name` of `vm`. Such emissions bump no announcement node. This is prototype
 * behavior: the proposal's R15.3 bumps it (README.md §1.6).
 */
export function asGraphEmission(vm: object, name: string, fn: () => void): void {
  const saved = graphEmission;
  graphEmission = { vm, name };
  try {
    fn();
  } finally {
    graphEmission = saved;
  }
}

/** True while the graph itself announces `name` of `vm`. */
export function isGraphEmission(vm: object, name: string): boolean {
  return graphEmission !== null && graphEmission.vm === vm && graphEmission.name === name;
}

// ── Change streams ───────────────────────────────────────────────────────────────────────────────────────────

/** The VM-local property-change surface of a view-model, read through the prototype chain (no activation). */
export function localSurface(vm: ComponentVMBase): Observable<string> {
  const getter = findDescriptor(vm, "propertyChanged")?.descriptor.get;
  if (getter === undefined) throw new TypeError(`${describeObject(vm)} has no propertyChanged surface`);
  return getter.call(vm) as Observable<string>;
}

/** The stream that announces changes of `name` on `source`, or null when `source` has none (R15.3). */
export function resolveStream(source: object, name: string): Observable<unknown> | null {
  if (source instanceof ComponentVMBase) {
    // A container's membership (its count and items) changes through collectionChanged, not propertyChanged.
    const collection = (source as { readonly collectionChanged?: unknown }).collectionChanged;
    if (name === "count" && isObservable(collection)) return collection as Observable<unknown>;
    return localSurface(source).pipe(filter((emitted) => emitted === name && !isGraphEmission(source, name)));
  }
  const record = source as Record<string, unknown>;
  if (source instanceof DiscriminatorVM && (name === "activeKey" || name === "modalDepth")) {
    return source.activeChanged;
  }
  if (source instanceof FormVM && name === "isValid") return source.errorsChanged;
  const surface = record["propertyChanged"];
  if (isObservable(surface)) return (surface as Observable<unknown>).pipe(filter((emitted) => emitted === name));
  const own = record[`${name}Changed`];
  if (isObservable(own)) return own;
  const commandSurface = record["canExecuteChanged"];
  if (isObservable(commandSurface)) return commandSurface;
  return null;
}

// ── Announcement nodes ───────────────────────────────────────────────────────────────────────────────────────

interface AnnouncementEntry {
  readonly nodes: Map<string, ReactiveNode>;
  readonly subscriptions: Subscription[];
}

const announcements = new WeakMap<object, AnnouncementEntry>();
/** Nodes that a library publication in progress committed already (or chose not to); their stream skips them. */
const committing = new Map<ReactiveNode, number>();

function mark(node: ReactiveNode): void {
  committing.set(node, (committing.get(node) ?? 0) + 1);
}

function unmark(node: ReactiveNode): void {
  const count = (committing.get(node) ?? 0) - 1;
  if (count > 0) committing.set(node, count);
  else committing.delete(node);
}

/** The announcement node of (source, name), created and subscribed on first use; null when no stream exists. */
export function announcementNode(source: object, name: string): ReactiveNode | null {
  let entry = announcements.get(source);
  const existing = entry?.nodes.get(name);
  if (existing !== undefined) return existing;
  const stream = resolveStream(source, name);
  if (stream === null) return null;
  if (entry === undefined) {
    entry = { nodes: new Map(), subscriptions: [] };
    announcements.set(source, entry);
  }
  const node = new ReactiveNode("announcement", null, name, 0, Object.is);
  node.subject = source;
  entry.nodes.set(name, node);
  const subscription = stream.subscribe({
    next: () => {
      // A library publication committed this node before it delivered (R15.2, fix round 2).
      if (committing.has(node)) return;
      bumpVersions([node], true);
    },
    // A completed stream (a disposed command or helper) announces nothing more: no frame keeps its source (R17.2).
    complete: () => {
      releaseAnnouncements(source);
    },
  });
  if (announcements.get(source) === entry) entry.subscriptions.push(subscription);
  else subscription.unsubscribe();
  return node;
}

/** Records a dependency on (source, name) in the current frame, when there is one. */
export function trackAnnouncement(source: object, name: string): void {
  if (!isTracking()) return;
  const node = announcementNode(source, name);
  if (node !== null) track(node);
}

/** Releases the announcement nodes that follow `source` (graph release of a disposed view-model, R17.1). */
export function releaseAnnouncements(source: object): void {
  const entry = announcements.get(source);
  if (entry === undefined) return;
  announcements.delete(source);
  for (const subscription of entry.subscriptions) subscription.unsubscribe();
  for (const node of entry.nodes.values()) releaseNode(node);
}

/**
 * One library publication of `source` (R15.2, fix round 2): commits the announcement nodes of `commit` (the names
 * whose values changed) before `fn` delivers anything, keeps the change-stream emissions of `markNames` inside `fn`
 * from committing again, runs `fn` untracked as a library operation that holds the drain, and settles the
 * dependents when the outermost library operation returns. A nested publication (user code that publishes again
 * while the library delivers) commits again: it is a new change.
 */
export function publication<T>(
  source: object,
  commit: readonly string[],
  fn: () => T,
  markNames: readonly string[] = commit,
): T {
  const entry = announcements.get(source);
  const marked: ReactiveNode[] = [];
  const committed: ReactiveNode[] = [];
  if (entry !== undefined && !isGraphPublication(source, markNames)) {
    for (const name of markNames) {
      const node = entry.nodes.get(name);
      if (node === undefined || node.released) continue;
      marked.push(node);
      if (commit.includes(name)) committed.push(node);
    }
  }
  for (const node of marked) mark(node);
  try {
    return libraryOperation(() => {
      if (committed.length > 0) {
        if (inEvaluation()) {
          // A publication inside an evaluation frame (a getter that notifies) commits nothing; reported (R16).
          reportStreamFed(
            new ReactiveWriteError(`A library publication of ${describeObject(source)} inside an evaluation frame`),
          );
        } else {
          bumpVersions(committed, true);
        }
      }
      return untracked(fn);
    }, true);
  } finally {
    for (const node of marked) unmark(node);
  }
}

function isGraphPublication(source: object, names: readonly string[]): boolean {
  return names.length === 1 && names[0] !== undefined && isGraphEmission(source, names[0]);
}

// ── Tracking accessors (the prototype's native nodes) ────────────────────────────────────────────────────────

/** The library properties of a view-model that announce changes on its local surface (R15.1). */
export const NATIVE_VM_PROPERTIES = [
  "status",
  "isConstructed",
  "isCurrent",
  "model",
  "modeledHint",
  "state",
  "current",
] as const;

/**
 * Installs an own accessor for `name` on `target` that reads the prototype getter and records the announcement
 * node. Returns false when there is nothing to install (already own, no getter, or not a library getter).
 */
export function installTrackedAccessor(target: object, name: string, libraryOnly: boolean): boolean {
  if (Object.prototype.hasOwnProperty.call(target, name)) return false;
  const found = findDescriptor(target, name);
  const getter = found?.descriptor.get;
  if (found === undefined || getter === undefined) return false;
  if (libraryOnly && !libraryPrototypes.has(found.owner)) return false;
  const setter = found.descriptor.set;
  const descriptor: PropertyDescriptor = {
    configurable: true,
    enumerable: false,
    get(this: object): unknown {
      const value: unknown = getter.call(this);
      trackAnnouncement(target, name);
      return value;
    },
  };
  if (setter !== undefined) {
    descriptor.set = function (this: object, value: unknown): void {
      setter.call(this, value);
    };
  }
  Object.defineProperty(target, name, descriptor);
  return true;
}

/** Tracks the native library properties of a view-model instance (the prototype's R15.1). */
export function installNativeTracking(vm: ComponentVMBase): void {
  for (const name of NATIVE_VM_PROPERTIES) installTrackedAccessor(vm, name, true);
}
