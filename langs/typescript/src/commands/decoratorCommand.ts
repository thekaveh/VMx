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
    if (!this.#inner.canExecute()) return false;
    if (this.#extra === null) return true;
    try {
      return this.#extra();
    } catch {
      return false;
    }
  }

  execute(): void {
    if (!this.canExecute()) return;
    if (this.#pre) this.#pre();
    try {
      this.#inner.execute();
    } finally {
      // post runs whether or not the inner threw, so that a "busy" flag set
      // in preExecute always gets cleared.
      if (this.#post) this.#post();
    }
  }
}
