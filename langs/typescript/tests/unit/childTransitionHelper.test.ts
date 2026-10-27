/**
 * API edges of the supported child-transition helper (`_transitionChildren`)
 * and member disposal (`ownMember`) for a consumer subclass written outside
 * the library (spec/02-lifecycle.md §6.1 and §7.1, ADR-0162). LIFE-016..020
 * cover the catalog scenarios.
 */
import { describe, expect, it } from "vitest";
import type { SchedulerLike } from "rxjs";
import {
  ComponentVM,
  ComponentVMBase,
  ComponentVMOf,
  ConstructionStatus as S,
  ConstructionStatusChangedMessage,
  ForwardingComponentVM,
  MessageHub,
  RxDispatcher,
  ViewModelType,
  type IDispatcher,
  type IMessageHub,
} from "../../src/index.js";

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
  const child = (name: string, runInBackground = false): ComponentVM =>
    ComponentVM.builder()
      .name(name)
      .services(hub, runInBackground ? background : foreground)
      .background(runInBackground)
      .build();
  return { bg, hub, foreground, background, log, child };
}

class PanelVM extends ComponentVMBase {
  readonly members: ComponentVMBase[] = [];
  after: () => void = () => undefined;

  constructor(
    hub: IMessageHub,
    dispatcher: IDispatcher,
    opts: { name?: string; background?: boolean } = {},
  ) {
    super({ name: opts.name ?? "panel", hub, dispatcher, background: opts.background ?? false });
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  register<T extends ComponentVMBase>(member: T): T {
    this.members.push(member);
    return this.ownMember(member);
  }

  ownResource(resource: () => void): void {
    this.own(resource);
  }

  /** Calls the helper outside any lifecycle hook. */
  transitionNow(): void {
    this._transitionChildren(this.members, true);
  }

  protected override _onConstruct(): void {
    super._onConstruct();
    this._transitionChildren(this.members, true, () => this.after());
  }

  protected override _onDestruct(): void {
    this._transitionChildren([...this.members].reverse(), false, () => super._onDestruct());
  }
}

class FailingDisposeVM extends ComponentVMBase {
  constructor(
    name: string,
    hub: IMessageHub,
    private readonly onDispose: () => void,
  ) {
    super({ name, hub, dispatcher: RxDispatcher.immediate() });
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  protected override _onDispose(): void {
    this.onDispose();
  }
}

class MemberDecorator<M> extends ForwardingComponentVM<M> {
  register<T extends ComponentVMBase>(member: T): T {
    return this.ownMember(member);
  }

  transitionNow(children: ComponentVMBase[]): void {
    this._transitionChildren(children, true);
  }
}

describe("_transitionChildren usage guard", () => {
  it("throws outside a lifecycle hook and starts no child", () => {
    const s = setup();
    const panel = new PanelVM(s.hub, s.foreground);
    const a = panel.register(s.child("a"));

    expect(() => panel.transitionNow()).toThrow(/own construct or destruct hook/);

    expect(a.status).toBe(S.Destructed);
    expect(panel.status).toBe(S.Destructed);
  });

  it("throws on a constructed VM too, outside its hooks", () => {
    const s = setup();
    const panel = new PanelVM(s.hub, s.foreground);
    panel.construct();
    const late = panel.register(s.child("late"));

    expect(() => panel.transitionNow()).toThrow(Error);
    expect(late.status).toBe(S.Destructed);
  });

  it("throws when another VM's hook calls this VM's helper", () => {
    const s = setup();
    const b = new PanelVM(s.hub, s.foreground, { name: "b" });
    const child = b.register(s.child("child"));
    let failure: unknown = null;
    const a = ComponentVM.builder()
      .name("a")
      .services(s.hub, s.foreground)
      .onConstruct(() => {
        try {
          b.transitionNow();
        } catch (error) {
          failure = error;
        }
      })
      .build();

    a.construct();

    expect(failure).toBeInstanceOf(Error);
    expect((failure as Error).message).toMatch(/own construct or destruct hook/);
    expect(a.status).toBe(S.Constructed);
    expect(b.status).toBe(S.Destructed);
    expect(child.status).toBe(S.Destructed);
    expect(s.log).not.toContain("child:Constructing");
  });

  it("throws from a forwarding decorator, whose own hooks never run", () => {
    const s = setup();
    const inner = ComponentVMOf.builder<string>()
      .name("inner")
      .model("m")
      .services(s.hub, s.foreground)
      .build();
    const decorator = new MemberDecorator(inner);
    const a = s.child("a");

    expect(() => decorator.transitionNow([a])).toThrow(/own construct or destruct hook/);
    expect(a.status).toBe(S.Destructed);
  });

  it("is allowed from a background parent's hook", () => {
    const s = setup();
    const panel = new PanelVM(s.hub, s.background, { background: true });
    const a = panel.register(s.child("a"));

    panel.construct();
    s.bg.runAll();

    expect(a.status).toBe(S.Constructed);
    expect(panel.status).toBe(S.Constructed);
  });
});

describe("_transitionChildren walk", () => {
  it("runs both reconstruct phases through the helper", () => {
    const s = setup();
    const panel = new PanelVM(s.hub, s.foreground);
    panel.register(s.child("a"));
    panel.register(s.child("b", true));
    panel.construct();
    s.bg.runAll();
    s.log.length = 0;

    panel.reconstruct();
    expect(panel.status).toBe(S.Destructing);
    s.bg.runAll();

    expect(panel.status).toBe(S.Constructed);
    expect(s.log).toEqual([
      "panel:Destructing",
      "b:Destructing",
      "b:Destructed",
      "a:Destructing",
      "a:Destructed",
      "panel:Destructed",
      "panel:Constructing",
      "a:Constructing",
      "a:Constructed",
      "b:Constructing",
      "b:Constructed",
      "panel:Constructed",
    ]);
  });

  it("joins a child that is already destructing", () => {
    const s = setup();
    const panel = new PanelVM(s.hub, s.foreground);
    const a = panel.register(s.child("a", true));
    panel.construct();
    s.bg.runAll();

    a.destruct();
    expect(a.status).toBe(S.Destructing);
    expect(() => panel.destruct()).not.toThrow();
    expect(panel.status).toBe(S.Destructing);

    s.bg.runAll();
    expect(a.status).toBe(S.Destructed);
    expect(panel.status).toBe(S.Destructed);
  });

  it("rolls the parent back when after throws", () => {
    const s = setup();
    const panel = new PanelVM(s.hub, s.foreground);
    const a = panel.register(s.child("a"));
    panel.after = () => {
      throw new Error("after failed");
    };

    expect(() => panel.construct()).toThrow("after failed");
    expect(panel.status).toBe(S.Destructed);
    expect(a.status).toBe(S.Constructed);
  });

  it("skips a child that is already at the target", () => {
    const s = setup();
    const panel = new PanelVM(s.hub, s.foreground);
    const a = panel.register(s.child("a"));
    a.construct();
    s.log.length = 0;

    panel.construct();

    expect(s.log).toEqual(["panel:Constructing", "panel:Constructed"]);
  });
});

describe("ownMember", () => {
  it("returns the member and disposes it before the parent", () => {
    const s = setup();
    const panel = new PanelVM(s.hub, s.foreground);
    const a = s.child("a");

    expect(panel.register(a)).toBe(a);
    panel.dispose();

    expect(s.log).toEqual(["a:Disposed", "panel:Disposed"]);
  });

  it("disposes a member registered after Disposed and surfaces its failure", () => {
    const s = setup();
    const panel = new PanelVM(s.hub, s.foreground);
    panel.dispose();
    const failure = new Error("late member failed");
    const late = new FailingDisposeVM("late", s.hub, () => {
      throw failure;
    });

    expect(() => panel.register(late)).toThrow(failure);
    expect(late.status).toBe(S.Disposed);
  });

  it("rejects registering the VM itself, directly or through a decorator", () => {
    const s = setup();
    const panel = new PanelVM(s.hub, s.foreground);

    expect(() => panel.register(panel)).toThrow(/its own member/);

    const inner = ComponentVMOf.builder<string>()
      .name("inner")
      .model("m")
      .services(s.hub, s.foreground)
      .build();
    const decorator = new MemberDecorator(inner);
    expect(() => decorator.register(inner)).toThrow(/its own member/);
    expect(() => decorator.register(decorator)).toThrow(/its own member/);
  });

  it("registers through a forwarding decorator on the wrapped component", () => {
    const s = setup();
    const inner = ComponentVMOf.builder<string>()
      .name("inner")
      .model("m")
      .services(s.hub, s.foreground)
      .build();
    const decorator = new MemberDecorator(inner);
    const a = decorator.register(s.child("a"));

    inner.dispose();

    expect(a.status).toBe(S.Disposed);
    expect(s.log).toEqual(["a:Disposed", "inner:Disposed"]);
  });

  it("treats a re-entrant dispose of the parent during the member cascade as a no-op", () => {
    const s = setup();
    const panel = new PanelVM(s.hub, s.foreground);
    let reentrantStatus: S | null = null;
    panel.register(
      new FailingDisposeVM("first", s.hub, () => {
        panel.dispose();
        reentrantStatus = panel.status;
      }),
    );
    panel.register(s.child("second"));

    panel.dispose();

    expect(reentrantStatus).toBe(S.Destructed);
    expect(s.log).toEqual(["first:Disposed", "second:Disposed", "panel:Disposed"]);
  });

  it("disposes a member registered during the member cascade at once", () => {
    const s = setup();
    const panel = new PanelVM(s.hub, s.foreground);
    const late = s.child("late");
    panel.register(new FailingDisposeVM("first", s.hub, () => panel.register(late)));

    panel.dispose();

    expect(late.status).toBe(S.Disposed);
    expect(s.log).toEqual(["first:Disposed", "late:Disposed", "panel:Disposed"]);
  });

  it("surfaces the first failure in execution order after the whole teardown", () => {
    const s = setup();
    const panel = new PanelVM(s.hub, s.foreground);
    const first = new Error("first");
    const second = new Error("second");
    const a = panel.register(new FailingDisposeVM("a", s.hub, () => { throw first; }));
    const b = panel.register(new FailingDisposeVM("b", s.hub, () => { throw second; }));
    let released = false;
    panel.register(s.child("c"));
    panel.ownResource(() => {
      released = true;
    });

    expect(() => panel.dispose()).toThrow(first);

    expect(a.status).toBe(S.Disposed);
    expect(b.status).toBe(S.Disposed);
    expect(panel.status).toBe(S.Disposed);
    expect(released).toBe(true);
  });

  it("disposes a registered member once even when it is registered twice", () => {
    const s = setup();
    const panel = new PanelVM(s.hub, s.foreground);
    const a = s.child("a");
    panel.register(a);
    panel.register(a);

    panel.dispose();

    expect(s.log.filter((entry) => entry === "a:Disposed")).toHaveLength(1);
  });
});
