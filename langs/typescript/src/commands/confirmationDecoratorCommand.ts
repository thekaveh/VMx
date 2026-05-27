/**
 * ConfirmationDecoratorCommand — gates execution on an async confirm delegate.
 *
 * See spec/04-commands.md §Decorators and ADR-0012.
 */
import type { Observable } from "rxjs";
import type { ICommand } from "./types.js";

export type ConfirmDelegate = () => Promise<boolean>;

export class ConfirmationDecoratorCommand implements ICommand {
  readonly #inner: ICommand;
  readonly #confirm: ConfirmDelegate;

  constructor(inner: ICommand, confirm: ConfirmDelegate) {
    this.#inner = inner;
    this.#confirm = confirm;
  }

  get canExecuteChanged(): Observable<void> {
    return this.#inner.canExecuteChanged;
  }

  canExecute(): boolean {
    return this.#inner.canExecute();
  }

  /**
   * Fire-and-forget. The returned promise resolves after the confirm flow
   * completes; you can also await it for sequencing tests / batched UX.
   */
  execute(): void {
    void this.executeAsync();
  }

  async executeAsync(): Promise<void> {
    if (!this.canExecute()) return;
    const ok = await this.#confirm();
    if (ok) this.#inner.execute();
  }
}
