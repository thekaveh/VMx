import { describe, it, expect, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { Subject } from "rxjs";
import {
  AsyncRelayCommand,
  RelayCommand,
  RelayCommandOf,
} from "../../src/index.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// CMD-001
// ---------------------------------------------------------------------------

describe("CMD-001", () => {
  it("execute invokes the configured task", () => {
    const fn = vi.fn();
    const cmd = RelayCommand.builder().task(fn).build();
    cmd.execute();
    expect(fn).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// CMD-002
// ---------------------------------------------------------------------------

describe("CMD-002", () => {
  it("can_execute with no predicate returns true", () => {
    const cmd = RelayCommand.builder().build();
    expect(cmd.canExecute()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// CMD-003
// ---------------------------------------------------------------------------

describe("CMD-003", () => {
  it("can_execute returns the predicate result", () => {
    const cmd = RelayCommand.builder().predicate(() => false).build();
    expect(cmd.canExecute()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// CMD-004
// ---------------------------------------------------------------------------

describe("CMD-004", () => {
  it("Trigger emission fires CanExecuteChanged", () => {
    const trigger = new Subject<void>();
    const cmd = RelayCommand.builder().triggers(trigger).build();
    const fired: number[] = [];
    cmd.canExecuteChanged.subscribe(() => fired.push(1));

    trigger.next();

    expect(fired).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// CMD-005
// ---------------------------------------------------------------------------

describe("CMD-005", () => {
  it("Parameterized variant passes parameter", () => {
    const recorder: number[] = [];
    const cmd = RelayCommandOf.builder<number>()
      .task((p) => recorder.push(p))
      .build();

    cmd.execute(42);

    expect(recorder).toEqual([42]);
  });
});

// ---------------------------------------------------------------------------
// CMD-006
// ---------------------------------------------------------------------------

describe("CMD-006", () => {
  it("execute with null task is a no-op", () => {
    const cmd = RelayCommand.builder().build(); // no task
    expect(() => cmd.execute()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// CMD-007
// ---------------------------------------------------------------------------

describe("CMD-007", () => {
  it("Command truth-table matches fixture", () => {
    const raw = readFileSync(
      join(__dirname, "..", "..", "src", "fixtures", "command-truthtable.json"),
      "utf-8",
    );
    const data = JSON.parse(raw) as {
      cases: Array<{
        id: string;
        predicate: boolean | null;
        task: string | null;
        trigger_emits: boolean;
        can_execute: boolean;
        execute_invokes_task: boolean;
        can_execute_changed_fires: boolean;
      }>;
    };

    for (const row of data.cases) {
      const taskInvoked = { count: 0 };
      const trigger = new Subject<void>();
      const canExecuteChanged = { count: 0 };

      let builder = RelayCommand.builder();
      if (row.predicate !== null) builder = builder.predicate(() => row.predicate as boolean);
      if (row.task !== null) builder = builder.task(() => { taskInvoked.count++; });
      builder = builder.triggers(trigger);

      const cmd = builder.build();
      cmd.canExecuteChanged.subscribe(() => { canExecuteChanged.count++; });

      if (row.trigger_emits) trigger.next();
      const canExec = cmd.canExecute();
      cmd.execute();

      expect(canExec, `${row.id} can_execute`).toBe(row.can_execute);
      expect(taskInvoked.count > 0, `${row.id} execute_invokes_task`).toBe(row.execute_invokes_task);
      expect(canExecuteChanged.count > 0, `${row.id} can_execute_changed_fires`).toBe(row.can_execute_changed_fires);
    }
  });
});

describe("CMD-014", () => {
  it("imperative raise emits once without evaluating the predicate or task", () => {
    const predicate = vi.fn(() => true);
    const task = vi.fn();
    const cmd = RelayCommand.builder().predicate(predicate).task(task).build();
    let fired = 0;
    cmd.canExecuteChanged.subscribe(() => fired++);

    cmd.raiseCanExecuteChanged();

    expect(fired).toBe(1);
    expect(predicate).not.toHaveBeenCalled();
    expect(task).not.toHaveBeenCalled();
  });
});

describe("CMD-015", () => {
  it("repeated imperative and trigger notifications are additive", () => {
    const trigger = new Subject<void>();
    const cmd = RelayCommand.builder().triggers(trigger).build();
    let fired = 0;
    cmd.canExecuteChanged.subscribe(() => fired++);

    cmd.raiseCanExecuteChanged();
    cmd.raiseCanExecuteChanged();
    trigger.next();

    expect(fired).toBe(3);
  });
});

describe("CMD-016", () => {
  it("imperative raise after disposal is a no-op for every concrete relay", () => {
    const relay = RelayCommand.builder().build();
    const parameterized = RelayCommandOf.builder<number>().build();
    const asyncCommand = AsyncRelayCommand.builder().build();
    relay.dispose();
    parameterized.dispose();
    asyncCommand.dispose();
    let fired = 0;
    relay.canExecuteChanged.subscribe(() => fired++);
    parameterized.canExecuteChanged.subscribe(() => fired++);
    asyncCommand.canExecuteChanged.subscribe(() => fired++);

    relay.raiseCanExecuteChanged();
    parameterized.raiseCanExecuteChanged();
    asyncCommand.raiseCanExecuteChanged();

    expect(fired).toBe(0);
  });
});

describe("CMD-017", () => {
  it("parameterized imperative raise emits exactly once", () => {
    const cmd = RelayCommandOf.builder<number>().build();
    let fired = 0;
    cmd.canExecuteChanged.subscribe(() => fired++);

    cmd.raiseCanExecuteChanged();

    expect(fired).toBe(1);
  });
});

describe("CMD-018", () => {
  it("async imperative raise while idle emits exactly once", () => {
    const cmd = AsyncRelayCommand.builder().build();
    let fired = 0;
    cmd.canExecuteChanged.subscribe(() => fired++);

    cmd.raiseCanExecuteChanged();

    expect(fired).toBe(1);
  });
});

describe("CMD-019", () => {
  it("async imperative raise while in flight is additive", async () => {
    let startedResolve!: () => void;
    let releaseResolve!: () => void;
    const started = new Promise<void>((resolve) => { startedResolve = resolve; });
    const release = new Promise<void>((resolve) => { releaseResolve = resolve; });
    const cmd = AsyncRelayCommand.builder().task(async () => {
      startedResolve();
      await release;
    }).build();
    let fired = 0;
    cmd.canExecuteChanged.subscribe(() => fired++);

    const run = cmd.executeAsync();
    await started;
    expect(fired).toBe(1);
    cmd.raiseCanExecuteChanged();
    expect(fired).toBe(2);
    releaseResolve();
    await run;

    expect(fired).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// CMD-013
// ---------------------------------------------------------------------------

describe("CMD-013", () => {
  it("disposed RelayCommand instances are inert", () => {
    const fn = vi.fn();
    const cmd = RelayCommand.builder().task(fn).build();

    cmd.dispose();
    cmd.execute();

    expect(cmd.canExecute()).toBe(false);
    expect(fn).not.toHaveBeenCalled();
  });

  it("disposed RelayCommandOf instances are inert", () => {
    const fn = vi.fn();
    const cmd = RelayCommandOf.builder<number>().task(fn).build();

    cmd.dispose();
    cmd.execute(42);

    expect(cmd.canExecute(42)).toBe(false);
    expect(fn).not.toHaveBeenCalled();
  });

  it("disposed AsyncRelayCommand instances are inert", async () => {
    const fn = vi.fn();
    const cmd = AsyncRelayCommand.builder().task(() => {
      fn();
      return Promise.resolve();
    }).build();

    cmd.dispose();
    cmd.execute();
    await cmd.executeAsync();

    expect(cmd.canExecute()).toBe(false);
    expect(fn).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// CMD-012 — async command cancellation (spec/04-commands.md §10, ADR-0056)
// ---------------------------------------------------------------------------

describe("CMD-012", () => {
  it("cancel() cancels an in-flight async task; returns to non-executing; no throw by default", async () => {
    let observedAbort = false;
    let startedResolve!: () => void;
    const started = new Promise<void>((r) => {
      startedResolve = r;
    });

    const cmd = AsyncRelayCommand.builder()
      .task(
        (signal) =>
          new Promise<void>((_, reject) => {
            startedResolve();
            signal.addEventListener(
              "abort",
              () => {
                observedAbort = true;
                reject(signal.reason as Error);
              },
              { once: true },
            );
          }),
      )
      .build();

    expect(cmd.canExecute()).toBe(true);

    const run = cmd.executeAsync();
    await started; // the task is now in flight

    expect(cmd.isExecuting).toBe(true);
    expect(cmd.canExecute()).toBe(false); // an in-flight async command is not re-executable

    cmd.cancel();
    await expect(run).resolves.toBeUndefined(); // MUST NOT reject by default

    expect(observedAbort).toBe(true);
    expect(cmd.isExecuting).toBe(false); // returns to a non-executing state
    expect(cmd.canExecute()).toBe(true); // canExecute reflects the cleared in-flight state
    cmd.dispose();
  });

  it("re-raises a cancellation originating from the caller's supplied AbortSignal", async () => {
    let startedResolve!: () => void;
    const started = new Promise<void>((r) => {
      startedResolve = r;
    });
    const external = new AbortController();

    const cmd = AsyncRelayCommand.builder()
      .task(
        (signal) =>
          new Promise<void>((_, reject) => {
            startedResolve();
            signal.addEventListener("abort", () => reject(signal.reason as Error), {
              once: true,
            });
          }),
      )
      .build();

    const run = cmd.executeAsync(external.signal);
    await started;

    external.abort(); // the caller's signal — NOT cmd.cancel()

    // spec §10.3: an externally-originated cancellation is re-raised, not swallowed
    // by the non-throwing default (which covers only our own cancel()/dispose()).
    await expect(run).rejects.toBeDefined();
    expect(cmd.isExecuting).toBe(false);
    cmd.dispose();
  });

  it("throwOnCancel() surfaces the cancellation to the awaiter", async () => {
    let startedResolve!: () => void;
    const started = new Promise<void>((r) => {
      startedResolve = r;
    });

    const cmd = AsyncRelayCommand.builder()
      .throwOnCancel()
      .task(
        (signal) =>
          new Promise<void>((_, reject) => {
            startedResolve();
            signal.addEventListener(
              "abort",
              () => reject(signal.reason as Error),
              { once: true },
            );
          }),
      )
      .build();

    const run = cmd.executeAsync();
    await started;
    cmd.cancel();

    await expect(run).rejects.toBeDefined();
    expect(cmd.isExecuting).toBe(false);
    cmd.dispose();
  });

  it("execute() does not route command cancellation to errors when throwOnCancel is set", async () => {
    let startedResolve!: () => void;
    const started = new Promise<void>((r) => {
      startedResolve = r;
    });
    const errors: unknown[] = [];

    const cmd = AsyncRelayCommand.builder()
      .throwOnCancel()
      .task(
        (signal) =>
          new Promise<void>((_, reject) => {
            startedResolve();
            signal.addEventListener(
              "abort",
              () => {
                const reason =
                  signal.reason instanceof Error
                    ? signal.reason
                    : new DOMException("Aborted", "AbortError");
                reject(reason);
              },
              { once: true },
            );
          }),
      )
      .build();
    cmd.errors.subscribe((err) => errors.push(err));

    cmd.execute();
    await started;
    cmd.cancel();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(errors).toEqual([]);
    expect(cmd.isExecuting).toBe(false);
    cmd.dispose();
  });

  it("execute() still routes non-cancellation faults after cancel() to errors", async () => {
    let startedResolve!: () => void;
    const started = new Promise<void>((r) => {
      startedResolve = r;
    });
    const failure = new Error("late fault");
    const errors: unknown[] = [];

    const cmd = AsyncRelayCommand.builder()
      .task(
        (signal) =>
          new Promise<void>((_, reject) => {
            startedResolve();
            signal.addEventListener("abort", () => reject(failure), { once: true });
          }),
      )
      .build();
    cmd.errors.subscribe((err) => errors.push(err));

    cmd.execute();
    await started;
    cmd.cancel();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(errors).toEqual([failure]);
    expect(cmd.isExecuting).toBe(false);
    cmd.dispose();
  });
});
