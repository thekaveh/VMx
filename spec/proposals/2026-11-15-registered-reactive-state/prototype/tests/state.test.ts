/**
 * RSTATE-001 to RSTATE-005: state registration, registration errors, accepted writes, multi-key patches, and
 * computeds before activation.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, ExpandableState } from "@thekaveh/vmx";
import { activate, configureReactiveDiagnostics, ReactiveWriteError, tracked } from "../src/index.js";
import { base, Recorder, type Services, services } from "./support.js";

class Pair extends ComponentVM {
  declare a: number;
  declare readonly b: string;
  readonly write;
  calls = 0;

  constructor(s: Services, name = "pair") {
    super(base(s, name));
    this.write = this.observable({ a: 1, b: "x" });
    this.computed("label");
  }

  get label(): string {
    this.calls += 1;
    return `${this.b}${String(this.a)}`;
  }
}

function quietly<T>(fn: () => T): T {
  configureReactiveDiagnostics({ development: false });
  try {
    return fn();
  } finally {
    configureReactiveDiagnostics({ development: undefined });
  }
}

describe("RSTATE-001 registering state installs accessors; writer and setter write", () => {
  it("installs configurable, enumerable own accessors in key order and announces nothing at registration", () => {
    const s = services();
    const rec = new Recorder(s.hub);
    const vm = new Pair(s);
    const a = Object.getOwnPropertyDescriptor(vm, "a");
    assert.ok(a?.get !== undefined && a.set !== undefined);
    assert.equal(a.configurable, true);
    assert.equal(a.enumerable, true);
    assert.deepEqual(
      Object.keys(vm).filter((key) => key === "a" || key === "b"),
      ["a", "b"],
    );
    assert.equal(vm.a, 1);
    assert.equal(vm.b, "x");
    activate(vm);
    assert.deepEqual(rec.take(), []);
  });

  it("the setter writes one key and the writer writes its patch", () => {
    const s = services();
    const vm = new Pair(s);
    const rec = new Recorder(s.hub).local(vm);
    vm.a = 2;
    assert.deepEqual(rec.take(), ["hub:pair.a", "local:pair.a", "hub:pair.label", "local:pair.label"]);
    vm.write({ b: "y" });
    assert.equal(vm.b, "y");
    assert.deepEqual(rec.take(), ["hub:pair.b", "local:pair.b", "hub:pair.label", "local:pair.label"]);
    assert.equal(vm.label, "y2");
  });

  it("the writer rejects an unknown key at runtime and writes nothing", () => {
    const s = services();
    const vm = new Pair(s);
    const rec = new Recorder(s.hub);
    assert.throws(() => vm.write({ a: 5, ...({ nope: 1 } as object) }), /no state key 'nope'/);
    assert.equal(vm.a, 1);
    assert.deepEqual(rec.take(), []);
  });
});

describe("RSTATE-002 registration errors", () => {
  it("rejects a duplicate name", () => {
    class Dup extends ComponentVM {
      declare readonly a: number;
      constructor(s: Services) {
        super(base(s, "dup"));
        this.observable({ a: 1 });
        this.observable({ a: 2 });
      }
    }
    assert.throws(() => new Dup(services()), /'a' is already registered/);
  });

  it("rejects a state key that names an accessor, a computed without a getter, and library names", () => {
    class Bad extends ComponentVM {
      get g(): number {
        return 1;
      }
      readonly plain: number = 3;
      method(): number {
        return 1;
      }
      constructor(s: Services, which: string) {
        super(base(s, "bad"));
        if (which === "accessor") this.observable({ g: 2 });
        if (which === "noGetter") this.computed("method");
        if (which === "library") this.computed("status");
        if (which === "libraryState") this.observable({ hint: "h" });
        if (which === "own") this.observable({ plain: 4 });
      }
    }
    assert.throws(() => new Bad(services(), "accessor"), /names an accessor/);
    assert.throws(() => new Bad(services(), "noGetter"), /has no getter/);
    assert.throws(() => new Bad(services(), "library"), /VMx library property/);
    assert.throws(() => new Bad(services(), "libraryState"), /VMx library property/);
    assert.throws(() => new Bad(services(), "own"), /already an own property/);
  });

  it("rejects invalidate of a name that is not a registered computed", () => {
    const vm = new Pair(services());
    assert.throws(() => vm.invalidate("a"), /not a registered computed/);
  });

  it("reports a name shadowed by a class field at activation", () => {
    class Base extends ComponentVM {
      declare x: number;
      constructor(s: Services) {
        super(base(s, "shadow"));
        this.observable({ x: 0 });
      }
    }
    class Sub extends Base {
      override x = 5;
    }
    const vm = new Sub(services());
    assert.equal(Object.getOwnPropertyDescriptor(vm, "x")?.value, 5);
    assert.throws(() => activate(vm), /x is shadowed by a class field; declare it with declare/);
  });

  it("throws ReactiveWriteError for a registration inside an evaluation frame", () => {
    class Inner extends ComponentVM {
      constructor(s: Services) {
        super(base(s, "inner"));
        this.computed("bad");
        activate(this);
      }
      get bad(): number {
        this.signal(1);
        return 1;
      }
    }
    const vm = new Inner(services());
    assert.throws(() => vm.bad, ReactiveWriteError);
  });
});

describe("RSTATE-003 accepted writes", () => {
  it("an equal write is silent", () => {
    const s = services();
    const vm = new Pair(s);
    activate(vm);
    const rec = new Recorder(s.hub);
    vm.a = 1;
    vm.write({ a: 1, b: "x" });
    assert.deepEqual(rec.take(), []);
  });

  it("a custom equality decides", () => {
    interface Item {
      readonly id: number;
      readonly text: string;
    }
    class Holder extends ComponentVM {
      declare readonly item: Item;
      readonly write;
      constructor(s: Services) {
        super(base(s, "holder"));
        this.write = this.observable({ item: { id: 1, text: "a" } }, { item: (x, y) => x.id === y.id });
      }
    }
    const s = services();
    const vm = new Holder(s);
    const rec = new Recorder(s.hub);
    vm.write({ item: { id: 1, text: "changed" } });
    assert.deepEqual(rec.take(), []);
    assert.equal(vm.item.text, "a");
    vm.write({ item: { id: 2, text: "b" } });
    assert.deepEqual(rec.take(), ["hub:holder.item"]);
  });

  it("writes after disposal started are ignored, including from _onDispose", () => {
    const s = services();
    let duringDispose: (() => void) | null = null;
    class Disposing extends ComponentVM {
      declare readonly v: number;
      readonly write;
      constructor() {
        super(base(s, "disposing"));
        this.write = this.observable({ v: 0 });
      }
      protected override _onDispose(): void {
        this.write({ v: 99 });
        duringDispose?.();
      }
    }
    const vm = new Disposing();
    activate(vm);
    vm.construct();
    const rec = new Recorder(s.hub);
    duringDispose = () => vm.write({ v: 7 });
    vm.dispose();
    vm.write({ v: 5 });
    assert.equal(vm.v, 0);
    assert.deepEqual(rec.hubNames(), []);
  });
});

describe("RSTATE-004 a multi-key patch is one write", () => {
  it("evaluates and announces a dependent once, after the patch keys in registration order", () => {
    quietly(() => {
      const s = services();
      const vm = new Pair(s);
      activate(vm);
      const rec = new Recorder(s.hub);
      vm.calls = 0;
      vm.write({ b: "z", a: 9 });
      assert.equal(vm.calls, 1);
      assert.deepEqual(rec.hubNames(), ["pair.a", "pair.b", "pair.label"]);
    });
  });

  it("two writes are two settles", () => {
    quietly(() => {
      const s = services();
      const vm = new Pair(s);
      activate(vm);
      const rec = new Recorder(s.hub);
      vm.calls = 0;
      vm.a = 2;
      vm.write({ b: "q" });
      assert.equal(vm.calls, 2);
      assert.deepEqual(rec.hubNames(), ["pair.a", "pair.label", "pair.b", "pair.label"]);
    });
  });
});

describe("RSTATE-005 before activation a registered computed is a plain getter", () => {
  it("calls the getter on every read and announces nothing", () => {
    quietly(() => {
      const s = services();
      const vm = new Pair(s);
      const rec = new Recorder(s.hub);
      vm.calls = 0;
      assert.equal(vm.label, "x1");
      assert.equal(vm.label, "x1");
      assert.equal(vm.calls, 2);
      vm.a = 3;
      assert.deepEqual(rec.hubNames(), ["pair.a"]);
    });
  });

  it("its reads are recorded by the caller's frame", () => {
    const s = services();
    const inner = new Pair(s, "inner");
    class Outer extends ComponentVM {
      constructor() {
        super(base(s, "outer"));
        this.computed("shout");
      }
      get shout(): string {
        return inner.label.toUpperCase();
      }
    }
    const outer = new Outer();
    activate(outer);
    const rec = new Recorder(s.hub);
    inner.a = 4;
    assert.deepEqual(rec.hubNames(), ["inner.a", "outer.shout"]);
    assert.equal(outer.shout, "X4");
  });

  it("an ExpandableState read through tracked() is a native node in the prototype", () => {
    const s = services();
    class Item extends ComponentVM {
      readonly expansion = this.own(tracked(new ExpandableState(false)));
      constructor() {
        super(base(s, "item"));
        this.computed("open");
      }
      get open(): boolean {
        return this.expansion.isExpanded;
      }
    }
    const vm = new Item();
    activate(vm);
    const rec = new Recorder(s.hub);
    vm.expansion.expand();
    assert.deepEqual(rec.hubNames(), ["item.open"]);
  });
});
