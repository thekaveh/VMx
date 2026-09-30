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
    if (this.#disposed) return false;
    for (const c of this.#inner) if (c.canExecute()) return !this.#isDisposed();
    return false;
  }

  execute(): void {
    // A child's predicate or action may dispose the composite; no further
    // child runs once disposal is observed (spec §8.4, ADR-0134).
    for (const c of this.#inner) {
      if (this.#isDisposed()) return;
      if (!c.canExecute() || this.#isDisposed()) continue;
      c.execute();
    }
  }

  /**
   * Make the composite inert (spec §8.4, ADR-0134). Idempotent. The inner
   * commands stay owned by their creator. `canExecuteChanged` is a lazy merge
   * of the inner streams, so nothing else is owned or released here.
   */
  dispose(): void {
    this.#disposed = true;
  }

  /** Re-reads disposal after a call-out that may have disposed this wrapper. */
  #isDisposed(): boolean {
    return this.#disposed;
  }
}
