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
  readonly #strict: boolean;
  readonly #hub: IMessageHub;

  #model: TM;
  #snapshot: TM;
  #disposed = false;

  readonly #onApproved = new Subject<TM>();
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
    const { initial, persister, hub, strict = false, snapshotter } = options;

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

    this.#model = initial;
    this.#snapshot = this.#snapshotter(initial);

    this.denyCommand = RelayCommand.builder()
      .task(() => this.#deny())
      .build();

    this.approveCommand = RelayCommand.builder()
      .task(() => {
        // Fire-and-forget parity: Python retrieves the task exception and C#
        // discards the Task; a bare `void` here turned a rejecting persister
        // into a fatal unhandled rejection on Node >= 15. Callers who need
        // the failure await approveAsync() directly.
        void this.approveAsync().catch(() => undefined);
      })
      .predicate(() => !this.#strict || this.isDirty)
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
   * Uses `JSON.stringify` comparison for plain objects.
   */
  get isDirty(): boolean {
    return JSON.stringify(this.#model) !== JSON.stringify(this.#snapshot);
  }

  /** Observable that emits the current model after each successful persist. */
  get onApproved(): Observable<TM> {
    return this.#onApproved.asObservable();
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
    this.#model = model;
    if (this.#strict && this.isDirty !== wasDirty) {
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
    this.#canExecuteTrigger.complete();
    this.denyCommand.dispose();
    this.approveCommand.dispose();
  }

  // ── Internal ───────────────────────────────────────────────────────────────

  #deny(): void {
    if (this.#disposed) return;
    const wasDirty = this.isDirty;
    this.#model = this.#snapshotter(this.#snapshot);

    this.#hub.send(new FormRevertedMessage(this, "FormVM"));
    this.#hub.send(
      PropertyChangedMessage.create(this, "FormVM", "model"),
    );

    if (this.#strict && wasDirty !== this.isDirty) {
      this.#canExecuteTrigger.next();
    }
  }
}

// ---------------------------------------------------------------------------
// Builder (colocated per the canonical TS builder pattern; see
// `componentVM.ts` for the reference structure). Per ADR-0035 §2 FV1 / FV2.
// ---------------------------------------------------------------------------

/**
 * Immutable fluent builder for {@link FormVM}.
 *
 * Required setters: {@link initial}, {@link persister}.
 * Optional setters: {@link hub}, {@link strict}, {@link snapshotter}.
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

  constructor(from?: FormVMBuilder<TM>) {
    if (from) {
      this.#initial = from.#initial;
      this.#initialSet = from.#initialSet;
      this.#persister = from.#persister;
      this.#hub = from.#hub;
      this.#strict = from.#strict;
      this.#snapshotter = from.#snapshotter;
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

    return new FormVM<TM>(options);
  }
}
