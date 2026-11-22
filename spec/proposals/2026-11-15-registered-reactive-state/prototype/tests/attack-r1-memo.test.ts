/**
 * Attack round 1: memoization with fresh objects, and what the development diagnostics do to memoized reads.
 *
 * Expectations: `Object.is` by default, a custom equality per property (design goal V2); "memoized" (V2);
 * "diagnostics change no behavior" (R19.*, diagnostics.test.ts).
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, PropertyChangedMessage } from "@thekaveh/vmx";
import { activate, configureReactiveDiagnostics, shallowEqual } from "../src/index.js";
import { base, captureReports, type Services, services } from "./support.js";

function withDevelopment<T>(development: boolean, fn: () => T): T {
  configureReactiveDiagnostics({ development });
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

describe("attack-r1 memoization with fresh objects", () => {
  it("M1 an equal fresh array: Object.is announces it; shallowEqual keeps the old instance (expected to hold)", () => {
    withDevelopment(false, () => {
      const s = services();
      class Lists extends ComponentVM {
        declare n: number;
        declare noise: number;
        constructor() {
          super(base(s, "lists"));
          this.observable({ n: 1, noise: 0 });
          this.computed({ fresh: Object.is, stable: shallowEqual });
        }
        get fresh(): readonly number[] {
          void this.noise;
          return [this.n];
        }
        get stable(): readonly number[] {
          void this.noise;
          return [this.n];
        }
      }
      const vm = new Lists();
      activate(vm);
      const fresh = vm.fresh;
      const stable = vm.stable;
      assert.equal(vm.fresh, fresh, "memoized: repeated reads return the same instance");
      const names = hubNames(s);
      vm.noise = 1;
      assert.deepEqual(names, ["lists.noise", "lists.fresh"]);
      assert.notEqual(vm.fresh, fresh);
      assert.equal(vm.stable, stable);
    });
  });

  it("M2 the development staleness check does not report a computed that returns a fresh class instance", () => {
    withDevelopment(true, () => {
      const reports = captureReports();
      const s = services();
      class Range {
        constructor(
          readonly from: number,
          readonly to: number,
        ) {}
      }
      class Picker extends ComponentVM {
        declare from: number;
        declare to: number;
        constructor() {
          super(base(s, "picker"));
          this.observable({ from: 1, to: 2 });
          this.computed("range", "index");
        }
        get range(): Range {
          return new Range(this.from, this.to);
        }
        get index(): ReadonlyMap<number, string> {
          return new Map([[this.from, "from"]]);
        }
      }
      const vm = new Picker();
      activate(vm);
      void vm.range;
      void vm.index;
      assert.deepEqual(reports, []);
    });
  });

  it("M3 reading a memoized computed does not run its getter again, also with development diagnostics on", () => {
    for (const development of [false, true]) {
      withDevelopment(development, () => {
        const s = services();
        class Counted extends ComponentVM {
          declare n: number;
          calls = 0;
          constructor() {
            super(base(s, "counted"));
            this.observable({ n: 1 });
            this.computed("twice");
          }
          get twice(): number {
            this.calls += 1;
            return this.n * 2;
          }
        }
        const vm = new Counted();
        activate(vm);
        vm.calls = 0;
        for (let i = 0; i < 5; i += 1) assert.equal(vm.twice, 2);
        assert.equal(vm.calls, 0, `development=${String(development)}: the getter ran ${String(vm.calls)} times`);
      });
    }
  });

  it("M4 GAP: a change scope whose writes cancel out still re-evaluates dependents and announces an object value", () => {
    withDevelopment(false, () => {
      const s = services();
      class Box extends ComponentVM {
        declare x: number;
        constructor() {
          super(base(s, "box"));
          this.observable({ x: 0 });
          this.computed("point", "label");
        }
        get point(): { readonly x: number } {
          return { x: this.x };
        }
        get label(): string {
          return `x=${String(this.x)}`;
        }
      }
      const vm = new Box();
      activate(vm);
      const names = hubNames(s);
      vm.change(() => {
        vm.x = 1;
        vm.x = 0;
      });
      // Documented behavior (R7.2: a value that changed back is no change) holds for x and label;
      // the fresh object `point` is announced although nothing it reads changed.
      assert.deepEqual(names, ["box.point"]);
    });
  });
});
