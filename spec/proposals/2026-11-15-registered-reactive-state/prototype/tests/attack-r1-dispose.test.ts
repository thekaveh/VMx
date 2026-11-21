/**
 * Attack round 1: dispose during propagation, a computed that reads a disposed member, and leaks (graph edges kept
 * after dispose). Run Node with --expose-gc for the WeakRef probes.
 *
 * Expectations: "Dispose releases every computed, effect and dependency edge; a disposed VM is never notified and
 * never kept alive by the graph" (a design goal); "computed publication works from construction until dispose (VMx
 * publishes in every status except Disposed)" (a design goal); spec 05 §2.3 (a helper call admitted before disposal
 * completes both emissions; one that begins after disposal is a no-op).
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, ConstructionStatus, PropertyChangedMessage } from "@thekaveh/vmx";
import { activate, untracked } from "../src/index.js";
import { base, type Services, services, tick } from "./support.js";

type Gc = () => void;

function gcOrSkip(t: { skip(message: string): void }): Gc | null {
  const gc = (globalThis as { readonly gc?: Gc }).gc;
  if (gc === undefined) {
    t.skip("run node with --expose-gc");
    return null;
  }
  return gc;
}

class Child extends ComponentVM {
  declare done: boolean;
  constructor(s: Services, name = "child") {
    super(base(s, name));
    this.observable({ done: false });
  }
}

class LongLived extends ComponentVM {
  declare tick: number;
  constructor(s: Services) {
    super(base(s, "longLived"));
    this.observable({ tick: 0 });
  }
}

async function collected(ref: WeakRef<object>, owner: LongLived, gc: Gc): Promise<boolean> {
  for (let i = 0; i < 20 && ref.deref() !== undefined; i += 1) {
    owner.tick = i + 1;
    await tick();
    gc();
  }
  return ref.deref() === undefined;
}

describe("attack-r1 leaks", () => {
  // The dispose is untracked so that the effect does not pick up the child's status through the prototype's own
  // lifecycle hook (that hidden dependency is attack T1a in attack-r1-lifecycle; its extra run happens to clear the
  // edge, so with the hidden dependency fixed this leak is the common case).
  it("D1 an effect that disposes a VM it read in the same run keeps no reference to it (WeakRef probe)", async (t) => {
    const gc = gcOrSkip(t);
    if (gc === null) return;
    const s = services();
    const owner = new LongLived(s);
    owner.construct();
    const make = (): WeakRef<Child> => {
      const holder: { target: Child | null } = { target: new Child(s) };
      const ref = new WeakRef(holder.target as Child);
      owner.effect(() => {
        const c = holder.target;
        if (c === null) return;
        if (c.done) {
          untracked(() => c.dispose());
          holder.target = null;
        }
      });
      (ref.deref() as Child).done = true;
      return ref;
    };
    const ref = make();
    assert.equal(await collected(ref, owner, gc), true, "the disposed child is still reachable");
  });

  it("D1c control: the same effect, with the dispose made outside the run, lets the child go", async (t) => {
    const gc = gcOrSkip(t);
    if (gc === null) return;
    const s = services();
    const owner = new LongLived(s);
    owner.construct();
    const make = (): WeakRef<Child> => {
      const holder: { target: Child | null } = { target: new Child(s) };
      const ref = new WeakRef(holder.target as Child);
      owner.effect(() => {
        const c = holder.target;
        if (c === null) return;
        if (c.done) {
          holder.target = null;
          queueMicrotask(() => c.dispose());
        }
      });
      (ref.deref() as Child).done = true;
      return ref;
    };
    const ref = make();
    assert.equal(await collected(ref, owner, gc), true);
  });
});

describe("attack-r1 dispose during propagation", () => {
  it("D2 a write to the owner's state while its members are being disposed is accepted (owner still Constructed)", () => {
    const s = services();
    let statusAtWrite: ConstructionStatus | undefined;
    let readBack: number | undefined;
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
        this.member(
          new Member(() => {
            statusAtWrite = this.status;
            this.count = 5;
            readBack = this.count;
          }),
        );
      }
    }
    const owner = new Owner();
    owner.construct();
    owner.dispose();
    assert.equal(statusAtWrite, ConstructionStatus.Constructed);
    assert.equal(readBack, 5, "the write was silently dropped while the owner was still Constructed");
  });

  it("D3 a dispose inside a change scope: nothing announced, later writes ignored, no error (expected to hold)", () => {
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
    activate(vm);
    const names: string[] = [];
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage) names.push(m.propertyName);
    });
    vm.change(() => {
      vm.a = 1;
      vm.dispose();
      vm.b = 2;
    });
    assert.deepEqual(names, []);
    assert.equal(vm.a, 1);
    assert.equal(vm.b, 0);
    assert.equal(vm.sum, 0);
  });

  it("D4 a computed that reads a disposed member keeps working and sees the member's last values (expected to hold)", () => {
    const s = services();
    class Text extends ComponentVM {
      declare text: string;
      constructor() {
        super(base(s, "text"));
        this.observable({ text: "a" });
        this.computed("upper");
      }
      get upper(): string {
        return this.text.toUpperCase();
      }
    }
    class Owner extends ComponentVM {
      declare suffix: string;
      readonly child: Text;
      constructor() {
        super(base(s, "owner"));
        this.observable({ suffix: "" });
        this.child = this.member(new Text());
        this.computed("label");
      }
      get label(): string {
        return `${this.child.isConstructed ? "" : "gone:"}${this.child.upper}${this.suffix}`;
      }
    }
    const owner = new Owner();
    owner.construct();
    const announcedLabels: string[] = [];
    s.hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === owner && m.propertyName === "label") announcedLabels.push(owner.label);
    });
    owner.child.text = "b";
    owner.child.dispose();
    owner.child.text = "c";
    owner.suffix = "!";
    assert.deepEqual(announcedLabels, ["B", "gone:B", "gone:B!"]);
    assert.equal(owner.label, "gone:B!");
  });

  it("D5 a source VM disposed by an observer in the middle of a drain: dependents stay consistent (expected to hold)", () => {
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
        this.computed("label");
      }
      get label(): string {
        return settings.theme.toUpperCase();
      }
    }
    const a = new Item("a");
    const b = new Item("b");
    activate(a);
    activate(b);
    const seen: string[] = [];
    s.hub.messages.subscribe((m) => {
      if (!(m instanceof PropertyChangedMessage)) return;
      if (m.sender === a) settings.dispose();
      if (m.sender === a || m.sender === b) seen.push(`${m.senderName}=${a.label}/${b.label}`);
    });
    settings.theme = "dark";
    settings.theme = "ignored";
    assert.deepEqual(seen, ["a=DARK/DARK", "b=DARK/DARK"]);
  });

  it("D6 an owner disposed by its member's _onConstruct during the member walk ends Disposed (expected to hold)", () => {
    const s = services();
    const log: string[] = [];
    class Member extends ComponentVM {
      constructor(readonly hook: () => void) {
        super(base(s, "member"));
      }
      protected override _onConstruct(): void {
        this.hook();
      }
      protected override _onDispose(): void {
        log.push("member:dispose");
      }
    }
    class Owner extends ComponentVM {
      readonly first: Member;
      readonly second: Member;
      constructor() {
        super(base(s, "owner"));
        this.first = this.member(new Member(() => this.dispose()));
        this.second = this.member(new Member(() => log.push("second:construct")));
        this.effect(() => {
          log.push("effect:run");
          return () => log.push("effect:cleanup");
        });
      }
      protected override _onDispose(): void {
        log.push("owner:dispose");
      }
    }
    const owner = new Owner();
    owner.construct();
    assert.equal(owner.status, ConstructionStatus.Disposed);
    assert.equal(owner.first.status, ConstructionStatus.Disposed);
    assert.equal(owner.second.status, ConstructionStatus.Disposed);
    assert.deepEqual(log, ["member:dispose", "member:dispose", "owner:dispose"]);
  });
});
