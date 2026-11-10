/**
 * Container walks and the child-transition helper skip a child that is
 * Disposed (spec ch. 02 §6 and §6.1, ch. 06 §5, ch. 07 §2, ch. 08 §3,
 * ADR-0189).
 */
import { describe, expect, it } from "vitest";
import {
  AggregateVM2,
  ComponentVM,
  ComponentVMBase,
  CompositeVM,
  ConstructionStatus as S,
  GroupVM,
  MessageHub,
  RxDispatcher,
  ViewModelType,
} from "../../src/index.js";

const dispatcher = RxDispatcher.immediate();

function leaf(hub: MessageHub, name: string): ComponentVM {
  return ComponentVM.builder().name(name).services(hub, dispatcher).build();
}

interface Box {
  box: ComponentVMBase;
  a: ComponentVM;
  b: ComponentVM;
  members: () => readonly ComponentVMBase[];
}

type MakeBox = () => Box;

const makeComposite: MakeBox = () => {
  const hub = new MessageHub();
  const a = leaf(hub, "a");
  const b = leaf(hub, "b");
  const box = CompositeVM.builder<ComponentVM>()
    .name("box").services(hub, dispatcher).children(() => [a, b]).build();
  return { box, a, b, members: () => box.snapshot() };
};

const makeGroup: MakeBox = () => {
  const hub = new MessageHub();
  const a = leaf(hub, "a");
  const b = leaf(hub, "b");
  const box = GroupVM.builder<ComponentVM>()
    .name("box").services(hub, dispatcher).children(() => [a, b]).build();
  return { box, a, b, members: () => box.snapshot() };
};

const makeAggregate: MakeBox = () => {
  const hub = new MessageHub();
  const box = AggregateVM2.builder<ComponentVM, ComponentVM>()
    .name("box")
    .services(hub, dispatcher)
    .component1(() => leaf(hub, "a"))
    .component2(() => leaf(hub, "b"))
    .build();
  box.construct();
  const a = box.component1 as ComponentVM;
  const b = box.component2 as ComponentVM;
  return { box, a, b, members: () => box.components() };
};

/** Constructs `box` unless the factory already did. */
function constructed(make: MakeBox): Box {
  const made = make();
  if (made.box.status !== S.Constructed) made.box.construct();
  return made;
}

const MEMBERSHIP_CONTAINERS: [string, MakeBox][] = [
  ["CompositeVM", makeComposite],
  ["GroupVM", makeGroup],
];

describe("LIFE-022", () => {
  for (const [kind, make] of [...MEMBERSHIP_CONTAINERS, ["AggregateVM2", makeAggregate]] as [
    string,
    MakeBox,
  ][]) {
    it(`${kind}: destruct() and construct() skip a child that was disposed directly`, () => {
      const { box, a, b, members } = constructed(make);

      b.dispose();
      expect(() => box.destruct()).not.toThrow();

      expect(box.status).toBe(S.Destructed);
      expect(a.status).toBe(S.Destructed);
      expect(b.status).toBe(S.Disposed);
      if (kind !== "AggregateVM2") expect(members()).toContain(b);

      expect(() => box.construct()).not.toThrow();

      expect(box.status).toBe(S.Constructed);
      if (kind === "AggregateVM2") {
        const slots = members();
        expect(slots).toHaveLength(2);
        expect(slots).not.toContain(a);
        expect(slots).not.toContain(b);
        for (const slot of slots) expect(slot.status).toBe(S.Constructed);
      } else {
        expect(a.status).toBe(S.Constructed);
        expect(b.status).toBe(S.Disposed);
      }
    });

    it(`${kind}: reconstruct() from Constructed skips a disposed child`, () => {
      const { box, b } = constructed(make);

      b.dispose();
      expect(() => box.reconstruct()).not.toThrow();

      expect(box.status).toBe(S.Constructed);
      for (const member of box instanceof AggregateVM2 ? box.components() : [b]) {
        if (member !== b) expect(member.status).toBe(S.Constructed);
      }
    });
  }

  for (const [kind, make] of MEMBERSHIP_CONTAINERS) {
    it(`${kind}: a child disposed while the container is Destructed is skipped by construct()`, () => {
      const { box, a, b } = constructed(make);
      box.destruct();

      b.dispose();
      expect(() => box.construct()).not.toThrow();

      expect(box.status).toBe(S.Constructed);
      expect(a.status).toBe(S.Constructed);
      expect(b.status).toBe(S.Disposed);
    });
  }

  it("the child-transition helper skips a Disposed member in both walks", () => {
    const hub = new MessageHub();

    class LeafWithMembers extends ComponentVMBase {
      readonly m1 = leaf(hub, "m1");
      readonly m2 = leaf(hub, "m2");

      get type(): ViewModelType {
        return ViewModelType.Component;
      }

      protected override _onConstruct(): void {
        this._transitionChildren([this.m1, this.m2], true);
      }

      protected override _onDestruct(): void {
        this._transitionChildren([this.m1, this.m2], false);
      }
    }

    const vm = new LeafWithMembers({ name: "vm", hub, dispatcher });
    vm.construct();
    vm.m2.dispose();

    expect(() => vm.destruct()).not.toThrow();
    expect(vm.status).toBe(S.Destructed);
    expect(vm.m1.status).toBe(S.Destructed);

    expect(() => vm.construct()).not.toThrow();
    expect(vm.status).toBe(S.Constructed);
    expect(vm.m1.status).toBe(S.Constructed);
    expect(vm.m2.status).toBe(S.Disposed);
  });
});
