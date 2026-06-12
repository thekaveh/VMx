/**
 * CompositeCommand — aggregates N inner commands.
 *
 * See spec/04-commands.md §Decorators and ADR-0012.
 */
import { merge, NEVER, type Observable } from "rxjs";
import type { ICommand } from "./types.js";

export class CompositeCommand implements ICommand {
  readonly #inner: readonly ICommand[];
  readonly canExecuteChanged: Observable<void>;
  #disposed = false;

  constructor(...inner: ICommand[]) {
    this.#inner = inner;
    this.canExecuteChanged =
      inner.length === 0
        ? NEVER
        : merge(...inner.map((c) => c.canExecuteChanged));
  }

  canExecute(): boolean {
    for (const c of this.#inner) if (c.canExecute()) return true;
    return false;
  }

  execute(): void {
    for (const c of this.#inner) if (c.canExecute()) c.execute();
  }

  /**
   * Mark the composite as disposed. Idempotent. `canExecuteChanged` is a
   * lazy merge of the inner streams — subscribers' own teardown closes the
   * chain, so nothing is owned or released here. Provided for teardown
   * symmetry with the C# IDisposable surface.
   */
  dispose(): void {
    this.#disposed = true;
  }
}
