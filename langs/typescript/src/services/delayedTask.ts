import type { SchedulerLike, Subscription } from "rxjs";
import { reportUnhandled } from "./reportUnhandled.js";

/**
 * Holds at most one delayed action on an injected scheduler (spec/11 §6.3,
 * ADR-0219).
 *
 * `schedule` replaces the pending action and restarts its delay, `cancel`
 * stops it, `isPending` reports it, and `dispose` cancels it and makes later
 * calls inert. The action runs where the scheduler runs it, never through
 * `IDispatcher`. Pass rxjs `asyncScheduler` for real time, or a virtual-time
 * scheduler in tests.
 *
 * After `schedule`, `cancel` or `dispose` returns, the replaced or cancelled
 * action never starts, even when the scheduler runs it anyway. A failing
 * action is reported through rxjs `config.onUnhandledError` (spec/03 §3.6);
 * the task stays usable. Disposal never disposes the scheduler.
 */
export class DelayedTask {
  readonly #scheduler: SchedulerLike;
  #generation = 0;
  #pending = false;
  #disposed = false;
  #handle: Subscription | null = null;

  constructor(scheduler: SchedulerLike) {
    this.#scheduler = scheduler;
  }

  /** True from `schedule` until the action starts, `cancel` or `dispose`. */
  get isPending(): boolean {
    return this.#pending;
  }

  /**
   * Cancels the pending action, if any, and schedules `action` after
   * `delayMs` milliseconds. A zero or negative delay runs the action at the
   * scheduler's next opportunity. Has no effect after `dispose`.
   */
  schedule(delayMs: number, action: () => void): void {
    if (this.#disposed) return;
    this.#cancelPending();
    const generation = ++this.#generation;
    this.#pending = true;
    const handle = this.#scheduler.schedule(
      () => this.#run(generation, action),
      Math.max(0, delayMs),
    );
    if (this.#isCurrent(generation)) {
      this.#handle = handle;
    } else {
      // The action already ran inline, or a nested call replaced it.
      handle.unsubscribe();
    }
  }

  /** Cancels the pending action. Has no effect when none is pending. */
  cancel(): void {
    this.#cancelPending();
  }

  /** Cancels the pending action. Later calls have no effect. */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#cancelPending();
  }

  #isCurrent(generation: number): boolean {
    return generation === this.#generation && this.#pending && !this.#disposed;
  }

  #cancelPending(): void {
    if (!this.#pending) return;
    this.#generation++;
    this.#pending = false;
    const handle = this.#handle;
    this.#handle = null;
    handle?.unsubscribe();
  }

  #run(generation: number, action: () => void): void {
    if (!this.#isCurrent(generation)) return;
    this.#pending = false;
    this.#handle = null;
    try {
      action();
    } catch (error) {
      reportUnhandled(error);
    }
  }
}
