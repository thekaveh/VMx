/**
 * Attack round 1: ordering against the hub's batch and re-entrant drain rules (spec 03 §3.2 per-producer FIFO,
 * §3.3 rules 1 to 5; spec 05 §2.3 hub first, then local).
 *
 * The graph keeps its own FIFO queue next to the hub's queue. A hand-written `_notifyPropertyChanged` sends at the
 * write; a registered write made during a graph drain only appends a graph entry. The tests compare the two.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  ComponentVM,
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  PropertyChangedMessage,
} from "@thekaveh/vmx";
import { activate } from "../src/index.js";
import { base, type Services, services } from "./support.js";

/** Records hub property and status messages of the named senders, in delivery order. */
function hubLog(s: Services, names: ReadonlySet<string>, options: { readonly status?: boolean } = {}): string[] {
  const events: string[] = [];
  s.hub.messages.subscribe((m) => {
    if (m instanceof PropertyChangedMessage && names.has(m.senderName)) {
      events.push(`${m.senderName}.${m.propertyName}`);
    } else if (options.status === true && m instanceof ConstructionStatusChangedMessage && names.has(m.senderName)) {
      events.push(`${m.senderName}:${ConstructionStatus[m.status]}`);
    }
  });
  return events;
}

class Trigger extends ComponentVM {
  declare go: boolean;
  constructor(s: Services) {
    super(base(s, "trigger"));
    this.observable({ go: false });
  }
}

/** Writes registered state in _onConstruct. */
class ReactiveChild extends ComponentVM {
  declare ready: boolean;
  constructor(s: Services) {
    super(base(s, "reactive"));
    this.observable({ ready: false });
  }
  protected override _onConstruct(): void {
    this.ready = true;
  }
}

/** The same VM, hand-written (the 3.30.0 idiom). */
class HandChild extends ComponentVM {
  #ready = false;
  constructor(s: Services) {
    super(base(s, "hand"));
  }
  get ready(): boolean {
    return this.#ready;
  }
  protected override _onConstruct(): void {
    this.#ready = true;
    this._notifyPropertyChanged("ready");
  }
}

describe("attack-r1 ordering: the graph queue against the hub queue", () => {
  it("O1 a VM constructed by an observer during a graph drain announces its _onConstruct write before Constructed", () => {
    const s = services();
    const trigger = new Trigger(s);
    const reactive = new ReactiveChild(s);
    const hand = new HandChild(s);
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === trigger && m.propertyName === "go") {
        hand.construct();
        reactive.construct();
      }
    });
    const events = hubLog(s, new Set(["hand", "reactive"]), { status: true });
    trigger.go = true;
    const handOrder = events.filter((e) => e.startsWith("hand"));
    const reactiveOrder = events.filter((e) => e.startsWith("reactive")).map((e) => e.replace("reactive", "hand"));
    assert.deepEqual(handOrder, ["hand:Constructing", "hand.ready", "hand:Constructed"], "control (hand-written)");
    assert.deepEqual(reactiveOrder, handOrder, `all events: ${events.join(", ")}`);
  });

  it("O1b the same construct at top level keeps the order (control: the reorder needs an active graph drain)", () => {
    const s = services();
    const reactive = new ReactiveChild(s);
    const events = hubLog(s, new Set(["reactive"]), { status: true });
    reactive.construct();
    assert.deepEqual(events, ["reactive:Constructing", "reactive.ready", "reactive:Constructed"]);
  });

  it("O2 a registered write and a hand-written notification in one effect run reach the hub in statement order", () => {
    const s = services();
    class Mixed extends ComponentVM {
      declare source: number;
      declare mirror: number;
      #legacy = 0;
      constructor() {
        super(base(s, "mixed"));
        this.observable({ source: 0, mirror: -1 });
        this.effect(() => {
          const v = this.source;
          this.mirror = v; // registered state (a partially migrated VM)
          this.#legacy = v; // hand-written state
          this._notifyPropertyChanged("legacy");
        });
      }
      get legacy(): number {
        return this.#legacy;
      }
    }
    const vm = new Mixed();
    const events = hubLog(s, new Set(["mixed"]));
    vm.construct();
    const firstRun = [...events];
    events.length = 0;
    vm.source = 1;
    const reRun = [...events];
    assert.deepEqual(firstRun, ["mixed.mirror", "mixed.legacy"], "first run (outside a drain)");
    assert.deepEqual(reRun, ["mixed.source", "mixed.mirror", "mixed.legacy"], "re-run (inside the drain)");
  });
});

describe("attack-r1 ordering: hub transactions and determinism (expected to hold)", () => {
  it("O3 inside hub.batch with a re-entrant local observer, the hub later delivers in the local order", () => {
    const s = services();
    class Pair extends ComponentVM {
      declare a: number;
      declare b: number;
      constructor() {
        super(base(s, "pair"));
        this.observable({ a: 0, b: 0 });
        this.computed("sum");
      }
      get sum(): number {
        return this.a + this.b;
      }
    }
    const vm = new Pair();
    const local: string[] = [];
    vm.propertyChanged.subscribe((name) => {
      local.push(`pair.${name}`);
      if (name === "a" && vm.b === 0) vm.b = 1;
    });
    const hub = hubLog(s, new Set(["pair"]));
    s.hub.batch(() => {
      vm.a = 1;
      assert.deepEqual(hub, [], "the hub waits for the batch");
    });
    assert.deepEqual(local, ["pair.a", "pair.sum", "pair.b", "pair.sum"]);
    assert.deepEqual(hub, local);
  });

  it("O4 one write announces across view-models by height, then creation order", () => {
    const s = services();
    class Settings extends ComponentVM {
      declare theme: string;
      constructor() {
        super(base(s, "settings"));
        this.observable({ theme: "light" });
      }
    }
    const settings = new Settings();
    class Item extends ComponentVM {
      constructor(name: string) {
        super(base(s, name));
        this.computed("label", "badge");
      }
      get label(): string {
        return `${this.name}:${settings.theme}`;
      }
      get badge(): string {
        return this.label.toUpperCase();
      }
    }
    const second = new Item("itemB");
    const first = new Item("itemA");
    activate(first);
    activate(second);
    const events = hubLog(s, new Set(["settings", "itemA", "itemB"]));
    settings.theme = "dark";
    assert.deepEqual(events, ["settings.theme", "itemB.label", "itemA.label", "itemB.badge", "itemA.badge"]);
  });
});
