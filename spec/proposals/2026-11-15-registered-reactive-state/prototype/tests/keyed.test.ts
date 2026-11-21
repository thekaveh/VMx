/**
 * RSTATE-033 and RSTATE-034: keyedResource, followKey, and the destruct and construct cycle (R14.*).
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  AsyncResourceStatus,
  AsyncResourceVM,
  ComponentVM,
  ConstructionStatus,
  type IDispatcher,
  type IMessageHub,
} from "@thekaveh/vmx";
import { activate, walk } from "../src/index.js";
import { base, deferred, Recorder, type Services, services, streamFed, tick } from "./support.js";

function abortError(): Error {
  return Object.assign(new Error("aborted"), { name: "AbortError" });
}

interface KeyedOwnerOptions {
  readonly autoLoad?: boolean;
  readonly cancelWhenDisabled?: boolean;
}

class KeyedOwner extends ComponentVM {
  declare readonly topic: string;
  declare readonly hidden: boolean;
  readonly write;
  readonly loads: string[] = [];
  readonly pending = new Map<string, ReturnType<typeof deferred<string>>>();
  readonly query: AsyncResourceVM<string>;

  constructor(s: Services, options: KeyedOwnerOptions = {}) {
    super(base(s, "owner"));
    this.write = this.observable({ topic: "t1", hidden: false });
    this.query = this.keyedResource({
      key: () => this.topic,
      enabled: () => !this.hidden,
      load: (key, signal) => {
        this.loads.push(key);
        const result = deferred<string>();
        this.pending.set(key, result);
        signal.addEventListener("abort", () => result.reject(abortError()));
        return result.promise;
      },
      ...options,
    });
    this.computed("statusText");
  }

  get statusText(): string {
    const state = this.query.state;
    return state.status === AsyncResourceStatus.Ready ? `ready:${state.value}` : state.status;
  }

  async finish(key: string): Promise<void> {
    this.pending.get(key)?.resolve(`data(${key})`);
    await tick();
  }
}

describe("RSTATE-033 keyedResource", () => {
  it("creates an AsyncResourceVM member with the owner's services and name", () => {
    const s = services();
    const vm = new KeyedOwner(s);
    assert.ok(vm.query instanceof AsyncResourceVM);
    assert.equal(vm.query.name, "owner:resource");
    assert.equal(vm.query.hub, vm.hub);
    assert.ok([...walk(vm)].includes(vm.query));
    vm.construct();
    assert.equal(vm.query.status, ConstructionStatus.Constructed);
    vm.dispose();
    assert.equal(vm.query.status, ConstructionStatus.Disposed);
  });

  it("autoLoad false: the first load stays on demand, then the key drives reloads, latest wins", async () => {
    const s = services();
    const vm = new KeyedOwner(s);
    vm.construct();
    assert.deepEqual(vm.loads, []);
    void vm.query.load();
    assert.deepEqual(vm.loads, ["t1"]);
    await vm.finish("t1");
    assert.equal(vm.statusText, "ready:data(t1)");
    vm.write({ topic: "t2" });
    vm.write({ topic: "t3" });
    assert.deepEqual(vm.loads, ["t1", "t2", "t3"]);
    await vm.finish("t2");
    assert.equal(vm.statusText, "Loading", "a superseded load is ignored");
    await vm.finish("t3");
    assert.equal(vm.statusText, "ready:data(t3)");
  });

  it("autoLoad true loads at construct; the resource state is tracked", async () => {
    const s = services();
    const vm = new KeyedOwner(s, { autoLoad: true });
    activate(vm);
    const rec = new Recorder(s.hub);
    vm.construct();
    assert.deepEqual(vm.loads, ["t1"]);
    await vm.finish("t1");
    assert.ok(rec.hubNames().includes("owner.statusText"));
    assert.equal(vm.statusText, "ready:data(t1)");
  });
});

describe("RSTATE-034 followKey and the destruct and construct cycle", () => {
  it("disabling cancels a load in flight and marks it outdated; enabling reloads it", async () => {
    const vm = new KeyedOwner(services(), { autoLoad: true });
    vm.construct();
    assert.equal(vm.query.state.status, AsyncResourceStatus.Loading);
    vm.write({ hidden: true });
    await tick();
    assert.equal(vm.query.state.status, AsyncResourceStatus.Idle);
    vm.write({ hidden: false });
    assert.deepEqual(vm.loads, ["t1", "t1"]);
  });

  it("a key change while disabled marks it outdated; enabling reloads with the new key", async () => {
    const vm = new KeyedOwner(services(), { autoLoad: true });
    vm.construct();
    await vm.finish("t1");
    vm.write({ hidden: true });
    vm.write({ topic: "t2" });
    assert.deepEqual(vm.loads, ["t1"]);
    vm.write({ hidden: false });
    assert.deepEqual(vm.loads, ["t1", "t2"]);
  });

  it("destruct cancels a load in flight; construct reloads it, and reloads when the key changed meanwhile", async () => {
    const vm = new KeyedOwner(services(), { autoLoad: true });
    vm.construct();
    vm.destruct();
    await tick();
    assert.equal(vm.query.state.status, AsyncResourceStatus.Idle);
    vm.construct();
    assert.deepEqual(vm.loads, ["t1", "t1"]);
    await vm.finish("t1");
    vm.destruct();
    vm.write({ topic: "t3" });
    assert.deepEqual(vm.loads, ["t1", "t1"], "a stopped driver does not follow the key");
    vm.construct();
    assert.deepEqual(vm.loads, ["t1", "t1", "t3"]);
  });

  it("an Error state reloads when enabled again; cancelWhenDisabled false keeps the load", async () => {
    const vm = new KeyedOwner(services(), { autoLoad: true });
    vm.construct();
    vm.pending.get("t1")?.reject(new Error("offline"));
    await tick();
    assert.equal(vm.query.state.status, AsyncResourceStatus.Error);
    vm.write({ hidden: true });
    vm.write({ hidden: false });
    assert.deepEqual(vm.loads, ["t1", "t1"]);

    const keep = new KeyedOwner(services(), { autoLoad: true, cancelWhenDisabled: false });
    keep.construct();
    keep.write({ hidden: true });
    await tick();
    assert.equal(keep.query.state.status, AsyncResourceStatus.Loading);
  });

  it("a throwing key keeps the previous key and is reported once", async () => {
    const s = services();
    class Fragile extends ComponentVM {
      declare readonly page: number;
      readonly write;
      readonly loads: number[] = [];
      readonly resource: AsyncResourceVM<number>;
      constructor() {
        super(base(s, "fragile"));
        this.write = this.observable({ page: 1 });
        this.resource = this.member(
          new AsyncResourceVM<number>({
            ...base(s, "resource"),
            loader: async () => {
              this.loads.push(this.page);
              return this.page;
            },
          }),
        );
        this.followKey(this.resource, {
          key: () => {
            if (this.page < 0) throw new Error("bad page");
            return this.page;
          },
          autoLoad: true,
        });
      }
    }
    const vm = new Fragile();
    vm.construct();
    await tick();
    vm.write({ page: -1 });
    vm.write({ page: -2 });
    vm.write({ page: 2 });
    await tick();
    assert.deepEqual(vm.loads, [1, 2]);
    const errors = (await streamFed()).map(String);
    assert.equal(errors.filter((error) => error.includes("bad page")).length, 1);
  });

  it("followKey drives a view-model that subclasses AsyncResourceVM (TypeScript only)", async () => {
    const s = services();
    interface PageOptions {
      readonly hub: IMessageHub;
      readonly dispatcher: IDispatcher;
    }
    class PageResource extends AsyncResourceVM<string> {
      declare readonly range: string;
      readonly write;
      readonly loads: string[] = [];
      constructor(o: PageOptions) {
        super({
          name: "page",
          hub: o.hub,
          dispatcher: o.dispatcher,
          loader: async () => {
            this.loads.push(this.range);
            return this.range;
          },
        });
        this.write = this.observable({ range: "a" });
        this.followKey(this, { key: () => this.range, autoLoad: true });
      }
    }
    const page = new PageResource(s);
    page.construct();
    await tick();
    page.write({ range: "b" });
    await tick();
    assert.deepEqual(page.loads, ["a", "b"]);
    assert.equal(page.state.status, AsyncResourceStatus.Ready);
  });
});
