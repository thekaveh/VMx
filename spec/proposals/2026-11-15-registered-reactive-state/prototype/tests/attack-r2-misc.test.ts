/**
 * Attack round 2: places where the design's text was silent or ambiguous.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, PropertyChangedMessage } from "@thekaveh/vmx";
import { activate, configureReactiveDiagnostics, ReactiveOverflowError } from "../src/index.js";
import { base, captureReports, type Services, services, tick } from "./support.js";

function hubNames(s: Services, sender: object): string[] {
  const names: string[] = [];
  s.hub.messages.subscribe((m) => {
    if (m instanceof PropertyChangedMessage && m.sender === sender) names.push(m.propertyName);
  });
  return names;
}

describe("attack-r2 misc", () => {
  // Fix round 2 (R12.3): an effect runs synchronously; a Promise-returning function is tracked up to
  // its first await, and development reports it once per class. The scenario and the runs are unchanged; the
  // expectation of the reports moved from the documented gap (none) to the resolved rule (one). The filter keeps the
  // assertion to this test's own report.
  it("MS1 an async effect tracks only the reads before its first await, and development reports it", async () => {
    const s = services();
    class Host extends ComponentVM {
      declare a: number;
      declare b: number;
      runs = 0;
      constructor() {
        super(base(s, "host"));
        this.observable({ a: 0, b: 0 });
        const body = async (): Promise<void> => {
          this.runs += 1;
          void this.a;
          await Promise.resolve();
          void this.b;
        };
        this.effect(body as unknown as () => void);
      }
    }
    const reports = captureReports();
    const vm = new Host();
    vm.construct();
    await tick();
    vm.b = 1;
    await tick();
    assert.equal(vm.runs, 1, "current behavior: b is read after the await and is not a dependency");
    vm.a = 1;
    await tick();
    assert.equal(vm.runs, 2);
    assert.equal(reports.filter((report) => report.startsWith("Host: an effect returned a Promise")).length, 1);
  });

  it("MS2 a computed whose baseline ran before a state key was registered (in _onConstruct) is current after the registration", () => {
    const s = services();
    class Late extends ComponentVM {
      declare extra: number;
      constructor() {
        super(base(s, "late"));
        this.computed("label");
      }
      get label(): string {
        return `extra=${String(this.extra)}`;
      }
      protected override _onConstruct(): void {
        // Activation (and the baseline of label) already happened, before _onConstruct (R13.1 step 2).
        this.observable({ extra: 5 });
      }
    }
    const vm = new Late();
    vm.construct();
    assert.equal(vm.extra, 5);
    assert.equal(vm.label, "extra=5", "the memoized label still reads the value from before the registration");
  });

  // Fix round 2 (R9.6): the development bound is a cycle detector (spec 03 §3.3): it counts how
  // often one entry repeats, not how many distinct entries one drain holds. The scenario is unchanged; the
  // expectation moved from the documented gap (an overflow without any repeated entry) to the resolved rule (every
  // announcement is delivered).
  it("MS4 one write that fans out to 10,500 distinct announcements is delivered completely in development", () => {
    configureReactiveDiagnostics({ development: true });
    try {
      const s = services();
      class Settings extends ComponentVM {
        declare locale: string;
        constructor() {
          super(base(s, "settings"));
          this.observable({ locale: "en" });
        }
      }
      const settings = new Settings();
      class Row extends ComponentVM {
        constructor(index: number) {
          super(base(s, `row${String(index)}`));
          this.computed("a", "b", "c", "d", "e");
        }
        get a(): string {
          return `a:${settings.locale}`;
        }
        get b(): string {
          return `b:${settings.locale}`;
        }
        get c(): string {
          return `c:${settings.locale}`;
        }
        get d(): string {
          return `d:${settings.locale}`;
        }
        get e(): string {
          return `e:${settings.locale}`;
        }
      }
      const rows = Array.from({ length: 2_100 }, (_, i) => new Row(i));
      for (const row of rows) activate(row);
      let delivered = 0;
      s.hub.messages.subscribe((m) => {
        if (m instanceof PropertyChangedMessage && m.sender !== settings) delivered += 1;
      });
      let thrown: unknown = null;
      try {
        settings.locale = "fr";
      } catch (error) {
        thrown = error;
      }
      assert.ok(!(thrown instanceof ReactiveOverflowError), `thrown: ${String(thrown)}`);
      assert.equal(thrown, null);
      assert.equal(delivered, 10_500, "every derived announcement was delivered");
      assert.equal(rows[0]?.a, "a:fr");
      for (const row of rows) row.dispose();
      settings.dispose();
    } finally {
      configureReactiveDiagnostics({ development: undefined });
    }
  });

  it("MS3 a registration of a new computed after activation does not re-announce the ones registered before (expected to hold)", () => {
    const s = services();
    class Grow extends ComponentVM {
      declare n: number;
      constructor() {
        super(base(s, "grow"));
        this.observable({ n: 1 });
        this.computed("first");
      }
      get first(): number {
        return this.n;
      }
      get second(): number {
        return this.n * 2;
      }
    }
    const vm = new Grow();
    activate(vm);
    const names = hubNames(s, vm);
    vm.computed("second");
    assert.deepEqual(names, []);
    vm.n = 2;
    assert.deepEqual(names, ["n", "first", "second"]);
  });
});
