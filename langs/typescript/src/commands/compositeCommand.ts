/**
 * CompositeCommand — aggregates N inner commands.
 *
 * See spec/04-commands.md §Decorators and ADR-0012.
 */
import { merge, NEVER, Subject, type Observable } from "rxjs";
import { withDisposalSignal } from "./disposalSignal.js";
import type { ICommand } from "./types.js";

export class CompositeCommand implements ICommand {
  readonly #inner: readonly ICommand[];
  readonly canExecuteChanged: Observable<void>;
  /** Emits once at disposal, so a binding re-reads `canExecute` (spec §8.4). */
  readonly #disposal = new Subject<void>();
  #disposed = false;

  constructor(...inner: ICommand[]) {
    this.#inner = inner;
    this.canExecuteChanged = withDisposalSignal(
      inner.length === 0 ? NEVER : merge(...inner.map((c) => c.canExecuteChanged)),
      this.#disposal,
    );
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
   * Make the composite inert (spec §8.4, ADR-0134). Idempotent. Notifies this
   * composite's `canExecuteChanged` subscribers once; subscribers of the inner
   * commands get nothing. The inner commands and their streams stay owned by
   * their creator.
   */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#disposal.next();
    this.#disposal.complete();
  }

  /** Re-reads disposal after a call-out that may have disposed this wrapper. */
  #isDisposed(): boolean {
    return this.#disposed;
  }
}
