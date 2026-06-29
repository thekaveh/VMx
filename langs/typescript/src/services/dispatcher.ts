/**
 * Dispatcher — paired Rx schedulers for foreground and background work.
 *
 * See spec/11-threading.md for the threading contract.
 */
import type { SchedulerLike } from "rxjs";
import { asyncScheduler, queueScheduler } from "rxjs";

export interface IDispatcher {
  readonly foreground: SchedulerLike;
  readonly background: SchedulerLike;
}

export class RxDispatcher implements IDispatcher {
  readonly foreground: SchedulerLike;
  readonly background: SchedulerLike;

  constructor(foreground: SchedulerLike, background: SchedulerLike) {
    this.foreground = foreground;
    this.background = background;
  }

  /**
   * Both foreground and background use queueScheduler (synchronous).
   * Suitable for console scripts and unit tests.
   */
  static immediate(): RxDispatcher {
    return new RxDispatcher(queueScheduler, queueScheduler);
  }

  /**
   * Default browser / Node dispatcher:
   *   foreground → queueScheduler (synchronous trampoline — runs inline,
   *                fair-queued against other queued work)
   *   background → asyncScheduler (macrotask — deferred past the current call
   *                stack AND the microtask queue, so background work does not
   *                starve pending I/O, timers, or paint).
   *
   * VMX-087: background previously used `asapScheduler` (a Promise microtask),
   * which drains before the next macrotask and can starve the event loop —
   * contradicting the "background" intent. `asyncScheduler` is the genuine
   * macrotask deferral. `immediate()` remains fully synchronous for tests.
   */
  static default(): RxDispatcher {
    return new RxDispatcher(queueScheduler, asyncScheduler);
  }
}
