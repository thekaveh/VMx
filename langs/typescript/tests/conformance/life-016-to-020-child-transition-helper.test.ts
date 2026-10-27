// LIFE-016..LIFE-020: the supported child-transition helper
// (`_transitionChildren`) and depth-first member disposal (`ownMember`) on a
// leaf VM subclassed from outside the library (spec/02-lifecycle.md §6.1 and
// §7.1, ADR-0162).

import { describe, expect, it } from "vitest";
import type { SchedulerLike } from "rxjs";
import {
  ComponentVM,
  ComponentVMBase,
  ConstructionStatus as S,
  ConstructionStatusChangedMessage,
  GroupVM,
  MessageHub,
  RxDispatcher,
  ViewModelType,
  type IDispatcher,
  type IMessageHub,
} from "../../src/index.js";

/** A background scheduler that runs queued work only when asked. */
class DeferredScheduler {
  #work: Array<() => void> = [];

  schedule(work: () => void): { unsubscribe(): void } {
    this.#work.push(work);
    return { unsubscribe() {} };
  }

  runAll(): void {
    while (this.#work.length > 0) {
      const batch = this.#work;
      this.#work = [];
      for (const work of batch) work();
    }
  }
}

function setup() {
  const bg = new DeferredScheduler();
  const hub = new MessageHub();
  const foreground = RxDispatcher.immediate();
  const background = new RxDispatcher(foreground.foreground, bg as unknown as SchedulerLike);
  const log: string[] = [];
  hub.messages.subscribe((message) => {
    if (message instanceof ConstructionStatusChangedMessage) {
      log.push(`${message.senderName}:${S[message.status]}`);
    }
  });
  const child = (
    name: string,
    opts: { background?: boolean; failConstruct?: boolean; onConstruct?: () => void } = {},
  ): ComponentVM =>
    ComponentVM.builder()
      .name(name)
      .services(hub, opts.background === true ? background : foreground)
      .background(opts.background === true)
      .onConstruct(() => {
        opts.onConstruct?.();
        if (opts.failConstruct === true) throw new Error(`${name} failed`);
      })
      .build();
  return { bg, hub, foreground, log, child };
}

/** A consumer leaf VM that transitions the children it is given. */
class LeafVM extends ComponentVMBase {
  constructor(
    hub: IMessageHub,
    dispatcher: IDispatcher,
    private readonly kids: readonly ComponentVMBase[],
    private readonly opts: { after?: () => void; destructOrder?: readonly ComponentVMBase[] } = {},
  ) {
    super({ name: "parent", hub, dispatcher });
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  protected override _onConstruct(): void {
    super._onConstruct();
    this._transitionChildren(this.kids, true, this.opts.after);
  }

  protected override _onDestruct(): void {
    this._transitionChildren(this.opts.destructOrder ?? this.kids, false, () => {
      super._onDestruct();
    });
  }
}

/** A consumer leaf VM that registers member VMs for disposal. */
class MemberHostVM extends ComponentVMBase {
  constructor(hub: IMessageHub, dispatcher: IDispatcher) {
    super({ name: "parent", hub, dispatcher });
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  register<T extends ComponentVMBase>(member: T): T {
    return this.ownMember(member);
  }
}

class ThrowingDisposeVM extends ComponentVMBase {
  constructor(name: string, hub: IMessageHub, dispatcher: IDispatcher, readonly failure: Error) {
    super({ name, hub, dispatcher });
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  protected override _onDispose(): void {
    throw this.failure;
  }
}

describe("LIFE-016", () => {
  it("defers the parent's terminal status until a background child settles", () => {
    const s = setup();
    const a = s.child("a", { background: true });
    const b = s.child("b");
    let afterRuns = 0;
    const parent = new LeafVM(s.hub, s.foreground, [a, b], {
      after: () => {
        afterRuns += 1;
        s.log.push("after");
      },
    });

    parent.construct();

    expect(parent.status).toBe(S.Constructing);
    expect(a.status).toBe(S.Constructing);
    expect(b.status).toBe(S.Destructed);
    expect(afterRuns).toBe(0);

    s.bg.runAll();

    expect(a.status).toBe(S.Constructed);
    expect(b.status).toBe(S.Constructed);
    expect(parent.status).toBe(S.Constructed);
    expect(afterRuns).toBe(1);
    expect(s.log).toEqual([
      "parent:Constructing",
      "a:Constructing",
      "a:Constructed",
      "b:Constructing",
      "b:Constructed",
      "after",
      "parent:Constructed",
    ]);
  });
});

describe("LIFE-017", () => {
  it("rolls the parent back, keeps constructed siblings and never starts later ones", () => {
    const s = setup();
    const a = s.child("a");
    const b = s.child("b", { failConstruct: true });
    const c = s.child("c");
    const parent = new LeafVM(s.hub, s.foreground, [a, b, c]);

    expect(() => parent.construct()).toThrow("b failed");

    expect(parent.status).toBe(S.Destructed);
    expect(a.status).toBe(S.Constructed);
    expect(b.status).toBe(S.Destructed);
    expect(c.status).toBe(S.Destructed);
    expect(s.log).not.toContain("c:Constructing");
  });
});

describe("LIFE-018", () => {
  it("disposes members depth-first in registration order before the parent", () => {
    const s = setup();
    const grandchild = s.child("grandchild");
    const first = GroupVM.builder<ComponentVM>()
      .name("first")
      .services(s.hub, s.foreground)
      .children(() => [grandchild])
      .build();
    const second = s.child("second");
    const parent = new MemberHostVM(s.hub, s.foreground);
    parent.register(first);
    parent.register(second);
    first.construct();
    second.construct();
    parent.construct();
    expect(grandchild.status).toBe(S.Constructed);

    const disposed: object[] = [];
    s.hub.messages.subscribe((message) => {
      if (message instanceof ConstructionStatusChangedMessage && message.status === S.Disposed) {
        disposed.push(message.sender);
      }
    });

    parent.dispose();

    expect(disposed).toHaveLength(4);
    expect(disposed[0]).toBe(grandchild);
    expect(disposed[1]).toBe(first);
    expect(disposed[2]).toBe(second);
    expect(disposed[3]).toBe(parent);
  });

  it("keeps disposing after a member's disposal hook throws, then surfaces the first failure", () => {
    const s = setup();
    const failure = new Error("first member failed");
    const parent = new MemberHostVM(s.hub, s.foreground);
    const first = parent.register(new ThrowingDisposeVM("first", s.hub, s.foreground, failure));
    const second = parent.register(s.child("second"));

    expect(() => parent.dispose()).toThrow(failure);

    expect(first.status).toBe(S.Disposed);
    expect(second.status).toBe(S.Disposed);
    expect(parent.status).toBe(S.Disposed);
  });

  it("disposes a member registered after the parent reached Disposed", () => {
    const s = setup();
    const parent = new MemberHostVM(s.hub, s.foreground);
    parent.dispose();
    const late = s.child("late");

    expect(parent.register(late)).toBe(late);

    expect(late.status).toBe(S.Disposed);
  });
});

describe("LIFE-019", () => {
  it("destructs children one at a time in the order the hook passes", () => {
    const s = setup();
    const a = s.child("a");
    const b = s.child("b");
    const c = s.child("c");
    const parent = new LeafVM(s.hub, s.foreground, [a, b, c], { destructOrder: [c, b, a] });
    parent.construct();
    s.log.length = 0;

    parent.destruct();

    expect(s.log).toEqual([
      "parent:Destructing",
      "c:Destructing",
      "c:Destructed",
      "b:Destructing",
      "b:Destructed",
      "a:Destructing",
      "a:Destructed",
      "parent:Destructed",
    ]);
  });
});

describe("LIFE-020", () => {
  it("joins a child that is already constructing instead of restarting it", () => {
    const s = setup();
    let hookRuns = 0;
    const a = s.child("a", { background: true, onConstruct: () => { hookRuns += 1; } });
    const parent = new LeafVM(s.hub, s.foreground, [a]);
    a.construct();
    expect(a.status).toBe(S.Constructing);

    expect(() => parent.construct()).not.toThrow();

    expect(parent.status).toBe(S.Constructing);
    s.bg.runAll();

    expect(hookRuns).toBe(1);
    expect(a.status).toBe(S.Constructed);
    expect(parent.status).toBe(S.Constructed);
    expect(s.log.slice(-2)).toEqual(["a:Constructed", "parent:Constructed"]);
  });
});
