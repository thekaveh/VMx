/**
 * AsyncRelayCommand — a cancellable async ICommand implementation.
 *
 * See spec/04-commands.md §10 (async command cancellation), ADR-0056.
 *
 * Behavior contract:
 * - The task receives an `AbortSignal` linked to both `cancel()` (an internal
 *   `AbortController`) and any external signal passed to `executeAsync`.
 * - Predicate null → canExecute returns true when idle.
 * - While an execution is in flight, canExecute returns false (so the command
 *   cannot double-run) and canExecuteChanged fires when the in-flight state flips
 *   on start and on completion.
 * - Cancellation is NON-THROWING by default (DIA-007 alignment): the awaited
 *   `executeAsync` resolves on cancel. Opt into rejection via `throwOnCancel()`.
 * - A rejecting task (non-cancellation) propagates to the awaiter of
 *   `executeAsync`; on the fire-and-forget `execute()` path — which has no caller
 *   to propagate to — it is routed to the `errors` observable instead of becoming
 *   an unhandled rejection (mirrors ConfirmationDecoratorCommand, ADR-0049).
 * - Builder is immutable (BLD-001): every setter returns a NEW builder instance.
 */
import { Subject, Subscription } from "rxjs";
import type { Observable } from "rxjs";
import type { IAsyncCommand } from "./types.js";

type AsyncTask = (signal: AbortSignal) => Promise<void>;

export class AsyncRelayCommand implements IAsyncCommand {
  readonly #task: AsyncTask;
  readonly #predicate: (() => boolean) | null;
  readonly #throwOnCancel: boolean;
  readonly #canExecuteChangedSubject = new Subject<void>();
  readonly #errorsSubject = new Subject<unknown>();
  // Single root Subscription (VMX-094): exception-safe trigger teardown.
  readonly #subscriptions = new Subscription();
  #controller: AbortController | null = null;
  #isExecuting = false;
  #disposed = false;

  constructor(
    task: AsyncTask | null,
    predicate: (() => boolean) | null,
    triggers: Observable<unknown>[],
    throwOnCancel: boolean,
  ) {
    this.#task = task ?? (() => Promise.resolve());
    this.#predicate = predicate;
    this.#throwOnCancel = throwOnCancel;
    for (const t of triggers) {
      this.#subscriptions.add(
        t.subscribe(() => this.#canExecuteChangedSubject.next()),
      );
    }
  }

  get isExecuting(): boolean {
    return this.#isExecuting;
  }

  get canExecuteChanged(): Observable<void> {
    return this.#canExecuteChangedSubject.asObservable();
  }

  /**
   * Surfaces a fault from the fire-and-forget `execute()` path (a rejecting task
   * that is not a cancellation). Await `executeAsync` to handle the error inline.
   * Cancellations never reach this channel. Completes on `dispose()`.
   */
  get errors(): Observable<unknown> {
    return this.#errorsSubject.asObservable();
  }

  canExecute(): boolean {
    if (this.#disposed) return false;
    if (this.#isExecuting) return false;
    if (this.#predicate === null) return true;
    try {
      return this.#predicate();
    } catch {
      return false;
    }
  }

  execute(): void {
    void this.executeAsync().catch((err: unknown) => {
      if (this.#disposed) return;
      if (isCancellationError(err)) return;
      this.#errorsSubject.next(err);
    });
  }

  async executeAsync(externalSignal?: AbortSignal): Promise<void> {
    if (!this.canExecute()) return;

    const controller = new AbortController();
    this.#controller = controller;
    if (externalSignal !== undefined) {
      if (externalSignal.aborted) {
        controller.abort(externalSignal.reason);
      } else {
        externalSignal.addEventListener(
          "abort",
          () => controller.abort(externalSignal.reason),
          { once: true },
        );
      }
    }

    this.#isExecuting = true;
    this.#canExecuteChangedSubject.next();
    try {
      await this.#task(controller.signal);
    } catch (err) {
      // Non-throwing default (DIA-007 alignment): command-originated
      // cancellation resolves quietly unless throwing is opted in. Arbitrary
      // task faults after abort still propagate.
      if (controller.signal.aborted && isCancellationError(err)) {
        if (this.#throwOnCancel) {
          throw err;
        }
      } else {
        throw err;
      }
    } finally {
      this.#isExecuting = false;
      this.#controller = null;
      this.#canExecuteChangedSubject.next();
    }
  }

  cancel(): void {
    this.#controller?.abort();
  }

  /** Idempotent: subsequent calls are a no-op. */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#controller?.abort();
    this.#canExecuteChangedSubject.complete();
    this.#errorsSubject.complete();
    this.#subscriptions.unsubscribe();
  }

  static builder(): AsyncRelayCommandBuilder {
    return new AsyncRelayCommandBuilder(null, null, [], false);
  }
}

export class AsyncRelayCommandBuilder {
  readonly #task: AsyncTask | null;
  readonly #predicate: (() => boolean) | null;
  readonly #triggers: readonly Observable<unknown>[];
  readonly #throwOnCancel: boolean;

  constructor(
    task: AsyncTask | null,
    predicate: (() => boolean) | null,
    triggers: readonly Observable<unknown>[],
    throwOnCancel: boolean,
  ) {
    this.#task = task;
    this.#predicate = predicate;
    this.#triggers = triggers;
    this.#throwOnCancel = throwOnCancel;
  }

  task(fn: AsyncTask): AsyncRelayCommandBuilder {
    return new AsyncRelayCommandBuilder(
      fn,
      this.#predicate,
      this.#triggers,
      this.#throwOnCancel,
    );
  }

  predicate(fn: () => boolean): AsyncRelayCommandBuilder {
    return new AsyncRelayCommandBuilder(
      this.#task,
      fn,
      this.#triggers,
      this.#throwOnCancel,
    );
  }

  triggers(obs: Observable<unknown>): AsyncRelayCommandBuilder {
    return new AsyncRelayCommandBuilder(
      this.#task,
      this.#predicate,
      [...this.#triggers, obs],
      this.#throwOnCancel,
    );
  }

  throwOnCancel(value = true): AsyncRelayCommandBuilder {
    return new AsyncRelayCommandBuilder(
      this.#task,
      this.#predicate,
      this.#triggers,
      value,
    );
  }

  build(): AsyncRelayCommand {
    return new AsyncRelayCommand(
      this.#task,
      this.#predicate,
      [...this.#triggers],
      this.#throwOnCancel,
    );
  }
}

function isCancellationError(err: unknown): boolean {
  return typeof err === "object"
    && err !== null
    && "name" in err
    && (err as { readonly name?: unknown }).name === "AbortError";
}
