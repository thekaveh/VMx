/**
 * RSTATE-027 to RSTATE-031: the reaction scope, effect, reaction, alive reactions, and construct and destruct
 * failures with reactions.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, ConstructionStatus } from "@thekaveh/vmx";
import { Subject } from "rxjs";
import { activate, untracked } from "../src/index.js";
import { base, type Services, services, streamFed } from "./support.js";

class Host extends ComponentVM {
  declare n: number;
  readonly log: string[] = [];
  constructor(s: Services, name = "host") {
    super(base(s, name));
    this.observable({ n: 0 });
  }
}

describe("RSTATE-027 the reaction scope and registration timing", () => {
  it("a reaction registered in the constructor starts at construct, not before", () => {
    const vm = new Host(services());
    vm.effect(() => {
      vm.log.push(`effect:${String(vm.n)}`);
    });
    vm.n = 1;
    assert.deepEqual(vm.log, []);
    vm.construct();
    assert.deepEqual(vm.log, ["effect:1"]);
  });

  it("registered while constructed it starts at once; while destructed at the next construct; after disposal never", () => {
    const vm = new Host(services());
    vm.construct();
    vm.effect(() => {
      vm.log.push(`now:${String(vm.n)}`);
    });
    assert.deepEqual(vm.log, ["now:0"]);
    vm.destruct();
    vm.effect(() => {
      vm.log.push(`later:${String(vm.n)}`);
    });
    assert.deepEqual(vm.log, ["now:0"]);
    vm.construct();
    assert.deepEqual(vm.log, ["now:0", "now:0", "later:0"]);
    vm.dispose();
    vm.effect(() => {
      vm.log.push("never");
    });
    assert.ok(!vm.log.includes("never"));
  });
});

describe("RSTATE-028 effect", () => {
  it("runs at start, re-runs after its cleanup when a dependency changes, cleans up at stop; may write", () => {
    const vm = new Host(services());
    const mirror = vm.signal(0);
    vm.effect(() => {
      const n = vm.n;
      vm.log.push(`run:${String(n)}`);
      mirror.value = n * 10;
      return () => vm.log.push(`cleanup:${String(n)}`);
    });
    vm.construct();
    vm.n = 1;
    assert.equal(mirror.peek(), 10);
    vm.destruct();
    vm.n = 2;
    assert.deepEqual(vm.log, ["run:0", "cleanup:0", "run:1", "cleanup:1"]);
    vm.construct();
    assert.deepEqual(vm.log.slice(4), ["run:2"]);
    assert.equal(mirror.peek(), 20);
  });

  it("effects run only while constructed", () => {
    const vm = new Host(services());
    vm.effect(() => {
      // The status is a native node; read untracked, it does not make the effect re-run on transitions.
      vm.log.push(`run:${String(vm.n)}@${untracked(() => ConstructionStatus[vm.status])}`);
    });
    vm.n = 1;
    vm.construct();
    vm.n = 2;
    vm.destruct();
    vm.n = 3;
    assert.deepEqual(vm.log, ["run:1@Constructing", "run:2@Constructed"]);
  });
});

describe("RSTATE-029 reaction, including immediate and previous", () => {
  it("delivers (value, previous) for changes by equals; a restart takes a new baseline", () => {
    const vm = new Host(services());
    vm.reaction(
      () => vm.n % 10,
      (value, previous) => vm.log.push(`${String(previous)}->${String(value)}`),
    );
    vm.construct();
    vm.n = 1;
    vm.n = 11;
    vm.n = 2;
    vm.destruct();
    vm.n = 3;
    vm.construct();
    vm.n = 4;
    assert.deepEqual(vm.log, ["0->1", "1->2", "3->4"]);
  });

  it("with immediate it also runs at each start; previous is the last value delivered before the stop", () => {
    const vm = new Host(services());
    vm.reaction(
      () => vm.n,
      (value, previous) => vm.log.push(`${String(previous)}->${String(value)}`),
      { immediate: true, equals: (a, b) => a === b },
    );
    vm.construct();
    vm.n = 5;
    vm.destruct();
    vm.n = 7;
    vm.construct();
    assert.deepEqual(vm.log, ["0->0", "0->5", "5->7"]);
  });
});

describe("RSTATE-030 alive reactions", () => {
  it("run from activation in every status but Disposed, without an immediate run", () => {
    const vm = new Host(services());
    vm.reaction(
      () => vm.n,
      (value) => vm.log.push(`alive:${String(value)}@${ConstructionStatus[vm.status]}`),
      { alive: true, immediate: true },
    );
    vm.n = 1;
    assert.deepEqual(vm.log, [], "not active before activation");
    activate(vm);
    vm.n = 2;
    vm.construct();
    vm.destruct();
    vm.n = 3;
    vm.dispose();
    vm.n = 4;
    assert.deepEqual(vm.log, ["alive:2@Destructed", "alive:3@Destructed"]);
  });
});

describe("RSTATE-031 construct and destruct failures with reactions", () => {
  it("a throwing setup stops the started reactions in reverse order and rolls the construct back", () => {
    const vm = new Host(services());
    vm.whileConstructed(() => {
      vm.log.push("setup:a");
      return () => vm.log.push("teardown:a");
    });
    vm.whileConstructed(() => {
      vm.log.push("setup:b");
      return () => vm.log.push("teardown:b");
    });
    vm.whileConstructed(() => {
      throw new Error("setup failed");
    });
    assert.throws(() => vm.construct(), /setup failed/);
    assert.equal(vm.status, ConstructionStatus.Destructed);
    assert.deepEqual(vm.log, ["setup:a", "setup:b", "teardown:b", "teardown:a"]);
  });

  it("a throwing _onDestruct rolls back to Constructed and resumes the paused reactions once", () => {
    const s = services();
    class Stubborn extends Host {
      fail = true;
      protected override _onDestruct(): void {
        this.n = 42;
        if (this.fail) throw new Error("destruct failed");
      }
    }
    const vm = new Stubborn(s);
    vm.effect(() => {
      vm.log.push(`effect:${String(vm.n)}@${untracked(() => ConstructionStatus[vm.status])}`);
    });
    vm.construct();
    assert.throws(() => vm.destruct(), /destruct failed/);
    assert.equal(vm.status, ConstructionStatus.Constructed);
    assert.deepEqual(vm.log, ["effect:0@Constructing", "effect:42@Constructed"]);
    vm.n = 43;
    assert.deepEqual(vm.log.slice(2), ["effect:43@Constructed"]);
  });

  it("a member that fails to destruct restarts the reactions and rolls back to Constructed", () => {
    const s = services();
    const vm = new Host(s);
    class Fragile extends ComponentVM {
      protected override _onDestruct(): void {
        throw new Error("member destruct failed");
      }
    }
    vm.member(new Fragile(base(s, "fragile")));
    const raw = new Subject<number>();
    vm.whileConstructed(() => raw.subscribe((value) => vm.log.push(`raw:${String(value)}`)));
    vm.construct();
    raw.next(1);
    assert.throws(() => vm.destruct(), /member destruct failed/);
    assert.equal(vm.status, ConstructionStatus.Constructed);
    raw.next(2);
    assert.deepEqual(vm.log, ["raw:1", "raw:2"]);
  });

  it("an effect's first run that throws fails the construct; a setup failure on re-start is reported", async () => {
    const vm = new Host(services());
    vm.effect(() => {
      if (vm.n === 0) throw new Error("first run failed");
    });
    assert.throws(() => vm.construct(), /first run failed/);
    assert.equal(vm.status, ConstructionStatus.Destructed);
    vm.n = 1;
    vm.construct();
    assert.equal(vm.status, ConstructionStatus.Constructed);
    assert.deepEqual(await streamFed(), []);
  });
});
