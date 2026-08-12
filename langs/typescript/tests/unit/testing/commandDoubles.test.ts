import { describe, expect, it } from "vitest";
import {
  AsyncCommandDouble,
  CommandDouble,
  CommandDoubleOf,
} from "../../../src/testing/index.js";

describe("CommandDouble", () => {
  it("controls admission, records attempts, raises changes, and faults", () => {
    const command = new CommandDouble({ canExecute: false });
    let changes = 0;
    command.canExecuteChanged.subscribe(() => changes++);

    command.execute();
    expect(command.executionCount).toBe(0);
    command.setCanExecute(true);
    command.execute();
    expect(command.executionCount).toBe(1);
    expect(changes).toBe(1);

    const fault = new Error("boom");
    command.failWith(fault);
    expect(() => command.execute()).toThrow(fault);
    expect(command.executionCount).toBe(2);
    command.clear();
    expect(command.executionCount).toBe(0);

    command.dispose();
    command.dispose();
    command.setCanExecute(true);
    command.execute();
    expect(command.canExecute()).toBe(false);
    expect(command.executionCount).toBe(0);
  });

  it("records admitted typed parameters as copied history", () => {
    const command = new CommandDoubleOf<number>();
    command.execute(1);
    command.execute(2);
    const snapshot = command.executions;
    command.clear();

    expect(snapshot).toEqual([1, 2]);
    expect(command.executions).toEqual([]);
    command.dispose();
  });
});

describe("AsyncCommandDouble", () => {
  it("allows deterministic resolution and prevents double execution", async () => {
    const command = new AsyncCommandDouble();
    const changes: boolean[] = [];
    command.canExecuteChanged.subscribe(() => changes.push(command.isExecuting));

    const first = command.executeAsync();
    const ignored = command.executeAsync();
    expect(command.isExecuting).toBe(true);
    expect(command.executionCount).toBe(1);
    expect(command.canExecute()).toBe(false);

    command.resolve();
    await Promise.all([first, ignored]);
    expect(command.isExecuting).toBe(false);
    expect(changes).toEqual([true, false]);
    command.dispose();
  });

  it("rejects controlled faults to awaiters", async () => {
    const command = new AsyncCommandDouble();
    const fault = new Error("failed");
    const execution = command.executeAsync();

    command.reject(fault);

    await expect(execution).rejects.toBe(fault);
    expect(command.isExecuting).toBe(false);
    command.dispose();
  });

  it("routes fire-and-forget faults to errors without an unhandled rejection", async () => {
    const command = new AsyncCommandDouble();
    const errors: unknown[] = [];
    command.errors.subscribe((error) => errors.push(error));
    const fault = new Error("reported");

    command.execute();
    command.reject(fault);
    await new Promise<void>((resolve) => setImmediate(resolve));

    expect(errors).toEqual([fault]);
    expect(command.isExecuting).toBe(false);
    command.dispose();
  });

  it("resolves command cancellation but rejects external abort", async () => {
    const command = new AsyncCommandDouble();
    const cancelled = command.executeAsync();
    command.cancel();
    await expect(cancelled).resolves.toBeUndefined();

    const controller = new AbortController();
    const externallyCancelled = command.executeAsync(controller.signal);
    controller.abort("consumer stopped");
    await expect(externallyCancelled).rejects.toMatchObject({ name: "AbortError" });
    expect(command.executionCount).toBe(2);
    command.dispose();
  });

  it("cancels pending work and becomes inert on idempotent disposal", async () => {
    const command = new AsyncCommandDouble();
    let errorsCompleted = 0;
    command.errors.subscribe({ complete: () => errorsCompleted++ });
    const pending = command.executeAsync();

    command.dispose();
    command.dispose();
    await expect(pending).resolves.toBeUndefined();
    await expect(command.executeAsync()).resolves.toBeUndefined();

    expect(command.isExecuting).toBe(false);
    expect(command.canExecute()).toBe(false);
    expect(errorsCompleted).toBe(1);
  });
});
