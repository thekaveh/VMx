/**
 * RelayCommand and RelayCommandOf<T> — concrete ICommand implementations.
 *
 * See spec/04-commands.md.
 *
 * Behavior contract:
 * - Predicate null → canExecute returns true unconditionally.
 * - Task null → execute is a no-op (no exception raised).
 * - Execute is gated on canExecute: if canExecute() is false, execute returns
 *   immediately without invoking the task (spec fixture row "predicate-false").
 * - Predicate that raises → treated as false (exception does NOT propagate).
 * - Task that raises → exception propagates to the caller of execute.
 * - Trigger emissions fire canExecuteChanged.
 * - Disposed commands are inert: canExecute returns false and execute is a no-op.
 * - Builder is immutable (BLD-001): every setter returns a NEW builder instance.
 * - Triggers are additive: multiple .triggers(obs) calls combine into trigger set.
 */
import { Subject, Subscription } from "rxjs";
import type { Observable } from "rxjs";
import type { ICommand, ICommandOf } from "./types.js";

// ---------------------------------------------------------------------------
// RelayCommand (non-parameterized)
// ---------------------------------------------------------------------------

export class RelayCommand implements ICommand {
  readonly #task: (() => void) | null;
  readonly #predicate: (() => boolean) | null;
  readonly #canExecuteChangedSubject = new Subject<void>();
  // Single root Subscription (VMX-094): aggregating the trigger subscriptions
  // makes teardown exception-safe — a throwing child unsubscribe no longer
  // aborts the loop and strands the remaining subscriptions, and the root
  // tears every child down even when one throws.
  readonly #subscriptions = new Subscription();
  #disposed = false;

  constructor(
    task: (() => void) | null,
    predicate: (() => boolean) | null,
    triggers: Observable<unknown>[],
  ) {
    this.#task = task;
    this.#predicate = predicate;
    for (const t of triggers) {
      this.#subscriptions.add(
        t.subscribe(() => this.#canExecuteChangedSubject.next()),
      );
    }
  }

  canExecute(): boolean {
    if (this.#disposed) return false;
    if (this.#predicate === null) return true;
    try {
      return this.#predicate();
    } catch {
      return false;
    }
  }

  execute(): void {
    if (!this.canExecute()) return;
    if (this.#task !== null) this.#task();
  }

  get canExecuteChanged(): Observable<void> {
    return this.#canExecuteChangedSubject.asObservable();
  }

  /** Idempotent: subsequent calls are a no-op. */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    // Complete the subject first so subscribers always observe completion, then
    // tear down every trigger subscription via the root (VMX-094).
    this.#canExecuteChangedSubject.next();
    this.#canExecuteChangedSubject.complete();
    this.#subscriptions.unsubscribe();
  }

  static builder(): RelayCommandBuilder {
    return new RelayCommandBuilder(null, null, []);
  }
}

export class RelayCommandBuilder {
  readonly #task: (() => void) | null;
  readonly #predicate: (() => boolean) | null;
  readonly #triggers: readonly Observable<unknown>[];

  constructor(
    task: (() => void) | null,
    predicate: (() => boolean) | null,
    triggers: readonly Observable<unknown>[],
  ) {
    this.#task = task;
    this.#predicate = predicate;
    this.#triggers = triggers;
  }

  task(fn: () => void): RelayCommandBuilder {
    return new RelayCommandBuilder(fn, this.#predicate, this.#triggers);
  }

  predicate(fn: () => boolean): RelayCommandBuilder {
    return new RelayCommandBuilder(this.#task, fn, this.#triggers);
  }

  triggers(obs: Observable<unknown>): RelayCommandBuilder {
    return new RelayCommandBuilder(this.#task, this.#predicate, [
      ...this.#triggers,
      obs,
    ]);
  }

  build(): RelayCommand {
    return new RelayCommand(
      this.#task,
      this.#predicate,
      [...this.#triggers],
    );
  }
}

// ---------------------------------------------------------------------------
// RelayCommandOf<T> (parameterized)
// ---------------------------------------------------------------------------

export class RelayCommandOf<T> implements ICommandOf<T> {
  readonly #task: ((p: T) => void) | null;
  readonly #predicate: ((p: T) => boolean) | null;
  readonly #canExecuteChangedSubject = new Subject<void>();
  // Single root Subscription (VMX-094) — see RelayCommand for rationale.
  readonly #subscriptions = new Subscription();
  #disposed = false;

  constructor(
    task: ((p: T) => void) | null,
    predicate: ((p: T) => boolean) | null,
    triggers: Observable<unknown>[],
  ) {
    this.#task = task;
    this.#predicate = predicate;
    for (const t of triggers) {
      this.#subscriptions.add(
        t.subscribe(() => this.#canExecuteChangedSubject.next()),
      );
    }
  }

  canExecute(parameter: T): boolean {
    if (this.#disposed) return false;
    if (this.#predicate === null) return true;
    try {
      return this.#predicate(parameter);
    } catch {
      return false;
    }
  }

  execute(parameter: T): void {
    if (!this.canExecute(parameter)) return;
    if (this.#task !== null) this.#task(parameter);
  }

  get canExecuteChanged(): Observable<void> {
    return this.#canExecuteChangedSubject.asObservable();
  }

  /** Idempotent: subsequent calls are a no-op. */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#canExecuteChangedSubject.next();
    this.#canExecuteChangedSubject.complete();
    this.#subscriptions.unsubscribe();
  }

  static builder<T>(): RelayCommandOfBuilder<T> {
    return new RelayCommandOfBuilder<T>(null, null, []);
  }
}

export class RelayCommandOfBuilder<T> {
  readonly #task: ((p: T) => void) | null;
  readonly #predicate: ((p: T) => boolean) | null;
  readonly #triggers: readonly Observable<unknown>[];

  constructor(
    task: ((p: T) => void) | null,
    predicate: ((p: T) => boolean) | null,
    triggers: readonly Observable<unknown>[],
  ) {
    this.#task = task;
    this.#predicate = predicate;
    this.#triggers = triggers;
  }

  task(fn: (p: T) => void): RelayCommandOfBuilder<T> {
    return new RelayCommandOfBuilder(fn, this.#predicate, this.#triggers);
  }

  predicate(fn: (p: T) => boolean): RelayCommandOfBuilder<T> {
    return new RelayCommandOfBuilder(this.#task, fn, this.#triggers);
  }

  triggers(obs: Observable<unknown>): RelayCommandOfBuilder<T> {
    return new RelayCommandOfBuilder(this.#task, this.#predicate, [
      ...this.#triggers,
      obs,
    ]);
  }

  build(): RelayCommandOf<T> {
    return new RelayCommandOf<T>(
      this.#task,
      this.#predicate,
      [...this.#triggers],
    );
  }
}
