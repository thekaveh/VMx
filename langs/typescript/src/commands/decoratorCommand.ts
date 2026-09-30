/**
 * DecoratorCommand — wraps a single inner command with pre/post + extra-predicate.
 *
 * See spec/04-commands.md §Decorators and ADR-0012.
 */
import type { Observable } from "rxjs";
import type { ICommand } from "./types.js";

export interface DecoratorCommandOptions {
  preExecute?: () => void;
  postExecute?: () => void;
  extraPredicate?: () => boolean;
}

export class DecoratorCommand implements ICommand {
  readonly #inner: ICommand;
  readonly #pre: (() => void) | null;
  readonly #post: (() => void) | null;
  readonly #extra: (() => boolean) | null;
  #disposed = false;

  constructor(inner: ICommand, opts: DecoratorCommandOptions = {}) {
    this.#inner = inner;
    this.#pre = opts.preExecute ?? null;
    this.#post = opts.postExecute ?? null;
    this.#extra = opts.extraPredicate ?? null;
  }

  get canExecuteChanged(): Observable<void> {
    return this.#inner.canExecuteChanged;
  }

  canExecute(): boolean {
    if (this.#disposed || !this.#inner.canExecute()) return false;
    if (this.#extra === null) return !this.#isDisposed();
    try {
      // The extra predicate may dispose the decorator.
      return this.#extra() && !this.#isDisposed();
    } catch {
      return false;
    }
  }

  execute(): void {
    if (!this.canExecute()) return;
    if (this.#pre) this.#pre();
    try {
      // The pre-action may dispose the decorator: skip the inner command, but
      // keep the admitted pre/post pair balanced (spec §8.4, ADR-0134).
      if (!this.#isDisposed()) this.#inner.execute();
    } finally {
      // post runs whether or not the inner threw, so that a "busy" flag set
      // in preExecute always gets cleared.
      if (this.#post) this.#post();
    }
  }

  /**
   * Make the decorator inert (spec §8.4, ADR-0134). Idempotent. The inner
   * command stays owned by its creator. `canExecuteChanged` delegates lazily
   * to the inner command, so nothing else is owned or released here.
   */
  dispose(): void {
    this.#disposed = true;
  }

  /** Re-reads disposal after a call-out that may have disposed this wrapper. */
  #isDisposed(): boolean {
    return this.#disposed;
  }
}
