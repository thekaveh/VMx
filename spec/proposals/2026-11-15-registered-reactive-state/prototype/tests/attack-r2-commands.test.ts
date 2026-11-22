/**
 * Attack round 2: commands whose predicates read tracked state across view-models, combined with the VMx command
 * combinators that code would use next to the helpers (`wrapWith` and the V3 helper commands).
 *
 * Expectations used: design goal V3 "canExecute re-evaluates when its tracked dependencies change" and
 * "raiseCanExecuteChanged() called when its dependencies change"; R10.7.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { type AsyncResourceVM, ComponentVM, succeedWith, wrapWith } from "@thekaveh/vmx";
import { activate } from "../src/index.js";
import { base, type Services, services, tick } from "./support.js";

class Gate extends ComponentVM {
  declare open: boolean;
  constructor(s: Services, name = "gate") {
    super(base(s, name));
    this.observable({ open: true });
  }
}

describe("attack-r2 commands across view-models", () => {
  // Fix round 2 (R10.2): every VMx command tracks its own predicate, including the extra predicate
  // of a DecoratorCommand (wrapWith). The scenario is unchanged; the expectation moved from the documented gap
  // (raises 0) to the resolved rule (raises 1).
  it("CM1 wrapWith(resource.reloadCommand, predicate over registered state) is raised when that state changes", async () => {
    const s = services();
    const gate = new Gate(s);
    class Item extends ComponentVM {
      readonly query: AsyncResourceVM<string>;
      readonly retry;
      constructor() {
        super(base(s, "item"));
        this.query = this.keyedResource({ key: () => "fixed", load: async () => "data", autoLoad: true });
        this.retry = wrapWith(this.query.reloadCommand, () => gate.open);
      }
    }
    const item = new Item();
    item.construct();
    await tick();
    assert.equal(item.retry.canExecute(), true);
    let raises = 0;
    item.retry.canExecuteChanged.subscribe(() => {
      raises += 1;
    });
    gate.open = false;
    assert.equal(item.retry.canExecute(), false);
    assert.equal(raises, 1, "the bound control is told to re-query once");
  });

  it("CM2 a helper command over the same inputs is raised (control for CM1, expected to hold)", async () => {
    const s = services();
    const gate = new Gate(s);
    class Item extends ComponentVM {
      readonly query: AsyncResourceVM<string>;
      readonly retry;
      constructor() {
        super(base(s, "item"));
        this.query = this.keyedResource({ key: () => "fixed", load: async () => "data", autoLoad: true });
        this.retry = this.asyncRelayCommand(
          (signal) => this.query.reload(signal),
          () => this.query.reloadCommand.canExecute() && gate.open,
        );
      }
    }
    const item = new Item();
    item.construct();
    await tick();
    assert.equal(item.retry.canExecute(), true);
    let raises = 0;
    item.retry.canExecuteChanged.subscribe(() => {
      raises += 1;
    });
    gate.open = false;
    assert.equal(raises, 1);
    assert.equal(item.retry.canExecute(), false);
  });

  it("CM3 succeedWith over two helper commands forwards each tracked raise (expected to hold)", () => {
    const s = services();
    const first = new Gate(s, "first");
    const second = new Gate(s, "second");
    class Toolbar extends ComponentVM {
      readonly a = this.relayCommand(
        () => undefined,
        () => first.open,
      );
      readonly b = this.relayCommand(
        () => undefined,
        () => second.open,
      );
      readonly both = succeedWith(this.a, this.b);
      constructor() {
        super(base(s, "toolbar"));
      }
    }
    const toolbar = new Toolbar();
    let raises = 0;
    toolbar.both.canExecuteChanged.subscribe(() => {
      raises += 1;
      toolbar.both.canExecute(); // the bound control re-queries
    });
    assert.equal(toolbar.both.canExecute(), true);
    first.open = false;
    second.open = false;
    assert.equal(raises, 2);
  });

  it("CM4 a predicate over a computed of a VM that is activated later keeps raising across the activation (expected to hold)", () => {
    const s = services();
    class Source extends ComponentVM {
      declare n: number;
      constructor() {
        super(base(s, "source"));
        this.observable({ n: 0 });
        this.computed("positive");
      }
      get positive(): boolean {
        return this.n > 0;
      }
    }
    const source = new Source();
    class Consumer extends ComponentVM {
      readonly go = this.relayCommand(
        () => undefined,
        () => source.positive,
      );
      constructor() {
        super(base(s, "consumer"));
      }
    }
    const consumer = new Consumer();
    let raises = 0;
    consumer.go.canExecuteChanged.subscribe(() => {
      raises += 1;
      consumer.go.canExecute();
    });
    assert.equal(consumer.go.canExecute(), false); // plain getter: the frame reads n
    activate(source);
    source.n = 1;
    assert.equal(raises, 1);
    source.n = 2; // positive stays true
    source.n = 0;
    assert.equal(raises, 2, `raises ${String(raises)}`);
    assert.equal(consumer.go.canExecute(), false);
  });
});
