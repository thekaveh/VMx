// A container's construct()/destruct() completes only when every child has
// reached Constructed/Destructed (spec/02-lifecycle.md §6, spec/08 §2-§3). A
// background child settles later, so the container must stay in its transient
// status until then. Mirrors the C# `*_Background_Child_*` tests.

import { describe, expect, it } from "vitest";
import type { SchedulerLike } from "rxjs";
import {
  AggregateVM1,
  AggregateVM2,
  ComponentVM,
  ComponentVMBase,
  CompositeVM,
  ConstructionStatus as S,
  ConstructionStatusChangedMessage,
  GroupVM,
  MessageHub,
  RxDispatcher,
  StatusTransitionError,
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
  const dispatcher = new RxDispatcher(
    RxDispatcher.immediate().foreground,
    bg as unknown as SchedulerLike,
  );
  const hub = new MessageHub();
  const latest = new Map<string, ComponentVM>();
  /** A factory for a background child; `latest` tracks the newest instance. */
  const child = (name: string, opts: { failConstruct?: boolean } = {}) => (): ComponentVM => {
    const vm = ComponentVM.builder()
      .name(name)
      .services(hub, dispatcher)
      .background(true)
      .onConstruct(() => {
        if (opts.failConstruct === true) throw new Error(`${name} failed`);
      })
      .build();
    latest.set(name, vm);
    return vm;
  };
  const vm = (name: string): ComponentVM => latest.get(name)!;
  return { bg, dispatcher, hub, child, vm };
}

type Container = ComponentVMBase;

const kinds: Array<{
  kind: string;
  make: (s: ReturnType<typeof setup>, kids: Array<() => ComponentVM>) => Container;
}> = [
  {
    kind: "aggregate",
    make: (s, kids) => {
      if (kids.length === 1) {
        return AggregateVM1.builder<ComponentVM>()
          .name("agg")
          .services(s.hub, s.dispatcher)
          .component1(kids[0]!)
          .build();
      }
      return AggregateVM2.builder<ComponentVM, ComponentVM>()
        .name("agg")
        .services(s.hub, s.dispatcher)
        .component1(kids[0]!)
        .component2(kids[1]!)
        .build();
    },
  },
  {
    kind: "composite",
    make: (s, kids) =>
      CompositeVM.builder<ComponentVM>()
        .name("root")
        .services(s.hub, s.dispatcher)
        .children(() => kids.map((k) => k()))
        .build(),
  },
  {
    kind: "group",
    make: (s, kids) =>
      GroupVM.builder<ComponentVM>()
        .name("group")
        .services(s.hub, s.dispatcher)
        .children(() => kids.map((k) => k()))
        .build(),
  },
];

describe.each(kinds)("$kind – background child settle", ({ make }) => {
  it("construct remains in progress until the background child is Constructed", () => {
    const s = setup();
    const container = make(s, [s.child("child")]);

    container.construct();
    expect(s.vm("child").status).toBe(S.Constructing);
    expect(container.status).toBe(S.Constructing);

    s.bg.runAll();
    expect(s.vm("child").status).toBe(S.Constructed);
    expect(container.status).toBe(S.Constructed);
  });

  it("destruct remains in progress until the background child is Destructed", () => {
    const s = setup();
    const container = make(s, [s.child("child")]);
    container.construct();
    s.bg.runAll();
    expect(container.status).toBe(S.Constructed);

    container.destruct();
    expect(s.vm("child").status).toBe(S.Destructing);
    expect(container.status).toBe(S.Destructing);

    s.bg.runAll();
    expect(s.vm("child").status).toBe(S.Destructed);
    expect(container.status).toBe(S.Destructed);
  });

  it("a background child construct failure rolls the container back", () => {
    const s = setup();
    const container = make(s, [s.child("child", { failConstruct: true })]);

    container.construct();
    expect(container.status).toBe(S.Constructing);
    expect(() => s.bg.runAll()).toThrow("child failed");

    expect(s.vm("child").status).toBe(S.Destructed);
    expect(container.status).toBe(S.Destructed);
    // Recoverable: a later construct is legal again.
    expect(container.canConstruct()).toBe(true);
  });

  it("children settle sequentially and the container waits for the last one", () => {
    const s = setup();
    const container = make(s, [s.child("a"), s.child("b")]);

    container.construct();
    expect(s.vm("a").status).toBe(S.Constructing);
    expect(container.status).toBe(S.Constructing);

    s.bg.runAll();
    expect(s.vm("a").status).toBe(S.Constructed);
    expect(s.vm("b").status).toBe(S.Constructed);
    expect(container.status).toBe(S.Constructed);
  });

  it("dispose during a pending construct is terminal and publishes no settle", () => {
    const s = setup();
    const container = make(s, [s.child("child")]);
    const statuses: S[] = [];
    container.propertyChanged.subscribe((name) => {
      if (name === "status") statuses.push(container.status);
    });

    container.construct();
    container.dispose();
    s.bg.runAll();

    expect(container.status).toBe(S.Disposed);
    expect(s.vm("child").status).toBe(S.Disposed);
    expect(statuses).toEqual([S.Constructing, S.Disposed]);
  });

  it("reconstruct waits for the background child destruct, then construct", () => {
    const s = setup();
    const container = make(s, [s.child("child")]);
    container.construct();
    s.bg.runAll();

    container.reconstruct();
    expect(container.status).toBe(S.Destructing);
    s.bg.runAll();
    expect(s.vm("child").status).toBe(S.Constructed);
    expect(container.status).toBe(S.Constructed);
  });
});

describe("composite – current selector runs after background children settle", () => {
  it("applies the initial current only once every child is Constructed", () => {
    const s = setup();
    const child = s.child("child")();
    let selectorSawChild: S | null = null;
    const composite = CompositeVM.builder<ComponentVM>()
      .name("root")
      .services(s.hub, s.dispatcher)
      .children(() => [child])
      .current((xs) => {
        const first = [...xs][0] ?? null;
        selectorSawChild = first?.status ?? null;
        return first;
      })
      .build();

    composite.construct();
    expect(composite.current).toBeNull();
    s.bg.runAll();
    expect(selectorSawChild).toBe(S.Constructed);
    expect(composite.current).toBe(child);
    expect(composite.status).toBe(S.Constructed);
  });
});

describe("nested containers – background grandchild settle", () => {
  it("a composite waits for a group that waits for its background child", () => {
    const s = setup();
    const group = GroupVM.builder<ComponentVM>()
      .name("group")
      .services(s.hub, s.dispatcher)
      .children(() => [s.child("leaf")()])
      .build();
    const root = CompositeVM.builder<ComponentVMBase>()
      .name("root")
      .services(s.hub, s.dispatcher)
      .children(() => [group])
      .build();

    root.construct();
    expect(group.status).toBe(S.Constructing);
    expect(root.status).toBe(S.Constructing);

    s.bg.runAll();
    expect(s.vm("leaf").status).toBe(S.Constructed);
    expect(group.status).toBe(S.Constructed);
    expect(root.status).toBe(S.Constructed);
  });
});

describe("background VM – terminal publication holds the in-flight guard", () => {
  it.each([false, true])(
    "background=%s: a reentrant destruct from a Constructed observer is rejected",
    (background) => {
      const s = setup();
      const vm = ComponentVM.builder()
        .name("vm")
        .services(s.hub, s.dispatcher)
        .background(background)
        .build();
      const seen: string[] = [];
      vm.propertyChanged.subscribe((name) => {
        if (name === "status" || name === "isConstructed") {
          seen.push(`${name}:${String(vm.status)}`);
        }
      });
      let reentrant: unknown = null;
      s.hub.messages.subscribe((m) => {
        if (
          m instanceof ConstructionStatusChangedMessage &&
          m.sender === vm &&
          m.status === S.Constructed &&
          reentrant === null
        ) {
          try {
            vm.destruct();
            reentrant = "accepted";
          } catch (error) {
            reentrant = error;
          }
        }
      });

      vm.construct();
      s.bg.runAll();

      expect(reentrant).toBeInstanceOf(StatusTransitionError);
      expect(vm.status).toBe(S.Constructed);
      expect(seen).toEqual([
        `status:${String(S.Constructing)}`,
        `isConstructed:${String(S.Constructing)}`,
        `status:${String(S.Constructed)}`,
        `isConstructed:${String(S.Constructed)}`,
      ]);
    },
  );
});

describe("deferred container continuation failures", () => {
  it("a throwing composite current selector surfaces from the background work and rolls back", () => {
    // No allowRxUnhandledErrors(): tests/setup.ts fails the test if the error
    // escapes through rxjs reportUnhandledError (a throwing subscriber).
    const s = setup();
    const child = s.child("child")();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("root")
      .services(s.hub, s.dispatcher)
      .children(() => [child])
      .current(() => {
        throw new Error("selector boom");
      })
      .build();

    composite.construct();
    expect(composite.status).toBe(S.Constructing);
    expect(() => s.bg.runAll()).toThrow("selector boom");

    expect(child.status).toBe(S.Constructed);
    expect(composite.status).toBe(S.Destructed);
    expect(composite.canConstruct()).toBe(true);
  });

  it("a sync sibling whose construct throws after a background child surfaces from the background work", () => {
    const s = setup();
    const aggregate = AggregateVM2.builder<ComponentVM, ComponentVM>()
      .name("agg")
      .services(s.hub, s.dispatcher)
      .component1(s.child("a"))
      .component2(() =>
        ComponentVM.builder()
          .name("b")
          .services(s.hub, s.dispatcher)
          .onConstruct(() => {
            throw new Error("b failed");
          })
          .build(),
      )
      .build();

    aggregate.construct();
    expect(aggregate.status).toBe(S.Constructing);
    expect(() => s.bg.runAll()).toThrow("b failed");

    expect(aggregate.component2?.status).toBe(S.Destructed);
    expect(aggregate.status).toBe(S.Destructed);
  });

  it("an all-synchronous container still throws from construct()", () => {
    const s = setup();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("root")
      .services(s.hub, s.dispatcher)
      .children(() => [ComponentVM.builder().name("c").services(s.hub, s.dispatcher).build()])
      .current(() => {
        throw new Error("selector boom");
      })
      .build();

    expect(() => composite.construct()).toThrow("selector boom");
    expect(composite.status).toBe(S.Destructed);
  });
});

describe("factory population – background children are joined, never restarted", () => {
  /** Runs the newest background work first and collects its failures. */
  class LifoScheduler {
    readonly #work: Array<() => void> = [];
    readonly errors: unknown[] = [];

    schedule(work: () => void): { unsubscribe(): void } {
      this.#work.push(work);
      return { unsubscribe() {} };
    }

    runAll(): void {
      for (let work = this.#work.pop(); work !== undefined; work = this.#work.pop()) {
        try {
          work();
        } catch (error) {
          this.errors.push(error);
        }
      }
    }
  }

  it.each(["composite", "group"])(
    "%s: a later child that fails while an earlier one is pending rolls the container back",
    (kind) => {
      const bg = new LifoScheduler();
      const dispatcher = new RxDispatcher(
        RxDispatcher.immediate().foreground,
        bg as unknown as SchedulerLike,
      );
      const hub = new MessageHub();
      let badHookRuns = 0;
      const ok = ComponentVM.builder().name("ok").services(hub, dispatcher).background(true).build();
      const bad = ComponentVM.builder()
        .name("bad")
        .services(hub, dispatcher)
        .background(true)
        .onConstruct(() => {
          badHookRuns += 1;
          throw new Error("bad failed");
        })
        .build();
      const container: ComponentVMBase =
        kind === "composite"
          ? CompositeVM.builder<ComponentVM>()
              .name("root")
              .services(hub, dispatcher)
              .children(() => [ok, bad])
              .build()
          : GroupVM.builder<ComponentVM>()
              .name("root")
              .services(hub, dispatcher)
              .children(() => [ok, bad])
              .build();

      container.construct();
      expect(ok.status).toBe(S.Constructing);
      expect(bad.status).toBe(S.Constructing);
      bg.runAll();

      expect(badHookRuns).toBe(1);
      expect(bad.status).toBe(S.Destructed);
      expect(container.status).toBe(S.Destructed);
      expect(container.canConstruct()).toBe(true);
    },
  );
});
