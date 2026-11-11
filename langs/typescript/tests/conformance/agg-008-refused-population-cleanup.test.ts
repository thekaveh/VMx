/**
 * A fixed-slot population that its preflight refuses disposes the candidates
 * that nobody owns (spec/08 §2 and §4, ADR-0224, #1324).
 */
import { describe, expect, it } from "vitest";
import {
  AggregateVM2,
  ComponentVM,
  CompositeVM,
  ConstructionStatus,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";

const hub = new MessageHub();
const dispatcher = RxDispatcher.immediate();

function leaf(name: string): ComponentVM {
  return ComponentVM.builder().name(name).services(hub, dispatcher).build();
}

/** A component that a constructed composite owns. */
function owned(name: string): { component: ComponentVM; owner: CompositeVM<ComponentVM> } {
  const component = leaf(name);
  const owner = CompositeVM.builder<ComponentVM>()
    .name("owner")
    .services(hub, dispatcher)
    .children(() => [component])
    .build();
  owner.construct();
  expect(component.status).toBe(ConstructionStatus.Constructed);
  return { component, owner };
}

function expectOwnedBy(component: ComponentVM, owner: CompositeVM<ComponentVM>): void {
  expect(component.status).toBe(ConstructionStatus.Constructed);
  expect(component._parent?.owner).toBe(owner);
  expect(owner.snapshot()).toEqual([component]);
}

describe("AGG-008", () => {
  it("a refused construct() disposes the unowned candidates and keeps the owned one", () => {
    const fresh = leaf("fresh");
    const { component: borrowed, owner } = owned("borrowed");
    const aggregate = new AggregateVM2({
      name: "aggregate",
      factory1: () => fresh,
      factory2: () => borrowed,
      hub,
      dispatcher,
    });

    expect(() => aggregate.construct()).toThrow(/already owned/);

    expect(fresh.status).toBe(ConstructionStatus.Disposed);
    expectOwnedBy(borrowed, owner);
    expect(aggregate.component1).toBeNull();
    expect(aggregate.component2).toBeNull();
  });

  it("a refused reconstruct() keeps the old slots and disposes the fresh candidates", () => {
    const first = leaf("first");
    const second = leaf("second");
    const replacement = leaf("replacement");
    const { component: borrowed, owner } = owned("borrowed");
    let calls1 = 0;
    let calls2 = 0;
    const aggregate = new AggregateVM2({
      name: "aggregate",
      factory1: () => (++calls1 === 1 ? first : replacement),
      factory2: () => (++calls2 === 1 ? second : borrowed),
      hub,
      dispatcher,
    });
    aggregate.construct();

    expect(() => aggregate.reconstruct()).toThrow(/already owned/);

    expect(aggregate.component1).toBe(first);
    expect(aggregate.component2).toBe(second);
    for (const old of [first, second]) {
      expect(old._parent?.owner).toBe(aggregate);
      expect(old.status).toBe(ConstructionStatus.Destructed);
    }
    expect(replacement.status).toBe(ConstructionStatus.Disposed);
    expect(replacement._parent).toBeNull();
    expectOwnedBy(borrowed, owner);
  });
});
