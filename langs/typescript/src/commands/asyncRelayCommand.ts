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
type CancellationOrigin = "command" | "external";

export class AsyncRelayCommand implements IAsyncCommand {
  readonly #task: AsyncTask | null;
  readonly #predicate: (() => boolean) | null;
  readonly #throwOnCancel: boolean;
  readonly #canExecuteChangedSubject = new Subject<void>();
  readonly #errorsSubject = new Subject<unknown>();
  // Single root Subscription (VMX-094): exception-safe trigger teardown.
  readonly #subscriptions = new Subscription();
  #controller: AbortController | null = null;
  #evaluatingPredicate = false;
  #isExecuting = false;
  #disposed = false;
  // First cancellation channel to affect the current execution. A later command
  // cancel must not retroactively hide an already-external cancellation.
  #cancellationOrigin: CancellationOrigin | null = null;

  constructor(
    task: AsyncTask | null,
    predicate: (() => boolean) | null,
    triggers: Observable<unknown>[],
    throwOnCancel: boolean,
  ) {
    this.#task = task;
    this.#predicate = predicate;
    this.#throwOnCancel = throwOnCancel;
    for (const t of triggers) {
      this.#subscriptions.add(
        t.subscribe(() => this.raiseCanExecuteChanged()),
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
   * Emit one re-evaluation notification without evaluating the predicate or task.
   * Valid while idle or in flight; a no-op after disposal.
   */
  raiseCanExecuteChanged(): void {
    if (this.#disposed) return;
    this.#canExecuteChangedSubject.next();
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
    if (this.#evaluatingPredicate) return false;
    if (this.#predicate === null) return true;
    this.#evaluatingPredicate = true;
    try {
      const allowed = this.#predicate();
      return allowed && this.#isAdmissionStillValid();
    } catch {
      return false;
    } finally {
      this.#evaluatingPredicate = false;
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
    if (this.#task === null) return;
    if (!this.canExecute()) return;
    this.#cancellationOrigin = null;

    const controller = new AbortController();
    this.#controller = controller;
    let externalAbortListener: (() => void) | null = null;
    if (externalSignal !== undefined) {
      if (externalSignal.aborted) {
        this.#cancellationOrigin = "external";
        controller.abort(externalSignal.reason);
      } else {
        externalAbortListener = () => {
          this.#cancellationOrigin ??= "external";
          controller.abort(externalSignal.reason);
        };
        externalSignal.addEventListener(
          "abort",
          externalAbortListener,
          { once: true },
        );
      }
    }

    this.#isExecuting = true;
    this.raiseCanExecuteChanged();
    try {
      await this.#task(controller.signal);
    } catch (err) {
      // Non-throwing default (DIA-007 alignment): swallow only a cancellation we
      // requested through the command's own channel (cancel()/dispose()) unless
      // throwing is opted in. A cancellation from the externally-supplied signal
      // remains external even if cancel() follows, and is re-raised per spec/04
      // §10.3; arbitrary task faults after abort still propagate.
      if (this.#wasCommandCancellation() && isCancellationError(err)) {
        if (this.#throwOnCancel) {
          throw err;
        }
      } else {
        throw err;
      }
    } finally {
      if (externalAbortListener !== null) {
        externalSignal?.removeEventListener("abort", externalAbortListener);
      }
      this.#isExecuting = false;
      this.#controller = null;
      this.#cancellationOrigin = null;
      this.raiseCanExecuteChanged();
    }
  }

  cancel(): void {
    if (!this.#isExecuting) return;
    this.#cancellationOrigin ??= "command";
    this.#controller?.abort();
  }

  #wasCommandCancellation(): boolean {
    return this.#cancellationOrigin === "command";
  }

  #isAdmissionStillValid(): boolean {
    return !this.#disposed && !this.#isExecuting;
  }

  /** Idempotent: subsequent calls are a no-op. */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    if (this.#isExecuting) this.#cancellationOrigin ??= "command";
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
