/**
 * Attack round 1: throwing computeds and effects (R16; spec 04 §2 predicate errors; HUB-007).
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, ConstructionStatus, PropertyChangedMessage } from "@thekaveh/vmx";
import { activate, configureReactiveDiagnostics } from "../src/index.js";
import { base, type Services, services, streamFed } from "./support.js";

function quietly<T>(fn: () => T): T {
  configureReactiveDiagnostics({ development: false });
  try {
    return fn();
  } finally {
    configureReactiveDiagnostics({ development: undefined });
  }
}

function hubNames(s: Services): string[] {
  const names: string[] = [];
  s.hub.messages.subscribe((m) => {
    if (m instanceof PropertyChangedMessage) names.push(`${m.senderName}.${m.propertyName}`);
  });
  return names;
}

class Source extends ComponentVM {
  declare level: number;
  constructor(s: Services) {
    super(base(s, "source"));
    this.observable({ level: 1 });
    this.computed("reading");
  }
  get reading(): number {
    if (this.level < 0) throw new Error(`bad level ${String(this.level)}`);
    return this.level;
  }
}

describe("attack-r1 throwing computeds and effects", () => {
  it("E1 an effect that reads a throwing computed is reported, stays subscribed and re-runs on recovery", async () => {
    await streamFed();
    const s = services();
    const source = new Source(s);
    const runs: string[] = [];
    class Watcher extends ComponentVM {
      constructor() {
        super(base(s, "watcher"));
        this.effect(() => {
          try {
            runs.push(`ok:${String(source.reading)}`);
          } catch {
            runs.push("caught");
            throw new Error("effect saw a fault");
          }
        });
      }
    }
    const watcher = new Watcher();
    activate(source);
    watcher.construct();
    source.level = -1;
    source.level = 2;
    assert.deepEqual(runs, ["ok:1", "caught", "ok:2"]);
    const reported = (await streamFed()).map(String);
    assert.equal(reported.filter((e) => e.includes("effect saw a fault")).length, 1);
    assert.equal(reported.filter((e) => e.includes("bad level")).length, 1);
  });

  // Fix round 1 (R12.4): an immediate reaction whose select throws at its start makes its start
  // delivery at its first successful run. The scenario is unchanged; the expectation moved from the documented
  // choice (a silent baseline) to the resolved rule.
  it("E2 an immediate reaction whose select throws at its start delivers its first good value as (value, value)", async () => {
    await streamFed();
    const s = services();
    const delivered: string[] = [];
    class Late extends ComponentVM {
      constructor(readonly source: Source) {
        super(base(s, "late"));
        this.reaction(
          () => this.source.reading,
          (value, previous) => delivered.push(`${String(previous)}->${String(value)}`),
          { immediate: true },
        );
      }
    }
    const source = new Source(s);
    source.level = -1;
    const vm = new Late(source);
    vm.construct();
    source.level = 5;
    source.level = 6;
    assert.deepEqual(delivered, ["5->5", "5->6"]);
    assert.equal((await streamFed()).length, 1);
  });

  it("E3 a computed that throws a non-Error value: readers get that value; the transitions are announced", async () => {
    await streamFed();
    const s = services();
    class Odd extends ComponentVM {
      declare n: number;
      constructor() {
        super(base(s, "odd"));
        this.observable({ n: 1 });
        this.computed("value");
      }
      get value(): number {
        if (this.n === 0) throw "zero"; // eslint-disable-line no-throw-literal -- the attack
        return this.n;
      }
    }
    quietly(() => {
      const vm = new Odd();
      activate(vm);
      const names = hubNames(s);
      vm.n = 0;
      assert.throws(
        () => vm.value,
        (thrown: unknown) => thrown === "zero",
      );
      vm.n = 2;
      assert.deepEqual(names, ["odd.n", "odd.value", "odd.n", "odd.value"]);
    });
    assert.deepEqual(await streamFed(), ["zero"]);
  });

  it("E4 a throwing _onDispose still releases the graph: nothing is announced afterwards", () => {
    const s = services();
    class Fragile extends ComponentVM {
      declare n: number;
      constructor() {
        super(base(s, "fragile"));
        this.observable({ n: 0 });
        this.computed("twice");
      }
      get twice(): number {
        return this.n * 2;
      }
      protected override _onDispose(): void {
        throw new Error("dispose failed");
      }
    }
    const vm = new Fragile();
    activate(vm);
    const names = hubNames(s);
    assert.throws(() => vm.dispose(), /dispose failed/);
    assert.equal(vm.status, ConstructionStatus.Disposed);
    vm.n = 3;
    assert.deepEqual(names, []);
    assert.equal(vm.twice, 0);
  });

  it("E5 value, error, value inside one change scope is no change and is not reported", async () => {
    await streamFed();
    const s = services();
    const source = new Source(s);
    quietly(() => {
      activate(source);
      const names = hubNames(s);
      source.change(() => {
        source.level = -3;
        assert.throws(() => source.reading, /bad level -3/);
        source.level = 1;
      });
      assert.deepEqual(names, []);
    });
    assert.deepEqual(await streamFed(), []);
  });
});
