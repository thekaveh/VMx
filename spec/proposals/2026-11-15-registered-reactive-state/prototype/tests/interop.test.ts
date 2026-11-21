/**
 * RSTATE-035 and RSTATE-036: native nodes (the library's own messages come first) and read() interop.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { AsyncRelayCommand, ComponentVM, ComponentVMOf, ExpandableState } from "@thekaveh/vmx";
import { activate, explain, read } from "../src/index.js";
import { base, Recorder, type Services, services, tick } from "./support.js";

interface Doc {
  readonly title: string;
}

class DocVM extends ComponentVMOf<Doc> {
  constructor(s: Services) {
    super({ ...base(s, "doc"), initialModel: { title: "draft" }, modeledHinter: (m) => m.title });
    this.computed("upper", "ready");
  }
  get upper(): string {
    return this.model.title.toUpperCase();
  }
  get ready(): boolean {
    return this.isConstructed;
  }
}

describe("RSTATE-035 native nodes: the library's own messages come before their dependents' messages", () => {
  it("a model assignment announces model and modeledHint, then the dependents (R15.2)", () => {
    const s = services();
    const doc = new DocVM(s);
    activate(doc);
    const rec = new Recorder(s.hub);
    doc.model = { title: "final" };
    assert.deepEqual(rec.hubNames(), ["doc.model", "doc.modeledHint", "doc.upper"]);
    assert.equal(doc.upper, "FINAL");
  });

  it("a status transition publishes its status message before a dependent computed", () => {
    const s = services();
    const doc = new DocVM(s);
    activate(doc);
    const rec = new Recorder(s.hub, { status: true });
    doc.construct();
    assert.deepEqual(rec.take(), ["status:doc.3", "status:doc.4", "hub:doc.ready"]);
  });
});

describe("RSTATE-036 read() interop", () => {
  class Legacy extends ComponentVM {
    #count = 0;
    get count(): number {
      return this.#count;
    }
    bump(): void {
      this.#count += 1;
      this._notifyPropertyChanged("count");
    }
  }

  it("a reactive view-model follows a hand-notifying one through read()", () => {
    const s = services();
    const legacy = new Legacy(base(s, "legacy"));
    class Reactive extends ComponentVM {
      constructor() {
        super(base(s, "reactive"));
        this.computed("doubled");
      }
      get doubled(): number {
        return read(legacy, "count") * 2;
      }
    }
    const reactive = new Reactive();
    activate(reactive);
    const rec = new Recorder(s.hub);
    legacy.bump();
    assert.deepEqual(rec.hubNames(), ["legacy.count", "reactive.doubled"]);
    assert.equal(reactive.doubled, 2);
  });

  it("once the source registers the name, the same call tracks the node", () => {
    const s = services();
    class Migrated extends ComponentVM {
      declare count: number;
      constructor() {
        super(base(s, "migrated"));
        this.observable({ count: 0 });
      }
    }
    const migrated = new Migrated();
    class Reactive extends ComponentVM {
      constructor() {
        super(base(s, "reactive"));
        this.computed("doubled");
      }
      get doubled(): number {
        return read(migrated, "count") * 2;
      }
    }
    const reactive = new Reactive();
    activate(reactive);
    assert.deepEqual(
      explain(reactive, "doubled").map((entry) => [entry.owner, entry.name]),
      [[migrated, "count"]],
    );
    const rec = new Recorder(s.hub);
    migrated.count = 4;
    assert.deepEqual(rec.hubNames(), ["migrated.count", "reactive.doubled"]);
  });

  it("follows the change streams of VMx helpers and rejects plain objects", async () => {
    const s = services();
    const expansion = new ExpandableState(false);
    const command = AsyncRelayCommand.builder()
      .task(async () => {
        await tick();
      })
      .build();
    class Item extends ComponentVM {
      constructor() {
        super(base(s, "item"));
        this.computed("open", "busy");
      }
      get open(): boolean {
        return read(expansion, "isExpanded");
      }
      get busy(): boolean {
        return read(command, "isExecuting");
      }
    }
    const item = new Item();
    activate(item);
    const rec = new Recorder(s.hub);
    expansion.expand();
    const running = command.executeAsync();
    assert.deepEqual(rec.hubNames(), ["item.open", "item.busy"]);
    await running;
    assert.deepEqual(rec.hubNames().slice(2), ["item.busy"]);
    assert.throws(() => read({ topic: "t1" }, "topic"), /not a VMx object/);
  });
});
