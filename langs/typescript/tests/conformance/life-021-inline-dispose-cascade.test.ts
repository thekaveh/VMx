// LIFE-021: a lifecycle call during the inline dispose cascade fails
// (spec/02-lifecycle.md §7.2, ADR-0175).
//
// A container disposes its children, and a leaf its members, before it
// publishes `Disposed`. A `construct()`, `destruct()`, or `reconstruct()` call
// that starts in that window throws the `StatusTransitionError` of a call on a
// `Disposed` VM and publishes nothing. Once the cascade has started, no hook is
// admitted and no status other than `Disposed` commits, including a commit
// that a background transition queued on the foreground (#1167).

import { describe, expect, it } from "vitest";
import {
  AggregateVM1,
  AggregateVM2,
  AggregateVM3,
  AggregateVM4,
  AggregateVM5,
  AggregateVM6,
  ComponentVM,
  ComponentVMBase,
  CompositeVM,
  ConstructionStatus as S,
  ConstructionStatusChangedMessage,
  GroupVM,
  MessageHub,
  RxDispatcher,
  StatusTransitionError,
  ViewModelType,
  type IDispatcher,
  type IMessageHub,
} from "../../src/index.js";
import { ManualDispatcher } from "../../src/testing/index.js";

type Operation = "construct" | "destruct" | "reconstruct";

/** A child or member VM whose dispose hook runs `onDispose`. */
class HookedVM extends ComponentVMBase {
  onDispose: () => void = () => {};

  constructor(name: string, hub: IMessageHub, dispatcher: IDispatcher) {
    super({ name, hub, dispatcher });
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  protected override _onDispose(): void {
    this.onDispose();
  }
}

/** A leaf VM with one registered member and counted lifecycle hooks. */
class MemberLeafVM extends ComponentVMBase {
  hookCalls = 0;

  constructor(
    hub: IMessageHub,
    dispatcher: IDispatcher,
    readonly member: ComponentVMBase,
    background = false,
  ) {
    super({ name: "leaf", hub, dispatcher, background });
    this.ownMember(member);
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  protected override _onConstruct(): void {
    this.hookCalls += 1;
  }

  protected override _onDestruct(): void {
    this.hookCalls += 1;
  }
}

/** Records the status messages each VM publishes, in order. */
function recordStatuses(hub: IMessageHub): Map<object, S[]> {
  const statuses = new Map<object, S[]>();
  hub.messages.subscribe((message) => {
    if (!(message instanceof ConstructionStatusChangedMessage)) return;
    const list = statuses.get(message.sender) ?? [];
    list.push(message.status);
    statuses.set(message.sender, list);
  });
  return statuses;
}

interface Container {
  readonly box: ComponentVMBase;
  readonly children: () => readonly ComponentVMBase[];
  readonly hookCalls: () => number;
  readonly factoryCalls: () => number;
}

interface ContainerKind {
  readonly name: string;
  readonly make: (hub: IMessageHub, dispatcher: IDispatcher, c1: HookedVM) => Container;
}

function plain(name: string, hub: IMessageHub, dispatcher: IDispatcher): HookedVM {
  return new HookedVM(name, hub, dispatcher);
}

function aggregateKind(
  arity: number,
  create: (opts: {
    name: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    factories: Array<() => ComponentVMBase>;
  }) => ComponentVMBase & { components(): readonly ComponentVMBase[] },
): ContainerKind {
  return {
    name: `AggregateVM${String(arity)}`,
    make: (hub, dispatcher, c1) => {
      let factoryCalls = 0;
      const factories = Array.from({ length: arity }, (_, i) => () => {
        factoryCalls += 1;
        return i === 0 && factoryCalls === 1 ? c1 : plain(`slot${String(i + 1)}`, hub, dispatcher);
      });
      const box = create({ name: "box", hub, dispatcher, factories });
      return {
        box,
        children: () => box.components(),
        hookCalls: () => 0,
        factoryCalls: () => factoryCalls,
      };
    },
  };
}

const KINDS: readonly ContainerKind[] = [
  {
    name: "CompositeVM",
    make: (hub, dispatcher, c1) => {
      let hookCalls = 0;
      let factoryCalls = 0;
      const c2 = plain("c2", hub, dispatcher);
      const box = CompositeVM.builder<ComponentVMBase>()
        .name("box")
        .services(hub, dispatcher)
        .children(() => {
          factoryCalls += 1;
          return [c1, c2];
        })
        .onConstruct(() => { hookCalls += 1; })
        .onDestruct(() => { hookCalls += 1; })
        .build();
      return {
        box,
        children: () => [...box],
        hookCalls: () => hookCalls,
        factoryCalls: () => factoryCalls,
      };
    },
  },
  {
    name: "GroupVM",
    make: (hub, dispatcher, c1) => {
      let hookCalls = 0;
      let factoryCalls = 0;
      const c2 = plain("c2", hub, dispatcher);
      const box = GroupVM.builder<ComponentVMBase>()
        .name("box")
        .services(hub, dispatcher)
        .children(() => {
          factoryCalls += 1;
          return factoryCalls === 1 ? [c1, c2] : [];
        })
        .onConstruct(() => { hookCalls += 1; })
        .onDestruct(() => { hookCalls += 1; })
        .build();
      return {
        box,
        children: () => [...box],
        hookCalls: () => hookCalls,
        factoryCalls: () => factoryCalls,
      };
    },
  },
  aggregateKind(1, ({ factories: [f1], ...o }) =>
    new AggregateVM1({ ...o, factory1: f1! })),
  aggregateKind(2, ({ factories: [f1, f2], ...o }) =>
    new AggregateVM2({ ...o, factory1: f1!, factory2: f2! })),
  aggregateKind(3, ({ factories: [f1, f2, f3], ...o }) =>
    new AggregateVM3({ ...o, factory1: f1!, factory2: f2!, factory3: f3! })),
  aggregateKind(4, ({ factories: [f1, f2, f3, f4], ...o }) =>
    new AggregateVM4({ ...o, factory1: f1!, factory2: f2!, factory3: f3!, factory4: f4! })),
  aggregateKind(5, ({ factories: [f1, f2, f3, f4, f5], ...o }) =>
    new AggregateVM5({
      ...o, factory1: f1!, factory2: f2!, factory3: f3!, factory4: f4!, factory5: f5!,
    })),
  aggregateKind(6, ({ factories: [f1, f2, f3, f4, f5, f6], ...o }) =>
    new AggregateVM6({
      ...o,
      factory1: f1!, factory2: f2!, factory3: f3!, factory4: f4!, factory5: f5!, factory6: f6!,
    })),
];

/** The call and the start status of the VM it is called on. */
const CASES: ReadonlyArray<{ op: Operation; from: S; label: string }> = [
  { op: "construct", from: S.Destructed, label: "Destructed" },
  { op: "destruct", from: S.Constructed, label: "Constructed" },
  { op: "construct", from: S.Constructed, label: "Constructed" },
  { op: "reconstruct", from: S.Constructed, label: "Constructed" },
];

function expectDisposedError(error: unknown, op: Operation): void {
  expect(error).toBeInstanceOf(StatusTransitionError);
  const transition = error as StatusTransitionError;
  expect(transition.currentStatus).toBe(S.Disposed);
  expect(transition.attemptedOperation).toBe(op);
  expect(transition.message).toBe(new StatusTransitionError(S.Disposed, op).message);
}

function call(vm: ComponentVMBase, op: Operation): unknown {
  try {
    vm[op]();
  } catch (error) {
    return error;
  }
  return undefined;
}

describe("LIFE-021", () => {
  describe.each(KINDS)("$name", (kind) => {
    it.each(CASES)("$op() from $label, called from c1's dispose hook, fails", ({ op, from }) => {
      const hub = new MessageHub();
      const dispatcher = RxDispatcher.immediate();
      const statuses = recordStatuses(hub);
      const c1 = plain("c1", hub, dispatcher);
      const { box, children, hookCalls, factoryCalls } = kind.make(hub, dispatcher, c1);

      // Construct once so that c1 exists, then reach the start status.
      box.construct();
      if (from === S.Destructed) box.destruct();
      expect(box.status).toBe(from);
      const held = children();
      expect(held).toContain(c1);
      const hooksBefore = hookCalls();
      const factoriesBefore = factoryCalls();
      statuses.clear();

      let recorded: unknown = "not called";
      let statusInHook: S | undefined;
      c1.onDispose = () => {
        statusInHook = box.status;
        recorded = call(box, op);
      };

      box.dispose();

      expectDisposedError(recorded, op);
      // The §2.1 predicates still read Status, which is not Disposed yet.
      expect(statusInHook).toBe(from);
      expect(hookCalls()).toBe(hooksBefore);
      expect(factoryCalls()).toBe(factoriesBefore);
      expect(statuses.get(box)).toEqual([S.Disposed]);
      expect(box.status).toBe(S.Disposed);
      // No slot or child was replaced or added during the cascade.
      expect(children().every((child) => held.includes(child))).toBe(true);
      for (const child of held) {
        expect(child.status).toBe(S.Disposed);
        expect(statuses.get(child)).toEqual([S.Disposed]);
      }
    });
  });

  describe("leaf member cascade", () => {
    it.each(CASES)("$op() from $label, called from the member's dispose hook, fails", ({ op, from }) => {
      const hub = new MessageHub();
      const dispatcher = RxDispatcher.immediate();
      const statuses = recordStatuses(hub);
      const member = plain("member", hub, dispatcher);
      const leaf = new MemberLeafVM(hub, dispatcher, member);
      if (from === S.Constructed) leaf.construct();
      const hooksBefore = leaf.hookCalls;
      statuses.clear();

      let recorded: unknown = "not called";
      member.onDispose = () => {
        recorded = call(leaf, op);
      };

      leaf.dispose();

      expectDisposedError(recorded, op);
      expect(leaf.hookCalls).toBe(hooksBefore);
      expect(statuses.get(leaf)).toEqual([S.Disposed]);
      expect(statuses.get(member)).toEqual([S.Disposed]);
    });

    it("a background leaf refuses construct() from the member's dispose hook", () => {
      const hub = new MessageHub();
      const dispatcher = new ManualDispatcher();
      const statuses = recordStatuses(hub);
      const member = plain("member", hub, dispatcher);
      const leaf = new MemberLeafVM(hub, dispatcher, member, true);

      let recorded: unknown = "not called";
      member.onDispose = () => {
        recorded = call(leaf, "construct");
        dispatcher.flushAll();
      };

      leaf.dispose();

      expectDisposedError(recorded, "construct");
      expect(leaf.hookCalls).toBe(0);
      expect(statuses.get(leaf)).toEqual([S.Disposed]);
    });

    it("a queued background Constructed commit drained in the member's dispose hook is dropped", () => {
      const hub = new MessageHub();
      const dispatcher = new ManualDispatcher();
      const statuses = recordStatuses(hub);
      const member = plain("member", hub, dispatcher);
      const leaf = new MemberLeafVM(hub, dispatcher, member, true);

      leaf.construct();
      dispatcher.flushBackground();
      // The construct hook has run; its Constructed commit waits on the foreground.
      expect(leaf.hookCalls).toBe(1);
      expect(leaf.status).toBe(S.Constructing);

      let statusAfterDrain: S | undefined;
      member.onDispose = () => {
        dispatcher.flushForeground();
        statusAfterDrain = leaf.status;
      };

      leaf.dispose();

      expect(statusAfterDrain).toBe(S.Constructing);
      expect(statuses.get(leaf)).toEqual([S.Constructing, S.Disposed]);
      expect(leaf.status).toBe(S.Disposed);
      expect(member.status).toBe(S.Disposed);
    });

    it("a queued background construct hook drained in the member's dispose hook does not run", () => {
      const hub = new MessageHub();
      const dispatcher = new ManualDispatcher();
      const statuses = recordStatuses(hub);
      const member = plain("member", hub, dispatcher);
      const leaf = new MemberLeafVM(hub, dispatcher, member, true);

      leaf.construct();
      expect(leaf.hookCalls).toBe(0);
      member.onDispose = () => {
        dispatcher.flushAll();
      };

      leaf.dispose();

      expect(leaf.hookCalls).toBe(0);
      expect(statuses.get(leaf)).toEqual([S.Constructing, S.Disposed]);
    });

    it("a reconstruct() whose Destructed subscriber disposes the leaf starts no construct phase", () => {
      const hub = new MessageHub();
      const dispatcher = RxDispatcher.immediate();
      const member = plain("member", hub, dispatcher);
      const leaf = new MemberLeafVM(hub, dispatcher, member);
      leaf.construct();
      const statuses = recordStatuses(hub);
      hub.messages.subscribe((message) => {
        if (
          message instanceof ConstructionStatusChangedMessage &&
          message.sender === leaf &&
          message.status === S.Destructed
        ) leaf.dispose();
      });
      const hooksBefore = leaf.hookCalls;

      expect(() => leaf.reconstruct()).not.toThrow();

      // Only the destruct hook ran.
      expect(leaf.hookCalls).toBe(hooksBefore + 1);
      expect(statuses.get(leaf)).toEqual([S.Destructing, S.Destructed, S.Disposed]);
      expect(member.status).toBe(S.Disposed);
    });
  });

  describe("container transitions that started before the cascade", () => {
    it("a composite waiting on a background child commits nothing when a child's dispose hook settles it", () => {
      const hub = new MessageHub();
      const dispatcher = new ManualDispatcher();
      const statuses = recordStatuses(hub);
      const c1 = plain("c1", hub, dispatcher);
      const c2 = ComponentVM.builder().name("c2").services(hub, dispatcher).background(true).build();
      const box = CompositeVM.builder<ComponentVMBase>()
        .name("box")
        .services(hub, dispatcher)
        .children(() => [c1, c2])
        .build();

      box.construct();
      // c2's construct hook is queued, so box waits in Constructing.
      expect(box.status).toBe(S.Constructing);
      expect(c2.status).toBe(S.Constructing);
      c1.onDispose = () => {
        dispatcher.flushBackground();
        dispatcher.flushForeground();
      };

      box.dispose();

      expect(statuses.get(box)).toEqual([S.Constructing, S.Disposed]);
      expect(c1.status).toBe(S.Disposed);
      expect(c2.status).toBe(S.Disposed);
    });
  });
});
