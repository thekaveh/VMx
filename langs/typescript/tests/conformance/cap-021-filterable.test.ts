// Conformance tests: CAP-021 — IFilterable<T> capability contract surface.
// See spec/14-capabilities.md §Filterable and ADR-0022.

import { describe, expect, it } from "vitest";

import type { IFilterable } from "../../src/capabilities/index.js";
import {
  CompositeVM,
  ComponentVM,
  declareCapabilities,
  hasCapability,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";

// Minimal CompositeVM wrapper that opts in to IFilterable by declaring it.
class FilterableComposite
  extends CompositeVM<ComponentVM>
  implements IFilterable<ComponentVM>
{
  filter: ((item: ComponentVM) => boolean) | null = null;
  constructor(hub: MessageHub) {
    super({
      name: "filterable",
      hint: "",
      hub,
      dispatcher: RxDispatcher.immediate(),
      childrenFactory: () => [],
    });
    declareCapabilities(this, "IFilterable");
  }
  canFilter(): boolean {
    return true;
  }
}

describe("CAP-021", () => {
  it("IFilterable<T> contract: settable filter predicate and canFilter() decision", () => {
    class TestFilterable<T> implements IFilterable<T> {
      filter: ((item: T) => boolean) | null = null;
      canFilter(): boolean {
        return true;
      }
    }

    const sut = new TestFilterable<number>();
    expect(sut.filter).toBeNull();
    expect(sut.canFilter()).toBe(true);

    const p = (x: number) => x > 0;
    sut.filter = p;
    expect(sut.filter).toBe(p);

    sut.filter = null;
    expect(sut.filter).toBeNull();
  });

  it("IFilterable<T>: setting filter to null clears the filter", () => {
    class TestFilterable<T> implements IFilterable<T> {
      filter: ((item: T) => boolean) | null = null;
      canFilter(): boolean {
        return this.filter !== null;
      }
    }

    const sut = new TestFilterable<string>();
    sut.filter = (s: string) => s.length > 0;
    expect(sut.filter).not.toBeNull();
    expect(sut.canFilter()).toBe(true);

    sut.filter = null;
    expect(sut.filter).toBeNull();
    expect(sut.canFilter()).toBe(false);
  });

  it("opt-in CompositeVM wrapper reports IFilterable; a non-opted-in VM reports false", () => {
    const hub = new MessageHub();
    const optIn = new FilterableComposite(hub);
    expect(hasCapability(optIn, "IFilterable")).toBe(true);
    expect(optIn.filter).toBeNull();
    optIn.filter = (vm) => vm.name.startsWith("a");
    expect(optIn.filter).not.toBeNull();
    optIn.filter = null;
    expect(optIn.filter).toBeNull();

    const plainComposite = CompositeVM.builder<ComponentVM>()
      .name("plain")
      .services(hub, RxDispatcher.immediate())
      .children(() => [])
      .build();
    const plainComponent = ComponentVM.builder()
      .name("leaf")
      .services(hub, RxDispatcher.immediate())
      .build();
    expect(hasCapability(plainComposite, "IFilterable")).toBe(false);
    expect(hasCapability(plainComponent, "IFilterable")).toBe(false);
  });
});
