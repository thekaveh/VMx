/**
 * NullDispatcher — null-object variant of IDispatcher.
 *
 * See spec/11-threading.md §"Null variant" and ADR-0017.
 *
 * Both schedulers are queueScheduler, which executes scheduled work
 * synchronously on the calling thread (no microtask, no macrotask hop).
 */
import { queueScheduler, type SchedulerLike } from "rxjs";
import type { IDispatcher } from "./dispatcher.js";

export class NullDispatcher implements IDispatcher {
  /** Shared singleton instance. */
  static readonly INSTANCE: NullDispatcher = new NullDispatcher();

  private constructor() {}

  readonly foreground: SchedulerLike = queueScheduler;
  readonly background: SchedulerLike = queueScheduler;
}
