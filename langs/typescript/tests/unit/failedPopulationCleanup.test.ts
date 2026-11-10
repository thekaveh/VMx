/**
 * A population that fails before its commit disposes the candidates it built
 * and nobody owns (#1324): aggregate factories and preflight, CompositeVMOf
 * projectors, and the first recompute of filtered projections.
 */
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
  CompositeVMOf,
  ConstructionStatus,
  FilteredCompositeVM,
  MessageHub,
  RxDispatcher,
  ScoredFilteredCompositeVM,
} from "../../src/index.js";

const hub = new MessageHub();
const dispatcher = RxDispatcher.immediate();
const services = { hub, dispatcher };

class FactoryFailure extends Error {}

function leaf(name: string): ComponentVM {
  return ComponentVM.builder().name(name).services(hub, dispatcher).build();
}

interface Built {
  aggregate: ComponentVMBase;
  slots: () => (ComponentVMBase | null)[];
}

/** An aggregate of `arity` slots whose factory for slot `i` is `slot(i)`. */
function aggregate(arity: number, slot: (index: number) => ComponentVM): Built {
  const f = (index: number) => () => slot(index);
  switch (arity) {
    case 2: {
      const a = new AggregateVM2({ name: "agg", factory1: f(1), factory2: f(2), ...services });
      return { aggregate: a, slots: () => [a.component1, a.component2] };
    }
    case 3: {
      const a = new AggregateVM3({
        name: "agg", factory1: f(1), factory2: f(2), factory3: f(3), ...services,
      });
      return { aggregate: a, slots: () => [a.component1, a.component2, a.component3] };
    }
    case 4: {
      const a = new AggregateVM4({
        name: "agg", factory1: f(1), factory2: f(2), factory3: f(3), factory4: f(4), ...services,
      });
      return {
        aggregate: a,
        slots: () => [a.component1, a.component2, a.component3, a.component4],
      };
    }
    case 5: {
      const a = new AggregateVM5({
        name: "agg", factory1: f(1), factory2: f(2), factory3: f(3), factory4: f(4),
        factory5: f(5), ...services,
      });
      return {
        aggregate: a,
        slots: () => [a.component1, a.component2, a.component3, a.component4, a.component5],
      };
    }
    default: {
      const a = new AggregateVM6({
        name: "agg", factory1: f(1), factory2: f(2), factory3: f(3), factory4: f(4),
        factory5: f(5), factory6: f(6), ...services,
      });
      return {
        aggregate: a,
        slots: () => [
          a.component1, a.component2, a.component3, a.component4, a.component5, a.component6,
        ],
      };
    }
  }
}

describe.each([2, 3, 4, 5, 6])("AggregateVM%i failed population", (arity) => {
  it("disposes the earlier candidates when the last factory throws on construct", () => {
    const built: ComponentVM[] = [];
    const { aggregate: agg, slots } = aggregate(arity, (index) => {
      if (index === arity) throw new FactoryFailure();
      const child = leaf(`s${index}`);
      built.push(child);
      return child;
    });

    expect(() => agg.construct()).toThrow(FactoryFailure);

    expect(built).toHaveLength(arity - 1);
    expect(built.every((child) => child.status === ConstructionStatus.Disposed)).toBe(true);
    expect(slots().every((child) => child === null)).toBe(true);
  });

  it("disposes the earlier candidates and keeps a candidate another aggregate owns", () => {
    const owner = new AggregateVM1({ name: "owner", factory1: () => leaf("owned"), ...services });
    owner.construct();
    const owned = owner.component1;
    if (owned === null) throw new Error("owner has no slot");
    const built: ComponentVM[] = [];
    const { aggregate: agg, slots } = aggregate(arity, (index) => {
      if (index === arity) return owned;
      const child = leaf(`s${index}`);
      built.push(child);
      return child;
    });

    expect(() => agg.construct()).toThrow(/already owned/);

    expect(built.every((child) => child.status === ConstructionStatus.Disposed)).toBe(true);
    expect(owned.status).toBe(ConstructionStatus.Constructed);
    expect(owned._parent?.owner).toBe(owner);
    expect(slots().every((child) => child === null)).toBe(true);
  });

  it("keeps the old slots and disposes the fresh candidates when reconstruct fails", () => {
    let failing = false;
    const fresh: ComponentVM[] = [];
    const { aggregate: agg, slots } = aggregate(arity, (index) => {
      if (failing && index === arity) throw new FactoryFailure();
      const child = leaf(`s${index}`);
      if (failing) fresh.push(child);
      return child;
    });
    agg.construct();
    const old = slots();

    failing = true;
    expect(() => agg.reconstruct()).toThrow(FactoryFailure);

    expect(slots()).toEqual(old);
    expect(old.every((child) => child?._parent?.owner === agg)).toBe(true);
    expect(fresh).toHaveLength(arity - 1);
    expect(fresh.every((child) => child.status === ConstructionStatus.Disposed)).toBe(true);
  });
});

describe("CompositeVMOf failed projection", () => {
  it("disposes the earlier children and leaves the composite empty", () => {
    const projected: ComponentVM[] = [];
    const composite = new CompositeVMOf<string, ComponentVM>({
      name: "c",
      childrenModels: () => ["a", "b"],
      childModelToChildViewModel: (model) => {
        if (model === "b") throw new FactoryFailure();
        const child = leaf(model);
        projected.push(child);
        return child;
      },
      ...services,
    });

    expect(() => composite.construct()).toThrow(FactoryFailure);

    expect(projected).toHaveLength(1);
    expect(projected[0]?.status).toBe(ConstructionStatus.Disposed);
    expect(composite.count).toBe(0);
  });
});

describe("filtered projection with a failing first recompute", () => {
  function source(): CompositeVM<ComponentVM> {
    const composite = new CompositeVM<ComponentVM>({ name: "source", ...services });
    composite.add(leaf("a"));
    return composite;
  }

  it("FilteredCompositeVM detaches from the source", () => {
    const src = source();
    let calls = 0;

    expect(() => new FilteredCompositeVM(src, {
      predicate: () => {
        calls++;
        throw new FactoryFailure();
      },
    })).toThrow(FactoryFailure);

    calls = 0;
    expect(() => { src.add(leaf("b")); }).not.toThrow();
    expect(calls).toBe(0);
  });

  it("ScoredFilteredCompositeVM detaches from the source", () => {
    const src = source();
    let calls = 0;

    expect(() => new ScoredFilteredCompositeVM(src, {
      scorer: () => {
        calls++;
        throw new FactoryFailure();
      },
    })).toThrow(FactoryFailure);

    calls = 0;
    expect(() => { src.add(leaf("b")); }).not.toThrow();
    expect(calls).toBe(0);
  });
});
