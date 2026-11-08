// Selection commits without a membership transaction (spec/06 §3.2, §4.3 and
// §5; ADR-0165, ADR-0173; #1149 and its 2026-11-07 scope comment, TS part of
// #1144).
//
// TypeScript runs on one thread, so rule 1's cross-thread case does not arise:
// every transaction a selection can meet is owned by the selecting "thread".
// Rule 4 therefore refuses every selection call while the composite's own
// transaction is uncommitted (a child attached but not admitted, a staged
// population, or a transfer detach whose commit has not run), and a selection
// from the commit on, including the add's own collectionChanged publication,
// commits. Rule 6 (a detach clears Current only while the detached child is
// still current) is implemented but cannot be observed here: in the window
// between a detach and its commit, rule 4 refuses every selection on that
// composite, the walk's assignment and an async delivery are no-ops, and the
// destruct clear can only clear.

import { describe, expect, it } from "vitest";
import type { SchedulerLike } from "rxjs";
import {
  ComponentVM,
  CompositeVM,
  ConstructionStatus as S,
  ConstructionStatusChangedMessage,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";
import type { IDispatcher } from "../../src/index.js";

class DeferredScheduler {
  #work: Array<() => void> = [];

  schedule(work: () => void): { unsubscribe(): void } {
    this.#work.push(work);
    return { unsubscribe() {} };
  }

  get pending(): number {
    return this.#work.length;
  }

  runAll(): void {
    while (this.#work.length > 0) {
      const batch = this.#work;
      this.#work = [];
      for (const work of batch) work();
    }
  }
}

interface Options {
  selector?: (children: ComponentVM[]) => ComponentVM | null;
  autoConstruct?: boolean;
  withFirst?: boolean;
  asyncSelection?: boolean;
  onCurrentChanged?: (vm: ComponentVM | null) => void;
  extra?: string[];
}

function setup(options: Options = {}) {
  const bg = new DeferredScheduler();
  const fg = new DeferredScheduler();
  const dispatcher: IDispatcher = new RxDispatcher(
    options.asyncSelection === true
      ? (fg as unknown as SchedulerLike)
      : RxDispatcher.immediate().foreground,
    bg as unknown as SchedulerLike,
  );
  const hub = new MessageHub();
  const child = (
    name: string,
    opts: { background?: boolean; onConstruct?: () => void } = {},
  ): ComponentVM =>
    ComponentVM.builder()
      .name(name)
      .services(hub, dispatcher)
      .background(opts.background ?? false)
      .onConstruct(opts.onConstruct ?? (() => {}))
      .build();
  const first = child("first", { background: options.withFirst !== false });
  const extra = (options.extra ?? []).map((name) => child(name));
  const initial = options.withFirst === false ? extra : [first, ...extra];
  const changes: (ComponentVM | null)[] = [];
  const root = CompositeVM.builder<ComponentVM>()
    .name("root")
    .services(hub, dispatcher)
    .children(() => initial)
    .autoConstructOnAdd(options.autoConstruct ?? true)
    .asyncSelection(options.asyncSelection ?? false)
    .current((xs) => (options.selector ?? ((all) => all[0] ?? null))([...xs]))
    .onCurrentChanged((vm) => {
      changes.push(vm);
      options.onCurrentChanged?.(vm);
    })
    .build();
  const statuses: S[] = [];
  hub.messages.subscribe((message) => {
    if (message instanceof ConstructionStatusChangedMessage && message.sender === root) {
      statuses.push(message.status);
    }
  });
  return { bg, fg, hub, dispatcher, child, first, extra, root, changes, statuses };
}

const TRANSACTION = /transaction is already in progress/;

describe("#1149 construct walk assignment (ADR-0165, ADR-0173)", () => {
  it("A: commits the selector result from the add's collectionChanged publication", () => {
    const { bg, child, first, root, changes, statuses } = setup();
    const late = child("late");
    root.construct();
    expect(root.status).toBe(S.Constructing);
    root.collectionChanged.subscribe(() => bg.runAll());

    expect(() => root.add(late)).not.toThrow();

    expect(statuses).toEqual([S.Constructing, S.Constructed]);
    expect(root.current).toBe(first);
    expect(changes).toEqual([first]);
    expect(root.snapshot()).toContain(late);
  });

  it("A: defers a dispose from onCurrentChanged until the publication and the add end", () => {
    let root!: CompositeVM<ComponentVM>;
    const seen: S[] = [];
    const fixture = setup({
      onCurrentChanged: () => {
        root.dispose();
        seen.push(root.status);
      },
    });
    root = fixture.root;
    const late = fixture.child("late");
    root.construct();
    fixture.root.collectionChanged.subscribe(() => fixture.bg.runAll());

    expect(() => root.add(late)).not.toThrow();

    expect(seen).toEqual([S.Constructing]);
    expect(fixture.changes).toEqual([fixture.first]);
    expect(root.status).toBe(S.Disposed);
    expect(fixture.statuses).not.toContain(S.Destructed);
  });

  it.each([
    ["first", (xs: ComponentVM[]) => xs[0] ?? null],
    ["late", (xs: ComponentVM[]) => xs.find((x) => x.name === "late") ?? null],
  ])(
    "B: a walk resumed in the add's hook phase (selector %s) constructs and selects nothing",
    (_name, selector) => {
      const { bg, child, root, changes } = setup({ selector });
      const late = child("late", { onConstruct: () => bg.runAll() });
      root.construct();

      expect(() => root.add(late)).not.toThrow();

      // ADR-0173 rule 4: the walk's assignment inside the add's uncommitted
      // window is a silent no-op, so a failed add needs no Current restore.
      expect(root.snapshot()).toContain(late);
      expect(root.status).toBe(S.Constructed);
      expect(root.current).toBeNull();
      expect(late.isCurrent).toBe(false);
      expect(changes).toEqual([]);
    },
  );

  it("C: a walk resumed after a deferred dispose selects nothing and the composite disposes", () => {
    const { bg, child, root, changes, statuses } = setup();
    const late = child("late");
    root.construct();
    root.collectionChanged.subscribe(() => {
      root.dispose();
      bg.runAll();
    });

    expect(() => root.add(late)).not.toThrow();

    expect(changes).toEqual([]);
    expect(root.current).toBeNull();
    expect(root.status).toBe(S.Disposed);
    expect(statuses).not.toContain(S.Destructed);
  });

  it("D: a selector that disposes the composite leaves nothing current", () => {
    let root!: CompositeVM<ComponentVM>;
    const fixture = setup({
      withFirst: false,
      extra: ["only"],
      selector: (xs) => {
        root.dispose();
        return xs[0] ?? null;
      },
    });
    root = fixture.root;
    const only = fixture.extra[0]!;

    expect(() => root.construct()).not.toThrow();

    expect(root.current).toBeNull();
    expect(only.isCurrent).toBe(false);
    expect(root.status).toBe(S.Disposed);
  });

  it("E: a walk resumed inside a transfer out of the composite selects nothing", () => {
    const fixture = setup({
      autoConstruct: false,
      extra: ["b"],
      selector: (xs) => xs.find((x) => x.name === "b") ?? null,
    });
    const { bg, child, root, changes, hub, dispatcher } = fixture;
    const b = fixture.extra[0]!;
    const a = child("a", { onConstruct: () => bg.runAll() });
    const other = CompositeVM.builder<ComponentVM>()
      .name("other").services(hub, dispatcher).children(() => [])
      .autoConstructOnAdd(true).build();
    other.construct();
    root.construct();
    root.add(a);
    root.current = a;

    expect(() => other.add(a)).not.toThrow();

    expect(other.snapshot()).toEqual([a]);
    expect(a.isCurrent).toBe(false);
    expect(root.status).toBe(S.Constructed);
    // ADR-0173 rule 4: the transfer's detach of `a` is uncommitted while `a`
    // constructs, so the walk's assignment of `b` is a silent no-op. The
    // detach commit then clears `a`, which is still current (rule 6).
    expect(root.current).toBeNull();
    expect(b.isCurrent).toBe(false);
    expect(changes).toEqual([a, null]);
  });

  it("COMP-025 guard: the walk's assignment stays synchronous with asyncSelection", () => {
    const { first, root, changes } = setup({ withFirst: false, extra: ["x"], asyncSelection: true });
    void first;
    root.construct();

    expect(root.status).toBe(S.Constructed);
    expect(root.current?.name).toBe("x");
    expect(changes.map((vm) => vm?.name)).toEqual(["x"]);
  });
});

describe("destruct clear (spec/06 §5, ADR-0173 rule 8, TS part of #1144)", () => {
  it("clears Current when destruct runs from the add's own collectionChanged handler", () => {
    const { child, first, root, changes } = setup({ withFirst: false, extra: ["x"] });
    void first;
    root.construct();
    const x = root.current!;
    root.collectionChanged.subscribe(() => root.destruct());

    expect(() => root.add(child("late"))).not.toThrow();

    expect(root.status).toBe(S.Destructed);
    expect(root.current).toBeNull();
    expect(x.isCurrent).toBe(false);
    expect(changes).toEqual([x, null]);
  });

  it("clears Current inside an uncommitted transfer out of the composite", () => {
    const fixture = setup({ withFirst: false, extra: ["b"], autoConstruct: false });
    const { child, root, changes, hub, dispatcher } = fixture;
    const b = fixture.extra[0]!;
    const a = child("a", { onConstruct: () => root.destruct() });
    const other = CompositeVM.builder<ComponentVM>()
      .name("other").services(hub, dispatcher).children(() => [])
      .autoConstructOnAdd(true).build();
    other.construct();
    root.construct();
    root.add(a);
    expect(root.current).toBe(b);

    expect(() => other.add(a)).not.toThrow();

    expect(root.status).toBe(S.Destructed);
    expect(root.current).toBeNull();
    expect(b.isCurrent).toBe(false);
    expect(changes).toEqual([b, null]);
    expect(other.snapshot()).toEqual([a]);
  });

  it("clears Current while disposal is deferred, then disposes", () => {
    let root!: CompositeVM<ComponentVM>;
    let once = true;
    const fixture = setup({
      withFirst: false,
      extra: ["x", "y"],
      selector: () => null,
      onCurrentChanged: (vm) => {
        if (vm === null || !once) return;
        once = false;
        root.dispose();
        root.destruct();
      },
    });
    root = fixture.root;
    root.construct();
    const x = fixture.extra[0]!;

    expect(() => root.selectComponent(x)).not.toThrow();

    expect(fixture.statuses).toEqual([S.Constructing, S.Constructed, S.Destructing, S.Destructed, S.Disposed]);
    expect(root.current).toBeNull();
    expect(x.isCurrent).toBe(false);
    expect(fixture.changes).toEqual([x, null]);
  });

  it("defers a dispose from onCurrentChanged(null) through the publication lease", () => {
    let root!: CompositeVM<ComponentVM>;
    const seen: S[] = [];
    const fixture = setup({
      withFirst: false,
      extra: ["x"],
      onCurrentChanged: (vm) => {
        if (vm !== null) return;
        root.dispose();
        seen.push(root.status);
      },
    });
    root = fixture.root;
    root.construct();

    root.destruct();

    expect(seen).toEqual([S.Destructing]);
    expect(root.current).toBeNull();
    expect(root.status).toBe(S.Disposed);
  });
});

describe("selection calls during the composite's own transaction (ADR-0173 rules 2-5)", () => {
  it("refuses every selection call before the add commits and leaves Current unchanged", () => {
    const errors: unknown[] = [];
    const checks: boolean[] = [];
    let root!: CompositeVM<ComponentVM>;
    const fixture = setup({ withFirst: false, extra: ["x", "y"] });
    root = fixture.root;
    const [x, y] = fixture.extra as [ComponentVM, ComponentVM];
    const attempt = (action: () => void): void => {
      try { action(); errors.push(null); } catch (error) { errors.push(error); }
    };
    const late = fixture.child("late", {
      onConstruct: () => {
        checks.push(root.canSelectComponent(late), root.canSelectComponent(y));
        attempt(() => { root.current = late; });
        attempt(() => { root.current = y; });
        attempt(() => { root.current = null; });
        attempt(() => root.selectComponent(y));
        attempt(() => root.deselectComponent(x));
        attempt(() => y.select());
        attempt(() => x.deselect());
      },
    });
    root.construct();
    expect(root.current).toBe(x);

    root.add(late);

    expect(checks).toEqual([false, false]);
    expect(errors.map((error) => (error as Error | null)?.message ?? null)).toEqual([
      expect.stringMatching(TRANSACTION),
      expect.stringMatching(TRANSACTION),
      expect.stringMatching(TRANSACTION),
      expect.stringMatching(/canSelectComponent returned false/),
      expect.stringMatching(TRANSACTION),
      expect.stringMatching(TRANSACTION),
      expect.stringMatching(TRANSACTION),
    ]);
    expect(root.current).toBe(x);
    expect(fixture.changes).toEqual([x]);
    expect(root.canSelectComponent(late)).toBe(true);
  });

  it("a failed add needs no Current restore", () => {
    const fixture = setup({ withFirst: false, extra: ["x"] });
    const { root } = fixture;
    const late = fixture.child("late", {
      onConstruct: () => {
        expect(() => { root.current = null; }).toThrow(TRANSACTION);
        throw new Error("hook failed");
      },
    });
    root.construct();
    const x = root.current;

    expect(() => root.add(late)).toThrow("hook failed");

    expect(root.current).toBe(x);
    expect(fixture.changes).toEqual([x]);
    expect(root.snapshot()).not.toContain(late);
  });

  it("refuses selection of a staged population candidate", () => {
    const hub = new MessageHub();
    const dispatcher = RxDispatcher.immediate();
    const seen: unknown[] = [];
    class Populating extends CompositeVM<ComponentVM> {
      stage(children: ComponentVM[]): void { this._attachPopulation(children); }
    }
    const root = new Populating({ name: "root", hub, dispatcher, autoConstructOnAdd: true });
    const make = (name: string, onConstruct?: () => void): ComponentVM =>
      ComponentVM.builder().name(name).services(hub, dispatcher)
        .onConstruct(onConstruct ?? (() => {})).build();
    const second = make("second");
    const candidate = make("candidate", () => {
      seen.push(root.canSelectComponent(candidate));
      try { root.current = candidate; seen.push("selected"); } catch (error) {
        seen.push((error as Error).message);
      }
    });
    root.construct();

    root.stage([candidate, second]);

    expect(seen).toEqual([false, expect.stringMatching(TRANSACTION)]);
    expect(root.current).toBeNull();
    expect(root.canSelectComponent(candidate)).toBe(true);
    root.current = candidate;
    expect(candidate.isCurrent).toBe(true);
  });

  it("commits a selection from the add's own collectionChanged publication", () => {
    const fixture = setup({ withFirst: false, extra: ["x"] });
    const { root } = fixture;
    const late = fixture.child("late");
    root.construct();
    const x = root.current!;
    root.collectionChanged.subscribe(() => {
      expect(root.canSelectComponent(late)).toBe(true);
      root.current = late;
    });

    expect(() => root.add(late)).not.toThrow();

    expect(root.current).toBe(late);
    expect(late.isCurrent).toBe(true);
    expect(x.isCurrent).toBe(false);
    expect(fixture.changes).toEqual([x, late]);
  });

  it("defers a dispose from onCurrentChanged in the publication phase until the add ends", () => {
    let root!: CompositeVM<ComponentVM>;
    const seen: S[] = [];
    let armed = false;
    const fixture = setup({
      withFirst: false,
      extra: ["x"],
      onCurrentChanged: () => {
        if (!armed) return;
        root.dispose();
        seen.push(root.status);
      },
    });
    root = fixture.root;
    const late = fixture.child("late");
    root.construct();
    const actions: string[] = [];
    root.collectionChanged.subscribe((event) => {
      actions.push(event.action);
      armed = true;
      root.current = late;
    });

    root.add(late);

    expect(seen).toEqual([S.Constructed]);
    expect(actions).toEqual(["add"]);
    expect(root.status).toBe(S.Disposed);
  });

  it("refuses a non-null selection while disposal is deferred but allows null clears", () => {
    const fixture = setup({ withFirst: false, extra: ["x", "y"] });
    const { root } = fixture;
    const [x, y] = fixture.extra as [ComponentVM, ComponentVM];
    const late = fixture.child("late");
    root.construct();
    const seen: unknown[] = [];
    root.collectionChanged.subscribe(() => {
      root.dispose();
      seen.push(root.canSelectComponent(y));
      try { root.current = y; } catch (error) { seen.push((error as Error).message); }
      expect(() => root.selectComponent(y)).toThrow(/canSelectComponent returned false/);
      root.deselectComponent(x);
      seen.push(root.current);
    });

    root.add(late);

    expect(seen).toEqual([false, expect.stringMatching(/disposing/), null]);
    expect(fixture.changes).toEqual([x, null]);
    expect(root.status).toBe(S.Disposed);
  });

  it("allows a child deselect while disposal is deferred", () => {
    const fixture = setup({ withFirst: false, extra: ["x"] });
    const { root } = fixture;
    const x = fixture.extra[0]!;
    root.construct();
    root.collectionChanged.subscribe(() => {
      root.dispose();
      x.deselect();
      root.current = null;
    });

    root.add(fixture.child("late"));

    expect(fixture.changes).toEqual([x, null]);
    expect(root.status).toBe(S.Disposed);
  });

  it("keeps the post-dispose refusal after Disposed", () => {
    const { root } = setup({ withFirst: false, extra: ["x"] });
    root.construct();
    root.dispose();

    expect(() => { root.current = null; }).toThrow(/disposed|disposing/);
  });
});

describe("asynchronous selection (ADR-0173 rule 7)", () => {
  it("validates at call time inside the add's uncommitted window", () => {
    const fixture = setup({ withFirst: false, extra: ["x", "y"], asyncSelection: true });
    const { root, fg } = fixture;
    const y = fixture.extra[1]!;
    const errors: string[] = [];
    const late = fixture.child("late", {
      onConstruct: () => {
        try { root.current = y; } catch (error) { errors.push((error as Error).message); }
      },
    });
    root.construct();

    root.add(late);
    fg.runAll();

    expect(errors).toEqual([expect.stringMatching(TRANSACTION)]);
    expect(root.current?.name).toBe("x");
  });

  it("drops a delivery that runs inside the add's uncommitted window", () => {
    const fixture = setup({ withFirst: false, extra: ["x", "y"], asyncSelection: true });
    const { root, fg } = fixture;
    const [x, y] = fixture.extra as [ComponentVM, ComponentVM];
    const late = fixture.child("late", { onConstruct: () => fg.runAll() });
    root.construct();
    root.current = y;
    expect(fg.pending).toBe(1);

    expect(() => root.add(late)).not.toThrow();
    fg.runAll();

    expect(root.current).toBe(x);
    expect(y.isCurrent).toBe(false);
    expect(fixture.changes).toEqual([x]);
  });

  it("commits a delivery that runs in the add's publication phase", () => {
    const fixture = setup({ withFirst: false, extra: ["x"], asyncSelection: true });
    const { root, fg } = fixture;
    const late = fixture.child("late");
    root.construct();
    root.collectionChanged.subscribe(() => {
      root.current = late;
      fg.runAll();
    });

    root.add(late);

    expect(root.current).toBe(late);
    expect(late.isCurrent).toBe(true);
  });

  it("drops a non-null delivery once disposal is pending", () => {
    const fixture = setup({ withFirst: false, extra: ["x", "y"], asyncSelection: true });
    const { root, fg } = fixture;
    const [x, y] = fixture.extra as [ComponentVM, ComponentVM];
    root.construct();
    root.current = y;
    root.collectionChanged.subscribe(() => {
      root.dispose();
      fg.runAll();
    });

    root.add(fixture.child("late"));

    expect(fixture.changes).toEqual([x]);
    expect(y.isCurrent).toBe(false);
    expect(root.status).toBe(S.Disposed);
  });
});
