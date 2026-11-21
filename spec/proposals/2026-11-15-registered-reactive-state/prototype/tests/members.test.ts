/**
 * RSTATE-024 to RSTATE-026: member injection and refusals, member lifecycle and late registration, members in
 * walks.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  AggregateVM1,
  ComponentVM,
  CompositeVM,
  ConstructionStatus,
  type IDispatcher,
  type IMessageHub,
  RxDispatcher,
} from "@thekaveh/vmx";
import { find, walk } from "../src/index.js";
import { base, Recorder, type Services, services } from "./support.js";

interface LeafOptions {
  readonly hub: IMessageHub;
  readonly dispatcher: IDispatcher;
  readonly key: string;
  readonly log?: string[];
  readonly failConstruct?: boolean;
  readonly failDestruct?: boolean;
}

class Leaf extends ComponentVM {
  readonly dispatcher: IDispatcher;
  readonly #o: LeafOptions;
  constructor(o: LeafOptions) {
    super({ name: o.key, hint: "", hub: o.hub, dispatcher: o.dispatcher });
    this.dispatcher = o.dispatcher;
    this.#o = o;
  }
  protected override _onConstruct(): void {
    this.#o.log?.push(`construct:${this.name}`);
    if (this.#o.failConstruct === true) throw new Error(`${this.name} construct failed`);
  }
  protected override _onDestruct(): void {
    this.#o.log?.push(`destruct:${this.name}`);
    if (this.#o.failDestruct === true) throw new Error(`${this.name} destruct failed`);
  }
  protected override _onDispose(): void {
    this.#o.log?.push(`dispose:${this.name}`);
  }
}

class Owner extends ComponentVM {
  readonly log: string[];
  readonly first: Leaf;
  readonly second: Leaf;
  constructor(s: Services, log: string[], options: { readonly secondFails?: boolean } = {}) {
    super(base(s, "owner"));
    this.log = log;
    this.first = this.member(Leaf, { key: "first", log });
    this.second = this.member(Leaf, {
      key: "second",
      log,
      ...(options.secondFails === true ? { failConstruct: true } : {}),
    });
    this.effect(() => {
      log.push("effect:start");
      return () => log.push("effect:stop");
    });
  }
  protected override _onConstruct(): void {
    this.log.push("construct:owner");
  }
  protected override _onDestruct(): void {
    this.log.push("destruct:owner");
  }
  protected override _onDispose(): void {
    this.log.push("dispose:owner");
  }
}

describe("RSTATE-024 member injection and refusals; containers refuse owned VMs", () => {
  it("member(Type, options) injects the owner's hub and dispatcher", () => {
    const s = { hub: services().hub, dispatcher: RxDispatcher.immediate() };
    const owner = new Owner(s, []);
    assert.equal(owner.first.hub, owner.hub);
    assert.equal(owner.first.dispatcher, s.dispatcher);
  });

  it("refuses the owner itself, a VM with another owner, a container child and an owner cycle", () => {
    const s = services();
    const a = new Owner(s, []);
    const b = new Owner(s, []);
    assert.throws(() => a.member(a), /its own member/);
    assert.throws(() => b.member(a.first), /already has an owner/);
    const container = new CompositeVM<Leaf>(base(s, "container"));
    const child = new Leaf({ ...s, key: "child" });
    container.add(child);
    assert.throws(() => a.member(child), /container parent/);
    assert.throws(() => a.first.member(a), /owner cycle/);
    assert.equal(a.member(a.first), a.first, "registering the same member again returns it");
  });

  it("a container refuses to add an owned VM before it changes anything", () => {
    const s = services();
    const owner = new Owner(s, []);
    const container = new CompositeVM<Leaf>(base(s, "container"));
    assert.throws(() => container.add(owner.first), /member of 'owner'/);
    assert.equal(container.count, 0);
    assert.equal(owner.first._parent, null);
  });
});

describe("RSTATE-025 member lifecycle and late registration", () => {
  // Fix round 1 (R13.2): the members are destructed in reverse order before the owner's _onDestruct
  // (design goal V4, attack L3). Fix round 2: destruct is the mirror of construct, so the reactions stop first, before
  // the members (attack LC1 to LC3), and dispose tears them down before the members too. The scenario is unchanged;
  // "effect:stop" moved from the end of both logs to their start.
  it("construct: _onConstruct, members in order, reactions, Constructed; destruct: reactions, members in reverse, _onDestruct; dispose", () => {
    const s = services();
    const log: string[] = [];
    const owner = new Owner(s, log);
    const rec = new Recorder(s.hub, { status: true });
    owner.construct();
    assert.deepEqual(log, ["construct:owner", "construct:first", "construct:second", "effect:start"]);
    const constructed = rec.take().filter((event) => event.endsWith(String(ConstructionStatus.Constructed)));
    assert.deepEqual(constructed, ["status:first.4", "status:second.4", "status:owner.4"]);
    log.length = 0;
    owner.destruct();
    assert.deepEqual(log, ["effect:stop", "destruct:second", "destruct:first", "destruct:owner"]);
    owner.construct();
    log.length = 0;
    owner.dispose();
    assert.deepEqual(log, ["effect:stop", "dispose:first", "dispose:second", "dispose:owner"]);
    const disposed = rec.take().filter((event) => event.endsWith(`.${String(ConstructionStatus.Disposed)}`));
    assert.deepEqual(disposed, ["status:first.0", "status:second.0", "status:owner.0"]);
  });

  it("a member that fails rolls the owner back; members that constructed stay Constructed", () => {
    const s = services();
    const log: string[] = [];
    const owner = new Owner(s, log, { secondFails: true });
    assert.throws(() => owner.construct(), /second construct failed/);
    assert.equal(owner.status, ConstructionStatus.Destructed);
    assert.equal(owner.first.status, ConstructionStatus.Constructed);
    assert.equal(owner.second.status, ConstructionStatus.Destructed);
    assert.ok(!log.includes("effect:start"), "reactions did not start");
  });

  it("late registration follows the owner's status", () => {
    const s = services();
    const log: string[] = [];
    const owner = new Owner(s, log);
    const waiting = owner.member(new Leaf({ ...s, key: "waiting", log }));
    assert.equal(waiting.status, ConstructionStatus.Destructed);
    owner.construct();
    assert.equal(waiting.status, ConstructionStatus.Constructed);
    const immediate = owner.member(new Leaf({ ...s, key: "immediate", log }));
    assert.equal(immediate.status, ConstructionStatus.Constructed);
    const failing = new Leaf({ ...s, key: "failing", log, failConstruct: true });
    assert.throws(() => owner.member(failing), /failing construct failed/);
    owner.dispose();
    assert.equal(failing.status, ConstructionStatus.Disposed, "it stayed registered");
    const afterDispose = owner.member(new Leaf({ ...s, key: "afterDispose", log }));
    assert.equal(afterDispose.status, ConstructionStatus.Disposed);
  });

  // Fix round 2 (R11.5): a member that reaches Disposed leaves its owner's member list, so the owner
  // keeps no reference to it (attack DD1). The scenario and the construct log are unchanged; the walk assertion moved
  // from "still visited" to "no longer visited".
  it("a member disposed early leaves the member list: the walks and the lifecycle skip it", () => {
    const s = services();
    const log: string[] = [];
    const owner = new Owner(s, log);
    owner.first.dispose();
    log.length = 0;
    owner.construct();
    assert.deepEqual(log, ["construct:owner", "construct:second", "effect:start"]);
    assert.ok(![...walk(owner)].includes(owner.first));
  });
});

describe("RSTATE-026 members in walks", () => {
  it("walk visits container children first, then members in registration order, depth-first", () => {
    const s = services();
    class Holder extends CompositeVM<Leaf> {
      readonly extra: Leaf;
      constructor() {
        super(base(s, "holder"));
        this.add(new Leaf({ ...s, key: "child" }));
        this.extra = this.member(new Leaf({ ...s, key: "extra" }));
        this.extra.member(new Leaf({ ...s, key: "nested" }));
      }
    }
    const holder = new Holder();
    assert.deepEqual(
      [...walk(holder)].map((vm) => vm.name),
      ["holder", "child", "extra", "nested"],
    );
    assert.equal(find(holder, (vm) => vm.name === "nested")?.name, "nested");
  });

  it("a member that a hand-written components() already yields is visited once", () => {
    const s = services();
    class Item extends ComponentVM {
      readonly left: Leaf;
      readonly right: Leaf;
      constructor() {
        super(base(s, "item"));
        this.left = this.member(new Leaf({ ...s, key: "left" }));
        this.right = this.member(new Leaf({ ...s, key: "right" }));
      }
      components(): readonly Leaf[] {
        return [this.left];
      }
    }
    assert.deepEqual(
      [...walk(new Item())].map((vm) => vm.name),
      ["item", "left", "right"],
    );
  });

  it("an aggregate's slots come before its members", () => {
    const s = services();
    const aggregate = new AggregateVM1<Leaf>({ ...base(s, "aggregate"), factory1: () => new Leaf({ ...s, key: "slot" }) });
    aggregate.construct();
    aggregate.member(new Leaf({ ...s, key: "other" }));
    assert.deepEqual(
      [...walk(aggregate)].map((vm) => vm.name),
      ["aggregate", "slot", "other"],
    );
  });
});
