/**
 * ConfirmationDecoratorCommand — gates execution on an async confirm delegate.
 *
 * See spec/04-commands.md §8.3 (§8.3.1 errors channel, §8.3.2 asynchronous
 * inner commands), ADR-0012, ADR-0049, ADR-0134, and ADR-0145.
 */
import { Subject } from "rxjs";
import type { Observable } from "rxjs";
import type { IAsyncCommand, ICommand } from "./types.js";

export type ConfirmDelegate = () => Promise<boolean>;

/** An inner command whose operation the awaited path can await (spec §8.3.2). */
type AsyncInnerCommand = ICommand & { executeAsync(): Promise<void> };

export class ConfirmationDecoratorCommand implements ICommand {
  readonly #inner: ICommand;
  readonly #confirm: ConfirmDelegate;
  readonly #errors = new Subject<unknown>();

  #disposed = false;

  constructor(inner: ICommand, confirm: ConfirmDelegate) {
    this.#inner = inner;
    this.#confirm = confirm;
  }

  get canExecuteChanged(): Observable<void> {
    return this.#inner.canExecuteChanged;
  }

  /**
   * Observable that surfaces an error from the fire-and-forget {@link execute}
   * path — either the confirm delegate rejecting or a synchronous inner command
   * throwing. `execute()` is synchronous and runs the confirm gate
   * asynchronously, so it cannot propagate the way the base `RelayCommand`'s
   * task does; instead of swallowing the error it is emitted here (VMX-009).
   * An asynchronous inner command reports its own failures on its own error
   * channel, so they never arrive here. Await {@link executeAsync} to observe
   * failures inline. Completes on {@link dispose}.
   */
  get errors(): Observable<unknown> {
    return this.#errors.asObservable();
  }

  canExecute(): boolean {
    // Re-check after the call-out: the inner predicate may dispose this
    // wrapper (spec/04 §8.4).
    return !this.#disposed && this.#inner.canExecute() && !this.#disposed;
  }

  /**
   * Fire-and-forget: starts the confirm flow and returns before it resolves.
   * Once confirmed, the inner command runs through its own `execute()`, so an
   * asynchronous inner keeps its failures on its own error channel and this
   * decorator does not watch its operation (spec §8.3.2). Await
   * {@link executeAsync} to sequence the flow inline.
   */
  execute(): void {
    // A rejecting confirm delegate or a throwing synchronous inner command
    // cannot propagate to this synchronous caller across the async confirm
    // gate. Surface it on the errors channel instead of swallowing it
    // (VMX-009) — a bare `void` here would also become a fatal unhandled
    // rejection. Await executeAsync() to observe it inline.
    void this.#run(false).catch((err: unknown) => {
      this.#errors.next(err);
    });
  }

  /**
   * Awaits the confirm delegate and, when it resolves `true`, invokes the inner
   * command exactly once: an asynchronous inner (an `IAsyncCommand` or another
   * `ConfirmationDecoratorCommand`) through its `executeAsync()`, any other
   * inner through `execute()`. The promise settles when that invocation does,
   * so for an asynchronous inner it resolves when the inner operation
   * finishes. A confirm or inner failure rejects it unchanged and is not
   * emitted on {@link errors} (spec §8.3.2, ADR-0145). The inner keeps its own
   * admission and cancellation rules.
   */
  async executeAsync(): Promise<void> {
    await this.#run(true);
  }

  /**
   * Make the decorator inert and complete the {@link errors} channel (spec
   * §8.4, ADR-0134). Idempotent. A pending confirmation that resolves later
   * runs no inner command and emits nothing. The inner command stays owned by
   * its creator: an inner operation already running is neither cancelled nor
   * disposed, and `canExecuteChanged` delegates lazily to it.
   */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#errors.complete();
  }

  /**
   * Runs the confirm flow. `awaitInner` selects the awaited path, which awaits
   * an asynchronous inner's operation; the fire-and-forget path always starts
   * the inner through its own `execute()`.
   */
  async #run(awaitInner: boolean): Promise<void> {
    // The inner predicate may dispose this wrapper; confirm is never consulted
    // after disposal (spec §8.4).
    if (!this.canExecute() || this.#isDisposed()) return;
    const ok = await this.#confirm();
    // A confirmation that resolves after disposal runs nothing (spec §8.4).
    if (!ok || this.#isDisposed()) return;
    const inner = this.#inner;
    if (awaitInner && isAsyncInner(inner)) {
      await inner.executeAsync();
    } else {
      inner.execute();
    }
  }

  /** Re-reads disposal after a call-out that may have disposed this wrapper. */
  #isDisposed(): boolean {
    return this.#disposed;
  }
}

/**
 * True when `command` offers awaitable execution (spec §8.3.2): another
 * confirmation decorator, or an {@link IAsyncCommand}. TypeScript interfaces
 * have no runtime identity, so the capability is detected structurally.
 */
function isAsyncInner(command: ICommand): command is AsyncInnerCommand {
  if (command instanceof ConfirmationDecoratorCommand) return true;
  const candidate = command as Partial<IAsyncCommand>;
  return typeof candidate.executeAsync === "function"
    && typeof candidate.cancel === "function"
    && "isExecuting" in candidate;
}
