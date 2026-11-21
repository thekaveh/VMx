/**
 * Rules not covered by one conformance ID alone: R3.2 setters, R3.4, R3.6, R3.7, R3.8, R4.4, R4.5, R7.3, R9.5,
 * R12.8 and the observer-failure rows of R16.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, ComponentVMOf, ForwardingComponentVM, PropertyChangedMessage } from "@thekaveh/vmx";
import { activate, ReactiveOverflowError, ReactiveWriteError } from "../src/index.js";
import { base, Recorder, type Services, services, streamFed } from "./support.js";

describe("registration rules", () => {
  it("R3.2 a computed with a prototype setter forwards assignments to it", () => {
    const s = services();
    class Range extends ComponentVM {
      declare start: number;
      constructor() {
        super(base(s, "range"));
        this.observable({ start: 0 });
        this.computed("end");
      }
      get end(): number {
        return this.start + 10;
      }
      set end(value: number) {
        this.start = value - 10;
      }
    }
    const vm = new Range();
    activate(vm);
    const rec = new Recorder(s.hub);
    vm.end = 25;
    assert.equal(vm.start, 15);
    assert.deepEqual(rec.hubNames(), ["range.start", "range.end"]);
  });

  it("R3.4 a registration after disposal started installs nothing; R3.6 signals and memos stop", () => {
    const s = services();
    class Late extends ComponentVM {
      declare readonly x: number;
      readonly sig = this.signal(1);
      readonly twice = this.memo(() => this.sig.value * 2);
      constructor() {
        super(base(s, "late"));
      }
    }
    const vm = new Late();
    assert.equal(vm.twice.value, 2);
    vm.dispose();
    const write = vm.observable({ x: 1 });
    write({ x: 2 });
    assert.equal(Object.getOwnPropertyDescriptor(vm, "x"), undefined);
    vm.sig.value = 5;
    assert.equal(vm.sig.peek(), 1, "a write after disposal is ignored");
    assert.equal(vm.twice.value, 2, "a memo keeps its last value");
  });

  it("R3.7 a base class and a subclass register their own names", () => {
    const s = services();
    class Base extends ComponentVM {
      declare readonly a: number;
      readonly setA;
      constructor(name: string) {
        super(base(s, name));
        this.setA = this.observable({ a: 1 });
        this.computed("doubleA");
      }
      get doubleA(): number {
        return this.a * 2;
      }
    }
    class Sub extends Base {
      declare readonly b: number;
      readonly setB;
      constructor() {
        super("sub");
        this.setB = this.observable({ b: 1 });
        this.computed("sum");
      }
      get sum(): number {
        return this.doubleA + this.b;
      }
    }
    const vm = new Sub();
    activate(vm);
    const rec = new Recorder(s.hub);
    vm.setA({ a: 2 });
    vm.setB({ b: 3 });
    assert.deepEqual(rec.hubNames(), ["sub.a", "sub.doubleA", "sub.sum", "sub.b", "sub.sum"]);
    assert.equal(vm.sum, 7);
  });

  it("R4.4 a write inside a baseline throws ReactiveWriteError and leaves an error node", () => {
    class Bad extends ComponentVM {
      declare n: number;
      constructor(s: Services) {
        super(base(s, "bad"));
        this.observable({ n: 0 });
        this.computed("sneaky");
      }
      get sneaky(): number {
        this.n = 1;
        return this.n;
      }
    }
    const vm = new Bad(services());
    activate(vm);
    assert.equal(vm.n, 0);
    assert.throws(() => vm.sneaky, ReactiveWriteError);
  });

  it("R4.5 no baseline in constructors: a subclass override that reads a subclass field is safe", () => {
    const s = services();
    class Route extends ComponentVM {
      declare readonly path: string;
      constructor(name: string) {
        super(base(s, name));
        this.observable({ path: "/docs" });
        this.computed("href");
      }
      get href(): string {
        return `?path=${this.path}`;
      }
    }
    class SearchRoute extends Route {
      readonly #filter = { term: "open" };
      constructor() {
        super("search");
      }
      override get href(): string {
        return `${super.href}&q=${this.#filter.term}`;
      }
    }
    const vm = new SearchRoute();
    vm.construct();
    assert.equal(vm.href, "?path=/docs&q=open");
  });
});

describe("R3.8 forwarding decorators follow the canonical identity", () => {
  it("a decorator's computed and reaction follow the wrapped view-model's lifecycle", () => {
    const s = services();
    const log: number[] = [];
    const wrapped = new ComponentVMOf<number>({ ...base(s, "wrapped"), initialModel: 1, modeledHinter: () => "" });
    class Doubling extends ForwardingComponentVM<number> {
      constructor() {
        super(wrapped);
        this.computed("doubled");
        this.effect(() => {
          log.push(this.doubled);
        });
      }
      get doubled(): number {
        return this.model * 2;
      }
    }
    const decorator = new Doubling();
    const fromDecorator: string[] = [];
    s.hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage && message.sender === decorator) {
        fromDecorator.push(message.propertyName);
      }
    });
    decorator.construct();
    assert.deepEqual(log, [2]);
    wrapped.model = 5;
    assert.deepEqual(log, [2, 10]);
    assert.deepEqual(fromDecorator, ["doubled"]);
    decorator.dispose();
    wrapped.model = 6;
    assert.deepEqual(log, [2, 10]);
  });
});

describe("drain rules", () => {
  it("R7.3 the body error of a change scope takes precedence over a drain overflow", () => {
    class Runaway extends ComponentVM {
      readonly n = this.signal(0);
      constructor(s: Services) {
        super(base(s, "runaway"));
        this.effect(() => {
          if (this.n.value > 0) this.n.value = this.n.value + 1;
        });
      }
    }
    const vm = new Runaway(services());
    vm.construct();
    assert.throws(
      () =>
        vm.change(() => {
          vm.n.value = 1;
          throw new Error("body");
        }),
      /body/,
    );
    assert.throws(() => {
      vm.n.value = 1_000_000;
    }, ReactiveOverflowError);
  });

  // Fix round 2 (R9.5): a disposal first delivers the announcements of the writes accepted before
  // it, through the helper, before Disposed is published (attack DD7); after Disposed nothing of the view-model is
  // queued or delivered. The scenario is unchanged; the expectation moved from ["pair.a"] to ["pair.a", "pair.b"].
  it("R9.5 a disposal during the drain delivers the queued announcements of the view-model first, then nothing more", () => {
    const s = services();
    class Pair extends ComponentVM {
      declare a: number;
      constructor() {
        super(base(s, "pair"));
        this.observable({ a: 0 });
        this.computed("b");
      }
      get b(): number {
        return this.a + 1;
      }
    }
    const vm = new Pair();
    activate(vm);
    const rec = new Recorder(s.hub);
    s.hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage && message.propertyName === "a") vm.dispose();
    });
    vm.a = 1;
    assert.deepEqual(rec.hubNames(), ["pair.a", "pair.b"]);
    vm.a = 2;
    assert.deepEqual(rec.hubNames(), ["pair.a", "pair.b"], "a write after Disposed is ignored");
  });

  it("R16 a failing hub observer and a failing local observer do not stop the drain", async () => {
    const s = services();
    class Pair extends ComponentVM {
      declare a: number;
      constructor() {
        super(base(s, "pair"));
        this.observable({ a: 0 });
        this.computed("b");
      }
      get b(): number {
        return this.a + 1;
      }
    }
    const vm = new Pair();
    s.hub.messages.subscribe(() => {
      throw new Error("hub observer failed");
    });
    vm.propertyChanged.subscribe(() => {
      throw new Error("local observer failed");
    });
    const rec = new Recorder(s.hub).local(vm);
    vm.a = 1;
    assert.deepEqual(rec.take(), ["hub:pair.a", "local:pair.a", "hub:pair.b", "local:pair.b"]);
    const errors = (await streamFed()).map(String);
    assert.ok(errors.some((error) => error.includes("local observer failed")));
  });

  it("R12.8 a throwing cleanup or teardown is isolated and swallowed", () => {
    const vm = new ComponentVM(base(services(), "cleanup"));
    const log: string[] = [];
    vm.whileConstructed(() => () => log.push("first"));
    vm.whileConstructed(() => () => {
      throw new Error("teardown failed");
    });
    vm.effect(() => () => {
      throw new Error("cleanup failed");
    });
    vm.construct();
    vm.destruct();
    assert.deepEqual(log, ["first"]);
    vm.construct();
    vm.dispose();
    assert.deepEqual(log, ["first", "first"]);
  });
});
