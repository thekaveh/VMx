/**
 * RSTATE-009 to RSTATE-015: announcements through the helper, glitch freedom, losslessness, ordering, change
 * scopes, independence from hub transactions, and re-entrant FIFO delivery.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, PropertyChangedMessage } from "@thekaveh/vmx";
import { activate, configureReactiveDiagnostics, ReactiveWriteError } from "../src/index.js";
import { base, Recorder, type Services, services } from "./support.js";

function quietly(fn: () => void): void {
  configureReactiveDiagnostics({ development: false });
  try {
    fn();
  } finally {
    configureReactiveDiagnostics({ development: undefined });
  }
}

/** A → B, A → C, B + C → D (R6.9). */
class Diamond extends ComponentVM {
  declare a: number;
  readonly write;
  readonly seen: string[] = [];
  dCalls = 0;
  constructor(s: Services) {
    super(base(s, "diamond"));
    this.write = this.observable({ a: 1 });
    this.computed("b", "c", "d");
  }
  get b(): number {
    return this.a + 1;
  }
  get c(): number {
    return this.a * 10;
  }
  get d(): string {
    this.dCalls += 1;
    this.seen.push(`${String(this.b)}/${String(this.c)}`);
    return `${String(this.b)}:${String(this.c)}`;
  }
}

describe("RSTATE-009 each changed published value is announced once per settle, hub first", () => {
  it("one hub message then one local emission per changed value", () => {
    const s = services();
    const vm = new Diamond(s);
    const rec = new Recorder(s.hub).local(vm);
    vm.a = 2;
    assert.deepEqual(rec.take(), [
      "hub:diamond.a",
      "local:diamond.a",
      "hub:diamond.b",
      "local:diamond.b",
      "hub:diamond.c",
      "local:diamond.c",
      "hub:diamond.d",
      "local:diamond.d",
    ]);
  });

  it("a computed that re-evaluates to an equal value is not announced, nor are its dependents", () => {
    class Parity extends ComponentVM {
      declare n: number;
      constructor(s: Services) {
        super(base(s, "parity"));
        this.observable({ n: 1 });
        this.computed("odd", "text");
      }
      get odd(): boolean {
        return this.n % 2 === 1;
      }
      get text(): string {
        return this.odd ? "odd" : "even";
      }
    }
    const s = services();
    const vm = new Parity(s);
    activate(vm);
    const rec = new Recorder(s.hub);
    vm.n = 3;
    assert.deepEqual(rec.hubNames(), ["parity.n"]);
    vm.n = 4;
    assert.deepEqual(rec.hubNames(), ["parity.n", "parity.n", "parity.odd", "parity.text"]);
  });
});

describe("RSTATE-010 glitch freedom (diamond)", () => {
  it("one write evaluates D once with a consistent B and C and announces it once", () => {
    quietly(() => {
      const s = services();
      const vm = new Diamond(s);
      activate(vm);
      const rec = new Recorder(s.hub);
      vm.dCalls = 0;
      vm.seen.length = 0;
      vm.a = 5;
      assert.equal(vm.dCalls, 1);
      assert.deepEqual(vm.seen, ["6/50"]);
      assert.equal(rec.hubNames().filter((name) => name === "diamond.d").length, 1);
    });
  });
});

describe("RSTATE-011 losslessness", () => {
  it("two writes announce D twice when it changed twice", () => {
    const s = services();
    const vm = new Diamond(s);
    activate(vm);
    const rec = new Recorder(s.hub);
    vm.a = 2;
    vm.a = 3;
    assert.equal(rec.hubNames().filter((name) => name === "diamond.d").length, 2);
  });

  it("a name changed by an outer and a nested settle is announced by both; observers read current state", () => {
    const s = services();
    const vm = new Diamond(s);
    activate(vm);
    const values: string[] = [];
    s.hub.messages.subscribe((message) => {
      if (!(message instanceof PropertyChangedMessage) || message.sender !== vm) return;
      if (message.propertyName === "a" && vm.a === 2) vm.a = 3;
      if (message.propertyName === "d") values.push(vm.d);
    });
    vm.a = 2;
    assert.deepEqual(values, ["4:30", "4:30"]);
  });
});

describe("RSTATE-012 ordering", () => {
  it("announcements by height then index, then command raises, then reaction runs; settles FIFO", () => {
    const s = services();
    const events: string[] = [];
    class Ordered extends ComponentVM {
      declare x: number;
      declare y: number;
      readonly write;
      readonly command = this.relayCommand(
        () => undefined,
        () => this.x > 0,
      );
      constructor() {
        super(base(s, "ordered"));
        this.write = this.observable({ x: 1, y: 1 });
        this.computed("top", "low");
        this.reaction(
          () => this.top,
          (value) => events.push(`reaction:${String(value)}`),
          { alive: true },
        );
      }
      get top(): number {
        return this.low + 1;
      }
      get low(): number {
        return this.x + this.y;
      }
    }
    const vm = new Ordered();
    activate(vm);
    vm.command.canExecute();
    vm.command.canExecuteChanged.subscribe(() => events.push("raise"));
    s.hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage) events.push(`hub:${message.propertyName}`);
    });
    vm.write({ y: 2, x: 3 });
    assert.deepEqual(events, ["hub:x", "hub:y", "hub:low", "hub:top", "raise", "reaction:6"]);
  });
});

describe("RSTATE-013 change scopes", () => {
  it("writes inside one scope settle once; a value that changed back is not announced; reads are fresh", () => {
    quietly(() => {
      const s = services();
      const vm = new Diamond(s);
      activate(vm);
      const rec = new Recorder(s.hub);
      vm.dCalls = 0;
      const seenInside: string[] = [];
      vm.change(() => {
        vm.a = 2;
        seenInside.push(vm.d);
        vm.a = 3;
        vm.change(() => {
          vm.a = 4;
        });
      });
      assert.deepEqual(seenInside, ["3:20"]);
      assert.deepEqual(rec.hubNames(), ["diamond.a", "diamond.b", "diamond.c", "diamond.d"]);
      assert.equal(vm.d, "5:40");
      rec.take();
      vm.change(() => {
        vm.a = 9;
        vm.a = 4;
      });
      assert.deepEqual(rec.hubNames(), []);
    });
  });

  it("a throwing body keeps its writes, settles, drains and rethrows", () => {
    const s = services();
    const vm = new Diamond(s);
    activate(vm);
    const rec = new Recorder(s.hub);
    assert.throws(
      () =>
        vm.change(() => {
          vm.a = 7;
          throw new Error("body");
        }),
      /body/,
    );
    assert.equal(vm.a, 7);
    assert.deepEqual(rec.hubNames(), ["diamond.a", "diamond.b", "diamond.c", "diamond.d"]);
  });

  it("change() inside an evaluation frame throws ReactiveWriteError", () => {
    class Bad extends ComponentVM {
      constructor(s: Services) {
        super(base(s, "bad"));
        this.computed("value");
      }
      get value(): number {
        return this.change(() => 1);
      }
    }
    const vm = new Bad(services());
    activate(vm);
    assert.throws(() => vm.value, ReactiveWriteError);
  });

  it("spans only the synchronous run: code after an await settles on its own", async () => {
    const s = services();
    const vm = new Diamond(s);
    activate(vm);
    const rec = new Recorder(s.hub);
    await vm.change(async () => {
      vm.a = 2;
      await Promise.resolve();
      assert.deepEqual(rec.hubNames(), ["diamond.a", "diamond.b", "diamond.c", "diamond.d"]);
      vm.a = 3;
      assert.equal(rec.hubNames().length, 8);
    });
  });
});

describe("RSTATE-014 independence from hub transactions", () => {
  it("inside hub.batch the local emissions happen at once and the hub messages wait", () => {
    const s = services();
    const vm = new Diamond(s);
    const rec = new Recorder(s.hub).local(vm);
    s.hub.batch(() => {
      vm.a = 2;
      assert.deepEqual(rec.take(), ["local:diamond.a", "local:diamond.b", "local:diamond.c", "local:diamond.d"]);
    });
    assert.deepEqual(rec.take(), ["hub:diamond.a", "hub:diamond.b", "hub:diamond.c", "hub:diamond.d"]);
  });

  it("a hub batch opens no change scope: two writes are two settles", () => {
    const s = services();
    const vm = new Diamond(s);
    activate(vm);
    const rec = new Recorder(s.hub);
    s.hub.batch(() => {
      vm.a = 2;
      vm.a = 3;
    });
    assert.equal(rec.hubNames().filter((name) => name === "diamond.d").length, 2);
  });

  it("a change scope opens no hub batch: the hub delivers during the scope's drain", () => {
    const s = services();
    const vm = new Diamond(s);
    activate(vm);
    const rec = new Recorder(s.hub);
    vm.change(() => {
      vm.a = 2;
    });
    assert.deepEqual(rec.hubNames(), ["diamond.a", "diamond.b", "diamond.c", "diamond.d"]);
  });
});

describe("RSTATE-015 re-entrant FIFO without recursion", () => {
  it("a write by an observer is settled at once, appended, and drained by the outermost write", () => {
    const s = services();
    class Chain extends ComponentVM {
      declare n: number;
      constructor() {
        super(base(s, "chain"));
        this.observable({ n: 0 });
        this.computed("next");
      }
      get next(): number {
        return this.n + 1;
      }
    }
    const vm = new Chain();
    activate(vm);
    const depths: number[] = [];
    const order: string[] = [];
    const previousLimit = Error.stackTraceLimit;
    Error.stackTraceLimit = 500;
    try {
      vm.propertyChanged.subscribe((name) => {
        order.push(`${name}=${String(name === "n" ? vm.n : vm.next)}`);
        if (name === "n") {
          depths.push((new Error().stack ?? "").split("\n").length);
          if (vm.n < 5) vm.n += 1;
        }
      });
      vm.n = 1;
    } finally {
      Error.stackTraceLimit = previousLimit;
    }
    assert.equal(vm.n, 5);
    // FIFO: each settle's entries follow the queued ones; observers read the state current at delivery (R9.4).
    assert.deepEqual(order, ["n=1", "next=3", "n=2", "next=4", "n=3", "next=5", "n=4", "next=6", "n=5", "next=6"]);
    assert.equal(new Set(depths).size, 1, `stack depths ${depths.join(",")}`);
  });
});
