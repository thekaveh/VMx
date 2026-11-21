/**
 * Attack round 2: re-entrancy. User callbacks that the graph calls during propagation (custom equalities), writes
 * made by observers during a drain, and reactions registered from inside a reaction.
 *
 * Expectations used:
 * - a design goal: "Lossless, not coalesced (spec 03 §3.3): propagation is synchronous. Each accepted write
 *   re-evaluates the affected computed values before the write returns, and publishes each value that changed".
 * - R6.2: "a write ... is accepted when ... the caller is not an evaluation frame"; R5.7: "a VMx library
 *   operation runs untracked"; the per-write settle analysis of plan D21: "no cause goes unprocessed".
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, PropertyChangedMessage } from "@thekaveh/vmx";
import { activate } from "../src/index.js";
import { base, type Services, services } from "./support.js";

function hubNames(s: Services): string[] {
  const names: string[] = [];
  s.hub.messages.subscribe((m) => {
    if (m instanceof PropertyChangedMessage) names.push(`${m.senderName}.${m.propertyName}`);
  });
  return names;
}

class Trigger extends ComponentVM {
  declare go: number;
  constructor(s: Services) {
    super(base(s, "trigger"));
    this.observable({ go: 0 });
  }
}

describe("attack-r2 re-entrancy: custom equalities are user code called during a settle", () => {
  it("RR1 a custom equality that writes another VM's state does not re-enter the settle: each change is announced once", () => {
    const s = services();
    class Audit extends ComponentVM {
      declare comparisons: number;
      constructor() {
        super(base(s, "audit"));
        this.observable({ comparisons: 0 });
      }
    }
    const audit = new Audit();
    class Source extends ComponentVM {
      declare level: number;
      constructor() {
        super(base(s, "source"));
        this.observable({ level: 1 });
        this.computed({
          rounded: (a: number, b: number): boolean => {
            audit.comparisons += 1; // a counter kept in another VM (instrumentation)
            return a === b;
          },
        });
      }
      get rounded(): number {
        return Math.round(this.level);
      }
    }
    const source = new Source();
    activate(source);
    const names = hubNames(s);
    source.level = 2;
    const counts = new Map<string, number>();
    for (const name of names) counts.set(name, (counts.get(name) ?? 0) + 1);
    assert.deepEqual(
      [...counts.entries()].filter(([, count]) => count > 1),
      [],
      `announced: ${names.join(", ")}`,
    );
    assert.deepEqual(names.filter((name) => name.startsWith("source.")), ["source.level", "source.rounded"]);
  });

  it("RR2 a state equality's reads are not dependencies of the effect that writes the state", () => {
    const s = services();
    class Settings extends ComponentVM {
      declare tolerance: number;
      constructor() {
        super(base(s, "settings"));
        this.observable({ tolerance: 0.5 });
      }
    }
    const settings = new Settings();
    class Sensor extends ComponentVM {
      declare raw: number;
      constructor() {
        super(base(s, "sensor"));
        this.observable({ raw: 1 });
      }
    }
    const sensor = new Sensor();
    class Display extends ComponentVM {
      declare shown: number;
      runs = 0;
      constructor() {
        super(base(s, "display"));
        this.observable({ shown: 0 }, { shown: (a, b) => Math.abs(a - b) < settings.tolerance });
        this.effect(() => {
          this.runs += 1;
          this.shown = sensor.raw; // the equality runs inside this write
        });
      }
    }
    const display = new Display();
    display.construct();
    assert.equal(display.runs, 1);
    settings.tolerance = 0.1;
    assert.equal(display.runs, 1, "changing the tolerance re-ran an effect that only reads sensor.raw");
    sensor.raw = 3;
    assert.equal(display.runs, 2);
  });
});

describe("attack-r2 re-entrancy: writes made during a drain", () => {
  // Spec gap (normative since fix round 2, R12.11): per-write losslessness holds for announcements. A reaction run is
  // scheduled per settle but samples the state when it runs, so two writes made during one drain are one delivery or
  // none.
  it("RR3 GAP: reaction() delivers each write at top level, but the same two writes during a drain deliver nothing", () => {
    const s = services();
    class Toggle extends ComponentVM {
      declare hidden: boolean;
      readonly deliveries: string[] = [];
      constructor(name: string) {
        super(base(s, name));
        this.observable({ hidden: false });
        this.reaction(
          () => this.hidden,
          (value, previous) => this.deliveries.push(`${String(previous)}->${String(value)}`),
        );
      }
    }
    const top = new Toggle("top");
    top.construct();
    top.hidden = true;
    top.hidden = false;

    const nested = new Toggle("nested");
    nested.construct();
    const trigger = new Trigger(s);
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === trigger) {
        nested.hidden = true;
        nested.hidden = false;
      }
    });
    const names = hubNames(s);
    trigger.go = 1;
    assert.deepEqual(top.deliveries, ["false->true", "true->false"]);
    assert.deepEqual(nested.deliveries, [], "current behavior: the reaction sampled the final value once");
    assert.deepEqual(
      names.filter((name) => name.startsWith("nested.")),
      ["nested.hidden", "nested.hidden"],
      "the announcements are lossless (two), the reaction is not",
    );
  });

  it("RR4 a hub observer that writes during a drain, then reads a computed of another VM, reads it fresh (expected to hold)", () => {
    const s = services();
    class Source extends ComponentVM {
      declare n: number;
      constructor() {
        super(base(s, "source"));
        this.observable({ n: 0 });
      }
    }
    const source = new Source();
    class View extends ComponentVM {
      constructor() {
        super(base(s, "view"));
        this.computed("text");
      }
      get text(): string {
        return `n=${String(source.n)}`;
      }
    }
    const view = new View();
    activate(view);
    const trigger = new Trigger(s);
    const reads: string[] = [];
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === trigger) {
        source.n = 5;
        reads.push(view.text);
      }
    });
    trigger.go = 1;
    assert.deepEqual(reads, ["n=5"]);
  });
});

describe("attack-r2 re-entrancy: reactions registered from inside a reaction", () => {
  // Fix round 2 (R12.10): a reaction registered during a run of another reaction of the same
  // view-model belongs to that run and is removed when that reaction runs again. The scenario is unchanged; the
  // expectation moved from the documented gap (every inner effect stays live) to the resolved rule (only the latest).
  it("RR5 an effect that registers an effect on each run keeps only the inner effect of its latest run", () => {
    const s = services();
    class Host extends ComponentVM {
      declare mode: string;
      declare tick: number;
      readonly inner: string[] = [];
      constructor() {
        super(base(s, "host"));
        this.observable({ mode: "a", tick: 0 });
        this.effect(() => {
          const mode = this.mode;
          this.effect(() => {
            void this.tick;
            this.inner.push(mode);
          });
        });
      }
    }
    const host = new Host();
    host.construct();
    host.mode = "b";
    host.mode = "c";
    host.inner.length = 0;
    host.tick = 1;
    assert.deepEqual(host.inner, ["c"], "the inner effects of earlier runs were removed");
  });
});
