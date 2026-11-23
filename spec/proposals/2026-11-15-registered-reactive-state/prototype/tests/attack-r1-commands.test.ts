/**
 * Attack round 1: commands whose predicate reads tracked state across view-models (R10.*; spec 04 §2, §4.3,
 * §10.2).
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM } from "@thekaveh/vmx";
import { base, captureReports, deferred, type Services, services, streamFed, tick } from "./support.js";

class Gate extends ComponentVM {
  declare open: boolean;
  constructor(s: Services, name = "gate") {
    super(base(s, name));
    this.observable({ open: true });
  }
}

describe("attack-r1 commands across view-models", () => {
  it("K1 a predicate over another VM raises once per change; after that VM is disposed: no raise, no error", async () => {
    await streamFed();
    const s = services();
    const gate = new Gate(s);
    class Door extends ComponentVM {
      readonly pass = this.relayCommand(
        () => undefined,
        () => gate.open,
      );
      constructor() {
        super(base(s, "door"));
      }
    }
    const door = new Door();
    let raises = 0;
    door.pass.canExecuteChanged.subscribe(() => {
      raises += 1;
      door.pass.canExecute();
    });
    assert.equal(door.pass.canExecute(), true);
    gate.open = false;
    gate.open = true;
    assert.equal(raises, 2);
    gate.dispose();
    gate.open = false;
    assert.equal(raises, 2);
    assert.equal(door.pass.canExecute(), true, "the last value of the disposed gate");
    assert.deepEqual(await streamFed(), []);
  });

  it("K2 an async command's tracked predicate re-arms after its execution completes", async () => {
    const s = services();
    const gate = new Gate(s);
    const run = deferred<void>();
    class Job extends ComponentVM {
      readonly start = this.asyncRelayCommand(
        async () => run.promise,
        () => gate.open,
      );
      constructor() {
        super(base(s, "job"));
      }
    }
    const job = new Job();
    let raises = 0;
    job.start.canExecuteChanged.subscribe(() => {
      raises += 1;
      job.start.canExecute();
    });
    assert.equal(job.start.canExecute(), true);
    const done = job.start.executeAsync();
    gate.open = false; // in flight: the view re-queries, the command answers false without the predicate
    run.resolve();
    await done;
    await tick();
    const afterCompletion = raises;
    gate.open = true;
    assert.equal(raises, afterCompletion + 1, "a change after completion raises again");
    assert.equal(job.start.canExecute(), true);
  });

  // Fix round 1 (R10.7): a canExecute() call inside a frame records the command's
  // CanExecuteChanged, so a predicate that delegates to a built-in command is raised when the built-in raises. The
  // test kept its scenario; its expectations moved from the documented gap to the resolved rule.
  it("K4 a predicate that delegates to a VMx built-in command (reloadCommand) is raised when the built-in raises", async () => {
    await streamFed();
    const reports = captureReports();
    const s = services();
    class Item extends ComponentVM {
      readonly query = this.keyedResource({
        key: () => "fixed",
        load: async () => "data",
        autoLoad: true,
      });
      readonly retry = this.relayCommand(
        () => void this.query.reload(),
        () => this.query.reloadCommand.canExecute(),
      );
      constructor() {
        super(base(s, "item"));
      }
    }
    const item = new Item();
    let raises = 0;
    item.retry.canExecuteChanged.subscribe(() => {
      raises += 1;
    });
    assert.equal(item.retry.canExecute(), false, "Idle: nothing to reload");
    item.construct(); // autoLoad: Idle -> Loading
    assert.equal(raises, 1, "the retry button is told to re-query when reloadCommand raises");
    void item.retry.canExecute(); // the view re-queries, which re-arms the tracked set (spec 04 §4)
    await tick(); // Loading -> Ready
    assert.equal(raises, 2, "and again when the load completes");
    assert.equal(item.retry.canExecute(), true);
    assert.deepEqual(reports, [], "a tracked delegation needs no diagnostic");
    assert.deepEqual(await streamFed(), []);
  });

  it("K3 a parameterized predicate over many rows: the union of reads grows linearly, not quadratically", () => {
    const s = services();
    class Row extends ComponentVM {
      declare locked: boolean;
      constructor(index: number) {
        super(base(s, `row${String(index)}`));
        this.observable({ locked: false });
      }
    }
    class Listing extends ComponentVM {
      readonly remove = this.relayCommandOf<Row>(
        () => undefined,
        (row) => !row.locked,
      );
      constructor() {
        super(base(s, "listing"));
      }
    }
    // White-box but deterministic: count the array elements that Array.prototype.includes scans while the
    // predicate runs (the union in graph.ts runFrame uses `sources.includes`). Timing is reported as information.
    const measure = (count: number): { readonly scanned: number; readonly ms: number } => {
      const rows = Array.from({ length: count }, (_, i) => new Row(i));
      const listing = new Listing();
      const original = Array.prototype.includes;
      let scanned = 0;
      Array.prototype.includes = function (this: unknown[], searchElement: unknown, fromIndex?: number): boolean {
        scanned += this.length;
        return Reflect.apply(original, this, [searchElement, fromIndex]) as boolean;
      };
      const started = performance.now();
      try {
        for (const row of rows) listing.remove.canExecute(row);
      } finally {
        Array.prototype.includes = original;
      }
      const ms = performance.now() - started;
      listing.dispose();
      for (const row of rows) row.dispose();
      return { scanned, ms };
    };
    const small = measure(2_000);
    const large = measure(8_000);
    assert.ok(
      large.scanned <= 32 * 8_000,
      `canExecute(row) for 8,000 rows scanned ${String(large.scanned)} union entries ` +
        `(2,000 rows: ${String(small.scanned)}); ${large.ms.toFixed(1)} ms vs ${small.ms.toFixed(1)} ms`,
    );
  });
});
