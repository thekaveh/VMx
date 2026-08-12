import { Subject, type Observable } from "rxjs";
import type { IAsyncCommand, ICommand, ICommandOf } from "../commands/types.js";

export interface CommandDoubleOptions {
  readonly canExecute?: boolean;
}

/** Runner-neutral controllable double for a parameterless command. */
export class CommandDouble implements ICommand {
  readonly #canExecuteChanged = new Subject<void>();
  #canExecute: boolean;
  #failure: Error | null = null;
  #executionCount = 0;
  #disposed = false;

  constructor(options: CommandDoubleOptions = {}) {
    this.#canExecute = options.canExecute ?? true;
  }

  get canExecuteChanged(): Observable<void> {
    return this.#canExecuteChanged.asObservable();
  }

  get executionCount(): number {
    return this.#executionCount;
  }

  canExecute(): boolean {
    return !this.#disposed && this.#canExecute;
  }

  execute(): void {
    if (!this.canExecute()) return;
    this.#executionCount += 1;
    if (this.#failure !== null) throw this.#failure;
  }

  setCanExecute(value: boolean): void {
    if (this.#disposed || value === this.#canExecute) return;
    this.#canExecute = value;
    this.raiseCanExecuteChanged();
  }

  raiseCanExecuteChanged(): void {
    if (!this.#disposed) this.#canExecuteChanged.next();
  }

  failWith(error: Error | null): void {
    this.#failure = error;
  }

  clear(): void {
    this.#executionCount = 0;
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#canExecuteChanged.complete();
  }
}

/** Runner-neutral controllable double for a parameterized command. */
export class CommandDoubleOf<T> implements ICommandOf<T> {
  readonly #canExecuteChanged = new Subject<void>();
  readonly #executions: T[] = [];
  #canExecute: boolean;
  #failure: Error | null = null;
  #disposed = false;

  constructor(options: CommandDoubleOptions = {}) {
    this.#canExecute = options.canExecute ?? true;
  }

  get canExecuteChanged(): Observable<void> {
    return this.#canExecuteChanged.asObservable();
  }

  get executions(): readonly T[] {
    return [...this.#executions];
  }

  canExecute(_parameter: T): boolean {
    return !this.#disposed && this.#canExecute;
  }

  execute(parameter: T): void {
    if (!this.canExecute(parameter)) return;
    this.#executions.push(parameter);
    if (this.#failure !== null) throw this.#failure;
  }

  setCanExecute(value: boolean): void {
    if (this.#disposed || value === this.#canExecute) return;
    this.#canExecute = value;
    this.raiseCanExecuteChanged();
  }

  raiseCanExecuteChanged(): void {
    if (!this.#disposed) this.#canExecuteChanged.next();
  }

  failWith(error: Error | null): void {
    this.#failure = error;
  }

  clear(): void {
    this.#executions.length = 0;
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#canExecuteChanged.complete();
  }
}

interface PendingExecution {
  readonly resolve: () => void;
  readonly reject: (error: unknown) => void;
  detachExternalAbort: () => void;
}

/** A manually completed, cancellable IAsyncCommand test double. */
export class AsyncCommandDouble implements IAsyncCommand {
  readonly #canExecuteChanged = new Subject<void>();
  readonly #errors = new Subject<unknown>();
  #canExecute = true;
  #executionCount = 0;
  #pending: PendingExecution | null = null;
  #disposed = false;

  get canExecuteChanged(): Observable<void> {
    return this.#canExecuteChanged.asObservable();
  }

  get errors(): Observable<unknown> {
    return this.#errors.asObservable();
  }

  get executionCount(): number {
    return this.#executionCount;
  }

  get isExecuting(): boolean {
    return this.#pending !== null;
  }

  canExecute(): boolean {
    return !this.#disposed && this.#canExecute && !this.isExecuting;
  }

  execute(): void {
    void this.executeAsync().catch((error: unknown) => {
      if (!this.#disposed && !isAbortError(error)) this.#errors.next(error);
    });
  }

  executeAsync(externalSignal?: AbortSignal): Promise<void> {
    if (!this.canExecute()) return Promise.resolve();
    this.#executionCount += 1;

    let resolvePending: () => void = () => undefined;
    let rejectPending: (error: unknown) => void = () => undefined;
    const controlled = new Promise<void>((resolve, reject) => {
      resolvePending = resolve;
      rejectPending = reject;
    });
    const pending: PendingExecution = {
      resolve: resolvePending,
      reject: rejectPending,
      detachExternalAbort: () => undefined,
    };
    this.#pending = pending;
    this.#canExecuteChanged.next();

    if (externalSignal !== undefined) {
      const abort = (): void => pending.reject(abortError(externalSignal.reason));
      if (externalSignal.aborted) {
        abort();
      } else {
        externalSignal.addEventListener("abort", abort, { once: true });
        pending.detachExternalAbort = () => externalSignal.removeEventListener("abort", abort);
      }
    }

    return controlled.finally(() => this.#finish(pending));
  }

  setCanExecute(value: boolean): void {
    if (this.#disposed || value === this.#canExecute) return;
    this.#canExecute = value;
    this.raiseCanExecuteChanged();
  }

  raiseCanExecuteChanged(): void {
    if (!this.#disposed) this.#canExecuteChanged.next();
  }

  resolve(): void {
    this.#pending?.resolve();
  }

  reject(error: unknown): void {
    this.#pending?.reject(error);
  }

  cancel(): void {
    this.#pending?.resolve();
  }

  clear(): void {
    this.#executionCount = 0;
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#pending?.resolve();
    this.#canExecuteChanged.complete();
    this.#errors.complete();
  }

  #finish(pending: PendingExecution): void {
    pending.detachExternalAbort();
    if (this.#pending !== pending) return;
    this.#pending = null;
    this.raiseCanExecuteChanged();
  }
}

function abortError(reason: unknown): Error {
  const message = typeof reason === "string" ? reason : "The operation was aborted";
  const error = new Error(message);
  error.name = "AbortError";
  return error;
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object"
    && error !== null
    && "name" in error
    && (error as { readonly name?: unknown }).name === "AbortError";
}
