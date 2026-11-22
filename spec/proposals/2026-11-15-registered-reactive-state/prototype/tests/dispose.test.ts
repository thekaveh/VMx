/**
 * RSTATE-032: the dispose order, a disposal publishes nothing, and retention (the WeakRef probe; run Node with
 * --expose-gc).
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, ConstructionStatus, ConstructionStatusChangedMessage, PropertyChangedMessage } from "@thekaveh/vmx";
import { activate } from "../src/index.js";
import { existingState } from "../src/vmState.js";
import { base, type Services, services, tick } from "./support.js";

class Settings extends ComponentVM {
  declare theme: string;
  declare unit: string;
  constructor(s: Services) {
    super(base(s, "settings"));
    this.observable({ theme: "light", unit: "s" });
  }
}

describe("RSTATE-032 dispose order and retention", () => {
  // Fix round 2 (R13.3): the reactions are torn down first, while the members they used are still
  // alive (attack LC3); members reach Disposed before the owner publishes Disposed (LIFE-013), so the teardowns now
  // come before the owner's _onDispose. The scenario is unchanged; the teardowns moved from after "onDispose" to the
  // start. The rest of the order (members, Disposed, _onDispose, own() LIFO, streams) is unchanged.
  it("reaction teardowns (LIFO), members, Disposed, _onDispose, own() resources (LIFO) with the commands, streams", () => {
    const s = services();
    const log: string[] = [];
    class Member extends ComponentVM {
      protected override _onDispose(): void {
        log.push("member:dispose");
      }
    }
    class Owner extends ComponentVM {
      readonly command = this.relayCommand(() => undefined);
      constructor() {
        super(base(s, "owner"));
        this.member(new Member(base(s, "member")));
        this.whileConstructed(() => () => log.push("teardown:a"));
        this.whileConstructed(() => () => log.push("teardown:b"));
        this.own(() => log.push("own:first"));
        this.own(() => log.push("own:last"));
      }
      protected override _onDispose(): void {
        log.push("onDispose");
      }
    }
    const owner = new Owner();
    owner.command.canExecuteChanged.subscribe({ complete: () => log.push("command:disposed") });
    owner.propertyChanged.subscribe({ complete: () => log.push("streams") });
    s.hub.messages.subscribe((message) => {
      if (message instanceof ConstructionStatusChangedMessage && message.status === ConstructionStatus.Disposed) {
        log.push(`Disposed:${message.senderName}`);
      }
    });
    owner.construct();
    owner.dispose();
    // The member's own dispose runs its Disposed and _onDispose before the owner publishes Disposed (R13.3 step 3).
    assert.deepEqual(log, [
      "teardown:b",
      "teardown:a",
      "Disposed:member",
      "member:dispose",
      "Disposed:owner",
      "onDispose",
      "own:last",
      "own:first",
      "command:disposed",
      "streams",
    ]);
  });

  it("a disposal publishes nothing; nodes keep their last values and record no edges", () => {
    const s = services();
    const settings = new Settings(s);
    class Item extends ComponentVM {
      constructor() {
        super(base(s, "item"));
        this.computed("label");
      }
      get label(): string {
        return settings.theme.toUpperCase();
      }
      protected override _onDispose(): void {
        settings.theme = "from-dispose";
      }
    }
    const item = new Item();
    activate(item);
    class Reader extends ComponentVM {
      constructor() {
        super(base(s, "reader"));
        this.computed("echo");
      }
      get echo(): string {
        return item.label;
      }
    }
    const reader = new Reader();
    activate(reader);
    const fromItem: string[] = [];
    s.hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage && message.sender === item) fromItem.push(message.propertyName);
    });
    item.dispose();
    assert.deepEqual(fromItem, [], "the write in _onDispose re-evaluated nothing of the disposing item");
    assert.equal(item.label, "LIGHT", "last value");
    settings.theme = "dark";
    assert.deepEqual(fromItem, []);
    assert.equal(item.label, "LIGHT");
    assert.equal(reader.echo, "LIGHT");
  });

  it("an effect that disposes its own view-model keeps no edge to what it read", () => {
    const s = services();
    const settings = new Settings(s);
    let runs = 0;
    class SelfDisposing extends ComponentVM {
      constructor() {
        super(base(s, "self"));
        this.effect(() => {
          runs += 1;
          if (settings.theme !== "stop") return;
          // A dependency that is new in this run, read before the disposal.
          void settings.unit;
          this.dispose();
        });
      }
    }
    const vm = new SelfDisposing();
    vm.construct();
    settings.theme = "stop";
    assert.equal(vm.status, ConstructionStatus.Disposed);
    settings.theme = "again";
    assert.equal(runs, 2);
    // White-box: neither node keeps an observer.
    assert.equal(existingState(settings)?.published.get("theme")?.node.observers.size, 0);
    assert.equal(existingState(settings)?.published.get("unit")?.node.observers.size, 0);
  });

  it("a disposed view-model is collectable while its former sources keep changing (WeakRef probe)", async (t) => {
    const gc = (globalThis as { readonly gc?: () => void }).gc;
    if (gc === undefined) {
      t.skip("run node with --expose-gc");
      return;
    }
    const s = services();
    const settings = new Settings(s);
    const make = (): WeakRef<object> => {
      class Item extends ComponentVM {
        readonly command = this.relayCommand(
          () => undefined,
          () => settings.theme !== "x",
        );
        readonly #shade = this.memo(() => `${settings.theme}!`);
        constructor() {
          super(base(s, "item"));
          this.computed("label");
          this.effect(() => {
            void settings.theme;
          });
          this.reaction(
            () => settings.theme,
            () => undefined,
            { alive: true },
          );
        }
        get label(): string {
          return `${this.#shade.value}${settings.theme}`;
        }
      }
      const item = new Item();
      item.construct();
      item.command.canExecute();
      settings.theme = "dark";
      const ref = new WeakRef(item);
      item.dispose();
      return ref;
    };
    const ref = make();
    for (let i = 0; i < 20 && ref.deref() !== undefined; i += 1) {
      settings.theme = `theme-${String(i)}`;
      await tick();
      gc();
    }
    assert.equal(ref.deref(), undefined);
  });
});
