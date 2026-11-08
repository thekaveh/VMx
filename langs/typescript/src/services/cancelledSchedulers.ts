import type { SchedulerLike } from "rxjs";

/**
 * Schedulers that cancelled their queued work by unsubscribing it (#1052).
 *
 * VMx runs a lifecycle action that was unsubscribed before it ran, because a
 * flush error drops queued actions that way. A scheduler that cancels work on
 * purpose, such as `ManualDispatcher` on `dispose()`, marks itself here first,
 * so its cancelled VMx work stays cancelled. Internal: not exported.
 */
const cancelled = new WeakSet<SchedulerLike>();

/** Mark `scheduler` as cancelling its queued work. Call it before unsubscribing. */
export function markSchedulerCancelled(scheduler: SchedulerLike): void {
  cancelled.add(scheduler);
}

/** True when `scheduler` has cancelled its queued work. */
export function isSchedulerCancelled(scheduler: SchedulerLike): boolean {
  return cancelled.has(scheduler);
}
