import type { SchedulerLike } from "rxjs";

/**
 * Schedulers that cancelled their queued work by unsubscribing it (#1052).
 *
 * VMx runs a lifecycle action that was unsubscribed before it ran, because a
 * flush error drops queued actions that way. A scheduler that cancels work on
 * purpose, such as `ManualDispatcher` on `dispose()`, marks itself here first,
 * so its cancelled VMx work stays cancelled.
 */
const cancelled = new WeakSet<SchedulerLike>();

/**
 * Mark `scheduler` as cancelling its queued work (ADR-0200 §2.3). The mark is
 * permanent.
 *
 * A custom scheduler that cancels its queued work calls this before it
 * unsubscribes that work. VMx then runs no lifecycle hook and publishes no
 * status for the VMx work that it unsubscribes. A failure that already
 * happened is still reported through rxjs `config.onUnhandledError`. Without
 * the mark, VMx treats each unsubscribed VMx action as dropped by a flush
 * error and runs it, so the VM still settles (#1052).
 */
export function markSchedulerCancelled(scheduler: SchedulerLike): void {
  cancelled.add(scheduler);
}

/** True when `scheduler` has cancelled its queued work. Internal. */
export function isSchedulerCancelled(scheduler: SchedulerLike): boolean {
  return cancelled.has(scheduler);
}
