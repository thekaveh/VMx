/**
 * Attack round 2: members constructed or destructed out of order, and the teardown order of an owner's reactions
 * against its members.
 *
 * Expectations used:
 * - R12.1: an effect's first run happens "while the status is still Constructing and every member is
 *   Constructed" (members are constructed before the owner's reactions start).
 * - design goal V4: members are "constructed after the owner's construct and destructed (reverse order) before the
 *   owner's destruct"; the upstream-candidates plan §1.8.3 rule 3: "Destruct runs _onDestruct, then the teardowns in LIFO order".
 * - The mirror rule (inference): what starts after the members are Constructed is torn down before they are
 *   destructed, so a teardown never sees a member that it relied on already destructed.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, ConstructionStatus } from "@thekaveh/vmx";
import { untracked } from "../src/index.js";
import { base, type Services, services } from "./support.js";

class Connection extends ComponentVM {
  open = false;
  constructor(
    s: Services,
    readonly log: string[],
    name = "connection",
  ) {
    super(base(s, name));
  }
  protected override _onConstruct(): void {
    this.open = true;
    this.log.push(`${this.name}:open`);
  }
  protected override _onDestruct(): void {
    this.open = false;
    this.log.push(`${this.name}:close`);
  }
}

describe("attack-r2 lifecycle: owner reactions against its members", () => {
  it("LC1 destruct mirrors construct: an owner effect's cleanup runs while the member it used is still Constructed", () => {
    const s = services();
    const log: string[] = [];
    class Owner extends ComponentVM {
      readonly connection: Connection;
      constructor() {
        super(base(s, "owner"));
        this.connection = this.member(new Connection(s, log));
        this.effect(() => {
          const connection = this.connection;
          log.push(`effect:subscribe(open=${String(connection.open)})`);
          return () => log.push(`effect:unsubscribe(open=${String(connection.open)})`);
        });
      }
    }
    const owner = new Owner();
    owner.construct();
    owner.destruct();
    assert.deepEqual(log, [
      "connection:open",
      "effect:subscribe(open=true)",
      "effect:unsubscribe(open=true)",
      "connection:close",
    ]);
  });

  it("LC2 the same for whileConstructed: its teardown runs while the member is still Constructed", () => {
    const s = services();
    const log: string[] = [];
    class Owner extends ComponentVM {
      readonly connection: Connection;
      constructor() {
        super(base(s, "owner"));
        this.connection = this.member(new Connection(s, log));
        this.whileConstructed(() => {
          log.push(`setup(open=${String(this.connection.open)})`);
          return () => log.push(`teardown(open=${String(this.connection.open)})`);
        });
      }
    }
    const owner = new Owner();
    owner.construct();
    owner.destruct();
    assert.deepEqual(log, ["connection:open", "setup(open=true)", "teardown(open=true)", "connection:close"]);
  });

  it("LC3 dispose from Constructed: an owner effect's cleanup runs before its member is disposed", () => {
    const s = services();
    const log: string[] = [];
    class Member extends ComponentVM {
      constructor() {
        super(base(s, "member"));
      }
      protected override _onDispose(): void {
        log.push("member:dispose");
      }
    }
    class Owner extends ComponentVM {
      readonly part: Member;
      constructor() {
        super(base(s, "owner"));
        this.part = this.member(new Member());
        this.effect(() => {
          const part = this.part;
          return () => log.push(`effect:cleanup(member=${ConstructionStatus[untracked(() => part.status)]})`);
        });
      }
    }
    const owner = new Owner();
    owner.construct();
    owner.dispose();
    assert.deepEqual(log, ["effect:cleanup(member=Constructed)", "member:dispose"]);
  });
});

describe("attack-r2 lifecycle: when an effect first runs", () => {
  // Spec gap: design goal V6 "Effects run only while the VM is Constructed"; R12.1 (fix round 1) moved the
  // first run into Constructing so that a failing first run can fail the construct. An effect that guards on
  // isConstructed therefore runs twice at every construct.
  it("LC6 GAP: an effect's first run sees status Constructing and isConstructed false, then runs again at Constructed", () => {
    const s = services();
    const seen: string[] = [];
    class Poller extends ComponentVM {
      constructor() {
        super(base(s, "poller"));
        this.effect(() => {
          seen.push(`${ConstructionStatus[untracked(() => this.status)]}:${String(this.isConstructed)}`);
        });
      }
    }
    new Poller().construct();
    assert.deepEqual(seen, ["Constructing:false", "Constructed:true"]);
  });
});

describe("attack-r2 lifecycle: registrations made inside _onConstruct", () => {
  // Fix round 2 (R12.10): a reaction registered while its view-model constructs belongs to that
  // construct and is removed when the view-model next publishes Destructed. The scenario is unchanged; the
  // expectation moved from the documented gap (three live copies) to the resolved rule (one).
  it("LC7 an effect registered in _onConstruct belongs to that construct: every reconstruct replaces it, so one copy runs", () => {
    const s = services();
    class Host extends ComponentVM {
      declare tick: number;
      runs = 0;
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
    }
    const host = new Host();
    host.construct();
    host.reconstruct();
    host.reconstruct();
    host.runs = 0;
    host.tick = 1;
    assert.equal(host.runs, 1, "one live copy of the effect");
  });
});

describe("attack-r2 lifecycle: members registered during transitions", () => {
  it("LC4 a member registered by another member's _onDestruct during the owner's destruct is constructed at the next construct (expected to hold)", () => {
    const s = services();
    const log: string[] = [];
    const holder: { owner: ComponentVM | null; late: Connection | null } = { owner: null, late: null };
    class First extends Connection {
      protected override _onDestruct(): void {
        super._onDestruct();
        holder.late ??= holder.owner?.member(new Connection(s, log, "late")) ?? null;
      }
    }
    class Owner extends ComponentVM {
      constructor() {
        super(base(s, "owner"));
        this.member(new First(s, log, "first"));
      }
    }
    const owner = new Owner();
    holder.owner = owner;
    owner.construct();
    owner.destruct();
    assert.equal(holder.late?.status, ConstructionStatus.Destructed);
    owner.construct();
    assert.equal(holder.late?.status, ConstructionStatus.Constructed);
    assert.deepEqual(log, ["first:open", "first:close", "first:open", "late:open"]);
  });

  it("LC5 reconstruct() restarts each member and each effect exactly once, in construct order (expected to hold)", () => {
    const s = services();
    const log: string[] = [];
    class Owner extends ComponentVM {
      constructor() {
        super(base(s, "owner"));
        this.member(new Connection(s, log, "a"));
        this.member(new Connection(s, log, "b"));
        this.effect(() => {
          log.push("effect:start");
          return () => log.push("effect:stop");
        });
      }
    }
    const owner = new Owner();
    owner.construct();
    log.length = 0;
    owner.reconstruct();
    assert.equal(owner.status, ConstructionStatus.Constructed);
    // Fix round 2 (R13.2): the destruct half is the mirror of construct (reactions, members in
    // reverse, hook), as LC1 to LC3 require; the construct half follows R13.1. The expectation moved from the fix
    // round 1 order (members, hook, reactions) that this comment named.
    assert.deepEqual(log, ["effect:stop", "b:close", "a:close", "a:open", "b:open", "effect:start"]);
  });
});
