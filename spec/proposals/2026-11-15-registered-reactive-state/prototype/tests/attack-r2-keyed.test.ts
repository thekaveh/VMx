/**
 * Attack round 2: the keyed resource under key errors, manual loads while disabled, key writes made by observers of
 * the resource's own messages, and nested object keys.
 *
 * Expectations used: design goal V7 "loads when first enabled, reloads (latest wins) when the key changes, marks itself
 * outdated while disabled and reloads when enabled again"; R14.4 (rule 2: a key change while enabled
 * reloads; rule 6: a throwing key() keeps the previous key; "outdated" means only "the disable rule cancelled a load";
 * startedKey follows every entry into Loading).
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  AsyncResourceStatus,
  type AsyncResourceVM,
  ComponentVM,
  PropertyChangedMessage,
} from "@thekaveh/vmx";
import { shallowEqual } from "../src/index.js";
import { base, captureReports, deferred, type Services, services, streamFed, tick } from "./support.js";

function abortError(): Error {
  return Object.assign(new Error("aborted"), { name: "AbortError" });
}

class KeyedOwner extends ComponentVM {
  declare readonly topic: string;
  declare readonly hidden: boolean;
  readonly write;
  readonly loads: string[] = [];
  readonly pending = new Map<string, ReturnType<typeof deferred<string>>>();
  readonly query: AsyncResourceVM<string>;

  constructor(s: Services, autoLoad = true) {
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
      autoLoad,
    });
  }

  async finish(key: string): Promise<void> {
    this.pending.get(key)?.resolve(`data(${key})`);
    await tick();
  }
}

describe("attack-r2 keyed resource", () => {
  it("KD1 a key() that throws at the driver's first evaluation still loads once the key becomes valid", async () => {
    await streamFed();
    const s = services();
    class Lazy extends ComponentVM {
      declare ready: boolean;
      declare id: string;
      readonly loads: string[] = [];
      readonly query: AsyncResourceVM<string>;
      constructor() {
        super(base(s, "lazy"));
        this.observable({ ready: false, id: "a" });
        this.query = this.keyedResource({
          key: () => {
            if (!this.ready) throw new Error("no key yet");
            return this.id;
          },
          load: async (key) => {
            this.loads.push(key);
            return `data(${key})`;
          },
          autoLoad: true,
        });
      }
    }
    const vm = new Lazy();
    vm.construct();
    await tick();
    const statusBefore = vm.query.state.status;
    vm.ready = true;
    await tick();
    assert.deepEqual(
      { loads: vm.loads, status: vm.query.state.status },
      { loads: ["a"], status: AsyncResourceStatus.Ready },
      `before the key was valid the resource was ${statusBefore}`,
    );
    await streamFed();
  });

  it("KD2 a manual load while disabled clears 'outdated': enabling does not load the same key again", async () => {
    const vm = new KeyedOwner(services());
    vm.construct(); // autoLoad: load(t1) in flight
    vm.write({ hidden: true }); // the disable rule cancels it: outdated
    await tick();
    assert.equal(vm.query.state.status, AsyncResourceStatus.Idle);
    void vm.query.load(); // the user loads anyway (for example a "load while hidden" action)
    await vm.finish("t1");
    assert.equal(vm.query.state.status, AsyncResourceStatus.Ready);
    vm.write({ hidden: false });
    assert.deepEqual(vm.loads, ["t1", "t1"], "the fresh data for the same key was loaded again");
  });

  /** A normalization done by another part of the app when a load starts: t1 becomes t2. */
  function normalizeOnLoading(s: Services, vm: KeyedOwner): void {
    s.hub.messages.subscribe((m) => {
      if (
        m instanceof PropertyChangedMessage &&
        m.sender === vm.query &&
        m.propertyName === "state" &&
        vm.query.state.status === AsyncResourceStatus.Loading &&
        vm.topic === "t1"
      ) {
        vm.write({ topic: "t2" });
      }
    });
  }

  it("KD3 a key written by an observer of the Loading message of a driver-started load is loaded once, not twice", async () => {
    const s = services();
    const vm = new KeyedOwner(s, true);
    normalizeOnLoading(s, vm);
    vm.construct(); // autoLoad: the driver starts the load
    assert.deepEqual(vm.loads, ["t2"], "the first load already used the written key");
    await tick();
  });

  it("KD3c control: the same observer with a manual load made at top level loads once (expected to hold)", async () => {
    const s = services();
    const vm = new KeyedOwner(s, false);
    normalizeOnLoading(s, vm);
    vm.construct();
    void vm.query.load();
    assert.deepEqual(vm.loads, ["t2"]);
    await tick();
  });

  // Fix round 2 (R19.8): a reload caused only by a key difference, while the key is structurally
  // equal to the key of the last load, is reported once per class under any equality. The scenario and the loads are
  // unchanged; the expectation of the reports moved from the documented gap (none) to the resolved rule (one).
  it("KD4 an object key with a nested array reloads on every show under equals: shallowEqual, and development names the cause", async () => {
    const reports = captureReports();
    const s = services();
    class Filtered extends ComponentVM {
      declare readonly ids: readonly number[];
      declare readonly hidden: boolean;
      readonly write;
      readonly loads: string[] = [];
      constructor() {
        super(base(s, "filtered"));
        this.write = this.observable({ ids: [1, 2] as readonly number[], hidden: false });
        this.keyedResource({
          key: () => ({ ids: this.ids.map(String) }),
          enabled: () => !this.hidden,
          equals: shallowEqual,
          load: async (key) => {
            this.loads.push(key.ids.join(","));
            return key.ids.length;
          },
          autoLoad: true,
        });
      }
    }
    const vm = new Filtered();
    vm.construct();
    await tick();
    vm.write({ hidden: true });
    vm.write({ hidden: false });
    await tick();
    assert.deepEqual(vm.loads, ["1,2", "1,2"], "behavior is unchanged: the equality decides");
    assert.equal(reports.filter((report) => report.includes("structurally equal")).length, 1, reports.join("\n"));
  });

  // Spec gap: design goal V7 says the resource "marks itself outdated while disabled and reloads when enabled again";
  // R14.4 rule 4 (fix round 1; normative since fix round 2) narrows "outdated" to "a load in flight was cancelled". A
  // Ready resource that is hidden and shown again with the same key is never refreshed.
  it("KD6 GAP: a Ready resource that is hidden and shown with the same key is not reloaded", async () => {
    const vm = new KeyedOwner(services());
    vm.construct();
    await vm.finish("t1");
    vm.write({ hidden: true });
    vm.write({ hidden: false });
    assert.deepEqual(vm.loads, ["t1"], "current behavior: no refresh after the owner was hidden");
  });

  it("KD5 a key change while a manual load is in flight with the old key reloads with the new key (expected to hold)", async () => {
    const vm = new KeyedOwner(services(), false);
    vm.construct();
    void vm.query.load();
    vm.write({ topic: "t2" });
    assert.deepEqual(vm.loads, ["t1", "t2"]);
    await vm.finish("t1");
    assert.equal(vm.query.state.status, AsyncResourceStatus.Loading, "the superseded load is ignored");
    await vm.finish("t2");
    assert.equal(vm.query.state.status, AsyncResourceStatus.Ready);
  });
});
