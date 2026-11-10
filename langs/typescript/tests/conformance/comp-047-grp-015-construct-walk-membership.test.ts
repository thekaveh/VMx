/**
 * The construct walk counts members only (spec/06 §5.1, spec/07 §4,
 * ADR-0186, #1313). A child that a removal or a failed add takes out of the
 * container during the walk does not roll the container back.
 *
 * TypeScript runs the four removal cases on one thread: a background child
 * settles when the test drains the background scheduler, and the removal
 * runs before that drain.
 */
import { describe, expect, it } from "vitest";
import type { SchedulerLike } from "rxjs";
import {
  ComponentVM,
  CompositeVM,
  ConstructionStatus as S,
  GroupVM,
  MessageHub,
  RxDispatcher,
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

  /** Runs the oldest queued work only. */
  runFirst(): void {
    this.#work.shift()?.();
  }

  /** Runs the newest queued work only. */
  runLast(): void {
    this.#work.pop()?.();
  }
}

interface Container {
  readonly status: S;
  construct(): void;
  add(child: ComponentVM): void;
  remove(child: ComponentVM): boolean;
  snapshot(): readonly ComponentVM[];
}

type Kind = "composite" | "group";

interface Child {
  vm: ComponentVM;
  runs: () => number;
}

function fixture(kind: Kind) {
  const bg = new DeferredScheduler();
  const dispatcher = new RxDispatcher(
    RxDispatcher.immediate().foreground,
    bg as unknown as SchedulerLike,
  );
  const hub = new MessageHub();
  const child = (name: string, opts: { background?: boolean; fails?: boolean } = {}): Child => {
    let runs = 0;
    const vm = ComponentVM.builder()
      .name(name)
      .services(hub, dispatcher)
      .background(opts.background ?? false)
      .onConstruct(() => {
        runs += 1;
        if (opts.fails === true) throw new Error(`${name} failed`);
      })
      .build();
    return { vm, runs: () => runs };
  };
  const container = (members: readonly ComponentVM[]): Container =>
    kind === "composite"
      ? CompositeVM.builder<ComponentVM>()
          .name("p")
          .services(hub, dispatcher)
          .children(() => members)
          .autoConstructOnAdd(true)
          .build()
      : GroupVM.builder<ComponentVM>()
          .name("p")
          .services(hub, dispatcher)
          .children(() => members)
          .autoConstructOnAdd(true)
          .build();
  return { bg, child, container };
}

function walkMembershipCases(kind: Kind): void {
  it("does not start a snapshot child removed before the walk reaches it", () => {
    const { bg, child, container } = fixture(kind);
    const a = child("a", { background: true });
    const s = child("s", { fails: true });
    // Added before construct(): the walk, not the factory population, starts
    // them in order, so the walk waits on `a` before it reaches `s`.
    const p = container([]);
    p.add(a.vm);
    p.add(s.vm);
    expect(a.vm.status).toBe(S.Destructed);

    expect(() => p.construct()).not.toThrow();
    expect(p.status).toBe(S.Constructing);
    expect(p.remove(s.vm)).toBe(true);
    expect(() => bg.runAll()).not.toThrow();

    expect(p.status).toBe(S.Constructed);
    expect(s.vm.status).toBe(S.Destructed);
    expect(s.runs()).toBe(0);
    expect(p.snapshot()).toEqual([a.vm]);
  });

  it("ignores the result of a snapshot child removed while the walk waits on it", () => {
    const { bg, child, container } = fixture(kind);
    const a = child("a", { background: true, fails: true });
    const p = container([a.vm]);

    expect(() => p.construct()).not.toThrow();
    expect(p.remove(a.vm)).toBe(true);
    // The child's own failure surfaces from its own work, not from p.
    expect(() => bg.runAll()).toThrow("a failed");

    expect(p.status).toBe(S.Constructed);
    expect(a.vm.status).toBe(S.Destructed);
    expect(a.runs()).toBe(1);
    expect(p.snapshot()).toEqual([]);
  });

  it("ignores the result of a late child removed while the walk waits on it", () => {
    const { bg, child, container } = fixture(kind);
    const anchor = child("anchor", { background: true });
    const l = child("l", { background: true, fails: true });
    const p = container([anchor.vm]);

    expect(() => p.construct()).not.toThrow();
    p.add(l.vm);
    expect(l.vm.status).toBe(S.Constructing);
    // The anchor settles; the walk joins l and waits on it.
    bg.runFirst();
    expect(p.status).toBe(S.Constructing);
    expect(p.remove(l.vm)).toBe(true);
    expect(() => bg.runAll()).toThrow("l failed");

    expect(p.status).toBe(S.Constructed);
    expect(l.vm.status).toBe(S.Destructed);
    expect(l.runs()).toBe(1);
    expect(p.snapshot()).toEqual([anchor.vm]);
  });

  it("skips a late child removed before the walk reaches it", () => {
    const { bg, child, container } = fixture(kind);
    const anchor = child("anchor", { background: true });
    const l = child("l", { background: true, fails: true });
    const p = container([anchor.vm]);

    expect(() => p.construct()).not.toThrow();
    p.add(l.vm);
    expect(p.remove(l.vm)).toBe(true);
    expect(() => bg.runLast()).toThrow("l failed");
    expect(() => bg.runAll()).not.toThrow();

    expect(p.status).toBe(S.Constructed);
    expect(l.vm.status).toBe(S.Destructed);
    expect(l.runs()).toBe(1);
    expect(p.snapshot()).toEqual([anchor.vm]);
  });

  it("fails and undoes a late add whose construction fails, and still constructs", () => {
    const { bg, child, container } = fixture(kind);
    const anchor = child("anchor", { background: true });
    const f = child("f", { fails: true });
    const p = container([anchor.vm]);

    expect(() => p.construct()).not.toThrow();
    expect(() => p.add(f.vm)).toThrow("f failed");
    expect(p.snapshot()).toEqual([anchor.vm]);
    expect(() => bg.runAll()).not.toThrow();

    expect(p.status).toBe(S.Constructed);
    expect(f.vm.status).toBe(S.Destructed);
    expect(f.runs()).toBe(1);
  });
}

describe("COMP-047", () => {
  walkMembershipCases("composite");
});

describe("GRP-015", () => {
  walkMembershipCases("group");
});
