/**
 * Scheduler recovery for ComponentVMBase (internal).
 *
 * An error in a flush of an rxjs scheduler unsubscribes the actions queued
 * behind it. This module runs the VMx actions that such a flush dropped (#1052),
 * tracks the VMx actions still queued (#1053), and keeps the first failure of
 * each background flush. It references no view-model. Nothing here is part of
 * the public API; the package index does not export this module.
 */
import type { SchedulerLike, Subscription } from "rxjs";
import { isSchedulerCancelled } from "../services/cancelledSchedulers.js";
import { reportUnhandled } from "../services/reportUnhandled.js";

/** The first failure recorded in a background `construct()` or `destruct()` flush. */
interface BackgroundScheduling {
  failure: { error: unknown } | null;
  /**
   * Set when an error left the flush before any failure was recorded (#1052).
   * That error is then the first failure, and later ones are not recorded.
   */
  flushFailed: boolean;
}

/**
 * The outermost background `construct()` or `destruct()` that is still inside
 * its `schedule()` call, per scheduler that serves both channels (#726, #1053).
 * A rollback failure anywhere in that flush is recorded here. That call throws
 * the first one after the flush drains, so no rollback queued in it is lost.
 */
const activeSharedDrains = new WeakMap<SchedulerLike, BackgroundScheduling>();

/**
 * Run `schedule` as the outermost drain of `scheduler` if none is active, then
 * throw the first failure of the flush. An error that leaves the flush, for
 * example from an action that VMx did not queue, is that first failure unless
 * a failure was recorded before it (#1052). Then that error is reported
 * through `reportUnhandled` (ADR-0200 §2.3).
 */
export function drainBackground(scheduler: SchedulerLike | null, schedule: () => void): void {
  const scheduling: BackgroundScheduling = { failure: null, flushFailed: false };
  const outermost = scheduler !== null && !activeSharedDrains.has(scheduler);
  if (outermost) activeSharedDrains.set(scheduler, scheduling);
  let thrown: { error: unknown } | null = null;
  try {
    schedule();
  } catch (error) {
    thrown = { error };
  } finally {
    if (outermost) activeSharedDrains.delete(scheduler);
  }
  const recorded = scheduling.failure;
  if (recorded !== null && thrown !== null && thrown.error !== recorded.error) {
    reportUnhandled(thrown.error);
  }
  const failure = recorded ?? thrown;
  if (failure !== null) throw failure.error;
}

/**
 * The VMx actions that a flush error dropped and that run now, per scheduler
 * (#1052). VMx work queued on that scheduler while they run joins this queue,
 * so it does not start a nested flush. Each dropped action's finalizer starts
 * or joins this queue in turn, so the order is that of the finalizers plus the
 * work they queue, not the order of a normal flush. Work that joins the queue
 * goes straight to it, past any `_scheduleForeground` override; this happens
 * only while a failed flush tears down.
 */
const recoveries = new WeakMap<SchedulerLike, Array<() => void>>();

/**
 * Run `run`, a VMx action that an error in a flush of `scheduler` dropped.
 *
 * rxjs calls this from the finalizer of the dropped action, while the flush
 * error is on its way to the caller. That error leaves the flush first, so a
 * failure of the recovered work is a later failure of the same flush. It is
 * reported through `reportUnhandled` (ADR-0200 §2.3) and is never thrown from
 * here: a throw from a finalizer would replace the flush error.
 */
function recoverDropped(scheduler: SchedulerLike, run: () => void): void {
  const drain = activeSharedDrains.get(scheduler);
  if (drain !== undefined) drain.flushFailed = true;
  const active = recoveries.get(scheduler);
  if (active !== undefined) {
    active.push(run);
    return;
  }
  const queue = [run];
  recoveries.set(scheduler, queue);
  try {
    for (let next = queue.shift(); next !== undefined; next = queue.shift()) {
      try {
        next();
      } catch (error) {
        // A later failure of a failed flush (see above).
        reportUnhandled(error);
      }
    }
  } finally {
    recoveries.delete(scheduler);
  }
}

/**
 * The actions that VMx queued on a scheduler and that have not run yet
 * (#1053). These are the lifecycle completions on the foreground, the
 * background actions of `construct()` and `destruct()`, and the asynchronous
 * selection deliveries of a composite (#1421).
 */
interface CountedActions {
  pending: number;
  /** Changes each time a counted action is queued or runs. */
  version: number;
}

const countedActions = new WeakMap<SchedulerLike, CountedActions>();

export function countedActionsOf(scheduler: SchedulerLike): CountedActions {
  let counted = countedActions.get(scheduler);
  if (counted === undefined) {
    counted = { pending: 0, version: 0 };
    countedActions.set(scheduler, counted);
  }
  return counted;
}

/**
 * Queue `work` through `schedule` as a counted action of `scheduler` (#1053).
 *
 * An error in a flush of `scheduler` unsubscribes the actions queued behind
 * it, including an error from an action that VMx did not queue. The finalizer
 * added here runs on any unsubscribe of the action. When the action has not
 * run and `scheduler` has not marked itself cancelled, the finalizer treats
 * the action as dropped and runs `work`, so the VM still settles (#1052).
 * VMx never unsubscribes these actions itself. A custom scheduler that cancels
 * queued work by unsubscribing it calls the public `markSchedulerCancelled`
 * first, as `ManualDispatcher` does; otherwise VMx runs that work, including
 * lifecycle work and asynchronous selection deliveries (ADR-0200).
 * `schedule` returns null when it cannot give the action's subscription, such
 * as for an override of `_scheduleForeground`.
 */
export function scheduleCounted(
  scheduler: SchedulerLike,
  schedule: (work: () => void) => Subscription | null,
  work: () => void,
): void {
  const counted = countedActionsOf(scheduler);
  counted.pending++;
  counted.version++;
  let ran = false;
  const run = (): void => {
    if (ran) return;
    ran = true;
    counted.pending = Math.max(0, counted.pending - 1);
    counted.version++;
    work();
  };
  const recovery = recoveries.get(scheduler);
  if (recovery !== undefined) {
    recovery.push(run);
    return;
  }
  // A custom SchedulerLike can return an object without rxjs `add`.
  const subscription: Partial<Subscription> | null = schedule(run);
  if (typeof subscription?.add === "function" && subscription.closed !== true) {
    subscription.add(() => {
      if (!ran && !isSchedulerCancelled(scheduler)) recoverDropped(scheduler, run);
    });
  }
}

/**
 * Record `error` on the active drain of `scheduler`, if one is open. The drain
 * keeps the first recorded failure of its flush and reports every later one
 * through `reportUnhandled` (ADR-0200 §2.3). Returns false when no drain is open.
 */
export function recordOnActiveDrain(scheduler: SchedulerLike | null, error: unknown): boolean {
  const drain = scheduler === null ? undefined : activeSharedDrains.get(scheduler);
  if (drain === undefined) return false;
  // An error that already left the flush is its first failure (#1052).
  if (drain.flushFailed || drain.failure !== null) reportUnhandled(error);
  else drain.failure = { error };
  return true;
}

/** True while `recoverDropped` runs the dropped actions of `scheduler` (#1052). */
export function isRecovering(scheduler: SchedulerLike): boolean {
  return recoveries.has(scheduler);
}
