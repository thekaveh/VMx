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

/** Optional custom snapshot function. Defaults to `structuredClone`. */
export type Snapshotter<TM> = (model: TM) => TM;

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

/**
 * Structural deep-equality used by {@link FormVM.isDirty} when no custom
 * `equals` is supplied. It mirrors the depth the default `structuredClone`
 * snapshotter clones, so comparison and snapshotting stay internally
 * consistent. Unlike the previous `JSON.stringify` comparison it:
 *
 * - never throws on `BigInt` (compared with `===`) or circular references
 *   (guarded with a visited-pair set);
 * - compares `Date` by instant, `Map`/`Set` by contents, `RegExp` by
 *   source/flags, arrays and plain objects by value;
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
    return a instanceof Date && b instanceof Date && a.getTime() === b.getTime();
  }

  if (a instanceof RegExp || b instanceof RegExp) {
    return (
      a instanceof RegExp &&
      b instanceof RegExp &&
      a.source === b.source &&
      a.flags === b.flags
    );
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
   * contains values structuredClone cannot serialize.
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
  readonly #equals: ModelEquals<TM>;
  readonly #validators: Record<string, FieldValidator<TM>>;
  readonly #modelValidator: ModelValidator<TM> | null;
  readonly #strict: boolean;
  readonly #hub: IMessageHub;

  #model: TM;
  #snapshot: TM;
  #errors: Record<string, string>;
  #disposed = false;

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
    this.#snapshotter = snapshotter ?? ((m: TM) => structuredClone(m));
    this.#equals = equals ?? ((a: TM, b: TM) => deepEquals(a, b));
    this.#validators = { ...(validators ?? {}) };
    this.#modelValidator = modelValidator ?? null;

    this.#model = initial;
    this.#snapshot = this.#snapshotter(initial);
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
          this.#approveErrors.next(err);
        });
      })
      .predicate(() => this.isValid && (!this.#strict || this.isDirty))
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
    return this.#errors[field];
  }

  // ── Mutation ───────────────────────────────────────────────────────────────

  /**
   * Replaces the current model. May change `isDirty`; in strict mode fires
   * `approveCommand.canExecuteChanged` on dirty transitions.
   */
  setModel(model: TM): void {
    if (model === null || model === undefined) {
      throw new Error("model must not be null or undefined");
    }
    const wasDirty = this.isDirty;
    const wasValid = this.isValid;
    this.#model = model;
    this.#revalidate();
    if ((this.#strict && this.isDirty !== wasDirty) || this.isValid !== wasValid) {
      this.#canExecuteTrigger.next();
    }
  }

  // ── Async core ─────────────────────────────────────────────────────────────

  /**
   * Awaitable approve flow. Invokes the persister, advances `snapshot` on success,
   * and fires `onApproved`. Throws when the persister throws (no state mutation).
   */
  async approveAsync(): Promise<void> {
    // A disposed form is a full no-op — the persister must not be invoked
    // (symmetric with the deny guard).
    if (this.#disposed) return;
    if (!this.isValid) return;
    const current = this.#model;

    // May throw — intentional. No state mutation if this throws.
    await this.#persister(current);

    // dispose() may have run during the await; rxjs would silently no-op
    // the emissions below, but the snapshot advance is a real state
    // mutation on a disposed form (C#/Python guard identically). The
    // analyzer narrows #disposed from the entry guard, but the await is a
    // genuine interleaving point.
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
    if (this.#disposed) return;

    // Success: advance snapshot and notify.
    const wasDirty = this.isDirty;
    this.#snapshot = this.#snapshotter(current);

    if (this.#strict && this.isDirty !== wasDirty) {
      this.#canExecuteTrigger.next();
    }

    // Emit the value that was actually persisted (parity with C#'s captured
    // `current`): a SetModel racing the persister await must not swap the
    // approved payload for a newer un-persisted model.
    this.#onApproved.next(current);
  }

  // ── Dispose ────────────────────────────────────────────────────────────────

  /** Complete the `onApproved` observable and dispose resources. Idempotent. */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
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
    const wasDirty = this.isDirty;
    const wasValid = this.isValid;
    this.#model = this.#snapshotter(this.#snapshot);
    this.#revalidate();

    this.#hub.send(new FormRevertedMessage(this, "FormVM"));
    this.#hub.send(
      PropertyChangedMessage.create(this, "FormVM", "model"),
    );

    if ((this.#strict && wasDirty !== this.isDirty) || wasValid !== this.isValid) {
      this.#canExecuteTrigger.next();
    }
  }

  #validate(model: TM): Record<string, string> {
    const errors: Record<string, string> = {};
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

  #revalidate(): void {
    const errors = this.#validate(this.#model);
    if (sameErrors(errors, this.#errors)) return;
    this.#errors = errors;
    this.#errorsChanged.next({ ...errors });
  }
}

function sameErrors(a: Record<string, string>, b: Record<string, string>): boolean {
  const aKeys = Object.keys(a);
  const bKeys = Object.keys(b);
  if (aKeys.length !== bKeys.length) return false;
  for (const key of aKeys) {
    if (a[key] !== b[key]) return false;
  }
  return true;
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
  #validators: Record<string, FieldValidator<TM>> = {};
  #modelValidator: ModelValidator<TM> | null = null;

  constructor(from?: FormVMBuilder<TM>) {
    if (from) {
      this.#initial = from.#initial;
      this.#initialSet = from.#initialSet;
      this.#persister = from.#persister;
      this.#hub = from.#hub;
      this.#strict = from.#strict;
      this.#snapshotter = from.#snapshotter;
      this.#equals = from.#equals;
      this.#validators = { ...from.#validators };
      this.#modelValidator = from.#modelValidator;
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

  /** Set a custom snapshot function (default: `structuredClone`). */
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

    return new FormVM<TM>(options);
  }
}
