/**
 * ICommand interfaces for the VMx command contract.
 *
 * See spec/04-commands.md.
 */
import type { Observable } from "rxjs";

export interface ICommand {
  canExecute(): boolean;
  execute(): void;
  readonly canExecuteChanged: Observable<void>;
}

export interface ICommandOf<T> {
  canExecute(parameter: T): boolean;
  execute(parameter: T): void;
  readonly canExecuteChanged: Observable<void>;
}

/**
 * An ICommand whose work is asynchronous and cancellable.
 *
 * See spec/04-commands.md §11 (async command cancellation), ADR-0056.
 *
 * `executeAsync` flows an `AbortSignal` into the task; `cancel()` aborts the
 * in-flight execution via an internal `AbortController`. Cancellation is
 * non-throwing to the caller by default — the awaited `executeAsync` resolves
 * on cancel rather than rejecting — mirroring the dialog cancellation contract
 * (spec/19-dialogs.md §6, DIA-007). While an execution is in flight `canExecute`
 * returns `false`, so the command cannot double-run.
 */
export interface IAsyncCommand extends ICommand {
  /** True while an execution is in flight; false when idle. */
  readonly isExecuting: boolean;
  /** Runs the async task, optionally linked to an external `AbortSignal`. */
  executeAsync(externalSignal?: AbortSignal): Promise<void>;
  /** Requests cancellation of the in-flight execution; a no-op when idle. */
  cancel(): void;
}
