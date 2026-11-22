/**
 * The reactive graph: nodes, tracking frames, writes, settles, change scopes and the drain
 * (the node kinds of R3.*, the rules R5.* to R9.* and R16, with the rules that the two fix rounds added).
 *
 * The graph knows nothing about VMx. Owners (view-model states) plug in through `NodeOwner`, published nodes
 * through their `publish` callback, and commands and reactions through `Frame`.
 *
 * Algorithm (informative): push-pull coloring with an equality cutoff. A write commits, marks its direct dependents dirty
 * and their transitive dependents "check", and then settles: every marked node that is eager (an activated
 * published computed, or a node read by a command or a reaction) is brought up to date at most once, lowest height
 * first. The changed set is computed against a snapshot that each node takes the first time it is written or
 * evaluated in the epoch, so a value that changed and changed back inside one change scope is not a change.
 *
 * Every node also carries a version that grows whenever its value changes. A frame records the version of each
 * node it reads, so a reaction can tell whether anything it read changed after it read it (R9.2 skip rule).
 *
 * Fix round 2 (R6.10, R9.6, R9.8, R15.2, R16): equalities run in their own context (`compareValues`); a change
 * from one error to a different error is a change; library operations defer their native commits (`nativeDepth`)
 * and library publications hold the drain (`holdDepth`); a producer flush delivers the announcements queued during
 * the flush; the development drain bound counts repetitions of one entry.
 */
import { developmentDiagnostics, reportStreamFed } from "./diagnostics.js";
import { type Equality, errorsEqual, shallowEqual } from "./equality.js";
import { ReactiveCycleError, ReactiveOverflowError, ReactiveWriteError } from "./errors.js";

/** The owner of a node, a command or a reaction: a view-model state (R3.*). */
export interface NodeOwner {
  /** Disposed is published: writes are ignored, nodes evaluate nothing, queued entries are dropped (R6.2, R13.3). */
  readonly disposing: boolean;
  /** `Class(name)`, for diagnostics. */
  readonly label: string;
  /** The object that `explain` names as the owner. */
  readonly target: object;
}

export type GraphNodeKind = "state" | "signal" | "computed" | "memo" | "announcement" | "invalidation";

const CLEAN = 0;
const CHECK = 1;
const DIRTY = 2;
type Color = typeof CLEAN | typeof CHECK | typeof DIRTY;

let indexCounter = 0;

/** One process-wide creation-order counter for published nodes, commands and reactions (R3.5). */
export function nextIndex(): number {
  indexCounter += 1;
  return indexCounter;
}

/** Something that reads nodes: a derived node or a frame of a command or a reaction. */
export interface Consumer {
  readonly isDerived: boolean;
  sources: ReactiveNode[];
}

/** One entry of the drain queue (R9.1). */
export interface QueueEntry {
  /** Entries of an owner whose Disposed is published are dropped (R9.2, R9.5). */
  readonly owner: NodeOwner | null;
  /** Names the entry in the overflow diagnostic (R9.6). */
  readonly key: string;
  /** An announcement entry; a direct send of its owner delivers it first (producer order, R9.8). */
  readonly announce: boolean;
  run(): void;
}

/** A source or derived value with an equality (the node kinds of R3.*). */
export class ReactiveNode {
  readonly index: number;
  readonly observers = new Set<Consumer>();
  height = 0;
  released = false;
  value: unknown;
  hasError = false;
  error: unknown = undefined;
  /** Grows by one whenever the value (or its error state) changes; frames compare it after a run (R9.2). */
  version = 0;
  /** Announces the node; set for published nodes only (state and computed). */
  publish: (() => void) | null = null;
  /** The object an announcement node follows (`explain` names it as the owner). */
  subject: object | null = null;
  snapEpoch = 0;
  snapValue: unknown = undefined;
  snapHasError = false;
  snapError: unknown = undefined;
  snapEvaluated = false;
  /** The last comparison made in an epoch, reused by the changed-set check (an equality is called once per pair). */
  cmpEpoch = 0;
  cmpA: unknown = undefined;
  cmpB: unknown = undefined;
  cmpEqual = false;

  constructor(
    readonly kind: GraphNodeKind,
    readonly owner: NodeOwner | null,
    readonly name: string,
    value: unknown,
    public equals: Equality<unknown>,
  ) {
    this.index = nextIndex();
    this.value = value;
  }
}

/** A computed or memo node: a node that is also a consumer. */
export class DerivedNode extends ReactiveNode implements Consumer {
  readonly isDerived = true;
  sources: ReactiveNode[] = [];
  color: Color = DIRTY;
  evaluated = false;
  evaluating = false;
  errorSettle = 0;
  /** A cycle closed through this node during its evaluation; the evaluation fails with it (R16). */
  cycle: ReactiveCycleError | undefined = undefined;
  /** Set for the published computeds of an activated view-model (R6.4 i). */
  eagerPublished = false;
  /** Number of command and reaction frames that read this node (R6.4 ii, iii). */
  frameObservers = 0;
  compute: ((previous: unknown) => unknown) | null;

  constructor(
    kind: "computed" | "memo",
    owner: NodeOwner | null,
    name: string,
    compute: (previous: unknown) => unknown,
    equals: Equality<unknown>,
  ) {
    super(kind, owner, name, undefined, equals);
    this.compute = compute;
  }
}

/** The frame of a command predicate or of a reaction (see the proposal's terms). */
export abstract class Frame implements Consumer {
  readonly isDerived = false;
  sources: ReactiveNode[] = [];
  /** The version of each source when the frame read it, parallel to `sources` (R9.2). */
  sourceVersions: number[] = [];
  /** The sources as a set, kept for a parameterized command's union (R10.2). */
  unionSet: Set<ReactiveNode> | null = null;
  /** Set by the graph release; a frame released while it runs keeps no edge (R17.1). */
  released = false;
  abstract readonly index: number;
  abstract readonly frameKind: "command" | "reaction";
  /** A settle changed one of the sources: returns the entry to queue (R6.6 b, c), or null. */
  abstract affected(): QueueEntry | null;

  /** True when a node the frame read changed after the frame read it (R9.2). */
  changedSinceRead(): boolean {
    const sources = this.sources;
    const versions = this.sourceVersions;
    for (let i = 0; i < sources.length; i += 1) {
      if (sources[i]?.version !== versions[i]) return true;
    }
    return false;
  }
}

// ── Tracking ─────────────────────────────────────────────────────────────────────────────────────────────────

interface Tracker {
  readonly consumer: Consumer | null;
  readonly link: boolean;
  readonly passThrough: boolean;
  readonly parent: Tracker | null;
  readonly recorded: ReactiveNode[];
  readonly versions: number[];
  readonly seen: Set<ReactiveNode>;
}

let tracker: Tracker | null = null;
let evaluationDepth = 0;
let probeDepth = 0;

function link(node: ReactiveNode, consumer: Consumer): void {
  if (node.observers.has(consumer)) return;
  node.observers.add(consumer);
  if (!consumer.isDerived && node instanceof DerivedNode) node.frameObservers += 1;
}

function unlink(node: ReactiveNode, consumer: Consumer): void {
  if (!node.observers.delete(consumer)) return;
  if (!consumer.isDerived && node instanceof DerivedNode) node.frameObservers -= 1;
}

/** Records a read of `node` in the current frame and, through pass-through frames, in the enclosing ones (R5.1). */
export function track(node: ReactiveNode): void {
  for (let t = tracker; t !== null; t = t.passThrough ? t.parent : null) {
    // A node never depends on itself: a cycle read through a pass-through predicate stops here (R16).
    if ((t.consumer as unknown) === node || t.seen.has(node)) continue;
    t.seen.add(node);
    t.recorded.push(node);
    // The first read decides: a change after it makes the reading reaction run again (R9.2).
    t.versions.push(node.version);
    if (t.link && t.consumer !== null && !node.released) link(node, t.consumer);
  }
}

/** True inside any frame that records reads. */
export function isTracking(): boolean {
  return tracker !== null;
}

/** True inside an evaluation frame: writes, registrations and lifecycle calls throw there. */
export function inEvaluation(): boolean {
  return evaluationDepth > 0;
}

/** True for a read from outside the graph: no frame, no settle, no probe (R19.1 "consumer read"). */
export function isConsumerRead(): boolean {
  return tracker === null && evaluationDepth === 0 && probeDepth === 0 && !settling;
}

export interface FrameOptions {
  /** An evaluation frame must not write. Every frame is one except an effect run. */
  readonly evaluation: boolean;
  /** The reads also count for the enclosing frame (a command predicate, R10.2). */
  readonly passThrough?: boolean;
  /** Keep the earlier sources (the parameterized command union, R10.2). */
  readonly union?: boolean;
}

function updateHeight(node: DerivedNode): void {
  let height = 0;
  for (const source of node.sources) if (source.height > height) height = source.height;
  node.height = height + 1;
}

function isReleased(consumer: Consumer): boolean {
  return consumer instanceof Frame ? consumer.released : (consumer as DerivedNode).released;
}

/** Replaces (or, for a union, extends) the consumer's sources with the frame's reads (R5.2, R10.2, R17.1). */
function commitSources(consumer: Consumer, t: Tracker, union: boolean): void {
  if (isReleased(consumer)) {
    // Released during its own run (an effect that disposed its view-model): keep no edge.
    for (const node of t.recorded) unlink(node, consumer);
    clearSources(consumer);
    return;
  }
  const frame = consumer instanceof Frame ? consumer : null;
  if (union && frame !== null) {
    const set = (frame.unionSet ??= new Set(frame.sources));
    for (let i = 0; i < t.recorded.length; i += 1) {
      const node = t.recorded[i];
      if (node === undefined || node.released || set.has(node)) continue;
      set.add(node);
      frame.sources.push(node);
      frame.sourceVersions.push(t.versions[i] ?? node.version);
    }
    return;
  }
  for (const old of consumer.sources) {
    if (!t.seen.has(old)) unlink(old, consumer);
  }
  // A node released during the run (a view-model disposed by an effect it read) is not kept (R17.2).
  const sources: ReactiveNode[] = [];
  const versions: number[] = [];
  for (let i = 0; i < t.recorded.length; i += 1) {
    const node = t.recorded[i];
    if (node === undefined) continue;
    if (node.released) {
      unlink(node, consumer);
      continue;
    }
    sources.push(node);
    versions.push(t.versions[i] ?? node.version);
  }
  consumer.sources = sources;
  if (frame !== null) frame.sourceVersions = versions;
}

/** Runs `fn` in the frame of `consumer`; its reads become the consumer's sources (R5.2). */
export function runFrame<T>(consumer: Consumer, fn: () => T, options: FrameOptions): T {
  const t: Tracker = {
    consumer,
    link: true,
    passThrough: options.passThrough === true,
    parent: tracker,
    recorded: [],
    versions: [],
    seen: new Set(),
  };
  const previous = tracker;
  tracker = t;
  if (options.evaluation) evaluationDepth += 1;
  try {
    return fn();
  } finally {
    tracker = previous;
    if (options.evaluation) evaluationDepth -= 1;
    commitSources(consumer, t, options.union === true);
    if (consumer instanceof DerivedNode) updateHeight(consumer);
  }
}

/** Runs `fn` without recording its reads in the current frame (R5.5). An evaluation frame stays one. */
export function untracked<T>(fn: () => T): T {
  const previous = tracker;
  tracker = null;
  try {
    return fn();
  } finally {
    tracker = previous;
  }
}

export interface ProbeResult<T> {
  readonly recorded: readonly ReactiveNode[];
  readonly ok: boolean;
  readonly value: T | undefined;
}

/** Evaluates `fn` in a probe frame: an evaluation frame that records reads but installs no edge (R19.1, R19.2). */
export function probe<T>(fn: () => T): ProbeResult<T> {
  const t: Tracker = {
    consumer: null,
    link: false,
    passThrough: false,
    parent: tracker,
    recorded: [],
    versions: [],
    seen: new Set(),
  };
  const previous = tracker;
  tracker = t;
  evaluationDepth += 1;
  probeDepth += 1;
  try {
    const value = fn();
    return { recorded: t.recorded, ok: true, value };
  } catch {
    return { recorded: t.recorded, ok: false, value: undefined };
  } finally {
    tracker = previous;
    evaluationDepth -= 1;
    probeDepth -= 1;
  }
}

/** Runs `fn` as an evaluation frame without recording (activation, R4.4). */
export function asEvaluation<T>(fn: () => T): T {
  evaluationDepth += 1;
  try {
    return fn();
  } finally {
    evaluationDepth -= 1;
  }
}

/** Throws `ReactiveWriteError` inside an evaluation frame (R6.2, R3.3, R16). */
export function assertWritable(what: string): void {
  if (evaluationDepth > 0) {
    throw new ReactiveWriteError(
      `${what} inside an evaluation frame (a computed, a memo, a command predicate, a reaction select, ` +
        "a keyed-driver selector, an equality or an activation) is not allowed",
    );
  }
}

// ── Equalities (fix round 2, R6.10) ──────────────────────────────────────────────────────────────────────────

/**
 * Calls an equality, which is user code, in its own context (R6.10, FR2): untracked, so its reads are no dependency
 * of the frame that caused the comparison (RR2); as an evaluation frame, so a write inside it throws
 * ReactiveWriteError instead of re-entering the settle (RR1); a throw counts as "not equal" and is reported on the
 * stream-fed route (EE3). `Object.is` and `shallowEqual` are library code and run directly. A development
 * diagnostic passes `report: false`: it never reports a user error a second time.
 */
export function compareValues(equals: Equality<unknown>, a: unknown, b: unknown, report = true): boolean {
  if (equals === Object.is) return Object.is(a, b);
  if (equals === shallowEqual) return shallowEqual(a, b);
  const previous = tracker;
  tracker = null;
  evaluationDepth += 1;
  try {
    return Boolean(equals(a, b));
  } catch (error) {
    if (report) reportStreamFed(error);
    return false;
  } finally {
    evaluationDepth -= 1;
    tracker = previous;
  }
}

/** Compares two values of `node` and remembers the pair for the changed-set check of the open epoch. */
function compareForNode(node: ReactiveNode, a: unknown, b: unknown): boolean {
  const equal = compareValues(node.equals, a, b);
  rememberComparison(node, a, b, equal);
  return equal;
}

function rememberComparison(node: ReactiveNode, a: unknown, b: unknown, equal: boolean): void {
  const e = epoch;
  if (e === null) return;
  node.cmpEpoch = e.id;
  node.cmpA = a;
  node.cmpB = b;
  node.cmpEqual = equal;
}

// ── Epochs, marking and evaluation ───────────────────────────────────────────────────────────────────────────

interface Epoch {
  readonly id: number;
  readonly touched: ReactiveNode[];
}

let epoch: Epoch | null = null;
let epochCounter = 0;
let changeDepth = 0;
let settling = false;
let settleCounter = 0;
const pendingDerived = new Set<DerivedNode>();

function openEpoch(): void {
  if (epoch !== null) return;
  epochCounter += 1;
  epoch = { id: epochCounter, touched: [] };
}

/** Takes the node's snapshot the first time it changes in the open epoch (R6.5 "settled value"). */
function touch(node: ReactiveNode): void {
  const e = epoch;
  if (e === null || node.snapEpoch === e.id) return;
  node.snapEpoch = e.id;
  node.snapValue = node.value;
  node.snapHasError = node.hasError;
  node.snapError = node.error;
  node.snapEvaluated = !(node instanceof DerivedNode) || node.evaluated;
  e.touched.push(node);
}

/** Makes the current value the settled value inside the open epoch (a baseline is no change, R4.1 step 3). */
function rebase(node: ReactiveNode): void {
  const e = epoch;
  if (e === null) return;
  if (node.snapEpoch !== e.id) {
    node.snapEpoch = e.id;
    e.touched.push(node);
  }
  node.snapValue = node.value;
  node.snapHasError = node.hasError;
  node.snapError = node.error;
  node.snapEvaluated = true;
}

/**
 * R6.5: the node changed in the epoch when its outcome differs from its settled outcome. Fix round 2 (R16): a
 * change from one error to a different error is a change (`errorsEqual`); the same error again is not.
 */
function isChanged(node: ReactiveNode, epochId: number): boolean {
  if (!node.snapEvaluated) return true;
  if (node.hasError !== node.snapHasError) return true;
  if (node.hasError) return !errorsEqual(node.snapError, node.error);
  if (node.cmpEpoch === epochId && Object.is(node.cmpA, node.snapValue) && Object.is(node.cmpB, node.value)) {
    return !node.cmpEqual;
  }
  return !compareValues(node.equals, node.snapValue, node.value);
}

function propagateCheck(node: DerivedNode): void {
  for (const observer of node.observers) {
    if (!(observer instanceof DerivedNode)) continue;
    pendingDerived.add(observer);
    if (observer.color === CLEAN) {
      observer.color = CHECK;
      propagateCheck(observer);
    }
  }
}

/** The node changed: direct dependents become dirty, transitive ones "check" (R6.3). */
function markObservers(node: ReactiveNode): void {
  for (const observer of node.observers) {
    if (!(observer instanceof DerivedNode)) continue;
    pendingDerived.add(observer);
    if (observer.color === CLEAN) {
      observer.color = DIRTY;
      propagateCheck(observer);
    } else {
      observer.color = DIRTY;
    }
  }
}

function ownerDisposing(node: ReactiveNode): boolean {
  return node.owner !== null && node.owner.disposing;
}

function evaluate(node: DerivedNode, report: boolean): void {
  const compute = node.compute;
  if (compute === null) {
    node.color = CLEAN;
    return;
  }
  touch(node);
  const hadValue = node.evaluated;
  const hadError = node.hasError;
  const previous = node.value;
  let next: unknown;
  let failed = false;
  let error: unknown;
  node.cycle = undefined;
  node.evaluating = true;
  try {
    next = runFrame(node, () => compute(previous), { evaluation: true });
  } catch (err) {
    failed = true;
    error = err;
  } finally {
    node.evaluating = false;
  }
  // R16: a cycle cannot be hidden. A getter that caught the cycle error (a predicate reads it as false, spec 04
  // §2) still fails with it.
  if (!failed && node.cycle !== undefined) {
    failed = true;
    error = node.cycle;
  }
  node.cycle = undefined;
  node.color = CLEAN;
  if (failed) {
    node.errorSettle = settling ? settleCounter : 0;
    const previousError = node.error;
    node.error = error;
    // Fix round 2 (R16): a transition into error, or a change to a different error, is a change. It is reported
    // once on the stream-fed route when a settle finds it.
    if (!hadError || !errorsEqual(previousError, error)) {
      node.hasError = true;
      node.version += 1;
      if (report && settling) reportStreamFed(error);
      markObservers(node);
    }
    return;
  }
  const changed = !hadValue || hadError || !compareForNode(node, previous, next);
  node.evaluated = true;
  node.hasError = false;
  node.error = undefined;
  if (changed) {
    node.value = next;
    node.version += 1;
    markObservers(node);
  }
}

function describe(node: ReactiveNode): string {
  return node.owner === null ? node.name : `${node.owner.label}.${node.name}`;
}

/** The error for a node read during its own evaluation; the node's evaluation then fails with it (R16). */
function cycleError(node: DerivedNode): ReactiveCycleError {
  const error = new ReactiveCycleError(`${describe(node)} was read during its own evaluation`);
  node.cycle ??= error;
  return error;
}

/** Brings `node` up to date: verify "check" sources first, evaluate when dirty (R6.4, R3.9). */
function refresh(node: DerivedNode, forRead: boolean): void {
  if (node.released || ownerDisposing(node)) return;
  if (node.evaluating) throw cycleError(node);
  if (node.color === CHECK) {
    for (const source of node.sources) {
      if (source instanceof DerivedNode) refresh(source, false);
      if (node.color !== CHECK) break;
    }
    if (node.color === CHECK) node.color = CLEAN;
  }
  // A node in error state re-evaluates on every read, at most once per settle (R3.9, R6.4).
  if (
    node.color === CLEAN &&
    forRead &&
    node.hasError &&
    !(settling && node.errorSettle === settleCounter)
  ) {
    node.color = DIRTY;
  }
  if (node.color === DIRTY) evaluate(node, true);
}

/** Evaluates the baseline of an activated computed: silent, unreported (R4.1 step 3, R16). */
export function baseline(node: DerivedNode): void {
  if (node.released || ownerDisposing(node)) return;
  // An earlier baseline of the same activation may have pulled this node already (at most once, R6.4).
  if (!(node.evaluated && node.color === CLEAN)) {
    node.color = DIRTY;
    evaluate(node, false);
  }
  rebase(node);
}

/** A tracked read of a source node (state, signal, announcement, invalidation). */
export function readSource(node: ReactiveNode): unknown {
  if (!node.released && !ownerDisposing(node)) track(node);
  return node.value;
}

/** A read of a derived node: tracked, pulled when dirty, rethrows its error (R3.9, R3.11). */
export function readDerived(node: DerivedNode, trackRead = true): unknown {
  if (node.released || ownerDisposing(node)) {
    // A disposed view-model's node returns its last value and records nothing (R5.6).
    if (node.hasError) throw node.error;
    return node.value;
  }
  if (node.evaluating) {
    // R16: the reader that closes a cycle records its edge before the error, so that every node of the cycle
    // recovers when the cycle opens.
    if (trackRead) track(node);
    throw cycleError(node);
  }
  try {
    refresh(node, true);
  } finally {
    // Tracked after the pull, so the frame records the version it actually read (R9.2).
    if (trackRead) track(node);
  }
  if (node.hasError) throw node.error;
  return node.value;
}

/** True when the node is clean and holds a memoized value (the staleness check reads it, R19.1). */
export function isMemoized(node: DerivedNode): boolean {
  return node.evaluated && !node.hasError && node.color === CLEAN && !node.released;
}

// ── Writes ───────────────────────────────────────────────────────────────────────────────────────────────────

/**
 * One write of several source nodes (R6.1, R6.2): equal values are skipped; nothing accepted, nothing done.
 * Returns true when the write was accepted.
 */
export function writeSources(changes: Iterable<readonly [ReactiveNode, unknown]>): boolean {
  assertWritable("A write");
  let accepted = false;
  for (const [node, value] of changes) {
    if (node.released || ownerDisposing(node)) continue;
    const old = node.value;
    // The equality runs before anything changes (R6.2), in its own context (R6.10).
    const equal = compareValues(node.equals, old, value);
    if (equal) continue;
    if (!accepted) {
      openEpoch();
      accepted = true;
    }
    touch(node);
    rememberComparison(node, old, value, false);
    node.value = value;
    node.version += 1;
    markObservers(node);
  }
  if (accepted) afterCommit();
  return accepted;
}

/**
 * One write that bumps version nodes: always accepted (R6.1 invalidate, R15.3 announcement bumps).
 *
 * `native` marks the commit of a native or announcement node by a library publication: inside a library operation
 * it waits for the operation's one settle (R15.2). A user write (`invalidate`, `memo.invalidate`, a late state
 * registration) settles at once, like any other write (fix round 2).
 */
export function bumpVersions(nodes: Iterable<ReactiveNode>, native: boolean): void {
  assertWritable(native ? "A library publication" : "An invalidation");
  let accepted = false;
  for (const node of nodes) {
    if (node.released || ownerDisposing(node)) continue;
    if (!accepted) {
      openEpoch();
      accepted = true;
    }
    touch(node);
    node.value = (node.value as number) + 1;
    node.version += 1;
    markObservers(node);
  }
  if (accepted && !(native && nativeDepth > 0)) afterCommit();
}

/** Inside a library operation: native commits wait for its settle (R15.2). */
let nativeDepth = 0;
/** Inside a library publication: the drain waits until the publication returns (R15.2, fix round 2). */
let holdDepth = 0;

/**
 * Runs one VMx library operation (a container or collection mutation, a selection change, a model assignment, a
 * resource load, a status transition, one publication of the dual-channel helper) as one write of its native
 * nodes (R15.2): the native commits made inside it settle once, when the outermost operation returns, after the
 * library's own messages, hooks and callbacks. A write that user code makes during the operation (a hub observer,
 * `onModelChanged`) is its own write: it settles at once, together with the native commits made before it.
 *
 * With `hold` (a library publication: the dual-channel helper, the local-only raise, a status transition, a command
 * raise), the drain also waits until the publication returns: the entries that user code queues while the library
 * delivers its own messages are delivered after them (fix round 2, R15.2).
 */
export function libraryOperation<T>(fn: () => T, hold: boolean): T {
  nativeDepth += 1;
  if (hold) holdDepth += 1;
  let failed = false;
  let error: unknown;
  let result: T | undefined;
  try {
    result = fn();
  } catch (err) {
    failed = true;
    error = err;
  }
  nativeDepth -= 1;
  if (hold) holdDepth -= 1;
  if (changeDepth === 0 && !settling) {
    try {
      if (nativeDepth === 0 && epoch !== null) settle();
      if (holdDepth === 0) drain();
    } catch (drainError) {
      if (!failed) throw drainError;
    }
  }
  if (failed) throw error;
  return result as T;
}

function afterCommit(): void {
  if (changeDepth > 0) return;
  settle();
  drain();
}

/** Runs `fn` as one change: its writes commit and settle once at the exit of the outermost scope (R7.*). */
export function change<R>(fn: () => R): R {
  assertWritable("change()");
  changeDepth += 1;
  openEpoch();
  let result: R | undefined;
  let failed = false;
  let error: unknown;
  try {
    result = fn();
  } catch (err) {
    failed = true;
    error = err;
  }
  changeDepth -= 1;
  if (changeDepth === 0) {
    try {
      settle();
      drain();
    } catch (drainError) {
      // The body error takes precedence over a diagnostic raised while draining (R7.3).
      if (!failed) throw drainError;
    }
  }
  if (failed) throw error;
  return result as R;
}

function isEager(node: DerivedNode): boolean {
  if (node.released || ownerDisposing(node)) return false;
  return node.eagerPublished || node.frameObservers > 0;
}

function byHeightThenIndex(a: ReactiveNode, b: ReactiveNode): number {
  return a.height - b.height || a.index - b.index;
}

/** Settles the open epoch and appends its entries to the drain queue (R6.4 to R6.6). */
function settle(): void {
  const e = epoch;
  if (e === null) return;
  settling = true;
  settleCounter += 1;
  try {
    while (pendingDerived.size > 0) {
      const batch: DerivedNode[] = [];
      for (const node of pendingDerived) if (isEager(node)) batch.push(node);
      pendingDerived.clear();
      if (batch.length === 0) break;
      batch.sort(byHeightThenIndex);
      for (const node of batch) refresh(node, false);
    }
  } finally {
    settling = false;
    epoch = null;
  }

  const changed = new Set<ReactiveNode>();
  for (const node of e.touched) {
    if (!node.released && isChanged(node, e.id)) changed.add(node);
  }

  // (a) announcements, by height then index (R6.6 a, R8.1).
  const announced: ReactiveNode[] = [];
  for (const node of changed) {
    if (node.publish !== null && !ownerDisposing(node)) announced.push(node);
  }
  announced.sort(byHeightThenIndex);
  for (const node of announced) {
    const publish = node.publish;
    if (publish !== null) enqueue({ owner: node.owner, key: describe(node), announce: true, run: publish });
  }

  // (b) command raises, then (c) reaction runs, each by index (R6.6 b, c). The edges are installed at read time,
  // so the observers of a changed node include a frame that is running now (an effect that wrote what it read).
  const affected = new Set<Frame>();
  for (const node of changed) {
    for (const observer of node.observers) {
      if (observer instanceof Frame) affected.add(observer);
    }
  }
  const frames = [...affected].sort((a, b) => a.index - b.index);
  for (const kind of ["command", "reaction"] as const) {
    for (const frame of frames) {
      if (frame.frameKind !== kind) continue;
      const entry = frame.affected();
      if (entry !== null) enqueue(entry);
    }
  }
}

// ── The drain ────────────────────────────────────────────────────────────────────────────────────────────────

/** The development bound: one entry (the same VM and name, command or reaction) processed this often (R9.6). */
const DRAIN_LIMIT = 10_000;
const queue: (QueueEntry | undefined)[] = [];
let head = 0;
let draining = false;
/** Queued announcement entries per owner, so that a direct send with nothing queued costs one lookup (R9.8). */
const queuedAnnouncements = new Map<NodeOwner, number>();
/** Producer flushes deliver synchronously; this bounds their nesting (R9.8). */
const FLUSH_DEPTH_LIMIT = 32;
let flushDepth = 0;

/** Appends an entry to the FIFO drain queue (R9.1). */
export function enqueue(entry: QueueEntry): void {
  queue.push(entry);
  if (entry.announce && entry.owner !== null) {
    queuedAnnouncements.set(entry.owner, (queuedAnnouncements.get(entry.owner) ?? 0) + 1);
  }
}

/** An entry left the queue (delivered, dropped or abandoned). */
function dequeued(entry: QueueEntry): void {
  if (!entry.announce || entry.owner === null) return;
  const count = (queuedAnnouncements.get(entry.owner) ?? 0) - 1;
  if (count > 0) queuedAnnouncements.set(entry.owner, count);
  else queuedAnnouncements.delete(entry.owner);
}

function overflowMessage(counts: ReadonlyMap<string, number>): string {
  const repeats = [...counts.entries()]
    .filter(([, count]) => count > 1)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([key, count]) => `${key} x${String(count)}`);
  return (
    `Reactive drain processed one entry more than ${String(DRAIN_LIMIT)} times; cycle involving: ` +
    repeats.join(", ")
  );
}

/**
 * Runs the queue in FIFO order until it is empty (R6.7, R9.2). A write made while a drain is active, while a
 * reaction starts or while a library publication delivers, only appends (R9.3, R12.9, R15.2), so delivery never
 * recurses on the call stack. Entries run untracked: an observer never records into the frame that caused the
 * delivery (R5.8).
 */
export function drain(): void {
  if (draining || holdDepth > 0) return;
  if (head >= queue.length) {
    queue.length = 0;
    head = 0;
    return;
  }
  draining = true;
  const savedTracker = tracker;
  tracker = null;
  // R9.6 (fix round 2): a cycle detector counts repetitions. One write that fans out to many distinct
  // announcements is finite and is never cut (MS4); an entry that keeps coming back is.
  const counts = developmentDiagnostics() ? new Map<string, number>() : null;
  let failed = false;
  let firstError: unknown;
  try {
    while (head < queue.length) {
      const entry = queue[head];
      head += 1;
      if (entry === undefined) continue;
      dequeued(entry);
      if (counts !== null) {
        const count = (counts.get(entry.key) ?? 0) + 1;
        counts.set(entry.key, count);
        if (count > DRAIN_LIMIT) throw new ReactiveOverflowError(overflowMessage(counts));
      }
      if (entry.owner !== null && entry.owner.disposing) continue;
      try {
        entry.run();
      } catch (error) {
        if (!failed) {
          failed = true;
          firstError = error;
        }
      }
    }
  } finally {
    // An abandoned rest of the queue (the development overflow) leaves no pending count behind.
    for (let i = head; i < queue.length; i += 1) {
      const entry = queue[i];
      if (entry !== undefined) dequeued(entry);
    }
    queue.length = 0;
    head = 0;
    draining = false;
    tracker = savedTracker;
  }
  if (failed) throw firstError;
}

/**
 * Runs `fn` as one drain entry would (R12.9): writes made inside it settle at once, and the entries they queue,
 * including a re-run of the reaction that is starting, are delivered after `fn` returns, never inside it. Inside an
 * active drain or a library publication `fn` simply runs, and the drain delivers what it queued later.
 */
export function runAsDrainEntry<T>(fn: () => T): T {
  if (draining || holdDepth > 0) return untracked(fn);
  draining = true;
  let result: T | undefined;
  let failed = false;
  let error: unknown;
  try {
    result = untracked(fn);
  } catch (err) {
    failed = true;
    error = err;
  }
  draining = false;
  if (changeDepth === 0) {
    try {
      drain();
    } catch (drainError) {
      if (!failed) throw drainError;
    }
  }
  if (failed) throw error;
  return result as T;
}

/**
 * Producer order (R9.8): before `owner` sends a message outside the graph, deliver, in queue order, every queued
 * announcement up to and including the last one of `owner`. Fix round 2 (OR5): the end is found again after each
 * delivery, so an announcement of `owner` that an observer queues during the flush also precedes the send. Other
 * entries (command raises, reaction runs) keep their places. The deliveries run untracked.
 */
export function flushProducer(owner: NodeOwner): void {
  // A flush delivers synchronously. Past a fixed depth (an observer loop that keeps sending), the entries stay in
  // the queue, where the drain delivers them in order and its development bound (R9.6) names the cycle.
  if (!queuedAnnouncements.has(owner) || flushDepth >= FLUSH_DEPTH_LIMIT) return;
  const savedTracker = tracker;
  tracker = null;
  flushDepth += 1;
  try {
    // One entry at a time: a nested flush (a delivery that makes another direct send) sees the rest in order.
    for (let i = head; i < queue.length && queuedAnnouncements.has(owner); i += 1) {
      const entry = queue[i];
      if (entry === undefined || !entry.announce) continue;
      queue[i] = undefined;
      dequeued(entry);
      if (entry.owner !== null && entry.owner.disposing) continue;
      try {
        entry.run();
      } catch (error) {
        reportStreamFed(error);
      }
    }
  } finally {
    flushDepth -= 1;
    tracker = savedTracker;
  }
}

/** Schedules entries outside a settle (a restarted reaction, R13.2) and drains when idle. */
export function enqueueAndDrain(entries: readonly QueueEntry[]): void {
  for (const entry of entries) enqueue(entry);
  if (changeDepth === 0) drain();
}

// ── Release ──────────────────────────────────────────────────────────────────────────────────────────────────

function clearSources(consumer: Consumer): void {
  consumer.sources = [];
  if (consumer instanceof Frame) {
    consumer.sourceVersions = [];
    consumer.unionSet = null;
  }
}

/** Removes every edge from the consumer's sources (a command raise, a reaction stop, a release). */
export function releaseConsumer(consumer: Consumer): void {
  for (const source of consumer.sources) unlink(source, consumer);
  clearSources(consumer);
}

/** Drops `node` from the sources of one consumer, keeping the parallel versions aligned. */
function removeSource(consumer: Consumer, node: ReactiveNode): void {
  const index = consumer.sources.indexOf(node);
  if (index < 0) return;
  consumer.sources.splice(index, 1);
  if (consumer instanceof Frame) {
    consumer.sourceVersions.splice(index, 1);
    consumer.unionSet?.delete(node);
  }
}

/** Releases a node: no edge to or from it remains; readers keep its last value (R17.1). */
export function releaseNode(node: ReactiveNode): void {
  if (node.released) return;
  node.released = true;
  node.publish = null;
  for (const observer of node.observers) {
    removeSource(observer, node);
    if (!observer.isDerived && node instanceof DerivedNode) node.frameObservers -= 1;
  }
  node.observers.clear();
  if (node instanceof DerivedNode) {
    releaseConsumer(node);
    node.compute = null;
    node.color = CLEAN;
    pendingDerived.delete(node);
  }
}

/** Releases a frame for good: no edge remains, also from a run in progress (R17.1). */
export function forgetFrame(frame: Frame): void {
  frame.released = true;
  releaseConsumer(frame);
}
