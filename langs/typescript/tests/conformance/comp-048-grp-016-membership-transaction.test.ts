/**
 * A membership change during an open membership transaction fails at once and
 * changes nothing (spec/06 §4.2, spec/07 §1.1, ADR-0187, #1314).
 *
 * TypeScript runs on one thread, so the open transaction is held on the call
 * chain of an add: the added child's construct hook (auto-construct-on-add)
 * makes each call. A population is attempted from the add's collectionChanged
 * subscriber, because only an unpopulated container populates.
 */
import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  CompositeVM,
  GroupVM,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";
import type { CollectionChangedEvent } from "../../src/index.js";
import type { Observable } from "rxjs";

const TRANSACTION = /membership transaction is already in progress/;

interface Container {
  construct(): void;
  add(child: ComponentVM): void;
  insert(index: number, child: ComponentVM): void;
  setAt(index: number, child: ComponentVM): void;
  remove(child: ComponentVM): boolean;
  removeAt(index: number): void;
  clear(): void;
  snapshot(): readonly ComponentVM[];
  readonly collectionChanged: Observable<CollectionChangedEvent>;
}

type Kind = "composite" | "group";

function fixture(kind: Kind) {
  const hub = new MessageHub();
  const dispatcher = RxDispatcher.immediate();
  const child = (name: string, onConstruct: () => void = () => {}): ComponentVM =>
    ComponentVM.builder().name(name).services(hub, dispatcher).onConstruct(onConstruct).build();
  const container = (name: string, members: readonly ComponentVM[], auto: boolean): Container =>
    kind === "composite"
      ? CompositeVM.builder<ComponentVM>()
          .name(name)
          .services(hub, dispatcher)
          .children(() => members)
          .autoConstructOnAdd(auto)
          .build()
      : GroupVM.builder<ComponentVM>()
          .name(name)
          .services(hub, dispatcher)
          .children(() => members)
          .autoConstructOnAdd(auto)
          .build();
  const events = (target: Container): string[] => {
    const log: string[] = [];
    target.collectionChanged.subscribe((event) => log.push(event.action));
    return log;
  };
  return { child, container, events };
}

function membershipTransactionCases(kind: Kind): void {
  it("refuses every membership change on the add's call chain and changes nothing", () => {
    const { child, container, events } = fixture(kind);
    const c = child("c");
    const y = child("y");
    const p = container("p", [c], true);
    const q = container("q", [], false);
    p.construct();
    q.construct();
    if (p instanceof CompositeVM) p.selectComponent(c);
    const pEvents = events(p);
    const qEvents = events(q);

    const refused: unknown[] = [];
    let inHook = false;
    const x = child("x", () => {
      if (inHook) return;
      inHook = true;
      const members = [...p.snapshot()];
      const attempts: Array<() => unknown> = [
        () => { p.add(y); },
        () => { p.insert(0, y); },
        () => { p.setAt(0, y); },
        () => { q.add(c); },
        () => p.remove(c),
        () => { p.removeAt(0); },
        () => { p.clear(); },
      ];
      for (const attempt of attempts) {
        try {
          attempt();
          refused.push(null);
        } catch (error) {
          refused.push(error);
        }
      }
      expect(p.snapshot()).toEqual(members);
      expect(q.snapshot()).toEqual([]);
      expect(c._parent).not.toBeNull();
      expect(y._parent).toBeNull();
      expect(pEvents).toEqual([]);
      expect(qEvents).toEqual([]);
      if (p instanceof CompositeVM) expect(p.current).toBe(c);
    });

    p.add(x);

    expect(refused).toHaveLength(7);
    for (const error of refused) {
      expect(error).toBeInstanceOf(Error);
      expect((error as Error).message).toMatch(TRANSACTION);
    }
    expect(p.snapshot()).toEqual([c, x]);
    expect(pEvents).toEqual(["add"]);

    // After the transaction ends, the same calls succeed.
    p.add(y);
    expect(p.remove(y)).toBe(true);
    p.insert(0, y);
    p.setAt(0, child("z"));
    p.removeAt(0);
    q.add(c);
    expect(q.snapshot()).toEqual([c]);
    expect(p.snapshot()).toEqual([x]);
    p.clear();
    expect(p.snapshot()).toEqual([]);
  });

  it("refuses a population on the add's call chain and changes nothing", () => {
    const { child, container } = fixture(kind);
    const k = child("k");
    const x = child("x");
    const p = container("p", [k], false);
    let refused: unknown = null;
    let members: readonly ComponentVM[] = [];
    let kParent: unknown = undefined;
    const subscription = p.collectionChanged.subscribe(() => {
      try {
        p.construct();
      } catch (error) {
        refused = error;
      }
      members = [...p.snapshot()];
      kParent = k._parent;
    });

    p.add(x);
    subscription.unsubscribe();

    expect(members).toEqual([x]);
    expect(kParent).toBeNull();
    expect(refused).toBeInstanceOf(Error);
    expect((refused as Error).message).toMatch(TRANSACTION);
    expect(p.snapshot()).toEqual([x]);

    // After the transaction ends, the population succeeds.
    p.construct();
    expect(p.snapshot()).toEqual([x, k]);
  });
}

describe("COMP-048", () => {
  membershipTransactionCases("composite");
});

describe("GRP-016", () => {
  membershipTransactionCases("group");
});
