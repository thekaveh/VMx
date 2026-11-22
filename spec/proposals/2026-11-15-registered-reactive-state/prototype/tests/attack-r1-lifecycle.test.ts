/**
 * Attack round 1: members constructed or destructed out of order, and registrations made during a transition.
 *
 * Expectations: design goal V4 "`this.member(vm)`: owned; constructed after the owner's construct and destructed
 * (reverse order) before the owner's destruct"; R11.4 "Late registration: Constructed owner constructs the
 * member at once ...; Constructing joins the walk"; design goal V6 "Effects run only while the VM is Constructed".
 * VMx precedent: CompositeVMBase._onDestruct destructs the children first and runs super._onDestruct() after them
 * (3.31.0 compositeVMBase.ts:665-677; the `_transitionChildren` example in componentVMBase.ts:1165-1167).
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, CompositeVM, ConstructionStatus } from "@thekaveh/vmx";
import { untracked } from "../src/index.js";
import { base, type Services, services, streamFed } from "./support.js";

class Leaf extends ComponentVM {
  constructor(
    s: Services,
    name: string,
    readonly log: string[],
    readonly onDestruct: () => void = () => undefined,
  ) {
    super(base(s, name));
  }
  protected override _onConstruct(): void {
    this.log.push(`construct:${this.name}`);
  }
  protected override _onDestruct(): void {
    this.log.push(`destruct:${this.name}`);
    this.onDestruct();
  }
}

describe("attack-r1 lifecycle: registration during a transition", () => {
  it("L1a a member registered by an effect's first run at construct is Constructed when the owner is", () => {
    const s = services();
    class Host extends ComponentVM {
      child: ComponentVM | null = null;
      constructor() {
        super(base(s, "host"));
        this.effect(() => {
          if (this.child === null) this.child = this.member(new ComponentVM(base(s, "late")));
        });
      }
    }
    const host = new Host();
    host.construct();
    assert.equal(host.status, ConstructionStatus.Constructed);
    assert.equal(host.child?.status, ConstructionStatus.Constructed);
  });

  it("L1b a member registered by a whileConstructed setup is Constructed when the owner is", () => {
    const s = services();
    class Host extends ComponentVM {
      child: ComponentVM | null = null;
      constructor() {
        super(base(s, "host"));
        this.whileConstructed(() => {
          this.child ??= this.member(new ComponentVM(base(s, "late")));
        });
      }
    }
    const host = new Host();
    host.construct();
    assert.equal(host.child?.status, ConstructionStatus.Constructed);
  });

  it("L1c control: the same registration in _onConstruct of an instrumented VM joins the walk", () => {
    const s = services();
    class Host extends ComponentVM {
      child: ComponentVM | null = null;
      constructor() {
        super(base(s, "host"));
        this.observable({});
      }
      protected override _onConstruct(): void {
        this.child ??= this.member(new ComponentVM(base(s, "late")));
      }
    }
    const host = new Host();
    host.construct();
    assert.equal(host.child?.status, ConstructionStatus.Constructed);
  });

  it("L1d a VM whose first registration is member() inside its own _onConstruct constructs that member with it", () => {
    const s = services();
    class Host extends ComponentVM {
      child: ComponentVM | null = null;
      constructor() {
        super(base(s, "host"));
      }
      protected override _onConstruct(): void {
        this.child ??= this.member(new ComponentVM(base(s, "late")));
      }
    }
    const host = new Host();
    host.construct();
    assert.equal(host.status, ConstructionStatus.Constructed);
    assert.equal(host.child?.status, ConstructionStatus.Constructed);
  });

  it("L2 an effect registered inside _onDestruct does not run while the VM is Destructing", () => {
    const s = services();
    const runs: string[] = [];
    let registered = false;
    class Host extends ComponentVM {
      constructor() {
        super(base(s, "host"));
        // Instrument the VM (any registration installs the hooks).
        this.observable({});
      }
      protected override _onDestruct(): void {
        if (registered) return;
        registered = true;
        this.effect(() => {
          runs.push(ConstructionStatus[untracked(() => this.status)]);
        });
      }
    }
    const host = new Host();
    host.construct();
    host.destruct();
    assert.deepEqual(runs, [], "an effect ran during destruct");
  });
});

describe("attack-r1 lifecycle: library calls made inside an effect add no hidden dependency", () => {
  class Item extends ComponentVM {
    declare done: boolean;
    constructor(s: Services, name: string) {
      super(base(s, name));
      this.observable({ done: false });
    }
  }

  it("T1a an effect that disposes a VM it read runs once per cause (no dependency on that VM's status)", () => {
    const s = services();
    const item = new Item(s, "item");
    class Host extends ComponentVM {
      runs = 0;
      constructor() {
        super(base(s, "host"));
        this.effect(() => {
          this.runs += 1;
          if (item.done) item.dispose();
        });
      }
    }
    const host = new Host();
    host.construct();
    item.done = true;
    assert.equal(host.runs, 2, "the first run, then the run caused by `done`");
  });

  it("T1b an effect that constructs a child with a member runs once, reports nothing, and ignores the child's later destruct", async () => {
    await streamFed();
    const s = services();
    class Child extends ComponentVM {
      readonly leaf = new ComponentVM(base(s, "leaf"));
      constructor() {
        super(base(s, "child"));
        this.member(this.leaf);
      }
    }
    class Owner extends ComponentVM {
      declare open: boolean;
      runs = 0;
      readonly child = new Child();
      constructor() {
        super(base(s, "owner"));
        this.observable({ open: true });
        this.effect(() => {
          this.runs += 1;
          if (this.open) this.child.construct();
        });
      }
    }
    const owner = new Owner();
    owner.construct();
    const runsAfterConstruct = owner.runs;
    owner.child.destruct();
    const reported = (await streamFed()).map(String);
    assert.deepEqual(
      { runsAfterConstruct, runsAfterDestruct: owner.runs, child: ConstructionStatus[owner.child.status], reported },
      { runsAfterConstruct: 1, runsAfterDestruct: 1, child: "Destructed", reported: [] },
    );
  });

  it("T1c an effect that registers a member on its first run is not run again by the owner's Constructed transition", () => {
    const s = services();
    class Host extends ComponentVM {
      declare mode: string;
      readonly runs: string[] = [];
      child: ComponentVM | null = null;
      constructor() {
        super(base(s, "host"));
        this.observable({ mode: "a" });
        this.effect(() => {
          this.runs.push(`${this.mode}@${ConstructionStatus[untracked(() => this.status)]}`);
          if (this.mode === "a" && this.child === null) this.child = this.member(new ComponentVM(base(s, "a")));
        });
      }
    }
    const host = new Host();
    host.construct();
    assert.deepEqual(host.runs, ["a@Constructing"]);
  });

  it("T1d an effect that adds an instrumented child to a container does not follow that child's status", () => {
    const s = services();
    class Row extends ComponentVM {
      constructor(name: string) {
        super(base(s, name));
        this.observable({});
      }
    }
    class Host extends ComponentVM {
      declare go: boolean;
      runs = 0;
      readonly list = new CompositeVM<Row>(base(s, "list"));
      constructor() {
        super(base(s, "host"));
        this.observable({ go: false });
        this.effect(() => {
          this.runs += 1;
          if (this.go && this.list.count === 0) this.list.add(new Row("row"));
        });
      }
    }
    const host = new Host();
    host.construct();
    host.go = true;
    const runs = host.runs;
    host.list.construct();
    assert.equal(runs, 2);
    assert.equal(host.runs, 2, "the container's construct of the row re-ran the effect");
  });

  it("T2 an effect that reads isConstructed never runs while the VM is Destructing", () => {
    const s = services();
    const seen: string[] = [];
    class Host extends ComponentVM {
      constructor() {
        super(base(s, "host"));
        this.effect(() => {
          const constructed = this.isConstructed;
          seen.push(`${String(constructed)}@${ConstructionStatus[untracked(() => this.status)]}`);
        });
      }
    }
    const host = new Host();
    host.construct();
    host.destruct();
    assert.ok(!seen.some((entry) => entry.endsWith("@Destructing")), `runs: ${seen.join(", ")}`);
  });
});

describe("attack-r1 lifecycle: member order", () => {
  function owner(s: Services, log: string[], connection: { open: boolean }): ComponentVM {
    class Owner extends ComponentVM {
      constructor() {
        super(base(s, "owner"));
        this.member(new Leaf(s, "first", log));
        this.member(
          new Leaf(s, "second", log, () => {
            // A member that uses an owner resource during its own destruct.
            if (!connection.open) throw new Error("second used the owner's connection after the owner closed it");
          }),
        );
      }
      protected override _onConstruct(): void {
        connection.open = true;
        log.push("construct:owner");
      }
      protected override _onDestruct(): void {
        connection.open = false;
        log.push("destruct:owner");
      }
    }
    return new Owner();
  }

  it("L3 members are destructed in reverse order before the owner's _onDestruct (mirror of construct)", () => {
    const s = services();
    const log: string[] = [];
    const vm = owner(s, log, { open: false });
    vm.construct();
    assert.deepEqual(log, ["construct:owner", "construct:first", "construct:second"]);
    log.length = 0;
    let error: unknown = null;
    try {
      vm.destruct();
    } catch (caught) {
      error = caught;
    }
    assert.deepEqual(log.slice(0, 3), ["destruct:second", "destruct:first", "destruct:owner"], String(error));
    assert.equal(error, null);
    assert.equal(vm.status, ConstructionStatus.Destructed);
  });

  it("L4 a member constructed before its owner is not constructed again; the owner's destruct destructs it (expected to hold)", () => {
    const s = services();
    const log: string[] = [];
    const early = new Leaf(s, "early", log);
    class Owner extends ComponentVM {
      constructor() {
        super(base(s, "owner"));
        this.member(early);
      }
    }
    const vm = new Owner();
    early.construct();
    vm.construct();
    vm.destruct();
    vm.construct();
    assert.deepEqual(log, ["construct:early", "destruct:early", "construct:early"]);
  });

  it("L5 a member destructed on its own while the owner is Constructed is skipped by the owner's destruct and rebuilt by its construct (expected to hold)", () => {
    const s = services();
    const log: string[] = [];
    const member = new Leaf(s, "member", log);
    class Owner extends ComponentVM {
      constructor() {
        super(base(s, "owner"));
        this.member(member);
      }
    }
    const vm = new Owner();
    vm.construct();
    member.destruct();
    vm.destruct();
    vm.construct();
    assert.deepEqual(log, ["construct:member", "destruct:member", "construct:member"]);
    assert.equal(member.status, ConstructionStatus.Constructed);
  });

  it("L6 dispose from Constructed runs no _onDestruct of the owner or its members, and tears reactions down (expected to hold)", () => {
    const s = services();
    const log: string[] = [];
    class Owner extends ComponentVM {
      constructor() {
        super(base(s, "owner"));
        this.member(new Leaf(s, "member", log));
        this.whileConstructed(() => () => log.push("teardown"));
      }
      protected override _onDestruct(): void {
        log.push("destruct:owner");
      }
    }
    const vm = new Owner();
    vm.construct();
    log.length = 0;
    vm.dispose();
    assert.deepEqual(log, ["teardown"]);
  });

  it("L7 nested construct order: owner hook, member A (hook, effect), member B (hook, effect), owner effect (expected to hold)", () => {
    const s = services();
    const log: string[] = [];
    class Part extends ComponentVM {
      constructor(name: string) {
        super(base(s, name));
        this.effect(() => {
          log.push(`effect:${this.name}`);
        });
      }
      protected override _onConstruct(): void {
        log.push(`construct:${this.name}`);
      }
    }
    class Owner extends ComponentVM {
      constructor() {
        super(base(s, "owner"));
        this.member(new Part("a"));
        this.member(new Part("b"));
        this.effect(() => {
          log.push("effect:owner");
        });
      }
      protected override _onConstruct(): void {
        log.push("construct:owner");
      }
    }
    new Owner().construct();
    assert.deepEqual(log, ["construct:owner", "construct:a", "effect:a", "construct:b", "effect:b", "effect:owner"]);
  });
});
