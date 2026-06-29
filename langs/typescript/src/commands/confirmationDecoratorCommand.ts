/**
 * ConfirmationDecoratorCommand — gates execution on an async confirm delegate.
 *
 * See spec/04-commands.md §Decorators and ADR-0012.
 */
import { Subject } from "rxjs";
import type { Observable } from "rxjs";
import type { ICommand } from "./types.js";

export type ConfirmDelegate = () => Promise<boolean>;

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
   * path — either the confirm delegate rejecting or the inner command throwing.
   * `execute()` is synchronous and runs the confirm gate asynchronously, so it
   * cannot propagate the way the base `RelayCommand`'s task does; instead of
   * swallowing the error it is emitted here (VMX-009). Await {@link executeAsync}
   * to observe it inline. Completes on {@link dispose}.
   */
  get errors(): Observable<unknown> {
    return this.#errors.asObservable();
  }

  canExecute(): boolean {
    return this.#inner.canExecute();
  }

  /**
   * Fire-and-forget. The returned promise resolves after the confirm flow
   * completes; you can also await it for sequencing tests / batched UX.
   */
  execute(): void {
    // A rejecting confirm delegate or a throwing inner command cannot propagate
    // to this synchronous caller across the async confirm gate. Surface it on
    // the errors channel instead of swallowing it (VMX-009) — a bare `void`
    // here would also become a fatal unhandled rejection. Await executeAsync()
    // to observe it inline.
    void this.executeAsync().catch((err: unknown) => {
      this.#errors.next(err);
    });
  }

  async executeAsync(): Promise<void> {
    if (!this.canExecute()) return;
    const ok = await this.#confirm();
    if (ok) this.#inner.execute();
  }

  /**
   * Mark the decorator as disposed and complete the {@link errors} channel.
   * Idempotent. `canExecuteChanged` delegates lazily to the inner command, so
   * nothing else is owned or released here — provided for teardown symmetry
   * with the C# IDisposable surface.
   */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#errors.complete();
  }
}
