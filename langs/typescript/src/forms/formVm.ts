/**
 * FormVM<TM> — snapshot/revert edit lifecycle ViewModel.
 *
 * See spec/20-form-vm.md and ADR-0030.
 */
import { Subject } from "rxjs";
import type { Observable } from "rxjs";
import { RelayCommand, RelayCommandBuilder } from "../commands/relayCommand.js";
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

  readonly #onApproved = new Subject<TM>();
  readonly #canExecuteTrigger = new Subject<void>();

  readonly denyCommand: RelayCommand;
  readonly approveCommand: RelayCommand;

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

    this.denyCommand = new RelayCommandBuilder(null, null, [])
      .task(() => this.#deny())
      .build();

    this.approveCommand = new RelayCommandBuilder(null, null, [])
      .task(() => {
        void this.approveAsync();
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
    const current = this.#model;

    // May throw — intentional. No state mutation if this throws.
    await this.#persister(current);

    // Success: advance snapshot and notify.
    const wasDirty = this.isDirty;
    this.#snapshot = this.#snapshotter(current);

    if (this.#strict && this.isDirty !== wasDirty) {
      this.#canExecuteTrigger.next();
    }

    this.#onApproved.next(this.#model);
  }

  // ── Dispose ────────────────────────────────────────────────────────────────

  /** Complete the `onApproved` observable and dispose resources. */
  dispose(): void {
    this.#onApproved.complete();
    this.#canExecuteTrigger.complete();
    this.denyCommand.dispose();
    this.approveCommand.dispose();
  }

  // ── Internal ───────────────────────────────────────────────────────────────

  #deny(): void {
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
