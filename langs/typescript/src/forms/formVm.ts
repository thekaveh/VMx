/**
 * FormVM<TM> — snapshot/revert edit lifecycle ViewModel.
 *
 * See spec/20-form-vm.md and ADR-0030.
 */
import { Subject } from "rxjs";
import type { Observable } from "rxjs";
import { BuilderValidationError } from "../builders/exceptions.js";
import { RelayCommand } from "../commands/relayCommand.js";
import { FormRevertedMessage } from "../messages/formReverted.js";
import { PropertyChangedMessage } from "../messages/propertyChanged.js";
import type { IMessageHub } from "../services/messageHub.js";
import { NullMessageHub } from "../services/nullMessageHub.js";

/** Consumer-supplied async persister delegate. Throw on failure. */
export type Persister<TM> = (model: TM) => Promise<void>;

/**
 * Optional custom snapshot function. Defaults to `structuredClone`. Pair a
 * custom implementation with a matching {@link ModelEquals} predicate so
 * snapshot, revert, and dirty-tracking semantics stay aligned.
 */
export type Snapshotter<TM> = (model: TM) => TM;

/** Derives the next pristine model from the captured, persisted value. */
export type ResetOnApproved<TM> = (model: TM) => TM;

/** Field-level validator. Return a string error, or null/undefined when valid. */
export type FieldValidator<TM> = (model: TM) => string | null | undefined;

/** Model-level validator returning field-name errors. Null entries clear fields. */
export type ModelValidator<TM> = (model: TM) => Record<string, string | null | undefined>;

/**
 * Optional custom equality predicate for dirty-tracking. Returns `true` when
 * `a` and `b` are considered the *same* (i.e. the form is clean). Defaults to
 * {@link deepEquals}.
 */
export type ModelEquals<TM> = (a: TM, b: TM) => boolean;

type SnapshotPhase =
  | "construction"
  | "approve snapshot advance"
  | "approve reset model"
  | "approve reset snapshot"
  | "deny/revert";

/**
 * The result of preparing a model update (§5.4): the next model and error map,
 * and the dirty and valid state before and after it. Every consumer callback
 * the update needs has already run, so committing it runs none.
 */
interface PreparedUpdate<TM> {
  readonly model: TM;
  readonly errors: Record<string, string>;
  readonly wasDirty: boolean;
  readonly wasValid: boolean;
  readonly isDirty: boolean;
}

/**
 * An update queued during an approval's pre-publication window (§5.3): set a
 * model, or deny. It replays as a new call after `onApproved`.
 */
type QueuedUpdate<TM> =
  | { readonly kind: "set"; readonly model: TM }
  | { readonly kind: "deny" };

/**
 * The notifications of one or more updates or approval admissions, in the
 * order they are sent (§5.4, ADR-0180): every error map first, then the other
 * notifications, then the persister starts of nested approvals.
 */
interface Notices {
  readonly errors: Array<() => void>;
  readonly afterScope: Array<() => void>;
  readonly starts: Array<() => void>;
}

function noNotices(): Notices {
  return { errors: [], afterScope: [], starts: [] };
}

function appendNotices(target: Notices, source: Notices): void {
  target.errors.push(...source.errors);
  target.afterScope.push(...source.afterScope);
  target.starts.push(...source.starts);
}

function hasReachableEnumerableAccessor(
  value: unknown,
  seen = new Set<object>(),
): boolean {
  if ((typeof value !== "object" && typeof value !== "function") || value === null) {
    return false;
  }

  const object = value;
  if (seen.has(object)) return false;
  seen.add(object);

  let descriptors: PropertyDescriptorMap;
  try {
    descriptors = Object.getOwnPropertyDescriptors(object);
  } catch {
    return true;
  }

  // Structured clone traverses enumerable string-keyed properties but ignores
  // symbol-keyed properties. Read descriptor values only; never invoke getters.
  for (const key of Object.keys(descriptors)) {
    const descriptor = descriptors[key];
    if (descriptor?.enumerable !== true) continue;
    if (!("value" in descriptor)) return true;
    if (hasReachableEnumerableAccessor(descriptor.value, seen)) return true;
  }

  try {
    // Structured clone follows engine-owned, non-enumerable Error slots such
    // as `cause`; omit localization rather than risk re-running nested accessors.
    if (value instanceof Error) {
      return true;
    } else if (value instanceof Map) {
      for (const [key, entryValue] of Map.prototype.entries.call(value)) {
        if (hasReachableEnumerableAccessor(key, seen)) return true;
        if (hasReachableEnumerableAccessor(entryValue, seen)) return true;
      }
    } else if (value instanceof Set) {
      for (const entryValue of Set.prototype.values.call(value)) {
        if (hasReachableEnumerableAccessor(entryValue, seen)) return true;
      }
    }
  } catch {
    return true;
  }

  return false;
}

function findUncloneableTopLevelField(model: unknown): string | undefined {
  if ((typeof model !== "object" && typeof model !== "function") || model === null) {
    return undefined;
  }

  let descriptors: PropertyDescriptorMap;
  try {
    descriptors = Object.getOwnPropertyDescriptors(model);
  } catch {
    // Proxies may reject descriptor inspection. Context is still useful even
    // when safe field localization is impossible.
    return undefined;
  }

  if (hasReachableEnumerableAccessor(model)) return undefined;

  for (const key of Object.keys(descriptors)) {
    const descriptor = descriptors[key];
    if (descriptor?.enumerable !== true || !("value" in descriptor)) continue;
    try {
      structuredClone(descriptor.value);
    } catch {
      return key;
    }
  }
  return undefined;
}

function defaultSnapshotError(
  model: unknown,
  phase: SnapshotPhase,
  cause: unknown,
): Error {
  const field = findUncloneableTopLevelField(model);
  const fieldContext = field === undefined
    ? ""
    : ` for top-level field ${JSON.stringify(field)}`;
  return new Error(
    `FormVM default structuredClone snapshot failed during ${phase}${fieldContext}. `
      + "Supply a custom snapshotter and a matching equals predicate through "
      + "FormVM options or FormVM.builder().snapshotter(...).equals(...).",
    { cause },
  );
}

// The error kinds structured cloning keeps. It rebuilds an error from its
// `name`, and any other name (a custom subclass, `AggregateError`) comes back
// as a plain `Error`.
const CLONEABLE_ERROR_NAMES: ReadonlySet<string> = new Set([
  "Error",
  "EvalError",
  "RangeError",
  "ReferenceError",
  "SyntaxError",
  "TypeError",
  "URIError",
]);

function errorKind(error: Error): string {
  // Cloning reads `name` as it is, so a non-string name is not a kept kind. An
  // inherited accessor can throw, as on a forged DOMException; that is no kind.
  let name: unknown;
  try {
    name = error.name;
  } catch {
    return "Error";
  }
  return typeof name === "string" && CLONEABLE_ERROR_NAMES.has(name) ? name : "Error";
}

/**
 * An own data property of an error, as structured cloning reads it. Inherited
 * values and accessors are not cloned, so they compare as absent.
 */
function ownErrorValue(error: Error, key: "message" | "cause"): { value: unknown } | undefined {
  const descriptor = Object.getOwnPropertyDescriptor(error, key);
  return descriptor !== undefined && "value" in descriptor
    ? { value: descriptor.value }
    : undefined;
}

function errorMessage(error: Error): string | undefined {
  const message = ownErrorValue(error, "message");
  return message === undefined ? undefined : String(message.value);
}

// A DOMException clones as a DOMException with its `name` and `message`, which
// it reads through prototype accessors. Its `cause`, custom properties, and
// subclass are dropped.

/** The cloned parts of a genuine DOMException; undefined for any other value. */
function domExceptionParts(error: Error): { name: unknown; message: unknown } | undefined {
  if (typeof DOMException === "undefined" || !(error instanceof DOMException)) return undefined;
  try {
    // The base accessors read the internal slots, so a subclass override is
    // ignored, and they throw for a value that only inherits the prototype.
    return {
      name: Reflect.get(DOMException.prototype, "name", error),
      message: Reflect.get(DOMException.prototype, "message", error),
    };
  } catch {
    return undefined;
  }
}

function isBuffer(value: object): value is ArrayBuffer | SharedArrayBuffer {
  return value instanceof ArrayBuffer
    || (typeof SharedArrayBuffer !== "undefined" && value instanceof SharedArrayBuffer);
}

function sameBinaryConstructor(a: object, b: object): boolean {
  return Object.getPrototypeOf(a) === Object.getPrototypeOf(b);
}

function equalBytes(
  a: ArrayBufferLike,
  aOffset: number,
  b: ArrayBufferLike,
  bOffset: number,
  byteLength: number,
): boolean {
  const aBytes = new Uint8Array(a, aOffset, byteLength);
  const bBytes = new Uint8Array(b, bOffset, byteLength);
  for (let index = 0; index < byteLength; index += 1) {
    if (aBytes[index] !== bBytes[index]) return false;
  }
  return true;
}

/** Compares two boxed primitives with the primitive rules of {@link deepEquals}. */
function boxedValuesEqual(a: { valueOf(): unknown }, b: { valueOf(): unknown }): boolean {
  const x = a.valueOf();
  const y = b.valueOf();
  return x === y || (x !== x && y !== y);
}

/**
 * Structural deep-equality used by {@link FormVM.isDirty} when no custom
 * `equals` is supplied. It mirrors the depth the default `structuredClone`
 * snapshotter clones, so comparison and snapshotting stay internally
 * consistent. Unlike the previous `JSON.stringify` comparison it:
 *
 * - never throws on `BigInt` (compared with `===`) or circular references
 *   (guarded with a visited-pair set);
 * - compares `Date` by instant, `Map`/`Set` by contents, `RegExp` by
 *   source/flags, binary buffers/views by constructor and bytes, and arrays and
 *   plain objects by value;
 * - compares `Error` values by what `structuredClone` keeps: the error kind
 *   (the standard error named by `name`, otherwise `Error`), the own
 *   `message`, and the own `cause`, compared recursively. The stack, custom
 *   properties, and subclass identity are not kept by the clone, so they are
 *   not compared;
 * - distinguishes an `undefined`-valued key from a missing key (as
 *   `structuredClone` preserves it);
 * - treats `NaN` as equal to `NaN` (and `+0`/`-0` as equal) for dirty-tracking.
 *
 * Map/Set membership uses SameValueZero (the engine's native `has`), so
 * object-typed Map keys / Set members are compared by reference — adequate for
 * the primitive-keyed models dirty-tracking targets.
 */
export function deepEquals(
  a: unknown,
  b: unknown,
  seen?: Map<unknown, Set<unknown>>,
): boolean {
  // Identity / primitive fast path (also makes +0 === -0 → equal).
  if (a === b) return true;

  // NaN: treat NaN as equal to NaN; any other number pair already failed `===`.
  if (typeof a === "number" && typeof b === "number") {
    return a !== a && b !== b;
  }

  // Anything non-object (incl. bigint, mismatched primitive types, null) that
  // did not pass `===` above is unequal. BigInt's only equal path is `===`.
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) {
    return false;
  }

  // Circular-reference guard: if this exact (a, b) pair is already in flight we
  // treat it as equal — any real difference surfaces on a finite branch first.
  const visited = seen ?? new Map<unknown, Set<unknown>>();
  const partners = visited.get(a);
  if (partners) {
    if (partners.has(b)) return true;
    partners.add(b);
  } else {
    visited.set(a, new Set([b]));
  }

  if (a instanceof Date || b instanceof Date) {
    if (!(a instanceof Date) || !(b instanceof Date)) return false;
    // Compare by instant; an invalid Date (NaN time) equals another invalid
    // Date, as structuredClone preserves it.
    const aTime = a.getTime();
    const bTime = b.getTime();
    return aTime === bTime || (aTime !== aTime && bTime !== bTime);
  }

  // Boxed primitives keep their value through structuredClone, so compare it
  // with the same rules as primitives: NaN equals NaN, and +0 equals -0.
  // Each constructor is checked directly: V8 does not specialize
  // `instanceof` against a loop variable, which doubled the cost (#767).
  if (a instanceof Number || b instanceof Number) {
    return a instanceof Number && b instanceof Number && boxedValuesEqual(a, b);
  }
  if (a instanceof Boolean || b instanceof Boolean) {
    return a instanceof Boolean && b instanceof Boolean && boxedValuesEqual(a, b);
  }
  if (a instanceof String || b instanceof String) {
    return a instanceof String && b instanceof String && boxedValuesEqual(a, b);
  }
  if (a instanceof BigInt || b instanceof BigInt) {
    return a instanceof BigInt && b instanceof BigInt && boxedValuesEqual(a, b);
  }

  if (a instanceof RegExp || b instanceof RegExp) {
    return (
      a instanceof RegExp &&
      b instanceof RegExp &&
      a.source === b.source &&
      a.flags === b.flags
    );
  }

  if (a instanceof Error || b instanceof Error) {
    if (!(a instanceof Error) || !(b instanceof Error)) return false;
    const aDom = domExceptionParts(a);
    const bDom = domExceptionParts(b);
    if (aDom !== undefined || bDom !== undefined) {
      return aDom !== undefined
        && bDom !== undefined
        && aDom.name === bDom.name
        && aDom.message === bDom.message;
    }
    if (errorKind(a) !== errorKind(b) || errorMessage(a) !== errorMessage(b)) return false;
    const aCause = ownErrorValue(a, "cause");
    const bCause = ownErrorValue(b, "cause");
    if (aCause === undefined || bCause === undefined) return aCause === bCause;
    return deepEquals(aCause.value, bCause.value, visited);
  }

  const aIsBuffer = isBuffer(a);
  const bIsBuffer = isBuffer(b);
  if (aIsBuffer || bIsBuffer) {
    return aIsBuffer
      && bIsBuffer
      && sameBinaryConstructor(a, b)
      && a.byteLength === b.byteLength
      && equalBytes(a, 0, b, 0, a.byteLength);
  }

  const aIsView = ArrayBuffer.isView(a);
  const bIsView = ArrayBuffer.isView(b);
  if (aIsView || bIsView) {
    return aIsView
      && bIsView
      && sameBinaryConstructor(a, b)
      && a.byteLength === b.byteLength
      && equalBytes(a.buffer, a.byteOffset, b.buffer, b.byteOffset, a.byteLength);
  }

  const aIsArray = Array.isArray(a);
  const bIsArray = Array.isArray(b);
  if (aIsArray || bIsArray) {
    if (!aIsArray || !bIsArray || a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      if (!deepEquals(a[i], b[i], visited)) return false;
    }
    return true;
  }

  if (a instanceof Map || b instanceof Map) {
    if (!(a instanceof Map) || !(b instanceof Map) || a.size !== b.size) return false;
    for (const [k, v] of a) {
      if (!b.has(k) || !deepEquals(v, b.get(k), visited)) return false;
    }
    return true;
  }

  if (a instanceof Set || b instanceof Set) {
    if (!(a instanceof Set) || !(b instanceof Set) || a.size !== b.size) return false;
    for (const v of a) {
      if (!b.has(v)) return false;
    }
    return true;
  }

  // Plain objects: own enumerable string keys, including undefined-valued keys.
  const aObj = a as Record<string, unknown>;
  const bObj = b as Record<string, unknown>;
  const aKeys = Object.keys(aObj);
  const bKeys = Object.keys(bObj);
  if (aKeys.length !== bKeys.length) return false;
  for (const key of aKeys) {
    if (!Object.prototype.hasOwnProperty.call(bObj, key)) return false;
    if (!deepEquals(aObj[key], bObj[key], visited)) return false;
  }
  return true;
}

/** Constructor options for FormVM. */
export interface FormVMOptions<TM> {
  /** Initial domain model; also becomes the initial snapshot. */
  initial: TM;
  /** Async persist delegate. Throw on failure. */
  persister: Persister<TM>;
  /** Message hub. Defaults to NullMessageHub.INSTANCE. */
  hub?: IMessageHub;
  /**
   * When true, `approveCommand.canExecute()` returns false when `isDirty` is false.
   * Default: false.
   */
  strict?: boolean;
  /**
   * Custom snapshot function. Defaults to `structuredClone` — a structured
   * deep clone; nested references are independent between Model and Snapshot.
   * Supply a custom snapshotter if you need shallow semantics or your model
   * contains values structuredClone cannot serialize, and pair it with a
   * matching `equals` predicate. A built-in clone failure is rethrown with the
   * FormVM phase and, when safely determinable, the owning top-level field;
   * the native error remains available as `cause`. Errors from a supplied
   * snapshotter pass through unchanged.
   */
  snapshotter?: Snapshotter<TM>;
  /**
   * Custom equality predicate for dirty-tracking (`isDirty = !equals(model,
   * snapshot)`). Defaults to {@link deepEquals}, a structural deep-equal that
   * matches what the default `structuredClone` snapshotter clones (handles
   * Date/Map/Set/BigInt/circular refs). Supply your own to compare on a subset
   * of fields or with reference semantics.
   */
  equals?: ModelEquals<TM>;
  /** Optional field validators keyed by idiomatic field/property name. */
  validators?: Record<string, FieldValidator<TM>>;
  /** Optional model-level validator returning field-name errors. */
  modelValidator?: ModelValidator<TM>;
  /** Optional post-persist callback that derives the next pristine model. */
  resetOnApproved?: ResetOnApproved<TM>;
}

/**
 * ViewModel that wraps a mutable domain model with an edit lifecycle.
 *
 * Captures a snapshot at construction; allows mutation via {@link setModel};
 * provides {@link denyCommand} (revert) and {@link approveCommand} (persist).
 */
export class FormVM<TM> {
  readonly #persister: Persister<TM>;
  readonly #snapshotter: Snapshotter<TM>;
  readonly #usesDefaultSnapshotter: boolean;
  readonly #equals: ModelEquals<TM>;
  readonly #validators: Record<string, FieldValidator<TM>>;
  readonly #modelValidator: ModelValidator<TM> | null;
  readonly #resetOnApproved: ResetOnApproved<TM> | null;
  readonly #strict: boolean;
  readonly #hub: IMessageHub;

  #model: TM;
  #snapshot: TM;
  #errors: Record<string, string>;
  #disposed = false;
  #activeSyncOperations = 0;
  #teardownPending = false;
  // Single-flight admission (§5.3): set when an approval is admitted, cleared
  // when it settles. Disposal leaves it set; a disposed form is inert anyway.
  #approvalInFlight = false;
  // The approval's pre-publication window (§5.3): open from the start of the
  // post-persist commit until onApproved delivery starts. A setModel or deny
  // made inside it is prepared, then queued in #queuedUpdates, and replays
  // after onApproved.
  #approvalPrePublishing = false;
  #queuedUpdates: QueuedUpdate<TM>[] = [];
  // Update generation (§5.4): advanced by every committed state change (an
  // assignment, a revert, or an approval snapshot advance or reset) and by
  // every update queued during approval publication (§5.3). A preparation that
  // finishes under a newer generation is stale.
  #generation = 0;
  // Nested updates (§5.4, ADR-0180): the setModel and deny frames that are
  // running their preparation or committing. A call nested in one of them
  // queues its notifications in #pendingNotices for the outermost frame.
  #preparationDepth = 0;
  #pendingNotices = noNotices();
  // True while the outermost update sends its error maps. An update made from
  // an errorsChanged observer then queues its notifications in
  // #scopedNotices; its error maps follow the current ones, and the rest
  // follows the outer update's notifications.
  #deliveringErrors = false;
  #scopedNotices = noNotices();

  readonly #onApproved = new Subject<TM>();
  readonly #approveErrors = new Subject<unknown>();
  readonly #errorsChanged = new Subject<Record<string, string>>();
  readonly #canExecuteTrigger = new Subject<void>();

  readonly denyCommand: RelayCommand;
  readonly approveCommand: RelayCommand;

  /**
   * Entry point for the immutable fluent builder. Mirrors the
   * `.builder()` convention used by the other VM family members
   * (`ComponentVM`, `CompositeVM`, …). See ADR-0035 §2 FV1 / FV2.
   */
  static builder<TM>(): FormVMBuilder<TM> {
    return new FormVMBuilder<TM>();
  }

  constructor(options: FormVMOptions<TM>) {
    const {
      initial,
      persister,
      hub,
      strict = false,
      snapshotter,
      equals,
      validators,
      modelValidator,
      resetOnApproved,
    } = options;

    if (initial === null || initial === undefined) {
      throw new Error("initial must not be null or undefined");
    }
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
    if (persister === null || persister === undefined) {
      throw new Error("persister must not be null or undefined");
    }

    this.#persister = persister;
    this.#hub = hub ?? NullMessageHub.INSTANCE;
    this.#strict = strict;
    this.#usesDefaultSnapshotter = snapshotter === undefined;
    this.#snapshotter = snapshotter ?? ((m: TM) => structuredClone(m));
    this.#equals = equals ?? ((a: TM, b: TM) => deepEquals(a, b));
    this.#validators = fieldRecord(validators);
    this.#modelValidator = modelValidator ?? null;
    this.#resetOnApproved = resetOnApproved ?? null;

    this.#model = initial;
    this.#snapshot = this.#takeSnapshot(initial, "construction");
    // The same preparation as an update (§5.4): a throwing validator fails
    // construction, so no form exists.
    this.#errors = this.#validate(initial);

    this.denyCommand = RelayCommand.builder()
      .task(() => this.#deny())
      .build();

    this.approveCommand = RelayCommand.builder()
      .task(() => {
        // Fire-and-forget: ApproveCommand.execute() is synchronous (void), so a
        // rejecting persister cannot propagate to the caller. Surface it on the
        // approveErrors channel instead of swallowing it (VMX-008) — a bare
        // `void` here would also turn the rejection into a fatal unhandled
        // rejection on Node >= 15. Callers who want to await the failure inline
        // use approveAsync() directly.
        void this.approveAsync().catch((err: unknown) => {
          // A failure observed after disposal is intentionally dropped. If an
          // observer disposes reentrantly while this admitted publication is in
          // flight, defer teardown until every current observer has received it.
          if (this.#disposed) return;
          this.#beginSyncOperation();
          try {
            this.#approveErrors.next(err);
          } finally {
            this.#endSyncOperation();
          }
        });
      })
      // While an approval is in flight the command is disabled, so execute()
      // refuses a second approval before reaching the task (§5.3).
      .predicate(() =>
        !this.#approvalInFlight && this.isValid && (!this.#strict || this.isDirty))
      .triggers(this.#canExecuteTrigger)
      .build();
  }

  // ── Properties ─────────────────────────────────────────────────────────────

  /** Live, editable model. Set via {@link setModel} to mutate. */
  get model(): TM {
    return this.#model;
  }

  /** Read-only snapshot captured at construction (until next approve). */
  get snapshot(): TM {
    return this.#snapshot;
  }

  /**
   * True when `model` is structurally not equal to `snapshot`.
   * Uses the injectable `equals` predicate (default {@link deepEquals}).
   */
  get isDirty(): boolean {
    return !this.#equals(this.#model, this.#snapshot);
  }

  /** Current validation errors keyed by field/property name. */
  get errors(): Record<string, string> {
    return { ...this.#errors };
  }

  /** True when the current model has no validation errors. */
  get isValid(): boolean {
    return Object.keys(this.#errors).length === 0;
  }

  /** Observable that emits the current model after each successful persist. */
  get onApproved(): Observable<TM> {
    return this.#onApproved.asObservable();
  }

  /**
   * Observable that surfaces the error thrown by the persister when the approve
   * COMMAND (`approveCommand.execute()`) fails. That path is fire-and-forget
   * (`RelayCommand.execute` is `void`), so a rejection cannot propagate to the
   * caller — it is emitted here instead of being swallowed (VMX-008). The
   * awaitable {@link approveAsync} path keeps its throw behavior; await it
   * directly to handle the failure inline. Completes on {@link dispose}.
   */
  get approveErrors(): Observable<unknown> {
    return this.#approveErrors.asObservable();
  }

  /** Emits only when the effective validation error map changes. */
  get errorsChanged(): Observable<Record<string, string>> {
    return this.#errorsChanged.asObservable();
  }

  /** Return the current validation error for a field, if any. */
  fieldError(field: string): string | undefined {
    return ownValue(this.#errors, field);
  }

  // ── Mutation ───────────────────────────────────────────────────────────────

  /**
   * Replaces the current model. May change `isDirty`; in strict mode fires
   * `approveCommand.canExecuteChanged` on dirty transitions.
   * A call begun after disposal returns before inspecting the candidate.
   *
   * The update is failure-atomic (§5.4): the equality comparisons and the
   * validators run before anything is committed. If one throws, the error
   * propagates and the form is unchanged, with nothing published. If a
   * callback disposes the form or commits another update, this call commits
   * and publishes nothing.
   *
   * A call made from `resetOnApproved`, the approval's snapshotter or
   * validators, or a settlement `errorsChanged` or `canExecuteChanged`
   * observer is queued (§5.3, ADR-0174). It runs the same preparation first,
   * so a failure still reaches the caller, but it commits and publishes
   * nothing until it replays after `onApproved`.
   *
   * A call made from a preparation callback of another `setModel` or deny,
   * or from an `errorsChanged` observer of one, commits at once but returns
   * before its notifications. The outermost update sends them before it
   * returns, and drops them once the form is disposed (§5.4, ADR-0180).
   */
  setModel(model: TM): void {
    if (this.#disposed) return;
    // Reject a missing model before any deferral (spec/20 §5.2), so a null
    // queued during approval settlement cannot fail that approval later.
    if (model === null || model === undefined) {
      throw new Error("model must not be null or undefined");
    }
    this.#runUpdate((own) => this.#applySetModel(model, own));
  }

  #applySetModel(model: TM, own: Notices): void {
    // Preparation: every consumer callback runs before any commit.
    const generation = this.#generation;
    const unchanged = this.#equals(this.#model, model);
    if (this.#approvalPrePublishing) {
      // §5.3: prepare at call time so a failure reaches this caller. An
      // equal candidate is still queued, because an earlier queued update
      // can change the model before this one replays. The replay prepares
      // again, so the result here is discarded.
      this.#prepare(model);
      this.#enqueue(generation, { kind: "set", model });
      return;
    }
    if (unchanged) return;
    const update = this.#prepare(model);
    if (this.#isStale(generation)) return;

    // Commit in one step, then queue the notifications; no consumer callback
    // runs between.
    const errorsChanged = this.#commit(update);
    if (errorsChanged) {
      const errors = { ...update.errors };
      own.errors.push(() => this.#errorsChanged.next(errors));
    }
    if (this.#approveStateChanged(update)) {
      own.afterScope.push(() => this.#canExecuteTrigger.next());
    }
    const message = PropertyChangedMessage.create(this, "FormVM", "model");
    own.afterScope.push(() => this.#hub.send(message));
  }

  // ── Async core ─────────────────────────────────────────────────────────────

  /**
   * Awaitable approve flow. Invokes the persister, advances `snapshot` on success,
   * and fires `onApproved`. Throws when the persister throws (no state mutation).
   * Only one approval runs at a time: a call made while another is in flight
   * returns without persisting, mutating, throwing, or emitting (§5.3).
   *
   * A `setModel` or deny queued during the post-persist commit or settlement
   * replays after `onApproved` (or after a failed commit's settlement). If a
   * replay throws, the later ones still run, and the first replay failure is
   * thrown here after the last one, unless the approval already failed.
   *
   * A call made from a preparation callback of a `setModel` or deny, or from
   * an `errorsChanged` observer of one, is admitted at once. Its
   * `canExecuteChanged` and its persister call wait for the outermost update
   * (§5.4, ADR-0180). A `dispose()` before the persister starts prevents the
   * call, and the returned promise then resolves (§10).
   */
  async approveAsync(): Promise<void> {
    // A disposed form is a full no-op — the persister must not be invoked
    // (symmetric with the deny guard).
    if (this.#disposed) return;
    if (!this.isValid) return;
    // A refused call is observably the same as approving an invalid form,
    // whether it comes from a caller, the persister, or an observer.
    if (this.#approvalInFlight) return;

    // Admission: mark the approval in flight before the capture and the
    // persister call, then announce the disabled command once.
    this.#approvalInFlight = true;
    const current = this.#model;
    if (this.#isNested()) {
      // §5.4: the outermost update sends the admission notification, then
      // calls the persister after the rest of its queue.
      await new Promise<void>((resolve, reject) => {
        this.#takeNotices({
          errors: [],
          afterScope: [() => this.#canExecuteTrigger.next()],
          starts: [() => {
            void this.#runAdmitted(current).then(resolve, reject);
          }],
        });
      });
      return;
    }
    this.#raiseApproveCanExecuteChanged();
    await this.#runAdmitted(current);
  }

  /**
   * Runs an admitted approval: calls the persister, then commits and settles.
   * A form disposed since admission, by an admission observer or before a
   * nested approval's start, never calls the persister (§10).
   */
  async #runAdmitted(current: TM): Promise<void> {
    if (this.#disposed) return;

    try {
      // May throw — intentional. No state mutation if this throws.
      await this.#persister(current);
    } catch (error: unknown) {
      // Failure or cancellation settles the approval before the error reaches
      // its one channel: this awaiter, or approveErrors on the command path.
      this.#settleFailedApproval();
      throw error;
    }

    // dispose() may have run during the await; rxjs would silently no-op
    // the emissions below, but the snapshot advance is a real state
    // mutation on a disposed form (C#/Python guard identically). The
    // analyzer narrows #disposed from the entry guard, but the await is a
    // genuine interleaving point.
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
    if (this.#disposed) return;

    // §5.3: the pre-publication window opens with the post-persist commit, so a
    // setModel or deny from the reset, the snapshotter, a validator, or a
    // settlement observer is queued.
    this.#approvalPrePublishing = true;
    this.#beginSyncOperation();
    let failure: { readonly error: unknown } | undefined;
    try {
      this.#commitAndPublishApproval(current);
    } catch (error: unknown) {
      failure = { error };
    } finally {
      this.#approvalPrePublishing = false;
      this.#endSyncOperation();
    }

    // The queued updates replay after the publication scope ends. A failure
    // the approval already carries wins over a replay failure.
    const replayFailure = this.#replayQueuedUpdates();
    const routed = failure ?? replayFailure;
    if (routed !== undefined) throw routed.error;
  }

  /**
   * Commits a persisted approval, then publishes its settlement and
   * `onApproved`. A failed commit settles the approval as failed and rethrows.
   * Runs inside the pre-publication window and closes it before `onApproved`
   * delivery, or before a failed settlement's notification.
   */
  #commitAndPublishApproval(current: TM): void {
    // Success: atomically install the configured reset state, or preserve the
    // legacy snapshot-advance behavior when no reset is configured.
    let errorsChanged = false;
    try {
      if (this.#resetOnApproved !== null) {
        // Prepare callback output, two independent values, and validation
        // before committing any local field. A failure therefore leaves
        // state intact.
        const reset = this.#resetOnApproved(current);
        const nextModel = this.#takeSnapshot(reset, "approve reset model");
        const nextSnapshot = this.#takeSnapshot(reset, "approve reset snapshot");
        const nextErrors = this.#validate(nextModel);

        this.#model = nextModel;
        this.#snapshot = nextSnapshot;
        this.#generation += 1;
        if (!sameErrors(nextErrors, this.#errors)) {
          this.#errors = nextErrors;
          errorsChanged = true;
        }
      } else {
        this.#snapshot = this.#takeSnapshot(current, "approve snapshot advance");
        this.#generation += 1;
      }
    } catch (error: unknown) {
      // A failed reset or snapshot advance commits nothing and settles the
      // approval exactly like a persister failure. The window ends with the
      // failure, so the failed settlement's observers update directly.
      this.#approvalPrePublishing = false;
      this.#settleFailedApproval();
      throw error;
    }

    // Settlement: clear the mark first, so every notification below reaches
    // an idle form and an approval started by an observer is admitted.
    this.#approvalInFlight = false;
    if (errorsChanged) {
      this.#errorsChanged.next({ ...this.#errors });
      // A synchronous observer may dispose the form reentrantly.
      if (this.#disposed) return;
    }
    // Exactly one notification per settlement. It also covers any
    // strict-mode dirty or validity change the commit made.
    this.#canExecuteTrigger.next();
    // A synchronous observer may dispose the form reentrantly.
    if (this.#disposed) return;
    this.#approvalPrePublishing = false;

    // Emit the value that was actually persisted (parity with C#'s captured
    // `current`): a SetModel racing the persister await must not swap the
    // approved payload for a newer un-persisted model.
    this.#onApproved.next(current);
  }

  /**
   * Queues an update prepared at `generation` (§5.3), unless a preparation
   * callback disposed the form or made another update meanwhile (§5.4).
   */
  #enqueue(generation: number, update: QueuedUpdate<TM>): void {
    if (this.#isStale(generation)) return;
    this.#queuedUpdates.push(update);
    this.#generation += 1;
  }

  /**
   * Replays the queued updates in call order, each as a new call (§5.3). A
   * failing replay does not stop the later ones. Returns the first failure.
   */
  #replayQueuedUpdates(): { readonly error: unknown } | undefined {
    const updates = this.#queuedUpdates;
    this.#queuedUpdates = [];
    let failure: { readonly error: unknown } | undefined;
    for (const update of updates) {
      try {
        if (update.kind === "set") {
          this.setModel(update.model);
        } else {
          this.#deny();
        }
      } catch (error: unknown) {
        failure ??= { error };
      }
    }
    return failure;
  }

  // ── Dispose ────────────────────────────────────────────────────────────────

  /** Complete the `onApproved` observable and dispose resources. Idempotent. */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    if (this.#activeSyncOperations > 0) {
      this.#teardownPending = true;
      return;
    }
    this.#teardown();
  }

  #teardown(): void {
    this.#onApproved.complete();
    this.#approveErrors.complete();
    this.#errorsChanged.complete();
    this.#canExecuteTrigger.complete();
    this.denyCommand.dispose();
    this.approveCommand.dispose();
  }

  // ── Internal ───────────────────────────────────────────────────────────────

  #deny(): void {
    if (this.#disposed) return;
    this.#runUpdate((own) => this.#applyDeny(own));
  }

  #applyDeny(own: Notices): void {
    // Preparation (§5.4): the snapshotter, validators, and equality
    // comparisons all run before any commit.
    const generation = this.#generation;
    const reverted = this.#takeSnapshot(this.#snapshot, "deny/revert");
    const update = this.#prepare(reverted);
    if (this.#approvalPrePublishing) {
      // §5.3: prepared at call time, committed when it replays.
      this.#enqueue(generation, { kind: "deny" });
      return;
    }
    if (this.#isStale(generation)) return;

    const errorsChanged = this.#commit(update);
    if (errorsChanged) {
      const errors = { ...update.errors };
      own.errors.push(() => this.#errorsChanged.next(errors));
    }
    const revertedMessage = new FormRevertedMessage(this, "FormVM");
    const modelMessage = PropertyChangedMessage.create(this, "FormVM", "model");
    own.afterScope.push(() => this.#hub.send(revertedMessage));
    own.afterScope.push(() => this.#hub.send(modelMessage));
    if (this.#approveStateChanged(update)) {
      own.afterScope.push(() => this.#canExecuteTrigger.next());
    }
  }

  /**
   * Runs one `setModel` or deny frame (§5.4, ADR-0180). `apply` prepares,
   * commits, and adds the update's notifications to `own`. A frame nested in
   * another update queues them for the outermost one, which sends the whole
   * queue before it returns. A failure of `apply` propagates after that.
   */
  #runUpdate(apply: (own: Notices) => void): void {
    this.#beginSyncOperation();
    const own = noNotices();
    let failure: { readonly error: unknown } | undefined;
    this.#preparationDepth += 1;
    try {
      apply(own);
    } catch (error: unknown) {
      failure = { error };
    }
    this.#preparationDepth -= 1;
    const delivery = this.#takeNotices(own);
    const deliveryFailure = delivery === undefined ? undefined : this.#deliver(delivery);
    this.#endSyncOperation();
    const routed = failure ?? deliveryFailure;
    if (routed !== undefined) throw routed.error;
  }

  /** True when a call comes from a nested window of an update (§5.4). */
  #isNested(): boolean {
    return this.#preparationDepth > 0 || this.#deliveringErrors;
  }

  /**
   * Adds `own` to the queue. A nested call's notifications are dropped once
   * the form is disposed. Returns the queue to send when the caller is the
   * outermost update, or undefined when the caller is nested. Inside the
   * error-map phase of a delivery, the outermost frame of an update moves the
   * whole queue, with the notifications of its own nested calls, to that
   * delivery.
   */
  #takeNotices(own: Notices): Notices | undefined {
    if (this.#preparationDepth > 0) {
      appendNotices(this.#pendingNotices, this.#markedNested(own));
      return undefined;
    }
    const delivery = this.#pendingNotices;
    this.#pendingNotices = noNotices();
    if (this.#deliveringErrors) {
      appendNotices(delivery, this.#markedNested(own));
      appendNotices(this.#scopedNotices, delivery);
      return undefined;
    }
    appendNotices(delivery, own);
    return delivery;
  }

  /** `notices`, marked as queued by a nested call (§5.4, ADR-0180). */
  #markedNested(notices: Notices): Notices {
    return {
      errors: notices.errors.map((send) => this.#unlessDisposed(send)),
      afterScope: notices.afterScope.map((send) => this.#unlessDisposed(send)),
      starts: notices.starts,
    };
  }

  #unlessDisposed(send: () => void): () => void {
    return () => {
      if (!this.#disposed) send();
    };
  }

  /**
   * Sends a queue (§5.4): every error map, including those that updates made
   * from an errorsChanged observer add meanwhile, then the other
   * notifications, then the persister starts of nested approvals. A failing
   * send does not stop the later ones. Returns the first failure.
   */
  #deliver(notices: Notices): { readonly error: unknown } | undefined {
    let failure: { readonly error: unknown } | undefined;
    const run = (send: () => void): void => {
      try {
        send();
      } catch (error: unknown) {
        failure ??= { error };
      }
    };
    this.#deliveringErrors = true;
    for (let sent = 0; sent < notices.errors.length;) {
      run(notices.errors[sent] as () => void);
      sent += 1;
      if (sent === notices.errors.length) {
        appendNotices(notices, this.#scopedNotices);
        this.#scopedNotices = noNotices();
      }
    }
    this.#deliveringErrors = false;
    for (const send of notices.afterScope) run(send);
    for (const start of notices.starts) run(start);
    return failure;
  }

  /**
   * Prepares an update to `model` (§5.4): runs the dirty comparisons and the
   * validators without changing any form state. A throwing callback
   * propagates with nothing prepared.
   */
  #prepare(model: TM): PreparedUpdate<TM> {
    const wasDirty = !this.#equals(this.#model, this.#snapshot);
    const wasValid = this.isValid;
    const errors = this.#validate(model);
    const isDirty = !this.#equals(model, this.#snapshot);
    return { model, errors, wasDirty, wasValid, isDirty };
  }

  /**
   * True when a preparation begun at `generation` may not commit: a callback
   * disposed the form or another update committed while it ran.
   */
  #isStale(generation: number): boolean {
    return this.#disposed || generation !== this.#generation;
  }

  /**
   * Installs a prepared model and error map in one step and advances the
   * commit generation. Runs no consumer callback. Returns true when the
   * effective error map changed.
   */
  #commit(update: PreparedUpdate<TM>): boolean {
    this.#model = update.model;
    this.#generation += 1;
    if (sameErrors(update.errors, this.#errors)) return false;
    this.#errors = update.errors;
    return true;
  }

  /** Whether a committed update changes what the approve gates depend on. */
  #approveStateChanged(update: PreparedUpdate<TM>): boolean {
    const isValid = Object.keys(update.errors).length === 0;
    return (this.#strict && update.isDirty !== update.wasDirty)
      || isValid !== update.wasValid;
  }

  /**
   * Settles an approval whose persister, reset, or snapshot advance failed:
   * clear the mark, then raise the one settlement notification. The caller
   * rethrows, so the outcome is routed after both. Disposal suppresses it.
   */
  #settleFailedApproval(): void {
    if (this.#disposed) return;
    this.#approvalInFlight = false;
    this.#raiseApproveCanExecuteChanged();
  }

  /** Raises one approve re-evaluation; a reentrant dispose waits for it. */
  #raiseApproveCanExecuteChanged(): void {
    this.#beginSyncOperation();
    try {
      this.#canExecuteTrigger.next();
    } finally {
      this.#endSyncOperation();
    }
  }

  #beginSyncOperation(): void {
    this.#activeSyncOperations += 1;
  }

  #endSyncOperation(): void {
    this.#activeSyncOperations -= 1;
    if (this.#activeSyncOperations === 0 && this.#teardownPending) {
      this.#teardownPending = false;
      this.#teardown();
    }
  }

  #validate(model: TM): Record<string, string> {
    const errors = fieldRecord<string>();
    for (const [field, validator] of Object.entries(this.#validators)) {
      const error = validator(model);
      if (error !== null && error !== undefined) errors[field] = error;
    }
    if (this.#modelValidator !== null) {
      for (const [field, error] of Object.entries(this.#modelValidator(model))) {
        if (error === null || error === undefined) {
          Reflect.deleteProperty(errors, field);
        } else {
          errors[field] = error;
        }
      }
    }
    return errors;
  }

  #takeSnapshot(model: TM, phase: SnapshotPhase): TM {
    if (!this.#usesDefaultSnapshotter) return this.#snapshotter(model);
    try {
      return this.#snapshotter(model);
    } catch (cause: unknown) {
      throw defaultSnapshotError(model, phase, cause);
    }
  }
}

function sameErrors(a: Record<string, string>, b: Record<string, string>): boolean {
  const aKeys = Object.keys(a);
  const bKeys = Object.keys(b);
  if (aKeys.length !== bKeys.length) return false;
  for (const key of aKeys) {
    if (ownValue(b, key) !== a[key]) return false;
  }
  return true;
}

/**
 * Field names are data. Validator and error maps are null-prototype records, so
 * names such as `__proto__`, `constructor`, or `toString` are ordinary own keys
 * and no inherited member leaks into a lookup. Public snapshots are spread into
 * plain objects, which keeps every key as an own, enumerable property.
 */
function fieldRecord<V>(source?: Readonly<Record<string, V>>): Record<string, V> {
  const record = Object.create(null) as Record<string, V>;
  if (source !== undefined) {
    for (const key of Object.keys(source)) record[key] = source[key] as V;
  }
  return record;
}

function ownValue<V>(record: Readonly<Record<string, V>>, key: string): V | undefined {
  return Object.prototype.hasOwnProperty.call(record, key) ? record[key] : undefined;
}

// ---------------------------------------------------------------------------
// Builder (colocated per the canonical TS builder pattern; see
// `componentVM.ts` for the reference structure). Per ADR-0035 §2 FV1 / FV2.
// ---------------------------------------------------------------------------

/**
 * Immutable fluent builder for {@link FormVM}.
 *
 * Required setters: {@link initial}, {@link persister}.
 * Optional setters: {@link hub}, {@link strict}, {@link snapshotter},
 * {@link equals}.
 *
 * Each setter returns a NEW builder instance (BLD-001). `build()`
 * validates the required fields and throws {@link BuilderValidationError}
 * on the first missing one (BLD-002).
 */
export class FormVMBuilder<TM> {
  #initial: TM | undefined = undefined;
  #initialSet = false;
  #persister: Persister<TM> | null = null;
  #hub: IMessageHub | null = null;
  #strict = false;
  #snapshotter: Snapshotter<TM> | null = null;
  #equals: ModelEquals<TM> | null = null;
  #validators: Record<string, FieldValidator<TM>> = fieldRecord();
  #modelValidator: ModelValidator<TM> | null = null;
  #resetOnApproved: ResetOnApproved<TM> | null = null;

  constructor(from?: FormVMBuilder<TM>) {
    if (from) {
      this.#initial = from.#initial;
      this.#initialSet = from.#initialSet;
      this.#persister = from.#persister;
      this.#hub = from.#hub;
      this.#strict = from.#strict;
      this.#snapshotter = from.#snapshotter;
      this.#equals = from.#equals;
      this.#validators = fieldRecord(from.#validators);
      this.#modelValidator = from.#modelValidator;
      this.#resetOnApproved = from.#resetOnApproved;
    }
  }

  /** Set the required initial domain model. */
  initial(value: TM): FormVMBuilder<TM> {
    const b = new FormVMBuilder<TM>(this);
    b.#initial = value;
    b.#initialSet = true;
    return b;
  }

  /** Set the required async persister delegate `(model) => Promise<void>`. */
  persister(value: Persister<TM>): FormVMBuilder<TM> {
    const b = new FormVMBuilder<TM>(this);
    b.#persister = value;
    return b;
  }

  /** Set the optional message hub (default: {@link NullMessageHub.INSTANCE}). */
  hub(value: IMessageHub): FormVMBuilder<TM> {
    const b = new FormVMBuilder<TM>(this);
    b.#hub = value;
    return b;
  }

  /**
   * Enable strict mode (`approveCommand.canExecute()` returns false when
   * `isDirty` is false). Default: `false`.
   */
  strict(value: boolean): FormVMBuilder<TM> {
    const b = new FormVMBuilder<TM>(this);
    b.#strict = value;
    return b;
  }

  /**
   * Set a custom snapshot function (default: `structuredClone`). The default
   * requires a structured-cloneable model and reports phase/field context on
   * failure. Pair a custom snapshotter with {@link equals}; custom errors pass
   * through unchanged.
   */
  snapshotter(value: Snapshotter<TM>): FormVMBuilder<TM> {
    const b = new FormVMBuilder<TM>(this);
    b.#snapshotter = value;
    return b;
  }

  /** Set a custom dirty-tracking equality predicate (default: {@link deepEquals}). */
  equals(value: ModelEquals<TM>): FormVMBuilder<TM> {
    const b = new FormVMBuilder<TM>(this);
    b.#equals = value;
    return b;
  }

  /** Register a field validator. The returned builder is a new instance. */
  validator(field: string, value: FieldValidator<TM>): FormVMBuilder<TM> {
    const b = new FormVMBuilder<TM>(this);
    b.#validators[field] = value;
    return b;
  }

  /** Register a model-level validator returning field-name errors. */
  modelValidator(value: ModelValidator<TM>): FormVMBuilder<TM> {
    const b = new FormVMBuilder<TM>(this);
    b.#modelValidator = value;
    return b;
  }

  /** Derive the next pristine model after persistence succeeds. */
  resetOnApproved(value: ResetOnApproved<TM>): FormVMBuilder<TM> {
    const b = new FormVMBuilder<TM>(this);
    b.#resetOnApproved = value;
    return b;
  }

  /**
   * Validate required fields and construct a {@link FormVM}.
   *
   * @throws {BuilderValidationError} If `initial` or `persister` is not set.
   */
  build(): FormVM<TM> {
    if (!this.#initialSet) throw new BuilderValidationError("initial");
    if (this.#persister === null) throw new BuilderValidationError("persister");

    const options: FormVMOptions<TM> = {
      initial: this.#initial as TM,
      persister: this.#persister,
    };
    if (this.#hub !== null) options.hub = this.#hub;
    options.strict = this.#strict;
    if (this.#snapshotter !== null) options.snapshotter = this.#snapshotter;
    if (this.#equals !== null) options.equals = this.#equals;
    if (Object.keys(this.#validators).length > 0) options.validators = { ...this.#validators };
    if (this.#modelValidator !== null) options.modelValidator = this.#modelValidator;
    if (this.#resetOnApproved !== null) options.resetOnApproved = this.#resetOnApproved;

    return new FormVM<TM>(options);
  }
}
