/**
 * RSTATE-016 to RSTATE-019: ReactiveWriteError, error states and reporting, cycles, the development drain bound.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, ComponentVMOf, ConstructionStatus } from "@thekaveh/vmx";
import {
  activate,
  configureReactiveDiagnostics,
  ReactiveCycleError,
  ReactiveOverflowError,
  ReactiveWriteError,
} from "../src/index.js";
import { base, Recorder, type Services, services, streamFed } from "./support.js";

class Writer extends ComponentVM {
  declare n: number;
  readonly other: ComponentVM;
  readonly servicesOf: Services;
  readonly command = this.relayCommand(
    () => undefined,
    () => {
      this.n = 5;
      return true;
    },
  );
  constructor(s: Services) {
    super(base(s, "writer"));
    this.servicesOf = s;
    this.other = new ComponentVM(base(s, "other"));
    // Instrument `other` before activation: the prototype guards the lifecycle calls of instrumented VMs only.
    this.other.observable({});
    this.observable({ n: 1 });
    this.computed("writes", "constructs", "registers");
  }
  get writes(): number {
    this.n = 2;
    return this.n;
  }
  get constructs(): number {
    this.other.construct();
    return 0;
  }
  get registers(): number {
    this.member(new ComponentVM(base(this.servicesOf, "late")));
    return 0;
  }
}

describe("RSTATE-016 ReactiveWriteError in evaluation frames", () => {
  for (const development of [true, false]) {
    it(`a write, a lifecycle call and member() inside a computed throw; a predicate reads false (development=${String(development)})`, () => {
      configureReactiveDiagnostics({ development });
      try {
        const vm = new Writer(services());
        activate(vm);
        assert.throws(() => vm.writes, ReactiveWriteError);
        assert.equal(vm.n, 1);
        assert.throws(() => vm.registers, ReactiveWriteError);
        assert.equal(vm.command.canExecute(), false);
        assert.equal(vm.n, 1);
        // A lifecycle call of an instrumented view-model throws before anything changes.
        assert.throws(() => vm.constructs, ReactiveWriteError);
        assert.equal(vm.other.status, ConstructionStatus.Destructed);
      } finally {
        configureReactiveDiagnostics({ development: undefined });
      }
    });
  }
});

describe("RSTATE-016 (library mutations of instrumented view-models)", () => {
  it("a model assignment inside a computed throws before the model changes", () => {
    const s = services();
    const doc = new ComponentVMOf<number>({ ...base(s, "doc"), initialModel: 1, modeledHinter: () => "" });
    doc.observable({});
    class Meddler extends ComponentVM {
      constructor() {
        super(base(s, "meddler"));
        this.computed("meddle");
      }
      get meddle(): number {
        doc.model = 2;
        return 0;
      }
    }
    const vm = new Meddler();
    activate(vm);
    assert.throws(() => vm.meddle, ReactiveWriteError);
    assert.equal(doc.model, 1);
  });
});

describe("RSTATE-017 error states and reporting", () => {
  class Source extends ComponentVM {
    declare level: number;
    calls = 0;
    constructor(s: Services) {
      super(base(s, "source"));
      this.observable({ level: 1 });
      this.computed("reading", "label");
    }
    get reading(): number {
      this.calls += 1;
      if (this.level < 0) throw new Error(`bad level ${String(this.level)}`);
      return this.level;
    }
    get label(): string {
      try {
        return `ok ${String(this.reading)}`;
      } catch {
        return "fault";
      }
    }
  }

  // Fix round 2 (R16): a change from one error to a different error (another message) is a change,
  // as attack EE1 and EE2 require: it is announced and reported. The scenario is unchanged; the expectation for
  // level -1 to -2 moved from "not a change" to an announcement of `reading` and one report.
  it("value-to-error, error-to-other-error and error-to-value transitions are announced and reported once each", async () => {
    configureReactiveDiagnostics({ development: false });
    try {
      const s = services();
      const vm = new Source(s);
      activate(vm);
      const rec = new Recorder(s.hub);
      vm.level = -1;
      assert.deepEqual(rec.take(), ["hub:source.level", "hub:source.reading", "hub:source.label"]);
      const first = await streamFed();
      assert.equal(first.length, 1);
      assert.match(String(first[0]), /bad level -1/);
      vm.level = -2;
      assert.deepEqual(rec.take(), ["hub:source.level", "hub:source.reading"], "label stays 'fault'");
      const second = await streamFed();
      assert.equal(second.length, 1);
      assert.match(String(second[0]), /bad level -2/);
      vm.calls = 0;
      assert.throws(() => vm.reading, /bad level -2/);
      assert.throws(() => vm.reading, /bad level -2/);
      assert.equal(vm.calls, 2, "an error is never memoized");
      assert.deepEqual(await streamFed(), [], "a direct read does not report");
      vm.level = 3;
      assert.deepEqual(rec.take(), ["hub:source.level", "hub:source.reading", "hub:source.label"]);
      assert.equal(vm.reading, 3);
    } finally {
      configureReactiveDiagnostics({ development: undefined });
    }
  });

  it("an effect re-run that throws is reported and stays active; a handler that throws does not loop", async () => {
    const s = services();
    const runs: number[] = [];
    const handled: number[] = [];
    class Effects extends ComponentVM {
      declare n: number;
      constructor() {
        super(base(s, "effects"));
        this.observable({ n: 0 });
        this.effect(() => {
          runs.push(this.n);
          if (this.n === 1) throw new Error("effect failed");
        });
        this.reaction(
          () => this.n,
          (value) => {
            handled.push(value);
            throw new Error("handler failed");
          },
        );
      }
    }
    const vm = new Effects();
    vm.construct();
    vm.n = 1;
    vm.n = 2;
    assert.deepEqual(runs, [0, 1, 2]);
    assert.deepEqual(handled, [1, 2]);
    const errors = (await streamFed()).map(String);
    assert.equal(errors.filter((e) => e.includes("effect failed")).length, 1);
    assert.equal(errors.filter((e) => e.includes("handler failed")).length, 2);
  });
});

describe("RSTATE-018 cycle detection", () => {
  it("a node read during its own evaluation throws ReactiveCycleError and the outer evaluation fails", () => {
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
    const vm = new Loop(services());
    activate(vm);
    assert.throws(() => vm.ping, ReactiveCycleError);
    assert.throws(() => vm.pong, ReactiveCycleError);
  });

  it("a memo that reads itself throws ReactiveCycleError", () => {
    class SelfMemo extends ComponentVM {
      readonly self: { readonly value: number } = this.memo((): number => this.self.value + 1);
      constructor(s: Services) {
        super(base(s, "self"));
      }
    }
    const vm = new SelfMemo(services());
    assert.throws(() => vm.self.value, ReactiveCycleError);
  });
});

describe("RSTATE-019 the development drain bound", () => {
  class Runaway extends ComponentVM {
    readonly go = this.signal(false);
    readonly count = this.signal(0);
    constructor(
      s: Services,
      readonly limit: number,
    ) {
      super(base(s, "runaway"));
      this.effect(() => {
        if (this.go.value && this.count.value < this.limit) this.count.value = this.count.value + 1;
      });
    }
  }

  it("an effect that writes what it reads overflows in development and names the repeating reaction", () => {
    const vm = new Runaway(services(), Number.POSITIVE_INFINITY);
    vm.construct();
    assert.throws(
      () => {
        vm.go.value = true;
      },
      (error: unknown) =>
        error instanceof ReactiveOverflowError && /Runaway\(runaway\):effect#\d+ x\d+/.test(error.message),
    );
    // The rest of the queue was abandoned; the graph still works.
    const before = vm.count.peek();
    vm.go.value = false;
    assert.equal(vm.count.peek(), before);
  });

  it("production builds have no bound", () => {
    configureReactiveDiagnostics({ development: false });
    try {
      const vm = new Runaway(services(), 12_000);
      vm.construct();
      vm.go.value = true;
      assert.equal(vm.count.peek(), 12_000);
    } finally {
      configureReactiveDiagnostics({ development: undefined });
    }
  });
});
