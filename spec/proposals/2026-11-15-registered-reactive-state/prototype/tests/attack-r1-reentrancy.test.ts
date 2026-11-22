/**
 * Attack round 1: re-entrancy. Writes made by an effect, a reaction handler, a hub observer or a command listener
 * while the graph propagates (spec 03 §3.3 rule 5; R9.3 "delivery never recurses on the call stack").
 *
 * Expectation used throughout: a reaction (effect, reaction handler) is never re-entered by its own write. A run
 * completes before the next run of the same reaction starts, its dependency set is the set of its latest run, and
 * every cleanup it returned runs exactly once.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, PropertyChangedMessage } from "@thekaveh/vmx";
import { activate } from "../src/index.js";
import { base, type Services, services } from "./support.js";

/** An effect that "normalizes" `flag` on its first run and otherwise reads `other`. */
class Normalizer extends ComponentVM {
  declare flag: boolean;
  declare other: number;
  readonly log: string[] = [];
  constructor(s: Services, register = true) {
    super(base(s, "normalizer"));
    this.observable({ flag: false, other: 0 });
    if (register) this.track();
  }
  track(): void {
    this.effect(() => {
      const flag = this.flag;
      this.log.push(`enter:${String(flag)}`);
      if (!flag) {
        this.flag = true;
        this.log.push(`exit:${String(flag)}`);
        return;
      }
      this.log.push(`other:${String(this.other)}`);
      this.log.push(`exit:${String(flag)}`);
    });
  }
}

const SEQUENTIAL = ["enter:false", "exit:false", "enter:true", "other:0", "exit:true"];

describe("attack-r1 re-entrancy: an effect's first run that writes what it read", () => {
  it("R1a at construct, the first run completes before the re-run it caused starts", () => {
    const vm = new Normalizer(services());
    vm.construct();
    assert.deepEqual(vm.log, SEQUENTIAL);
  });

  it("R1b registered while Constructed, the first run completes before the re-run it caused starts", () => {
    const vm = new Normalizer(services(), false);
    vm.construct();
    vm.track();
    assert.deepEqual(vm.log, SEQUENTIAL);
  });

  it("R2 the effect keeps the dependencies of its latest run (a later change of `other` re-runs it)", () => {
    const vm = new Normalizer(services());
    vm.construct();
    vm.log.length = 0;
    vm.other = 1;
    assert.deepEqual(vm.log, ["enter:true", "other:1", "exit:true"]);
  });

  it("R3 every cleanup that a run returned runs exactly once", () => {
    const opened: number[] = [];
    const closed: number[] = [];
    class Clamp extends ComponentVM {
      declare n: number;
      constructor(s: Services) {
        super(base(s, "clamp"));
        this.observable({ n: 0 });
        this.effect(() => {
          const n = this.n;
          if (n === 0) this.n = 1;
          opened.push(n);
          return () => closed.push(n);
        });
      }
    }
    const vm = new Clamp(services());
    vm.construct();
    vm.destruct();
    assert.deepEqual([...opened].sort(), [0, 1]);
    assert.deepEqual([...closed].sort(), [0, 1], `opened ${opened.join(",")}; closed ${closed.join(",")}`);
  });
});

describe("attack-r1 re-entrancy: an immediate reaction handler that writes what its select reads", () => {
  it("R4 the handler is not re-entered: one delivery completes before the next starts", () => {
    const log: string[] = [];
    class Seeder extends ComponentVM {
      declare n: number;
      constructor(s: Services) {
        super(base(s, "seeder"));
        this.observable({ n: 0 });
        this.reaction(
          () => this.n,
          (value) => {
            log.push(`enter:${String(value)}`);
            if (value === 0) this.n = 1;
            log.push(`exit:${String(value)}`);
          },
          { immediate: true },
        );
      }
    }
    new Seeder(services()).construct();
    assert.deepEqual(log, ["enter:0", "exit:0", "enter:1", "exit:1"]);
  });
});

describe("attack-r1 re-entrancy: writes during the drain (expected to hold)", () => {
  it("R5 a hub observer that writes during delivery: FIFO, lossless, every observer reads current state", () => {
    const s = services();
    class Doubler extends ComponentVM {
      declare a: number;
      constructor() {
        super(base(s, "doubler"));
        this.observable({ a: 0 });
        this.computed("double");
      }
      get double(): number {
        return this.a * 2;
      }
    }
    const vm = new Doubler();
    activate(vm);
    const seen: string[] = [];
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === vm && m.propertyName === "a" && vm.a === 1) vm.a = 2;
    });
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === vm) {
        seen.push(`${m.propertyName}=${String(vm.a)}/${String(vm.double)}`);
      }
    });
    vm.a = 1;
    assert.deepEqual(seen, ["a=2/4", "double=2/4", "a=2/4", "double=2/4"]);
  });

  class Mirror extends ComponentVM {
    declare source: number;
    declare mirror: number;
    constructor(
      s: Services,
      readonly events: string[],
    ) {
      super(base(s, "mirror"));
      this.observable({ source: 0, mirror: 0 });
      this.computed("mirrorText");
      this.effect(() => {
        const v = this.source;
        this.mirror = v * 2;
        // Read after the write: the run sees the settled value.
        events.push(`effect:${this.mirrorText}`);
      });
    }
    get mirrorText(): string {
      return `m${String(this.mirror)}`;
    }
  }

  function mirrorRun(): string[] {
    const s = services();
    const events: string[] = [];
    const vm = new Mirror(s, events);
    vm.construct();
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === vm) events.push(`hub:${m.propertyName}`);
    });
    events.length = 0;
    vm.source = 3;
    return events;
  }

  it("R6a inside an effect re-run, a write settles at once (fresh reads) and announces after the run", () => {
    assert.deepEqual(mirrorRun().slice(0, 4), ["hub:source", "effect:m6", "hub:mirror", "hub:mirrorText"]);
  });

  it("R6b an effect that writes and then reads the fresh value runs once per cause, not twice", () => {
    assert.deepEqual(mirrorRun(), ["hub:source", "effect:m6", "hub:mirror", "hub:mirrorText"]);
  });

  it("R7 a canExecuteChanged listener that writes what the predicate reads converges without recursion", () => {
    const s = services();
    class Counter extends ComponentVM {
      declare n: number;
      readonly step = this.relayCommand(
        () => undefined,
        () => this.n < 3,
      );
      constructor() {
        super(base(s, "counter"));
        this.observable({ n: 0 });
      }
    }
    const vm = new Counter();
    const depths: number[] = [];
    const previousLimit = Error.stackTraceLimit;
    Error.stackTraceLimit = 500;
    try {
      vm.step.canExecuteChanged.subscribe(() => {
        depths.push((new Error().stack ?? "").split("\n").length);
        if (vm.step.canExecute()) vm.n += 1;
      });
      vm.step.canExecute();
      vm.n = 1;
    } finally {
      Error.stackTraceLimit = previousLimit;
    }
    assert.equal(vm.n, 3);
    assert.equal(depths.length, 3);
    assert.equal(new Set(depths).size, 1, `stack depths ${depths.join(",")}`);
  });
});
