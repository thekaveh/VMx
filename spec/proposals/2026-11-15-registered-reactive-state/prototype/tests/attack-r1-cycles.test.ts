/**
 * Attack round 1: cycles between computed properties (R16: "A node read during its own evaluation throws
 * ReactiveCycleError"), including cycles closed through a command predicate and cycles that open and close again.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, PropertyChangedMessage } from "@thekaveh/vmx";
import { activate, configureReactiveDiagnostics, ReactiveCycleError } from "../src/index.js";
import { base, type Services, services, streamFed } from "./support.js";

function quietly<T>(fn: () => T): T {
  configureReactiveDiagnostics({ development: false });
  try {
    return fn();
  } finally {
    configureReactiveDiagnostics({ development: undefined });
  }
}

function hubNames(s: Services): string[] {
  const names: string[] = [];
  s.hub.messages.subscribe((m) => {
    if (m instanceof PropertyChangedMessage) names.push(`${m.senderName}.${m.propertyName}`);
  });
  return names;
}

describe("attack-r1 cycles", () => {
  it("C1 a cycle between a computed and a command predicate surfaces as ReactiveCycleError, not a silent false", async () => {
    await streamFed();
    const s = services();
    class Sharer extends ComponentVM {
      declare enabled: boolean;
      readonly shareCommand = this.relayCommand(
        () => undefined,
        () => this.enabled && this.showsShare,
      );
      constructor() {
        super(base(s, "sharer"));
        this.observable({ enabled: true });
        this.computed("showsShare");
      }
      get showsShare(): boolean {
        return this.shareCommand.canExecute();
      }
    }
    const vm = new Sharer();
    activate(vm);
    let thrown: unknown = null;
    let value: boolean | undefined;
    try {
      value = vm.showsShare;
    } catch (error) {
      thrown = error;
    }
    vm.enabled = false;
    vm.enabled = true;
    const reported = await streamFed();
    const surfaced = thrown instanceof ReactiveCycleError || reported.some((error) => error instanceof ReactiveCycleError);
    assert.ok(
      surfaced,
      `showsShare read ${String(value)}; thrown: ${String(thrown)}; reported: [${reported.map(String).join(" | ")}]`,
    );
  });

  it("C2 after a transient cycle is broken, every node of the cycle recovers and is announced", async () => {
    await streamFed();
    const s = services();
    class A extends ComponentVM {
      declare flag: boolean;
      declare fallback: number;
      declare bx: number;
      readonly write;
      other: B | null = null;
      constructor() {
        super(base(s, "a"));
        this.write = this.observable({ flag: false, fallback: 0, bx: 0 });
        this.computed("c");
      }
      get c(): number {
        return this.flag && this.other !== null ? this.other.d : this.fallback;
      }
    }
    class B extends ComponentVM {
      constructor(readonly a: A) {
        super(base(s, "b"));
        this.computed("d");
      }
      get d(): number {
        return this.a.bx + this.a.c + 1;
      }
    }
    quietly(() => {
      const a = new A();
      const b = new B(a);
      a.other = b;
      activate(a);
      activate(b);
      const names = hubNames(s);
      // One write closes the cycle (flag) and dirties the inner node directly (bx).
      a.write({ flag: true, bx: 1 });
      // Order not asserted: after the failed evaluation b.d has the lower height, so it is announced first.
      assert.deepEqual([...names].sort(), ["a.bx", "a.c", "a.flag", "b.d"], "both enter error state");
      names.length = 0;
      // The cycle is broken: a.c = fallback = 0, so b.d = 1 + 0 + 1 = 2.
      a.write({ flag: false });
      assert.deepEqual(names, ["a.flag", "a.c", "b.d"], "b.d must leave its error state and be announced");
      names.length = 0;
      a.write({ fallback: 5 });
      assert.deepEqual(names, ["a.fallback", "a.c", "b.d"], "b.d must still depend on a.c");
      assert.equal(b.d, 7);
    });
    const reported = await streamFed();
    assert.ok(reported.every((error) => error instanceof ReactiveCycleError));
  });

  class Loop extends ComponentVM {
    declare closed: boolean;
    declare n: number;
    constructor(s: Services) {
      super(base(s, "loop"));
      this.observable({ closed: false, n: 1 });
      this.computed("ping", "pong");
    }
    get ping(): number {
      return this.closed ? this.pong + 1 : this.n;
    }
    get pong(): number {
      return this.ping + 1;
    }
  }

  function closeReadOpen(reads: readonly ("ping" | "pong")[]): string[] {
    const s = services();
    return quietly(() => {
      const vm = new Loop(s);
      activate(vm);
      assert.equal(vm.pong, 2);
      vm.closed = true;
      for (const name of reads) assert.throws(() => vm[name], ReactiveCycleError);
      const names = hubNames(s);
      vm.closed = false;
      return names;
    });
  }

  it("C3a a cycle closed by a flag: after reading ping and pong while closed, opening it announces both", async () => {
    assert.deepEqual(closeReadOpen(["ping", "pong"]), ["loop.closed", "loop.ping", "loop.pong"]);
    await streamFed();
  });

  it("C3b the same, after reading only ping while closed: opening it still announces pong", async () => {
    assert.deepEqual(closeReadOpen(["ping"]), ["loop.closed", "loop.ping", "loop.pong"]);
    await streamFed();
  });
});
