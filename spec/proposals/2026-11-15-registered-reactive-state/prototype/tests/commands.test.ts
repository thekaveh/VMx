/**
 * RSTATE-022 and RSTATE-023: tracked predicates, and commands owned by the helpers.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM } from "@thekaveh/vmx";
import { Subject } from "rxjs";
import { activate } from "../src/index.js";
import { base, type Services, services, tick } from "./support.js";

class Editor extends ComponentVM {
  declare readonly text: string;
  declare readonly locked: boolean;
  readonly write;
  readonly external = new Subject<void>();
  predicateCalls = 0;
  readonly saveCommand = this.relayCommand(
    () => undefined,
    () => {
      this.predicateCalls += 1;
      return this.text.length > 0 && !this.locked;
    },
  );
  readonly pickCommand = this.relayCommandOf<string>(
    () => undefined,
    (choice) => (choice === "a" ? this.text.length > 0 : !this.locked),
  );
  readonly throwingCommand = this.relayCommand(
    () => undefined,
    () => {
      if (this.locked) throw new Error("locked");
      return this.text === "go";
    },
  );
  readonly triggeredCommand = this.relayCommand(() => undefined, undefined, { triggers: [this.external] });
  readonly asyncCommand = this.asyncRelayCommand(
    async (signal) => {
      await new Promise<void>((resolve, reject) => {
        signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
        setTimeout(resolve, 50);
      });
    },
    () => !this.locked,
    { throwOnCancel: true },
  );
  constructor(s: Services) {
    super(base(s, "editor"));
    this.write = this.observable({ text: "", locked: false });
  }
}

function raises(command: { readonly canExecuteChanged: { subscribe(fn: () => void): unknown } }): { count: number } {
  const counter = { count: 0 };
  command.canExecuteChanged.subscribe(() => {
    counter.count += 1;
  });
  return counter;
}

describe("RSTATE-022 tracked predicates", () => {
  it("raise once per settle that changes a node of the set; the library never evaluates the predicate", () => {
    const vm = new Editor(services());
    activate(vm);
    const counter = raises(vm.saveCommand);
    assert.equal(vm.saveCommand.canExecute(), false);
    const evaluated = vm.predicateCalls;
    vm.write({ text: "x", locked: true });
    assert.equal(counter.count, 1);
    assert.equal(vm.predicateCalls, evaluated, "the settle does not evaluate the predicate");
    // The set was cleared at the raise: no re-read, no further raise (spec 04 §4).
    vm.write({ locked: false });
    assert.equal(counter.count, 1);
    assert.equal(vm.saveCommand.canExecute(), true);
    vm.write({ text: "xy" });
    assert.equal(counter.count, 2);
  });

  it("a write that does not touch the set raises nothing", () => {
    const vm = new Editor(services());
    vm.write({ text: "x" });
    assert.equal(vm.saveCommand.canExecute(), true);
    const counter = raises(vm.saveCommand);
    vm.predicateCalls = 0;
    vm.change(() => {
      vm.write({ locked: true });
      vm.write({ locked: false });
    });
    assert.equal(counter.count, 0, "a change that changed back is no change");
  });

  it("a throwing predicate reads as false and keeps the reads it made", () => {
    const vm = new Editor(services());
    const counter = raises(vm.throwingCommand);
    vm.write({ locked: true });
    assert.equal(vm.throwingCommand.canExecute(), false);
    vm.write({ text: "go" });
    assert.equal(counter.count, 0, "text was not read before the throw");
    vm.write({ locked: false });
    assert.equal(counter.count, 1);
    assert.equal(vm.throwingCommand.canExecute(), true);
  });

  it("a parameterized command tracks the union of the reads since its last raise", () => {
    const vm = new Editor(services());
    const counter = raises(vm.pickCommand);
    assert.equal(vm.pickCommand.canExecute("a"), false);
    assert.equal(vm.pickCommand.canExecute("b"), true);
    vm.write({ locked: true });
    assert.equal(counter.count, 1);
    vm.write({ text: "z" });
    assert.equal(counter.count, 1, "the set was cleared at the raise");
  });

  it("a computed that calls canExecute() depends on the same nodes", () => {
    const s = services();
    class Toolbar extends ComponentVM {
      readonly editor: Editor;
      constructor() {
        super(base(s, "toolbar"));
        this.editor = this.member(new Editor(s));
        this.computed("saveVisible");
      }
      get saveVisible(): boolean {
        return this.editor.saveCommand.canExecute();
      }
    }
    const toolbar = new Toolbar();
    activate(toolbar);
    const names: string[] = [];
    toolbar.propertyChanged.subscribe((name) => names.push(name));
    toolbar.editor.write({ text: "a" });
    assert.deepEqual(names, ["saveVisible"]);
    assert.equal(toolbar.saveVisible, true);
  });
});

describe("RSTATE-023 commands created by the helpers are owned; triggers pass through", () => {
  it("disposal of the view-model disposes its commands", () => {
    const vm = new Editor(services());
    vm.write({ text: "x" });
    assert.equal(vm.saveCommand.canExecute(), true);
    vm.dispose();
    assert.equal(vm.saveCommand.canExecute(), false);
    assert.equal(vm.triggeredCommand.canExecute(), false);
    assert.equal(vm.asyncCommand.canExecute(), false);
  });

  it("explicit triggers and throwOnCancel pass through", async () => {
    const vm = new Editor(services());
    const counter = raises(vm.triggeredCommand);
    vm.external.next();
    assert.equal(counter.count, 1);
    const running = vm.asyncCommand.executeAsync();
    await tick();
    assert.equal(vm.asyncCommand.isExecuting, true);
    vm.asyncCommand.cancel();
    await assert.rejects(running, /aborted/);
    vm.dispose();
  });
});
