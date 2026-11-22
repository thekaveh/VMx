/**
 * Attack round 1: the keyed resource under rapid key changes and disable/enable (R14.*; design goal V7:
 * "loads when first enabled, reloads (latest wins) when the key changes, marks itself outdated while disabled and
 * reloads when enabled again").
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
import { base, deferred, type Services, services, streamFed, tick } from "./support.js";

function abortError(): Error {
  return Object.assign(new Error("aborted"), { name: "AbortError" });
}

interface Load {
  readonly key: string;
  readonly resolve: (value: string) => void;
}

interface KeyedOwnerOptions {
  readonly autoLoad?: boolean;
  readonly cleanupValue?: (value: string) => void;
}

class KeyedOwner extends ComponentVM {
  declare readonly topic: string;
  declare readonly hidden: boolean;
  readonly write;
  readonly loads: Load[] = [];
  readonly query: AsyncResourceVM<string>;

  constructor(s: Services, options: KeyedOwnerOptions = { autoLoad: true }) {
    super(base(s, "owner"));
    this.write = this.observable({ topic: "t1", hidden: false });
    this.query = this.keyedResource({
      key: () => this.topic,
      enabled: () => !this.hidden,
      load: (key, signal) => {
        const result = deferred<string>();
        this.loads.push({ key, resolve: (value) => result.resolve(value) });
        signal.addEventListener("abort", () => result.reject(abortError()));
        return result.promise;
      },
      ...options,
    });
  }

  keys(): string[] {
    return this.loads.map((load) => load.key);
  }

  value(): string {
    const state = this.query.state;
    return state.status === AsyncResourceStatus.Ready ? state.value : state.status;
  }
}

describe("attack-r1 keyed resource: rapid key changes (expected to hold)", () => {
  it("KR1 two key changes inside one drain start one load, with the latest key", async () => {
    const s = services();
    const vm = new KeyedOwner(s);
    vm.construct();
    vm.loads[0]?.resolve("data(t1)");
    await tick();
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === vm && m.propertyName === "topic" && vm.topic === "t2") {
        vm.write({ topic: "t3" });
      }
    });
    vm.write({ topic: "t2" });
    assert.deepEqual(vm.keys(), ["t1", "t3"]);
  });

  it("KR2 superseded loads that resolve late, even after the latest one, never replace it; their values are cleaned up", async () => {
    const cleaned: string[] = [];
    const vm = new KeyedOwner(services(), { autoLoad: true, cleanupValue: (value) => cleaned.push(value) });
    vm.construct();
    vm.write({ topic: "t2" });
    vm.write({ topic: "t3" });
    assert.deepEqual(vm.keys(), ["t1", "t2", "t3"]);
    vm.loads[2]?.resolve("data(t3)");
    await tick();
    vm.loads[1]?.resolve("data(t2)");
    vm.loads[0]?.resolve("data(t1)");
    await tick();
    assert.equal(vm.value(), "data(t3)");
    assert.deepEqual(await streamFed(), []);
  });

  it("KR3 rapid hide/show while loading: each hide cancels, each show reloads; the last load wins", async () => {
    const vm = new KeyedOwner(services());
    vm.construct();
    vm.write({ hidden: true });
    vm.write({ hidden: false });
    vm.write({ hidden: true });
    vm.write({ hidden: false });
    assert.deepEqual(vm.keys(), ["t1", "t1", "t1"]);
    vm.loads[0]?.resolve("first");
    vm.loads[1]?.resolve("second");
    vm.loads[2]?.resolve("third");
    await tick();
    assert.equal(vm.value(), "third");
  });

  it("KR4 show and a key change in one patch start exactly one load, with the new key", async () => {
    const vm = new KeyedOwner(services());
    vm.construct();
    vm.loads[0]?.resolve("data(t1)");
    await tick();
    vm.write({ hidden: true });
    vm.write({ hidden: false, topic: "t2" });
    assert.deepEqual(vm.keys(), ["t1", "t2"]);
  });

  it("KR5 hide and a key change in one patch start no load; showing loads the new key", async () => {
    const vm = new KeyedOwner(services());
    vm.construct();
    vm.loads[0]?.resolve("data(t1)");
    await tick();
    vm.write({ hidden: true, topic: "t2" });
    assert.deepEqual(vm.keys(), ["t1"]);
    vm.write({ hidden: false });
    assert.deepEqual(vm.keys(), ["t1", "t2"]);
  });

  it("KR6 a hide and show inside one change scope is no change: no cancel, no reload", async () => {
    const vm = new KeyedOwner(services());
    vm.construct();
    vm.change(() => {
      vm.write({ hidden: true });
      vm.write({ hidden: false });
    });
    assert.deepEqual(vm.keys(), ["t1"]);
    assert.equal(vm.query.state.status, AsyncResourceStatus.Loading);
    vm.loads[0]?.resolve("data(t1)");
    await tick();
    assert.equal(vm.value(), "data(t1)");
  });

  it("KR7 after dispose, key writes start nothing and nothing is reported", async () => {
    await streamFed();
    const vm = new KeyedOwner(services());
    vm.construct();
    vm.dispose();
    vm.write({ topic: "t2" });
    vm.write({ hidden: true });
    vm.write({ hidden: false });
    await tick();
    assert.deepEqual(vm.keys(), ["t1"]);
    assert.deepEqual(await streamFed(), []);
  });
});

describe("attack-r1 keyed resource: spec gaps (document the behavior)", () => {
  it("KR8 GAP: an object key with the default equality reloads when another read of the driver changes", async () => {
    const s = services();
    class Paged extends ComponentVM {
      declare readonly page: number;
      declare readonly viewers: number;
      readonly write;
      readonly loads: number[] = [];
      constructor(equals: boolean) {
        super(base(s, "paged"));
        this.write = this.observable({ page: 1, viewers: 1 });
        this.keyedResource({
          key: () => ({ page: this.page }),
          enabled: () => this.viewers > 0,
          load: async (key) => {
            this.loads.push(key.page);
            return key.page;
          },
          autoLoad: true,
          ...(equals ? { equals: shallowEqual } : {}),
        });
      }
    }
    const loose = new Paged(false);
    const strict = new Paged(true);
    loose.construct();
    strict.construct();
    await tick();
    loose.write({ viewers: 2 }); // enabled stays true and the page is unchanged
    strict.write({ viewers: 2 });
    await tick();
    assert.deepEqual(loose.loads, [1, 1], "default Object.is: a spurious reload");
    assert.deepEqual(strict.loads, [1], "shallowEqual: no reload");
  });

  // Fix round 1 (R14.4): `outdated` is set only when the disable rule cancels a load; enabling compares the
  // key with the started key. The scenario is unchanged; the expectation moved from the documented gap.
  it("KR9 a key that changes and changes back while hidden does not reload on show", async () => {
    const vm = new KeyedOwner(services());
    vm.construct();
    vm.loads[0]?.resolve("data(t1)");
    await tick();
    vm.write({ hidden: true });
    vm.write({ topic: "t2" });
    vm.write({ topic: "t1" });
    vm.write({ hidden: false });
    assert.deepEqual(vm.keys(), ["t1"]);
    assert.equal(vm.value(), "data(t1)");
  });

  it("KR9b a load cancelled by hiding still reloads on show, also after a key round trip", async () => {
    const vm = new KeyedOwner(services());
    vm.construct();
    vm.write({ hidden: true }); // cancels the t1 load in flight
    vm.write({ topic: "t2" });
    vm.write({ topic: "t1" });
    vm.write({ hidden: false });
    assert.deepEqual(vm.keys(), ["t1", "t1"]);
    vm.loads[1]?.resolve("data(t1)");
    await tick();
    assert.equal(vm.value(), "data(t1)");
  });
});
