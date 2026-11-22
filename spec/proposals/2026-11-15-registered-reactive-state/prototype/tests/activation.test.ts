/**
 * RSTATE-006 to RSTATE-008: activation triggers and cascade, silent baselines, memoization.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, CompositeVM, ConstructionStatus } from "@thekaveh/vmx";
import { activate, configureReactiveDiagnostics, untracked } from "../src/index.js";
import { base, Recorder, type Services, services, streamFed } from "./support.js";

/** A VM whose computed reads another VM's state: it announces only once activated. */
class Source extends ComponentVM {
  declare readonly n: number;
  readonly write;
  constructor(s: Services, name = "source") {
    super(base(s, name));
    this.write = this.observable({ n: 1 });
  }
}

class Reader extends ComponentVM {
  readonly log: string[] = [];
  constructor(
    s: Services,
    readonly source: Source,
    name = "reader",
  ) {
    super(base(s, name));
    this.computed("twice");
  }
  get twice(): number {
    this.log.push(`eval:${String(this.source.n)}`);
    return this.source.n * 2;
  }
  protected override _onConstruct(): void {
    this.log.push("onConstruct");
  }
}

function quietly(fn: () => void): void {
  configureReactiveDiagnostics({ development: false });
  try {
    fn();
  } finally {
    configureReactiveDiagnostics({ development: undefined });
  }
}

describe("RSTATE-006 activation triggers and the cascade", () => {
  it("(a) the first construct activates after Constructing is published and before _onConstruct", () => {
    quietly(() => {
      const s = services();
      const source = new Source(s);
      class StatusReader extends Reader {
        override get twice(): number {
          this.log.push(`status:${untracked(() => ConstructionStatus[this.status])}`);
          return super.twice;
        }
      }
      const reader = new StatusReader(s, source);
      const rec = new Recorder(s.hub, { status: true });
      source.write({ n: 2 });
      assert.deepEqual(rec.hubNames(), ["source.n"]);
      assert.deepEqual(reader.log, []);
      rec.take();
      reader.construct();
      assert.deepEqual(reader.log, ["status:Constructing", "eval:2", "onConstruct"]);
      rec.take();
      source.write({ n: 3 });
      assert.deepEqual(rec.hubNames(), ["source.n", "reader.twice"]);
    });
  });

  it("(b) the first subscription to the VM-local surface activates", () => {
    const s = services();
    const source = new Source(s);
    const reader = new Reader(s, source);
    const rec = new Recorder(s.hub);
    source.write({ n: 5 });
    assert.deepEqual(rec.take(), ["hub:source.n"]);
    reader.propertyChanged.subscribe(() => undefined);
    source.write({ n: 6 });
    assert.deepEqual(rec.take(), ["hub:source.n", "hub:reader.twice"]);
  });

  it("(c, d) members and container children of an activated owner activate, also when added later", () => {
    const s = services();
    const source = new Source(s);
    class Owner extends ComponentVM {
      readonly first: Reader;
      constructor() {
        super(base(s, "owner"));
        this.first = this.member(new Reader(s, source, "first"));
      }
    }
    const owner = new Owner();
    const container = new CompositeVM<Reader>(base(s, "container"));
    const child = new Reader(s, source, "child");
    container.add(child);
    activate(owner);
    activate(container);
    const late = owner.member(new Reader(s, source, "late"));
    const added = new Reader(s, source, "added");
    container.add(added);
    const rec = new Recorder(s.hub);
    source.write({ n: 10 });
    assert.deepEqual(rec.hubNames(), ["source.n", "first.twice", "child.twice", "late.twice", "added.twice"]);
    assert.equal(late.twice, 20);
  });

  it("(e) activate(vm) is idempotent and a no-op once disposal started", () => {
    quietly(() => {
      const s = services();
      const source = new Source(s);
      const reader = new Reader(s, source);
      activate(reader);
      activate(reader);
      assert.deepEqual(reader.log, ["eval:1"]);
      const other = new Reader(s, source, "other");
      other.dispose();
      activate(other);
      const rec = new Recorder(s.hub);
      source.write({ n: 2 });
      assert.deepEqual(rec.hubNames(), ["source.n", "reader.twice"]);
    });
  });
});

describe("RSTATE-007 baselines are silent; a throwing baseline leaves an error node", () => {
  it("activation announces nothing", () => {
    const s = services();
    const reader = new Reader(s, new Source(s));
    const rec = new Recorder(s.hub, { status: true });
    activate(reader);
    reader.construct();
    assert.deepEqual(
      rec.take().filter((event) => event.startsWith("hub:")),
      [],
    );
  });

  it("a throwing baseline is not reported or announced; a later recovery is announced", async () => {
    const s = services();
    const source = new Source(s);
    class Fragile extends ComponentVM {
      constructor() {
        super(base(s, "fragile"));
        this.computed("value");
      }
      get value(): number {
        if (source.n < 0) throw new Error("negative");
        return source.n;
      }
    }
    source.write({ n: -1 });
    const vm = new Fragile();
    const rec = new Recorder(s.hub);
    activate(vm);
    assert.deepEqual(await streamFed(), []);
    assert.throws(() => vm.value, /negative/);
    assert.deepEqual(await streamFed(), []);
    source.write({ n: 4 });
    assert.deepEqual(rec.hubNames(), ["source.n", "fragile.value"]);
    assert.equal(vm.value, 4);
  });
});

describe("RSTATE-008 memoization", () => {
  it("evaluates once for many reads and again only after a dependency change", () => {
    quietly(() => {
      const s = services();
      const source = new Source(s);
      const unrelated = new Source(s, "unrelated");
      const reader = new Reader(s, source);
      activate(reader);
      reader.log.length = 0;
      for (let i = 0; i < 5; i += 1) assert.equal(reader.twice, 2);
      assert.deepEqual(reader.log, []);
      unrelated.write({ n: 7 });
      assert.deepEqual(reader.log, []);
      source.write({ n: 3 });
      assert.deepEqual(reader.log, ["eval:3"]);
      assert.equal(reader.twice, 6);
      assert.deepEqual(reader.log, ["eval:3"]);
    });
  });

  it("activation evaluates each computed once, also when an earlier baseline pulled it", () => {
    quietly(() => {
      const s = services();
      const calls: string[] = [];
      class Chain extends ComponentVM {
        declare readonly n: number;
        constructor() {
          super(base(s, "chain"));
          this.observable({ n: 1 });
          this.computed("top", "low");
        }
        get top(): number {
          calls.push("top");
          return this.low + 1;
        }
        get low(): number {
          calls.push("low");
          return this.n;
        }
      }
      activate(new Chain());
      assert.deepEqual(calls, ["top", "low"]);
    });
  });

  it("a memo is lazy, memoized, and receives its previous value", () => {
    const s = services();
    const source = new Source(s);
    class WithMemo extends ComponentVM {
      calls = 0;
      readonly history = this.memo<readonly number[]>((previous) => {
        this.calls += 1;
        return [...(previous ?? []), source.n];
      });
      constructor() {
        super(base(s, "memo"));
      }
    }
    const vm = new WithMemo();
    assert.equal(vm.calls, 0);
    assert.deepEqual(vm.history.value, [1]);
    assert.deepEqual(vm.history.value, [1]);
    assert.equal(vm.calls, 1);
    source.write({ n: 2 });
    assert.equal(vm.calls, 1);
    assert.deepEqual(vm.history.peek(), [1, 2]);
    assert.equal(vm.calls, 2);
  });
});
