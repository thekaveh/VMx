/**
 * The rules added or changed by fix round 2, beyond the attack tests that found the gaps.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  ComponentVM,
  ConstructionStatus,
  ExpandableState,
  PropertyChangedMessage,
  RelayCommand,
  wrapWith,
} from "@thekaveh/vmx";
import {
  activate,
  configureReactiveDiagnostics,
  ReactiveOverflowError,
  ReactiveWriteError,
  read,
  walk,
} from "../src/index.js";
import { base, captureReports, type Services, services, streamFed } from "./support.js";

class Gate extends ComponentVM {
  declare open: boolean;
  constructor(s: Services, name = "gate") {
    super(base(s, name));
    this.observable({ open: true });
  }
}

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

function quietly<T>(fn: () => T): T {
  configureReactiveDiagnostics({ development: false });
  try {
    return fn();
  } finally {
    configureReactiveDiagnostics({ development: undefined });
  }
}

describe("R12.10 registration scopes and handles", () => {
  it("effect(), reaction() and whileConstructed() return a handle that removes the reaction for good", () => {
    const s = services();
    class Host extends ComponentVM {
      declare n: number;
      readonly log: string[] = [];
      constructor() {
        super(base(s, "host"));
        this.observable({ n: 0 });
      }
    }
    const vm = new Host();
    const stopEffect = vm.effect(() => {
      vm.log.push(`effect:${String(vm.n)}`);
      return () => vm.log.push("cleanup");
    });
    const stopReaction = vm.reaction(
      () => vm.n,
      (value) => vm.log.push(`reaction:${String(value)}`),
    );
    const stopSetup = vm.whileConstructed(() => () => vm.log.push("teardown"));
    vm.construct();
    vm.n = 1;
    stopEffect();
    stopReaction();
    stopSetup();
    vm.n = 2;
    vm.destruct();
    vm.construct();
    vm.n = 3;
    assert.deepEqual(vm.log, ["effect:0", "cleanup", "effect:1", "reaction:1", "cleanup", "teardown"]);
  });

  it("a reaction registered by an effect run ends when that effect stops, and its next first run registers it again", () => {
    const s = services();
    class Host extends ComponentVM {
      declare tick: number;
      readonly inner: number[] = [];
      constructor() {
        super(base(s, "host"));
        this.observable({ tick: 0 });
        this.effect(() => {
          this.effect(() => {
            this.inner.push(this.tick);
          });
        });
      }
    }
    const host = new Host();
    host.construct();
    host.tick = 1;
    host.destruct();
    host.tick = 2;
    host.construct();
    host.tick = 3;
    assert.deepEqual(host.inner, [0, 1, 2, 3], "exactly one inner effect at any time");
  });

  it("a cleanup returned by a run that removed its own reaction runs at once; a handle inside a computed throws", () => {
    const s = services();
    const log: string[] = [];
    class Host extends ComponentVM {
      declare n: number;
      stop: () => void = () => undefined;
      constructor() {
        super(base(s, "host"));
        this.observable({ n: 0 });
        this.computed("meddle");
        this.stop = this.effect(() => {
          const n = this.n;
          if (n === 1) this.stop(); // the run removes its own effect
          return () => log.push(`cleanup:${String(n)}`);
        });
      }
      get meddle(): number {
        this.stop();
        return 0;
      }
    }
    const host = new Host();
    host.construct();
    activate(host);
    assert.throws(() => host.meddle, ReactiveWriteError);
    host.n = 1;
    host.n = 2;
    assert.deepEqual(log, ["cleanup:0", "cleanup:1"], "each cleanup ran once; the removed effect ran no more");
  });

  it("a reaction registered in _onConstruct survives a destruct that rolls back, and a completed destruct removes it", () => {
    const s = services();
    class Host extends ComponentVM {
      declare tick: number;
      runs = 0;
      fail = true;
      constructor() {
        super(base(s, "host"));
        this.observable({ tick: 0 });
      }
      protected override _onConstruct(): void {
        this.effect(() => {
          void this.tick;
          this.runs += 1;
        });
      }
      protected override _onDestruct(): void {
        if (this.fail) throw new Error("destruct failed");
      }
    }
    const host = new Host();
    host.construct();
    assert.throws(() => host.destruct(), /destruct failed/);
    assert.equal(host.status, ConstructionStatus.Constructed);
    host.runs = 0;
    host.tick = 1;
    assert.equal(host.runs, 1, "the rollback restarted the one effect");
    host.fail = false;
    host.destruct();
    host.construct();
    host.runs = 0;
    host.tick = 2;
    assert.equal(host.runs, 1, "the completed destruct removed it; the next _onConstruct registered one again");
  });
});

describe("R13.2 a destruct that rolls back restarts the reactions it stopped", () => {
  it("a whileConstructed setup that the destruct tore down runs again after the rollback", () => {
    const s = services();
    const log: string[] = [];
    class Host extends ComponentVM {
      constructor() {
        super(base(s, "host"));
        this.whileConstructed(() => {
          log.push("setup");
          return () => log.push("teardown");
        });
      }
      protected override _onDestruct(): void {
        throw new Error("destruct failed");
      }
    }
    const host = new Host();
    host.construct();
    assert.throws(() => host.destruct(), /destruct failed/);
    assert.deepEqual(log, ["setup", "teardown", "setup"]);
  });
});

describe("R11.5 members leave the list at their disposal", () => {
  it("a disposed view-model registers nothing as a member", () => {
    const s = services();
    const owner = new ComponentVM(base(s, "owner"));
    owner.observable({});
    const done = new ComponentVM(base(s, "done"));
    done.dispose();
    assert.equal(owner.member(done), done);
    assert.deepEqual(
      [...walk(owner)].map((vm) => vm.name),
      ["owner"],
    );
  });
});

describe("R10.2 every VMx command tracks its own predicate", () => {
  it("a command built directly with the VMx builder raises when its predicate's nodes change", () => {
    const s = services();
    const gate = new Gate(s);
    const command = RelayCommand.builder()
      .predicate(() => gate.open)
      .build();
    let raises = 0;
    command.canExecuteChanged.subscribe(() => {
      raises += 1;
    });
    assert.equal(command.canExecute(), true);
    gate.open = false;
    assert.equal(raises, 1);
    gate.open = true;
    assert.equal(raises, 1, "the set was cleared at the raise (spec 04 §4)");
    assert.equal(command.canExecute(), true);
    gate.open = false;
    assert.equal(raises, 2);
    command.dispose();
    const afterDispose = raises;
    gate.open = true;
    assert.equal(raises, afterDispose, "a disposed command keeps no edge");
  });

  it("a decorator forwards its inner command's raise once and raises once for its own predicate", () => {
    const s = services();
    const gate = new Gate(s, "gate");
    const other = new Gate(s, "other");
    class Item extends ComponentVM {
      readonly save = this.relayCommand(
        () => undefined,
        () => gate.open,
      );
      readonly guarded = wrapWith(this.save, () => other.open);
      constructor() {
        super(base(s, "item"));
      }
    }
    const item = new Item();
    let raises = 0;
    item.guarded.canExecuteChanged.subscribe(() => {
      raises += 1;
      item.guarded.canExecute(); // the bound control re-queries
    });
    assert.equal(item.guarded.canExecute(), true);
    other.open = false;
    assert.equal(raises, 1, "the decorator's own predicate");
    gate.open = false;
    assert.equal(raises, 2, "the inner command's raise, forwarded once (no second raise from the decorator)");
  });
});

describe("R9.6 the development bound counts repetitions", () => {
  it("two effects that keep writing each other's inputs overflow and are both named", () => {
    const s = services();
    class PingPong extends ComponentVM {
      declare go: boolean;
      declare a: number;
      declare b: number;
      constructor() {
        super(base(s, "pingpong"));
        this.observable({ go: false, a: 0, b: 0 });
        this.effect(() => {
          if (this.go) this.b = this.a + 1;
        });
        this.effect(() => {
          if (this.go) this.a = this.b + 1;
        });
      }
    }
    const vm = new PingPong();
    vm.construct();
    assert.throws(
      () => {
        vm.go = true;
      },
      (error: unknown) =>
        error instanceof ReactiveOverflowError && (error.message.match(/:effect#\d+ x\d+/g) ?? []).length >= 2,
    );
    vm.go = false;
    assert.equal(vm.status, ConstructionStatus.Constructed, "the graph still works");
  });
});

describe("R15.2 state first: a publication commits before it delivers", () => {
  it("a hub observer of a hand-notifying view-model reads a computed over it through read() fresh", () => {
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
    const seen: string[] = [];
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === legacy) seen.push(`doubled=${String(reactive.doubled)}`);
    });
    legacy.bump();
    legacy.bump();
    assert.deepEqual(seen, ["doubled=2", "doubled=4"]);
  });

  it("a write by a hub observer during a publication is announced after the library's own local emission", () => {
    const s = services();
    class Mirror extends ComponentVM {
      declare copy: number;
      constructor() {
        super(base(s, "mirror"));
        this.observable({ copy: 0 });
      }
    }
    const mirror = new Mirror();
    const legacy = new Legacy(base(s, "legacy"));
    const order: string[] = [];
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === legacy) mirror.copy = legacy.count;
    });
    legacy.propertyChanged.subscribe((name) => order.push(`legacy:${name}`));
    mirror.propertyChanged.subscribe((name) => order.push(`mirror:${name}`));
    legacy.bump();
    assert.deepEqual(order, ["legacy:count", "mirror:copy"]);
  });

  it("a command raise commits before delivery: a listener that subscribed first reads a computed over canExecute() fresh", () => {
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
    const seen: boolean[] = [];
    toolbar.save.canExecuteChanged.subscribe(() => seen.push(toolbar.saveVisible));
    activate(toolbar);
    outside.ready = true;
    toolbar.save.raiseCanExecuteChanged();
    assert.deepEqual(seen, [true]);
  });

  it("an expansion change commits before its stream delivers", () => {
    const s = services();
    const expansion = new ExpandableState(false);
    const seen: boolean[] = [];
    class Item extends ComponentVM {
      constructor() {
        super(base(s, "item"));
        this.computed("open");
      }
      get open(): boolean {
        return read(expansion, "isExpanded");
      }
    }
    const item = new Item();
    expansion.isExpandedChanged.subscribe(() => seen.push(item.open));
    activate(item);
    expansion.expand();
    expansion.collapse();
    assert.deepEqual(seen, [true, false]);
  });
});

describe("R6.10 equalities run in their own context", () => {
  it("a write inside an equality throws ReactiveWriteError there, is not applied, and is reported once per call", async () => {
    await streamFed();
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
            audit.comparisons += 1;
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
    source.level = 2;
    assert.equal(audit.comparisons, 0);
    assert.equal(source.rounded, 2);
    const errors = await streamFed();
    assert.equal(errors.length, 1, "the changed-set check reuses the comparison of the evaluation");
    assert.ok(errors[0] instanceof ReactiveWriteError);
  });
});

describe("R16 error equality", () => {
  it("an error that changes to an equal error (the same class and message) is not a change", async () => {
    await streamFed();
    const s = services();
    class Parser extends ComponentVM {
      declare text: string;
      constructor() {
        super(base(s, "parser"));
        this.observable({ text: "1" });
        this.computed("value");
      }
      get value(): number {
        if (this.text.startsWith("x")) throw new Error("bad input");
        return Number(this.text);
      }
    }
    const names: string[] = [];
    quietly(() => {
      const vm = new Parser();
      activate(vm);
      s.hub.messages.subscribe((m) => {
        if (m instanceof PropertyChangedMessage) names.push(m.propertyName);
      });
      vm.text = "x1";
      vm.text = "x2";
    });
    assert.deepEqual(names, ["text", "value", "text"]);
    assert.equal((await streamFed()).length, 1, "reported once: at the transition into error");
  });
});

describe("R12.3 asynchronous effects", () => {
  it("the rejection of a Promise-returning effect goes to the stream-fed route", async () => {
    await streamFed();
    const s = services();
    class Host extends ComponentVM {
      constructor() {
        super(base(s, "host"));
        const body = async (): Promise<void> => {
          await Promise.resolve();
          throw new Error("async effect failed");
        };
        this.effect(body as unknown as () => void);
      }
    }
    new Host().construct();
    const errors = (await streamFed()).map(String);
    assert.ok(errors.some((error) => error.includes("async effect failed")), errors.join("\n"));
  });
});

describe("R3.13 state registered after activation", () => {
  it("re-evaluates and announces the view-model's computeds and is reported once per class in development", () => {
    const reports = captureReports();
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
        this.observable({ extra: 5 });
      }
    }
    const vm = new Late();
    const names: string[] = [];
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === vm) names.push(m.propertyName);
    });
    vm.construct();
    assert.equal(vm.label, "extra=5");
    assert.deepEqual(names, ["label"]);
    assert.equal(reports.filter((report) => report.startsWith("Late: state extra registered after activation")).length, 1);
  });
});
