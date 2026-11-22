/**
 * Attack round 2: cycles between computed properties: before activation, through private memos across view-models,
 * through a parameterized command predicate, through untracked(), and effects that write each other's inputs.
 *
 * Expectations used: R16 "A node read during its own evaluation throws ReactiveCycleError"; "every node
 * of the cycle recovers, and is announced, when the cycle opens".
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, PropertyChangedMessage } from "@thekaveh/vmx";
import { activate, configureReactiveDiagnostics, ReactiveCycleError, untracked } from "../src/index.js";
import { base, type Services, services, streamFed } from "./support.js";

function quietly<T>(fn: () => T): T {
  configureReactiveDiagnostics({ development: false });
  try {
    return fn();
  } finally {
    configureReactiveDiagnostics({ development: undefined });
  }
}

function hubNames(s: Services, sender?: object): string[] {
  const names: string[] = [];
  s.hub.messages.subscribe((m) => {
    if (!(m instanceof PropertyChangedMessage)) return;
    if (sender !== undefined && m.sender !== sender) return;
    names.push(`${m.senderName}.${m.propertyName}`);
  });
  return names;
}

class Loop extends ComponentVM {
  constructor(s: Services) {
    super(base(s, "loop"));
    this.computed("ping", "pong");
  }
  get ping(): number {
    return this.pong + 1;
  }
  get pong(): number {
    return this.ping + 1;
  }
}

describe("attack-r2 cycles", () => {
  // Fix round 2 (R16): a plain getter (before activation) that is read during its own evaluation
  // throws ReactiveCycleError too. The scenario is unchanged; the expectation moved from the documented gap
  // (RangeError before activation) to the resolved rule.
  it("CC1 the error for a cycle does not depend on activation: ReactiveCycleError before and after", () => {
    const s = services();
    const vm = new Loop(s);
    let before: unknown = null;
    try {
      void vm.ping;
    } catch (error) {
      before = error;
    }
    assert.ok(before instanceof ReactiveCycleError, `before activation: ${String(before)}`);
    activate(vm);
    assert.throws(() => vm.ping, ReactiveCycleError);
  });

  it("CC2 a cycle through a private memo of one VM and a computed of another throws ReactiveCycleError and recovers (expected to hold)", async () => {
    await streamFed();
    const s = services();
    class Left extends ComponentVM {
      declare linked: boolean;
      declare base: number;
      right: Right | null = null;
      readonly #mirror = this.memo(() => (this.linked && this.right !== null ? this.right.total : this.base));
      constructor() {
        super(base(s, "left"));
        this.observable({ linked: false, base: 1 });
      }
      get mirror(): number {
        return this.#mirror.value;
      }
    }
    class Right extends ComponentVM {
      constructor(readonly left: Left) {
        super(base(s, "right"));
        this.computed("total");
      }
      get total(): number {
        return this.left.mirror + 10;
      }
    }
    quietly(() => {
      const left = new Left();
      const right = new Right(left);
      left.right = right;
      activate(right);
      assert.equal(right.total, 11);
      left.linked = true;
      assert.throws(() => right.total, ReactiveCycleError);
      const names = hubNames(s, right);
      left.linked = false;
      assert.equal(right.total, 11);
      assert.deepEqual(names, ["right.total"], "the cycle opened: total recovered and was announced");
      left.base = 2;
      assert.equal(right.total, 12);
    });
    await streamFed();
  });

  it("CC3 a cycle closed through a parameterized command predicate surfaces and recovers (expected to hold)", async () => {
    await streamFed();
    const s = services();
    class Row extends ComponentVM {
      declare locked: boolean;
      declare looped: boolean;
      constructor() {
        super(base(s, "row"));
        this.observable({ locked: false, looped: false });
      }
    }
    const row = new Row();
    class Listing extends ComponentVM {
      readonly remove = this.relayCommandOf<Row>(
        () => undefined,
        (r) => !r.locked && (!r.looped || this.canRemove),
      );
      constructor() {
        super(base(s, "listing"));
        this.computed("canRemove");
      }
      get canRemove(): boolean {
        return this.remove.canExecute(row);
      }
    }
    quietly(() => {
      const listing = new Listing();
      activate(listing);
      assert.equal(listing.canRemove, true);
      row.looped = true;
      assert.throws(() => listing.canRemove, ReactiveCycleError);
      const names = hubNames(s, listing);
      row.looped = false;
      assert.equal(listing.canRemove, true);
      assert.deepEqual(names, ["listing.canRemove"]);
      row.locked = true;
      assert.equal(listing.canRemove, false);
    });
    await streamFed();
  });

  it("CC4 a self-read through untracked() is still a cycle (expected to hold)", () => {
    const s = services();
    class Self extends ComponentVM {
      constructor() {
        super(base(s, "self"));
        this.computed("value");
      }
      get value(): number {
        return untracked(() => this.value) + 1;
      }
    }
    const vm = new Self();
    activate(vm);
    assert.throws(() => vm.value, ReactiveCycleError);
  });

  it("CC5 two effects that write each other's inputs converge without the overflow bound (expected to hold)", () => {
    const s = services();
    class Pair extends ComponentVM {
      declare celsius: number;
      declare fahrenheit: number;
      runs = 0;
      constructor() {
        super(base(s, "pair"));
        this.observable({ celsius: 0, fahrenheit: 32 });
        this.effect(() => {
          this.runs += 1;
          this.fahrenheit = (this.celsius * 9) / 5 + 32;
        });
        this.effect(() => {
          this.runs += 1;
          this.celsius = ((this.fahrenheit - 32) * 5) / 9;
        });
      }
    }
    const vm = new Pair();
    vm.construct();
    vm.runs = 0;
    vm.celsius = 100;
    assert.equal(vm.fahrenheit, 212);
    assert.equal(vm.celsius, 100);
    assert.ok(vm.runs <= 4, `runs ${String(vm.runs)}`);
    vm.fahrenheit = 32;
    assert.equal(vm.celsius, 0);
  });
});
