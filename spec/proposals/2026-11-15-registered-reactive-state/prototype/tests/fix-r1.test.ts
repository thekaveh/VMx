/**
 * The rules added or changed by fix round 1, beyond the attack tests that found the gaps.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  ComponentVM,
  CompositeVM,
  ConstructionStatus,
  ExpandableState,
  PropertyChangedMessage,
} from "@thekaveh/vmx";
import { activate, ReactiveCycleError, ReactiveWriteError, read, untracked } from "../src/index.js";
import { base, captureReports, type Services, services, tick } from "./support.js";

function senderNames(s: Services, sender?: object): string[] {
  const names: string[] = [];
  s.hub.messages.subscribe((m) => {
    if (!(m instanceof PropertyChangedMessage)) return;
    if (sender !== undefined && m.sender !== sender) return;
    names.push(sender === undefined ? `${m.senderName}.${m.propertyName}` : m.propertyName);
  });
  return names;
}

describe("R9.8 producer order", () => {
  it("a direct send delivers the queued announcements before it, across producers, in queue order", () => {
    const s = services();
    class Source extends ComponentVM {
      declare x: number;
      constructor() {
        super(base(s, "source"));
        this.observable({ x: 0 });
      }
    }
    const source = new Source();
    class Mixed extends ComponentVM {
      constructor() {
        super(base(s, "mixed"));
        this.computed("doubled");
      }
      get doubled(): number {
        return source.x * 2;
      }
      ping(): void {
        this._notifyPropertyChanged("ping");
      }
    }
    const mixed = new Mixed();
    activate(mixed);
    class Trigger extends ComponentVM {
      declare go: boolean;
      constructor() {
        super(base(s, "trigger"));
        this.observable({ go: false });
      }
    }
    const trigger = new Trigger();
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === trigger && m.propertyName === "go") {
        source.x = 1; // settles; the announcements wait in the graph queue (a drain is active)
        mixed.ping(); // a direct send of mixed: source.x and mixed.doubled come first
      }
    });
    const names = senderNames(s);
    trigger.go = true;
    assert.deepEqual(names, ["trigger.go", "source.x", "mixed.doubled", "mixed.ping"]);
  });
});

describe("R5.7 and R5.8 library operations and deliveries run untracked", () => {
  it("R16 a library mutation of an untouched object inside a computed throws before it changes anything", () => {
    const s = services();
    const expansion = new ExpandableState(false);
    class Meddler extends ComponentVM {
      constructor() {
        super(base(s, "meddler"));
        this.computed("meddle");
      }
      get meddle(): boolean {
        expansion.expand();
        return true;
      }
    }
    const vm = new Meddler();
    activate(vm);
    assert.throws(() => vm.meddle, ReactiveWriteError);
    assert.equal(expansion.isExpanded, false);
  });

  it("an observer that reads state during a delivery an effect caused adds nothing to the effect", () => {
    const s = services();
    class Other extends ComponentVM {
      declare x: number;
      constructor() {
        super(base(s, "other"));
        this.observable({ x: 0 });
      }
    }
    const other = new Other();
    class Legacy extends ComponentVM {
      bump(): void {
        this._notifyPropertyChanged("count");
      }
    }
    const legacy = new Legacy(base(s, "legacy"));
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === legacy) void other.x;
    });
    class Host extends ComponentVM {
      declare go: number;
      runs = 0;
      constructor() {
        super(base(s, "host"));
        this.observable({ go: 0 });
        this.effect(() => {
          this.runs += 1;
          void this.go;
          legacy.bump();
        });
      }
    }
    const host = new Host();
    host.construct();
    other.x = 1;
    assert.equal(host.runs, 1, "the hub observer's read is not the effect's dependency");
    host.go = 1;
    assert.equal(host.runs, 2);
  });
});

describe("R10.7 canExecute() inside a frame follows the command's raises", () => {
  it("a computed over a built-in command of another view-model is re-evaluated when it raises", () => {
    const s = services();
    const list = new CompositeVM<ComponentVM>(base(s, "list"));
    const row = new ComponentVM(base(s, "row"));
    list.add(row);
    class Picker extends ComponentVM {
      constructor() {
        super(base(s, "picker"));
        this.computed("canPick");
      }
      get canPick(): boolean {
        return row.selectCommand.canExecute();
      }
    }
    const picker = new Picker();
    activate(picker);
    assert.equal(picker.canPick, false);
    const names = senderNames(s, picker);
    list.construct(); // the row becomes Constructed: its selectCommand raises
    assert.deepEqual(names, ["canPick"]);
    assert.equal(picker.canPick, true);
  });

  it("a computed over a helper command follows a raise for an input outside the graph (R10.6)", () => {
    const s = services();
    const outside = { ready: false };
    class Toolbar extends ComponentVM {
      readonly save = this.relayCommand(
        () => undefined,
        () => outside.ready,
      );
      constructor() {
        super(base(s, "toolbar"));
        this.computed("saveVisible");
      }
      get saveVisible(): boolean {
        return this.save.canExecute();
      }
    }
    const toolbar = new Toolbar();
    activate(toolbar);
    const names = senderNames(s, toolbar);
    outside.ready = true;
    toolbar.save.raiseCanExecuteChanged(); // the documented path for an input outside the graph
    assert.deepEqual(names, ["saveVisible"]);
    assert.equal(toolbar.saveVisible, true);
  });
});

describe("R15.1 container membership", () => {
  it("read(container, 'count') follows collectionChanged", () => {
    const s = services();
    const list = new CompositeVM<ComponentVM>(base(s, "list"));
    class Summary extends ComponentVM {
      constructor() {
        super(base(s, "summary"));
        this.computed("rows");
      }
      get rows(): string {
        return `${String(read(list, "count"))} rows`;
      }
    }
    const summary = new Summary();
    activate(summary);
    const names = senderNames(s, summary);
    list.add(new ComponentVM(base(s, "row")));
    assert.deepEqual(names, ["rows"]);
    assert.equal(summary.rows, "1 rows");
  });
});

describe("R19.6 reactive usage errors inside a predicate", () => {
  it("a predicate that writes reads as false and is reported once per class in development", () => {
    const reports = captureReports();
    class Writer extends ComponentVM {
      declare n: number;
      readonly command = this.relayCommand(
        () => undefined,
        () => {
          this.n = 5;
          return true;
        },
      );
      constructor(s: Services) {
        super(base(s, "writer"));
        this.observable({ n: 1 });
      }
    }
    const vm = new Writer(services());
    assert.equal(vm.command.canExecute(), false);
    assert.equal(vm.command.canExecute(), false);
    assert.equal(vm.n, 1);
    assert.equal(reports.filter((report) => report.includes("ReactiveWriteError")).length, 1);
  });
});

describe("R16 cycles cannot be hidden", () => {
  it("a getter that catches the cycle error still fails with it", () => {
    class Loop extends ComponentVM {
      constructor(s: Services) {
        super(base(s, "loop"));
        this.computed("safe", "other");
      }
      get safe(): number {
        try {
          return this.other + 1;
        } catch {
          return -1;
        }
      }
      get other(): number {
        return this.safe + 1;
      }
    }
    const vm = new Loop(services());
    activate(vm);
    assert.throws(() => vm.safe, ReactiveCycleError);
  });
});

describe("R11.4, R12.9, R13.2 and R13.3 lifecycle windows", () => {
  it("a reaction registered inside an unhooked _onConstruct starts before Constructed is published", () => {
    const s = services();
    const runs: string[] = [];
    class Host extends ComponentVM {
      constructor() {
        super(base(s, "host"));
      }
      protected override _onConstruct(): void {
        this.effect(() => {
          runs.push(ConstructionStatus[untracked(() => this.status)]);
        });
      }
    }
    const host = new Host();
    host.construct();
    assert.deepEqual(runs, ["Constructing"]);
    assert.equal(host.status, ConstructionStatus.Constructed);
  });

  it("a reaction registered during a destruct that fails starts when the rollback is published", () => {
    const s = services();
    const runs: string[] = [];
    let registered = false;
    class Host extends ComponentVM {
      constructor() {
        super(base(s, "host"));
        this.observable({});
      }
      protected override _onDestruct(): void {
        if (!registered) {
          registered = true;
          this.effect(() => {
            runs.push(ConstructionStatus[untracked(() => this.status)]);
          });
        }
        throw new Error("destruct failed");
      }
    }
    const host = new Host();
    host.construct();
    assert.throws(() => host.destruct(), /destruct failed/);
    assert.equal(host.status, ConstructionStatus.Constructed);
    assert.deepEqual(runs, ["Constructed"]);
  });

  it("an effect whose first run writes what it read and then throws fails the construct and does not run again", () => {
    const runs: number[] = [];
    class Host extends ComponentVM {
      declare n: number;
      constructor(s: Services) {
        super(base(s, "host"));
        this.observable({ n: 0 });
        this.effect(() => {
          const n = this.n;
          runs.push(n);
          if (n === 0) {
            this.n = 1;
            throw new Error("first run failed");
          }
        });
      }
    }
    const vm = new Host(services());
    assert.throws(() => vm.construct(), /first run failed/);
    assert.deepEqual(runs, [0]);
    assert.equal(vm.n, 1, "the write before the throw stays");
    assert.equal(vm.status, ConstructionStatus.Destructed);
  });

  it("an owner hook that fails after the members were destructed rolls back; the paused effect runs once", () => {
    const s = services();
    class Owner extends ComponentVM {
      readonly part = this.member(new ComponentVM(base(s, "part")));
      readonly seen: string[] = [];
      constructor() {
        super(base(s, "owner"));
        this.effect(() => {
          this.seen.push(String(this.part.isConstructed));
        });
      }
      protected override _onDestruct(): void {
        throw new Error("owner destruct failed");
      }
    }
    const owner = new Owner();
    owner.construct();
    assert.deepEqual(owner.seen, ["true"]);
    assert.throws(() => owner.destruct(), /owner destruct failed/);
    assert.equal(owner.status, ConstructionStatus.Constructed);
    // Spec 02 §6.1: a member that reached Destructed is not undone (the open-decisions ledger keeps the question).
    assert.equal(owner.part.status, ConstructionStatus.Destructed);
    assert.deepEqual(owner.seen, ["true", "false"], "paused during the destruct, resumed once after the rollback");
  });

  it("a reconstruct issued by another view-model's effect adds no dependency to that effect", () => {
    const s = services();
    class Target extends ComponentVM {
      setups = 0;
      constructor() {
        super(base(s, "target"));
        this.whileConstructed(() => {
          this.setups += 1;
        });
      }
    }
    const target = new Target();
    class Driver extends ComponentVM {
      declare go: number;
      runs = 0;
      constructor() {
        super(base(s, "driver"));
        this.observable({ go: 0 });
        this.effect(() => {
          this.runs += 1;
          if (this.go > 0) target.reconstruct();
        });
      }
    }
    const driver = new Driver();
    target.construct();
    driver.construct();
    driver.go = 1;
    assert.equal(target.setups, 2);
    assert.equal(driver.runs, 2);
    target.destruct();
    target.construct();
    assert.equal(driver.runs, 2, "the target's transitions do not re-run the driver's effect");
  });

  it("the owner still announces while its members are disposed, and nothing after Disposed", () => {
    const s = services();
    class Member extends ComponentVM {
      constructor(readonly onDispose: () => void) {
        super(base(s, "member"));
      }
      protected override _onDispose(): void {
        this.onDispose();
      }
    }
    class Owner extends ComponentVM {
      declare count: number;
      constructor() {
        super(base(s, "owner"));
        this.observable({ count: 0 });
        this.computed("label");
        this.member(
          new Member(() => {
            this.count = 5;
          }),
        );
      }
      get label(): string {
        return `n=${String(this.count)}`;
      }
      protected override _onDispose(): void {
        this.count = 6;
      }
    }
    const owner = new Owner();
    owner.construct();
    const names = senderNames(s, owner);
    owner.dispose();
    assert.deepEqual(names, ["count", "label"]);
    assert.equal(owner.count, 5);
    assert.equal(owner.label, "n=5");
  });
});

describe("R19.8 keyed resources with object keys", () => {
  it("an object key that is shallow-equal to the previous one reloads under Object.is and is reported once", async () => {
    const reports = captureReports();
    class Paged extends ComponentVM {
      declare readonly page: number;
      declare readonly viewers: number;
      readonly write;
      readonly loads: number[] = [];
      constructor(s: Services) {
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
        });
      }
    }
    const vm = new Paged(services());
    vm.construct();
    await tick();
    vm.write({ viewers: 2 });
    await tick();
    vm.write({ viewers: 3 });
    await tick();
    assert.deepEqual(vm.loads, [1, 1, 1], "behavior is unchanged (R14.*: Object.is is the default)");
    assert.equal(reports.filter((report) => report.includes("shallow-equal")).length, 1);
  });
});
