// Conformance tests: CMDD-014..017 — confirmation over an asynchronous inner.
// See spec/04-commands.md §8.3.2 and ADR-0145.
//
// Every wait is a deferred gate released by the test; no timers. Where a test
// asserts that something has NOT happened yet, it first drains the microtask
// queue so a premature resolution would already have been observed.

import type { Observable } from "rxjs";
import { describe, expect, it, vi } from "vitest";

import {
  AsyncRelayCommand,
  ConfirmationDecoratorCommand,
  RelayCommand,
} from "../../src/index.js";
import { AsyncCommandDouble } from "../../src/testing/index.js";

interface Gate<T> {
  readonly promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
}

function gate<T = void>(): Gate<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** Runs every queued promise reaction (bounded), without scheduling a timer. */
async function drainMicrotasks(): Promise<void> {
  for (let i = 0; i < 25; i += 1) await Promise.resolve();
}

/** Tracks whether an awaited call has settled, without consuming its outcome. */
function track(promise: Promise<void>): { readonly promise: Promise<void>; readonly settled: boolean } {
  const state = { promise, settled: false };
  promise.then(
    () => {
      state.settled = true;
    },
    () => {
      state.settled = true;
    },
  );
  return state;
}

function collect(source: Observable<unknown>): unknown[] {
  const seen: unknown[] = [];
  source.subscribe((value) => seen.push(value));
  return seen;
}

/**
 * An AsyncRelayCommand whose body blocks until `release()` and observes its
 * abort signal. `log` records body start and finish.
 */
function blockingAsyncCommand(options: { failWith?: Error; throwOnCancel?: boolean } = {}) {
  const released = gate();
  const probe = { runs: 0, signal: null as AbortSignal | null, log: [] as string[] };
  const command = AsyncRelayCommand.builder()
    .task(async (signal) => {
      probe.runs += 1;
      probe.signal = signal;
      probe.log.push("body started");
      await new Promise<void>((resolve, reject) => {
        signal.addEventListener("abort", () => reject(signal.reason as Error), { once: true });
        void released.promise.then(resolve);
      });
      probe.log.push("body finished");
      if (options.failWith !== undefined) throw options.failWith;
    })
    .throwOnCancel(options.throwOnCancel ?? false)
    .build();
  return { command, probe, release: () => released.resolve() };
}

describe("CMDD-014", () => {
  it("an awaited confirmation completes only after the async inner body is released, invoking it once through executeAsync", async () => {
    const inner = blockingAsyncCommand();
    const innerExecute = vi.spyOn(inner.command, "execute");
    const innerExecuteAsync = vi.spyOn(inner.command, "executeAsync");
    const decorator = new ConfirmationDecoratorCommand(inner.command, () => Promise.resolve(true));

    const call = track(
      decorator.executeAsync().then(() => {
        inner.probe.log.push("awaiter completed");
      }),
    );
    await drainMicrotasks();

    expect(inner.probe.runs).toBe(1);
    expect(inner.command.isExecuting).toBe(true);
    expect(call.settled).toBe(false);

    inner.release();
    await call.promise;

    expect(inner.probe.log).toEqual(["body started", "body finished", "awaiter completed"]);
    expect(inner.command.isExecuting).toBe(false);
    expect(inner.probe.runs).toBe(1);
    expect(innerExecuteAsync).toHaveBeenCalledTimes(1);
    expect(innerExecute).not.toHaveBeenCalled();
  });

  it("any IAsyncCommand counts as asynchronous, not only AsyncRelayCommand", async () => {
    const inner = new AsyncCommandDouble();
    const innerExecute = vi.spyOn(inner, "execute");
    const decorator = new ConfirmationDecoratorCommand(inner, () => Promise.resolve(true));

    const call = track(decorator.executeAsync());
    await drainMicrotasks();

    expect(inner.executionCount).toBe(1);
    expect(call.settled).toBe(false);

    inner.resolve();
    await call.promise;

    expect(inner.executionCount).toBe(1);
    expect(innerExecute).not.toHaveBeenCalled();
  });

  it("a false confirmation completes without invoking the async inner", async () => {
    const inner = blockingAsyncCommand();
    const innerExecute = vi.spyOn(inner.command, "execute");
    const innerExecuteAsync = vi.spyOn(inner.command, "executeAsync");
    const decorator = new ConfirmationDecoratorCommand(inner.command, () => Promise.resolve(false));

    await decorator.executeAsync();

    expect(inner.probe.runs).toBe(0);
    expect(innerExecute).not.toHaveBeenCalled();
    expect(innerExecuteAsync).not.toHaveBeenCalled();
    expect(inner.command.isExecuting).toBe(false);
  });

  it("a synchronous inner runs through execute() once and the awaiter completes after it returns", async () => {
    const log: string[] = [];
    const inner = RelayCommand.builder().task(() => log.push("inner")).build();
    const innerExecute = vi.spyOn(inner, "execute");
    const decorator = new ConfirmationDecoratorCommand(inner, () => Promise.resolve(true));

    await decorator.executeAsync().then(() => log.push("awaiter completed"));

    expect(log).toEqual(["inner", "awaiter completed"]);
    expect(innerExecute).toHaveBeenCalledTimes(1);
  });
});

describe("CMDD-015", () => {
  it("an awaited async inner failure reaches the awaiter and no errors channel", async () => {
    const boom = new Error("inner failed");
    const inner = blockingAsyncCommand({ failWith: boom });
    const decorator = new ConfirmationDecoratorCommand(inner.command, () => Promise.resolve(true));
    const decoratorErrors = collect(decorator.errors);
    const innerErrors = collect(inner.command.errors);

    const call = track(decorator.executeAsync());
    await drainMicrotasks();
    expect(call.settled).toBe(false);

    inner.release();

    await expect(call.promise).rejects.toBe(boom);
    await drainMicrotasks();
    expect(decoratorErrors).toEqual([]);
    expect(innerErrors).toEqual([]);
  });

  it("a fire-and-forget async inner failure reaches only the inner's errors, once", async () => {
    const boom = new Error("inner failed");
    const inner = blockingAsyncCommand({ failWith: boom });
    const innerExecute = vi.spyOn(inner.command, "execute");
    const decorator = new ConfirmationDecoratorCommand(inner.command, () => Promise.resolve(true));
    const decoratorErrors = collect(decorator.errors);
    const innerErrors: unknown[] = [];
    const innerFailed = gate<unknown>();
    inner.command.errors.subscribe((error) => {
      innerErrors.push(error);
      innerFailed.resolve(error);
    });

    decorator.execute();
    await drainMicrotasks();
    // Started through the inner's own fire-and-forget entry point.
    expect(innerExecute).toHaveBeenCalledTimes(1);
    expect(inner.probe.runs).toBe(1);

    inner.release();
    await innerFailed.promise;
    await drainMicrotasks();

    expect(innerErrors).toEqual([boom]);
    expect(decoratorErrors).toEqual([]);
    expect(inner.probe.runs).toBe(1);
  });

  it("a fire-and-forget confirm failure reaches only the decorator's errors, once", async () => {
    const boom = new Error("confirm failed");
    const inner = blockingAsyncCommand();
    const decorator = new ConfirmationDecoratorCommand(inner.command, () => Promise.reject(boom));
    const innerErrors = collect(inner.command.errors);
    const decoratorErrors: unknown[] = [];
    const confirmFailed = gate<unknown>();
    decorator.errors.subscribe((error) => {
      decoratorErrors.push(error);
      confirmFailed.resolve(error);
    });

    decorator.execute();
    await confirmFailed.promise;
    await drainMicrotasks();

    expect(decoratorErrors).toEqual([boom]);
    expect(innerErrors).toEqual([]);
    expect(inner.probe.runs).toBe(0);
  });
});

describe("CMDD-016", () => {
  it("an inner already executing when the confirmation resolves drops the call and the awaiter completes", async () => {
    const inner = blockingAsyncCommand();
    const confirmation = gate<boolean>();
    const decorator = new ConfirmationDecoratorCommand(inner.command, () => confirmation.promise);

    // Admitted while the inner is idle; the confirmation is still pending.
    const call = track(decorator.executeAsync());
    // The inner starts on its own and is executing when confirmation lands.
    const direct = inner.command.executeAsync();
    expect(inner.command.isExecuting).toBe(true);

    confirmation.resolve(true);
    await drainMicrotasks();

    expect(call.settled).toBe(true);
    await call.promise;
    expect(inner.probe.runs).toBe(1);
    expect(inner.command.isExecuting).toBe(true);

    inner.release();
    await direct;
    expect(inner.probe.runs).toBe(1);
  });

  it("an inner disabled while the confirmation is pending drops the call", async () => {
    let enabled = true;
    let runs = 0;
    const inner = AsyncRelayCommand.builder()
      .predicate(() => enabled)
      .task(() => {
        runs += 1;
        return Promise.resolve();
      })
      .build();
    const confirmation = gate<boolean>();
    const decorator = new ConfirmationDecoratorCommand(inner, () => confirmation.promise);

    const call = decorator.executeAsync();
    enabled = false;
    confirmation.resolve(true);
    await call;

    expect(runs).toBe(0);
  });

  it.each([
    ["the non-throwing default", false],
    ["throwOnCancel", true],
  ])("inner cancel() ends the awaited call with the inner's own outcome (%s)", async (_, throwOnCancel) => {
    const inner = blockingAsyncCommand({ throwOnCancel });
    const decorator = new ConfirmationDecoratorCommand(inner.command, () => Promise.resolve(true));
    const decoratorErrors = collect(decorator.errors);
    const innerErrors = collect(inner.command.errors);

    const call = track(decorator.executeAsync());
    await drainMicrotasks();
    expect(inner.command.isExecuting).toBe(true);
    expect(call.settled).toBe(false);

    inner.command.cancel();
    const reason: unknown = inner.probe.signal?.reason;

    if (throwOnCancel) {
      // The inner's own AbortError reaches the awaiter as the same object.
      expect((reason as Error).name).toBe("AbortError");
      await expect(call.promise).rejects.toBe(reason);
    } else {
      await expect(call.promise).resolves.toBeUndefined();
    }
    expect(inner.probe.signal?.aborted).toBe(true);
    expect(inner.probe.log).toEqual(["body started"]);
    expect(inner.command.isExecuting).toBe(false);
    await drainMicrotasks();
    expect(decoratorErrors).toEqual([]);
    expect(innerErrors).toEqual([]);
  });
});

describe("CMDD-017", () => {
  it("an outer wrapper awaits a nested wrapper's confirmation and inner operation end to end", async () => {
    const inner = blockingAsyncCommand();
    const innerExecute = vi.spyOn(inner.command, "execute");
    const confirms: string[] = [];
    const nested = new ConfirmationDecoratorCommand(inner.command, () => {
      confirms.push("nested");
      return Promise.resolve(true);
    });
    const nestedExecute = vi.spyOn(nested, "execute");
    const nestedExecuteAsync = vi.spyOn(nested, "executeAsync");
    const outer = new ConfirmationDecoratorCommand(nested, () => {
      confirms.push("outer");
      return Promise.resolve(true);
    });

    const call = track(outer.executeAsync());
    await drainMicrotasks();

    expect(confirms).toEqual(["outer", "nested"]);
    expect(inner.probe.runs).toBe(1);
    expect(call.settled).toBe(false);

    inner.release();
    await call.promise;

    expect(inner.probe.log).toEqual(["body started", "body finished"]);
    expect(inner.probe.runs).toBe(1);
    expect(nestedExecuteAsync).toHaveBeenCalledTimes(1);
    expect(nestedExecute).not.toHaveBeenCalled();
    expect(innerExecute).not.toHaveBeenCalled();
  });

  it("disposing the decorator while the inner runs neither cancels nor disposes it, and the awaiter completes", async () => {
    const inner = blockingAsyncCommand();
    const innerCancel = vi.spyOn(inner.command, "cancel");
    const innerDispose = vi.spyOn(inner.command, "dispose");
    let innerChangesCompleted = false;
    inner.command.canExecuteChanged.subscribe({
      complete: () => {
        innerChangesCompleted = true;
      },
    });
    const decorator = new ConfirmationDecoratorCommand(inner.command, () => Promise.resolve(true));

    const call = track(decorator.executeAsync());
    await drainMicrotasks();
    expect(inner.command.isExecuting).toBe(true);

    decorator.dispose();
    await drainMicrotasks();

    expect(innerCancel).not.toHaveBeenCalled();
    expect(innerDispose).not.toHaveBeenCalled();
    expect(inner.probe.signal?.aborted).toBe(false);
    expect(inner.command.isExecuting).toBe(true);
    expect(call.settled).toBe(false);

    inner.release();
    await call.promise;

    expect(inner.probe.log).toEqual(["body started", "body finished"]);
    expect(inner.command.isExecuting).toBe(false);
    expect(innerChangesCompleted).toBe(false);
    expect(inner.command.canExecute()).toBe(true);
    expect(decorator.canExecute()).toBe(false);
  });

  it.each(["executeAsync", "execute"] as const)(
    "disposing while the confirmation is pending starts no inner work (%s)",
    async (entryPoint) => {
      const inner = blockingAsyncCommand();
      const innerExecute = vi.spyOn(inner.command, "execute");
      const innerExecuteAsync = vi.spyOn(inner.command, "executeAsync");
      const confirmation = gate<boolean>();
      const decorator = new ConfirmationDecoratorCommand(inner.command, () => confirmation.promise);
      const decoratorErrors = collect(decorator.errors);

      let call: Promise<void> = Promise.resolve();
      if (entryPoint === "executeAsync") call = decorator.executeAsync();
      else decorator.execute();
      decorator.dispose();
      confirmation.resolve(true);
      await call;
      await drainMicrotasks();

      expect(inner.probe.runs).toBe(0);
      expect(innerExecute).not.toHaveBeenCalled();
      expect(innerExecuteAsync).not.toHaveBeenCalled();
      expect(inner.command.isExecuting).toBe(false);
      expect(decoratorErrors).toEqual([]);
    },
  );
});
