/**
 * Dispatcher — paired Rx schedulers for foreground and background work.
 *
 * See spec/11-threading.md for the threading contract.
 */
import type { SchedulerLike } from "rxjs";
import { asapScheduler, queueScheduler } from "rxjs";

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
   *   foreground → queueScheduler (microtask / synchronous in test)
   *   background → asapScheduler (next macrotask)
   */
  static default(): RxDispatcher {
    return new RxDispatcher(queueScheduler, asapScheduler);
  }
}
