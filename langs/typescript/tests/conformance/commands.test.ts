import { describe, it, expect, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { Subject } from "rxjs";
import { RelayCommand, RelayCommandOf } from "../../src/index.js";

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
