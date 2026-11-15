// #1886: the scheduler-recovery layer, driven without a view-model. The tests
// queue counted actions on a fake SchedulerLike, then drop them the way a flush
// error does: each action's subscription is unsubscribed before it runs (#1052).

import { describe, expect, it, vi } from "vitest";
import { Subscription, type SchedulerLike } from "rxjs";
import { scheduleCounted } from "../../src/components/schedulerRecovery.js";
import { captureRxUnhandledErrors } from "../setup.js";

/** Let rxjs deliver the unhandled-error reports it queued on a timer. */
async function afterReports(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

/** A held action: it runs only when the test runs it or drops it. */
interface Held {
  readonly work: () => void;
  readonly subscription: Subscription;
}

/** Identity is all `scheduleCounted` needs from the scheduler it keys its state by. */
function fakeScheduler(): SchedulerLike {
  return { now: () => 0 } as unknown as SchedulerLike;
}

/** Hold each queued action, as a scheduler does before its flush runs. */
function holdOn(held: Held[]): (work: () => void) => Subscription {
  return (work) => {
    const subscription = new Subscription();
    held.push({ work, subscription });
    return subscription;
  };
}

/** Drop every held action the way a flush error does: unsubscribe it unrun. */
function dropAll(held: Held[]): void {
  for (const action of held.splice(0)) action.subscription.unsubscribe();
}

describe("scheduler recovery", () => {
  it("runs a dropped counted action when a flush error unsubscribes it", () => {
    const scheduler = fakeScheduler();
    const held: Held[] = [];
    const work = vi.fn();

    scheduleCounted(scheduler, holdOn(held), work);
    expect(work).not.toHaveBeenCalled();

    dropAll(held);
    expect(work).toHaveBeenCalledTimes(1);
  });

  it("reports a later failure of a recovered action through reportUnhandled", async () => {
    const captured = captureRxUnhandledErrors();
    const scheduler = fakeScheduler();
    const held: Held[] = [];
    const later = new Error("later failure of a recovered action");

    scheduleCounted(scheduler, holdOn(held), () => {
      throw later;
    });
    dropAll(held);
    await afterReports();

    expect(captured).toHaveLength(1);
    expect(captured[0]).toBe(later);
  });
});
