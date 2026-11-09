// Conformance tests: DLY-001..DLY-005 — DelayedTask over a virtual-time
// scheduler. See spec/11-threading.md §6, spec/12-conformance.md §33 and
// ADR-0219 (#670).

import { describe, expect, it } from "vitest";
import { DelayedTask } from "../../src/services/delayedTask.js";
import { captureRxUnhandledErrors } from "../setup.js";
import { FakeScheduler } from "../unit/notifications/fakeScheduler.js";

const SECOND = 1000;

/** Waits one macrotask, so rxjs delivers its unhandled-error reports. */
function drainReports(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

describe("DLY-001", () => {
  it("a scheduled action runs once at its due time", () => {
    const scheduler = new FakeScheduler();
    const task = new DelayedTask(scheduler);
    const pendingWhenRun: boolean[] = [];

    task.schedule(10 * SECOND, () => pendingWhenRun.push(task.isPending));
    expect(task.isPending).toBe(true);

    scheduler.advanceBy(9 * SECOND);
    expect(pendingWhenRun).toEqual([]);
    expect(task.isPending).toBe(true);

    scheduler.advanceBy(1 * SECOND);
    expect(pendingWhenRun).toEqual([false]);
    expect(task.isPending).toBe(false);

    scheduler.advanceBy(10 * SECOND);
    expect(pendingWhenRun).toEqual([false]);
  });

  it("an action that schedules itself again runs as a polling loop", () => {
    const scheduler = new FakeScheduler();
    const task = new DelayedTask(scheduler);
    const runTimes: number[] = [];
    const poll = (): void => {
      runTimes.push(scheduler.now());
      if (runTimes.length < 3) task.schedule(5 * SECOND, poll);
    };

    task.schedule(5 * SECOND, poll);
    scheduler.advanceBy(30 * SECOND);

    expect(runTimes).toEqual([5 * SECOND, 10 * SECOND, 15 * SECOND]);
    expect(task.isPending).toBe(false);
  });
});

describe("DLY-002", () => {
  it("a second schedule replaces the pending action and restarts the delay", () => {
    const scheduler = new FakeScheduler();
    const task = new DelayedTask(scheduler);
    let aRuns = 0;
    let bRuns = 0;

    task.schedule(10 * SECOND, () => aRuns++);
    scheduler.advanceBy(6 * SECOND);
    task.schedule(10 * SECOND, () => bRuns++);
    scheduler.advanceBy(9 * SECOND);

    expect(aRuns).toBe(0);
    expect(bRuns).toBe(0);
    expect(task.isPending).toBe(true);

    scheduler.advanceBy(1 * SECOND);
    expect(bRuns).toBe(1);

    scheduler.advanceBy(10 * SECOND);
    expect(aRuns).toBe(0);
    expect(bRuns).toBe(1);
  });
});

describe("DLY-003", () => {
  it("cancel prevents the pending action", () => {
    const scheduler = new FakeScheduler();
    const task = new DelayedTask(scheduler);

    expect(() => task.cancel()).not.toThrow();
    expect(task.isPending).toBe(false);

    let cancelledRuns = 0;
    task.schedule(10 * SECOND, () => cancelledRuns++);
    scheduler.advanceBy(4 * SECOND);
    task.cancel();
    expect(task.isPending).toBe(false);

    scheduler.advanceBy(7 * SECOND);
    expect(cancelledRuns).toBe(0);

    const laterRunTimes: number[] = [];
    task.schedule(10 * SECOND, () => laterRunTimes.push(scheduler.now()));
    scheduler.advanceBy(9 * SECOND);
    expect(laterRunTimes).toEqual([]);
    scheduler.advanceBy(1 * SECOND);
    expect(laterRunTimes).toEqual([21 * SECOND]);
    expect(cancelledRuns).toBe(0);
  });
});

describe("DLY-004", () => {
  it("disposal cancels the pending action, and later calls have no effect", () => {
    const scheduler = new FakeScheduler();
    const task = new DelayedTask(scheduler);
    let pendingRuns = 0;
    task.schedule(10 * SECOND, () => pendingRuns++);

    task.dispose();
    task.dispose();
    expect(task.isPending).toBe(false);

    scheduler.advanceBy(11 * SECOND);
    expect(pendingRuns).toBe(0);

    let lateRuns = 0;
    expect(() => task.schedule(1 * SECOND, () => lateRuns++)).not.toThrow();
    expect(task.isPending).toBe(false);
    expect(() => task.cancel()).not.toThrow();
    expect(task.isPending).toBe(false);
    scheduler.advanceBy(5 * SECOND);
    expect(lateRuns).toBe(0);

    let otherRuns = 0;
    scheduler.schedule(() => otherRuns++, 1 * SECOND);
    scheduler.advanceBy(1 * SECOND);
    expect(otherRuns).toBe(1);
  });
});

describe("DLY-005", () => {
  it("a failing action stays isolated, and the task stays usable", async () => {
    const reports = captureRxUnhandledErrors();
    const scheduler = new FakeScheduler();
    const task = new DelayedTask(scheduler);
    const failure = new Error("delayed action failed");

    task.schedule(1 * SECOND, () => {
      throw failure;
    });
    expect(() => scheduler.advanceBy(2 * SECOND)).not.toThrow();
    expect(task.isPending).toBe(false);

    await drainReports();
    expect(reports).toEqual([failure]);

    let secondRuns = 0;
    task.schedule(1 * SECOND, () => secondRuns++);
    scheduler.advanceBy(2 * SECOND);
    expect(secondRuns).toBe(1);
  });
});
