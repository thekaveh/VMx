// Unit tests for DelayedTask edge cases (spec/11-threading.md §6.3, ADR-0219,
// #670): schedulers whose cancel does not stop a fire, inline schedulers,
// zero and negative delays, and disposal from inside the action.

import { asyncScheduler, queueScheduler, Subscription } from "rxjs";
import type { SchedulerAction, SchedulerLike } from "rxjs";
import { describe, expect, it } from "vitest";
import { DelayedTask } from "../../src/services/delayedTask.js";
import { FakeScheduler } from "./notifications/fakeScheduler.js";

/**
 * A scheduler that keeps every action and ignores unsubscribe, as a real
 * timer can when its cancel races the fire. `fireAll` runs every kept action.
 */
class IgnoresCancelScheduler implements SchedulerLike {
  readonly delays: number[] = [];
  readonly #actions: Array<() => void> = [];

  now(): number {
    return 0;
  }

  schedule<T>(
    work: (this: SchedulerAction<T>, state?: T) => void,
    delay = 0,
    state?: T,
  ): Subscription {
    this.delays.push(delay);
    const stub = new Subscription() as SchedulerAction<T>;
    this.#actions.push(() => work.call(stub, state));
    return new Subscription();
  }

  fireAll(): void {
    for (const action of this.#actions.splice(0)) action();
  }
}

describe("DelayedTask", () => {
  it("never starts a replaced action, even when the scheduler cancel does not stop it", () => {
    const scheduler = new IgnoresCancelScheduler();
    const task = new DelayedTask(scheduler);
    const runs: string[] = [];

    task.schedule(10, () => runs.push("a"));
    task.schedule(10, () => runs.push("b"));
    scheduler.fireAll();

    expect(runs).toEqual(["b"]);
    expect(task.isPending).toBe(false);
  });

  it("never starts a cancelled or disposed action, even when the scheduler cancel does not stop it", () => {
    const scheduler = new IgnoresCancelScheduler();
    const cancelled = new DelayedTask(scheduler);
    const disposed = new DelayedTask(scheduler);
    const runs: string[] = [];

    cancelled.schedule(10, () => runs.push("cancelled"));
    cancelled.cancel();
    disposed.schedule(10, () => runs.push("disposed"));
    disposed.dispose();
    scheduler.fireAll();

    expect(runs).toEqual([]);
  });

  it("passes a negative delay to the scheduler as zero", () => {
    const scheduler = new IgnoresCancelScheduler();
    const task = new DelayedTask(scheduler);

    task.schedule(-5, () => undefined);
    task.schedule(0, () => undefined);
    task.schedule(7, () => undefined);

    expect(scheduler.delays).toEqual([0, 0, 7]);
  });

  it("does not run a zero-delay action inside schedule on a timer scheduler", async () => {
    const task = new DelayedTask(asyncScheduler);
    let runs = 0;

    task.schedule(0, () => runs++);
    expect(runs).toBe(0);
    expect(task.isPending).toBe(true);

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(runs).toBe(1);
    expect(task.isPending).toBe(false);
  });

  it("stays consistent when the scheduler runs the action inline", () => {
    const task = new DelayedTask(queueScheduler);
    const pendingWhenRun: boolean[] = [];

    task.schedule(0, () => pendingWhenRun.push(task.isPending));

    expect(pendingWhenRun).toEqual([false]);
    expect(task.isPending).toBe(false);
    task.cancel();
    task.schedule(0, () => pendingWhenRun.push(task.isPending));
    expect(pendingWhenRun).toEqual([false, false]);
  });

  it("keeps a schedule made by an inline action pending", () => {
    const task = new DelayedTask(queueScheduler);
    let laterRuns = 0;

    task.schedule(0, () => {
      task.schedule(1000, () => laterRuns++);
    });

    // queueScheduler runs a delayed action on a timer, so the re-schedule
    // stays pending, and cancel stops it.
    expect(task.isPending).toBe(true);
    task.cancel();
    expect(task.isPending).toBe(false);
    expect(laterRuns).toBe(0);
  });

  it("leaves nothing pending when the scheduler throws", () => {
    const refusal = new Error("scheduler refused");
    const throwing: SchedulerLike = {
      now: () => 0,
      schedule: () => {
        throw refusal;
      },
    };
    const task = new DelayedTask(throwing);

    expect(() => task.schedule(10, () => {})).toThrow(refusal);
    expect(task.isPending).toBe(false);
  });

  it("makes later calls inert when the action disposes the task", () => {
    const scheduler = new FakeScheduler();
    const task = new DelayedTask(scheduler);
    let laterRuns = 0;

    task.schedule(10, () => task.dispose());
    scheduler.advanceBy(10);
    task.schedule(10, () => laterRuns++);
    scheduler.advanceBy(20);

    expect(task.isPending).toBe(false);
    expect(laterRuns).toBe(0);
  });
});
