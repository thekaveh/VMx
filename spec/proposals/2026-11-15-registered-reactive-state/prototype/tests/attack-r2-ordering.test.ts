/**
 * Attack round 2: ordering against the hub, "state first" for native nodes, and producer order (R9.8).
 *
 * Expectations used:
 * - a design goal: "Each accepted write re-evaluates the affected computed values before the write returns".
 * - spec 05 §2.3: "Both observers read the already-accepted state"; spec 03 §3.6 rule 3 "State first".
 * - R9.8: "a view-model's graph announcements and its direct sends reach the hub in the order they were
 *   caused (spec 03 §3.2)".
 * - R15.2: one settle per library operation; R15.5: native nodes over the library's change streams.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  type AsyncResourceVM,
  ComponentVM,
  ComponentVMOf,
  CompositeVM,
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  PropertyChangedMessage,
  whenPropertyChanged,
} from "@thekaveh/vmx";
import { activate } from "../src/index.js";
import { base, deferred, type Services, services, tick } from "./support.js";

function senderNames(s: Services, sender: object): string[] {
  const names: string[] = [];
  s.hub.messages.subscribe((m) => {
    if (m instanceof PropertyChangedMessage && m.sender === sender) names.push(m.propertyName);
  });
  return names;
}

/** An item whose computed derives from its keyed resource's state (a native node). */
class Item extends ComponentVM {
  readonly query: AsyncResourceVM<string>;
  readonly resolvers: ((value: string) => void)[] = [];
  constructor(s: Services) {
    super(base(s, "item"));
    this.query = this.keyedResource({
      key: () => "fixed",
      load: () => {
        const result = deferred<string>();
        this.resolvers.push(result.resolve);
        return result.promise;
      },
      autoLoad: true,
    });
    this.computed("statusText");
  }
  get statusText(): string {
    return this.query.state.status;
  }
}

describe("attack-r2 ordering: native nodes are current when the library's own messages are delivered", () => {
  it("OR1 a hub observer of the resource's state message reads the owner's computed over that state fresh", async () => {
    const s = services();
    const item = new Item(s);
    const seen: string[] = [];
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === item.query && m.propertyName === "state") {
        seen.push(`state=${item.query.state.status} statusText=${item.statusText}`);
      }
    });
    item.construct(); // autoLoad: Idle -> Loading
    item.resolvers[0]?.("data");
    await tick(); // Loading -> Ready
    assert.deepEqual(seen, ["state=Loading statusText=Loading", "state=Ready statusText=Ready"]);
  });

  it("OR1b the same through VMx's whenPropertyChanged helper (a call site that filters the hub by sender)", async () => {
    const s = services();
    const item = new Item(s);
    const seen: string[] = [];
    whenPropertyChanged(s.hub, item.query, "state").subscribe(() => {
      seen.push(`state=${item.query.state.status} statusText=${item.statusText}`);
    });
    item.construct();
    item.resolvers[0]?.("data");
    await tick();
    assert.deepEqual(seen, ["state=Loading statusText=Loading", "state=Ready statusText=Ready"]);
  });

  it("OR2 a hub observer of a status message reads a computed over isConstructed fresh", () => {
    const s = services();
    class Lamp extends ComponentVM {
      constructor() {
        super(base(s, "lamp"));
        this.computed("label");
      }
      get label(): string {
        return this.isConstructed ? "on" : "off";
      }
    }
    const lamp = new Lamp();
    activate(lamp);
    const seen: string[] = [];
    s.hub.messages.subscribe((m) => {
      if (m instanceof ConstructionStatusChangedMessage && m.sender === lamp) {
        seen.push(`${ConstructionStatus[m.status]}: isConstructed=${String(lamp.isConstructed)} label=${lamp.label}`);
      }
    });
    lamp.construct();
    lamp.destruct();
    assert.deepEqual(seen, [
      "Constructing: isConstructed=false label=off",
      "Constructed: isConstructed=true label=on",
      "Destructing: isConstructed=false label=off",
      "Destructed: isConstructed=false label=off",
    ]);
  });

  it("OR3 a local observer of the resource that subscribed before the owner activated reads the owner's computed fresh", async () => {
    const s = services();
    const item = new Item(s);
    const seen: string[] = [];
    // A view that binds the resource first and the item second (subscription order is the view's business).
    item.query.propertyChanged.subscribe((name) => {
      if (name === "state") seen.push(`state=${item.query.state.status} statusText=${item.statusText}`);
    });
    item.construct();
    item.resolvers[0]?.("data");
    await tick();
    assert.deepEqual(seen, ["state=Loading statusText=Loading", "state=Ready statusText=Ready"]);
  });

  // README.md limit 3: the prototype settles once per library operation for the methods that library.ts wraps;
  // R15.2 promises one settle per library operation natively.
  it("OR4 moving the selection is one library operation: a computed over the rows' isCurrent is not announced in between (R15.2)", () => {
    const s = services();
    class Row extends ComponentVM {
      constructor(name: string) {
        super(base(s, name));
        this.observable({}); // instrumented, so isCurrent is a native node in the prototype
      }
    }
    const list = new CompositeVM<Row>(base(s, "list"));
    const a = new Row("a");
    const b = new Row("b");
    list.add(a);
    list.add(b);
    list.construct();
    list.selectComponent(a);
    class Summary extends ComponentVM {
      constructor() {
        super(base(s, "summary"));
        this.computed("selected");
      }
      get selected(): number {
        return [a, b].filter((row) => row.isCurrent).length;
      }
    }
    const summary = new Summary();
    activate(summary);
    assert.equal(summary.selected, 1);
    const announced: number[] = [];
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === summary) announced.push(summary.selected);
    });
    list.selectComponent(b);
    assert.equal(summary.selected, 1);
    assert.deepEqual(announced, [], "selected stayed 1 across the move; any announcement is a glitch");
  });
});

describe("attack-r2 ordering: producer order (R9.8)", () => {
  it("OR5 an announcement settled during a producer flush still precedes the direct send that caused the flush", () => {
    const s = services();
    class Mixed extends ComponentVM {
      declare source: number;
      declare mirror: number;
      declare other: number;
      #legacy = 0;
      constructor() {
        super(base(s, "mixed"));
        this.observable({ source: 0, mirror: 0, other: 0 });
        this.effect(() => {
          const v = this.source;
          if (v === 0) return;
          this.mirror = v; // registered (queued: the drain is active)
          this.#legacy = v; // hand-written (a partially migrated VM)
          this._notifyPropertyChanged("legacy");
        });
      }
      get legacy(): number {
        return this.#legacy;
      }
    }
    const vm = new Mixed();
    vm.construct();
    // A hub observer that writes the same VM while the flush delivers `mirror`.
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === vm && m.propertyName === "mirror") vm.other = vm.mirror;
    });
    const names = senderNames(s, vm);
    vm.source = 1;
    // Control: with hand-written sends only, the hub's own re-entrant drain gives exactly this order (rule 5):
    // `other` is appended while `mirror` is delivered, before the effect sends `legacy`.
    assert.deepEqual(names, ["source", "mirror", "other", "legacy"]);
  });

  it("OR5c control: the same effect body with hand-written sends only, outside any delivery, gives mirror, other, legacy", () => {
    const s = services();
    class Hand extends ComponentVM {
      #mirror = 0;
      #other = 0;
      #legacy = 0;
      get mirror(): number {
        return this.#mirror;
      }
      get other(): number {
        return this.#other;
      }
      get legacy(): number {
        return this.#legacy;
      }
      setOther(v: number): void {
        this.#other = v;
        this._notifyPropertyChanged("other");
      }
      run(v: number): void {
        // The effect body of OR5, hand-written: an effect run is a graph drain entry, outside any hub delivery.
        this.#mirror = v;
        this._notifyPropertyChanged("mirror");
        this.#legacy = v;
        this._notifyPropertyChanged("legacy");
      }
    }
    const vm = new Hand(base(s, "hand"));
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === vm && m.propertyName === "mirror") vm.setOther(vm.mirror);
    });
    const names = senderNames(s, vm);
    vm.run(1);
    assert.deepEqual(names, ["mirror", "other", "legacy"]);
  });

  it("OR6 R9.8 holds for user code that a model assignment calls (onModelChanged)", () => {
    const s = services();
    interface Doc {
      readonly title: string;
    }
    class DocVM extends ComponentVMOf<Doc> {
      declare title: string;
      #shout = "";
      constructor() {
        super({
          ...base(s, "doc"),
          initialModel: { title: "a" },
          modeledHinter: () => "",
          onModelChanged: (m) => this.#onModel(m),
        });
        this.observable({ title: "a" });
      }
      get shout(): string {
        return this.#shout;
      }
      #onModel(m: Doc): void {
        this.title = m.title; // registered (migrated)
        this.#shout = m.title.toUpperCase(); // hand-written (not migrated yet)
        this._notifyPropertyChanged("shout");
      }
    }
    const doc = new DocVM();
    class Driver extends ComponentVM {
      declare next: string;
      constructor() {
        super(base(s, "driver"));
        this.observable({ next: "a" });
        // The model assignment happens inside an effect run, so a graph drain is active.
        this.effect(() => {
          const title = this.next;
          if (title !== "a") doc.model = { title };
        });
      }
    }
    const driver = new Driver();
    driver.construct();
    const names = senderNames(s, doc);
    driver.next = "b";
    assert.deepEqual(names, ["model", "title", "shout"], "title was written before shout was sent");
  });

  it("OR7 inside hub.batch a VM's reactive and hand-written sends keep statement order (expected to hold)", () => {
    const s = services();
    class Mixed extends ComponentVM {
      declare a: number;
      declare b: number;
      constructor() {
        super(base(s, "mixed"));
        this.observable({ a: 0, b: 0 });
      }
      ping(): void {
        this._notifyPropertyChanged("ping");
      }
    }
    const vm = new Mixed();
    const names = senderNames(s, vm);
    s.hub.batch(() => {
      vm.a = 1;
      vm.ping();
      vm.b = 2;
      assert.deepEqual(names, [], "the hub waits for the batch");
    });
    assert.deepEqual(names, ["a", "ping", "b"]);
  });
});
