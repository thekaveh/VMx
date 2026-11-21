/**
 * Attack round 2: dispose during propagation, reads of disposed view-models, and leaks. Run Node with --expose-gc
 * for the WeakRef probes.
 *
 * Expectations used:
 * - a design goal: "Dispose releases every computed, effect and dependency edge; a disposed VM is never notified and
 *   never kept alive by the graph".
 * - R5.6: "A disposed VM's node returns its last value and records nothing".
 * - spec 05 §2.3: "A helper call that begins after VM disposal is a no-op on both channels".
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, ConstructionStatus, ExpandableState, PropertyChangedMessage } from "@thekaveh/vmx";
import { read, tracked } from "../src/index.js";
import { base, services, streamFed, tick } from "./support.js";

type Gc = () => void;

function gcOrSkip(t: { skip(message: string): void }): Gc | null {
  const gc = (globalThis as { readonly gc?: Gc }).gc;
  if (gc === undefined) {
    t.skip("run node with --expose-gc");
    return null;
  }
  return gc;
}

async function collectedAfter(ref: WeakRef<object>, gc: Gc, churn: () => void): Promise<boolean> {
  for (let i = 0; i < 20 && ref.deref() !== undefined; i += 1) {
    churn();
    await tick();
    gc();
  }
  return ref.deref() === undefined;
}

describe("attack-r2 leaks", () => {
  it("DD1 a member disposed early is not kept alive by its long-lived owner (WeakRef probe)", async (t) => {
    const gc = gcOrSkip(t);
    if (gc === null) return;
    const s = services();
    class Shell extends ComponentVM {
      declare page: number;
      constructor() {
        super(base(s, "shell"));
        this.observable({ page: 0 });
      }
      /** Navigation: one member per page, the previous page disposed (a keyed slot without a slot type). */
      open(): WeakRef<ComponentVM> {
        const page = this.member(new ComponentVM(base(s, `page${String(this.page)}`)));
        page.dispose();
        this.page += 1;
        return new WeakRef(page);
      }
    }
    const shell = new Shell();
    shell.construct();
    const ref = shell.open();
    assert.equal(
      await collectedAfter(ref, gc, () => undefined),
      true,
      "the disposed member is still reachable (the owner's member list keeps it)",
    );
  });

  it("DD1c control: the same page, disposed but never registered as a member, is collected", async (t) => {
    const gc = gcOrSkip(t);
    if (gc === null) return;
    const s = services();
    class Shell extends ComponentVM {
      constructor() {
        super(base(s, "shell"));
        this.observable({});
      }
      open(): WeakRef<ComponentVM> {
        const page = new ComponentVM(base(s, "page"));
        page.dispose();
        return new WeakRef(page);
      }
    }
    const shell = new Shell();
    shell.construct();
    const ref = shell.open();
    assert.equal(await collectedAfter(ref, gc, () => undefined), true);
  });

  it("DD2 a disposed VM that read long-lived helpers through tracked(), read() and canExecute() is collectable (expected to hold)", async (t) => {
    const gc = gcOrSkip(t);
    if (gc === null) return;
    const s = services();
    const common = tracked(new ExpandableState(false));
    const other = new ExpandableState(false);
    class Settings extends ComponentVM {
      declare online: boolean;
      readonly save = this.relayCommand(
        () => undefined,
        () => this.online,
      );
      constructor() {
        super(base(s, "settings"));
        this.observable({ online: true });
      }
    }
    const settings = new Settings();
    settings.construct();
    const make = (): WeakRef<ComponentVM> => {
      class Item extends ComponentVM {
        constructor() {
          super(base(s, "item"));
          this.computed("summary");
          this.effect(() => {
            void this.summary;
          });
        }
        get summary(): string {
          return `${String(common.isExpanded)}/${String(read(other, "isExpanded"))}/${String(settings.save.canExecute())}`;
        }
      }
      const item = new Item();
      item.construct();
      void item.summary;
      item.dispose();
      return new WeakRef(item);
    };
    const ref = make();
    assert.equal(
      await collectedAfter(ref, gc, () => {
        common.toggleExpansion();
        other.toggleExpansion();
        settings.online = !settings.online;
      }),
      true,
    );
  });
});

describe("attack-r2 reads of disposed view-models", () => {
  it("DD3 a memo that was never read before its view-model was disposed does not read as undefined", () => {
    const s = services();
    class Box extends ComponentVM {
      readonly #doubled = this.memo(() => 21 * 2);
      constructor() {
        super(base(s, "box"));
      }
      get doubled(): number {
        return this.#doubled.value;
      }
    }
    const box = new Box();
    box.dispose();
    const value: number = box.doubled; // typed number
    assert.equal(value, 42, `read ${String(value)}`);
  });

  it("DD4 control: a registered computed that was never evaluated before disposal falls back to its getter (expected to hold)", () => {
    const s = services();
    class Box extends ComponentVM {
      constructor() {
        super(base(s, "box"));
        this.computed("doubled");
      }
      get doubled(): number {
        return 21 * 2;
      }
    }
    const box = new Box();
    box.dispose();
    assert.equal(box.doubled, 42);
  });
});

describe("attack-r2 dispose during propagation", () => {
  // Fix round 2 (R9.5): a disposal first delivers the announcements of the writes accepted before
  // it (DD7). `b` was accepted before the observer disposed the VM, so it is announced; the direct send `legacy`
  // begins after the disposal and is dropped (spec 05 §2.3). The scenario is unchanged; the expectation moved from
  // ["source", "a"] to ["source", "a", "b"].
  it("DD5 a VM disposed by a hub observer during a producer flush: its accepted writes are announced, the later direct send is dropped", async () => {
    await streamFed();
    const s = services();
    class Mixed extends ComponentVM {
      declare source: number;
      declare a: number;
      declare b: number;
      constructor() {
        super(base(s, "mixed"));
        this.observable({ source: 0, a: 0, b: 0 });
        this.effect(() => {
          const v = this.source;
          if (v === 0) return;
          this.a = v;
          this.b = v;
          this._notifyPropertyChanged("legacy"); // flushes a and b first (R9.8)
        });
      }
    }
    const vm = new Mixed();
    vm.construct();
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === vm && m.propertyName === "a") vm.dispose();
    });
    const names: string[] = [];
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === vm) names.push(m.propertyName);
    });
    vm.source = 1;
    assert.equal(vm.status, ConstructionStatus.Disposed);
    assert.deepEqual(names, ["source", "a", "b"]);
    assert.deepEqual(await streamFed(), []);
  });

  it("DD7 a write accepted before disposal, made during a drain, is still announced (as the hand-written equivalent is)", () => {
    const s = services();
    class Dialog extends ComponentVM {
      declare result: string;
      constructor() {
        super(base(s, "dialog"));
        this.observable({ result: "" });
      }
      close(value: string): void {
        this.result = value;
        this.dispose();
      }
    }
    class HandDialog extends ComponentVM {
      #result = "";
      get result(): string {
        return this.#result;
      }
      close(value: string): void {
        this.#result = value;
        this._notifyPropertyChanged("result");
        this.dispose();
      }
    }
    class Trigger extends ComponentVM {
      declare go: number;
      constructor() {
        super(base(s, "trigger"));
        this.observable({ go: 0 });
      }
    }
    const dialog = new Dialog();
    const hand = new HandDialog(base(s, "hand"));
    const trigger = new Trigger();
    // A keyboard shortcut handled by a hub observer closes both dialogs (a drain is active).
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === trigger) {
        dialog.close("ok");
        hand.close("ok");
      }
    });
    const results: string[] = [];
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.propertyName === "result") results.push(m.senderName);
    });
    trigger.go = 1;
    assert.equal(dialog.result, "ok", "the write was accepted before the disposal");
    assert.deepEqual([...results].sort(), ["dialog", "hand"]);
  });

  it("DD6 an effect cleanup that disposes its own VM during a destruct ends Disposed without errors (expected to hold)", async () => {
    await streamFed();
    const s = services();
    const log: string[] = [];
    class Host extends ComponentVM {
      declare n: number;
      constructor() {
        super(base(s, "host"));
        this.observable({ n: 0 });
        this.effect(() => {
          log.push(`run:${String(this.n)}`);
          return () => {
            log.push("cleanup");
            this.dispose();
          };
        });
        this.whileConstructed(() => () => log.push("teardown"));
      }
      protected override _onDispose(): void {
        log.push("dispose");
      }
    }
    const vm = new Host();
    vm.construct();
    vm.destruct();
    vm.n = 1;
    assert.equal(vm.status, ConstructionStatus.Disposed);
    assert.deepEqual(log, ["run:0", "teardown", "cleanup", "dispose"]);
    assert.deepEqual(await streamFed(), []);
  });
});
