/**
 * A failed add returns a background child to `Destructed` (spec/06 §4.2,
 * spec/07 §1.1, ADR-0218 rule 7, #1372). The add started the child, and the
 * child's construct is still in flight at the rollback. Compensation does not
 * wait for it. Once the child settles `Constructed` with no parent, VMx calls
 * its `destruct()`.
 *
 * TypeScript runs on one thread: a background child settles when the test
 * drains the queued background scheduler.
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
}

interface Container {
  readonly status: S;
  construct(): void;
  dispose(): void;
  add(child: ComponentVM): void;
  insert(index: number, child: ComponentVM): void;
  setAt(index: number, child: ComponentVM): void;
  snapshot(): readonly ComponentVM[];
}

type Kind = "composite" | "group";
type Operation = "add" | "insert" | "setAt";
type ContainerState = "Constructed" | "Constructing";

const DISPOSING = "Cannot attach a child while the container is disposing";

function fixture(kind: Kind) {
  const bg = new DeferredScheduler();
  const dispatcher = new RxDispatcher(
    RxDispatcher.immediate().foreground,
    bg as unknown as SchedulerLike,
  );
  const hub = new MessageHub();
  const child = (name: string, background: boolean): ComponentVM =>
    ComponentVM.builder().name(name).services(hub, dispatcher).background(background).build();
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

function attach(p: Container, operation: Operation, c: ComponentVM): void {
  if (operation === "add") p.add(c);
  else if (operation === "insert") p.insert(0, c);
  // Index 1 holds the synchronous member `m`.
  else p.setAt(1, c);
}

function rollbackCases(kind: Kind): void {
  const operations: readonly Operation[] = ["add", "insert", "setAt"];
  const states: readonly ContainerState[] = ["Constructed", "Constructing"];
  for (const operation of operations) {
    for (const state of states) {
      for (const background of [true, false]) {
        const label = background ? "background" : "synchronous";
        it(`${operation} on a ${state} container returns a ${label} child to Destructed`, () => {
          const { bg, child, container } = fixture(kind);
          // The container waits on `a` while it is Constructing.
          const a = child("a", true);
          const m = child("m", false);
          const p = container([a, m]);
          p.construct();
          if (state === "Constructed") bg.runAll();
          expect(p.status).toBe(S[state]);

          const c = child("c", background);
          expect(c.status).toBe(S.Destructed);
          const subscription = c.propertyChanged.subscribe((name) => {
            if (name === "status" && c.status === S.Constructing) p.dispose();
          });

          expect(() => attach(p, operation, c)).toThrow(DISPOSING);
          expect(c._parent).toBeNull();
          expect(p.snapshot()).not.toContain(c);

          expect(() => bg.runAll()).not.toThrow();
          subscription.unsubscribe();

          expect(c.status).toBe(S.Destructed);
          expect(c._parent).toBeNull();
          expect(p.status).toBe(S.Disposed);
        });
      }
    }
  }

  it("leaves a background child that has a parent again when it settles", () => {
    const { bg, child, container } = fixture(kind);
    const p = container([]);
    p.construct();
    // A Destructed container does not start the child it adopts.
    const other = container([]);
    const c = child("c", true);
    const subscription = c.propertyChanged.subscribe((name) => {
      if (name === "status" && c.status === S.Constructing) p.dispose();
    });

    expect(() => p.add(c)).toThrow(DISPOSING);
    subscription.unsubscribe();
    // The consumer adopts the child before its construct settles.
    other.add(c);
    expect(() => bg.runAll()).not.toThrow();

    expect(c.status).toBe(S.Constructed);
    expect(other.snapshot()).toEqual([c]);
  });
}

describe("COMP-054", () => {
  rollbackCases("composite");
});

describe("GRP-017", () => {
  rollbackCases("group");
});
