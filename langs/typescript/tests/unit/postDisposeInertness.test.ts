// Members documented as inert after dispose stay inert (disposal contract).

import { BehaviorSubject } from "rxjs";
import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  CompositeVM,
  DerivedProperty,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";

describe("post-dispose inertness", () => {
  it("a disposed child does not change its parent's selection", () => {
    const hub = new MessageHub();
    const kids = ["a", "b"].map((name) =>
      ComponentVM.builder().name(name).services(hub, RxDispatcher.immediate()).build(),
    );
    const parent = CompositeVM.builder<ComponentVM>()
      .name("p")
      .services(hub, RxDispatcher.immediate())
      .children(() => kids)
      .build();
    parent.construct();
    parent.selectComponent(kids[0]!);
    kids[0]!.dispose();
    kids[1]!.dispose();

    expect(kids[0]!.canDeselect()).toBe(false);
    kids[0]!.deselect();
    kids[1]!.select();

    expect(parent.current).toBe(kids[0]);
  });

  it("a disposed derived property rejects writes", () => {
    const writes: number[] = [];
    const property = new DerivedProperty(
      new BehaviorSubject(1),
      () => true,
      (value: number) => writes.push(value),
    );
    property.dispose();

    expect(property.canSet(7)).toBe(false);
    expect(() => property.setValue(7)).toThrow("canSet");
    expect(writes).toEqual([]);
  });
});
