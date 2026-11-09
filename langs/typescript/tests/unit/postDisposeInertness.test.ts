// Members documented as inert after dispose stay inert (disposal contract).

import { BehaviorSubject } from "rxjs";
import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  CompositeVM,
  DerivedProperty,
  GroupVM,
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

  // Disposal contract, TypeScript exception: membership changes and every
  // selection after Disposed throw Error (#1319).
  function disposedComposite() {
    const hub = new MessageHub();
    const kids = ["a", "b"].map((name) =>
      ComponentVM.builder().name(name).services(hub, RxDispatcher.immediate()).build(),
    );
    const composite = CompositeVM.builder<ComponentVM>()
      .name("p")
      .services(hub, RxDispatcher.immediate())
      .children(() => kids)
      .build();
    composite.construct();
    composite.current = kids[0]!;
    composite.dispose();
    return { composite, a: kids[0]!, b: kids[1]! };
  }

  const extra = () =>
    ComponentVM.builder().name("x").services(new MessageHub(), RxDispatcher.immediate()).build();

  it("a disposed composite refuses membership and selection changes", () => {
    let d = disposedComposite();
    expect(() => d.composite.add(extra())).toThrow("disposing");

    d = disposedComposite();
    expect(() => d.composite.remove(d.b)).toThrow("disposing");

    d = disposedComposite();
    expect(() => d.composite.clear()).toThrow("disposing");
    expect(d.composite.count).toBe(2);

    d = disposedComposite();
    expect(() => (d.composite.current = d.b)).toThrow("disposing");
    expect(d.composite.current).toBe(d.a);

    d = disposedComposite();
    expect(() => (d.composite.current = null)).toThrow("disposing");
    expect(d.composite.current).toBe(d.a);

    d = disposedComposite();
    expect(() => (d.composite.current = d.a)).toThrow("disposing");
    expect(d.composite.current).toBe(d.a);
  });

  it("a disposed group refuses membership changes", () => {
    const hub = new MessageHub();
    const a = ComponentVM.builder().name("a").services(hub, RxDispatcher.immediate()).build();
    const group = GroupVM.builder<ComponentVM>()
      .name("g")
      .services(hub, RxDispatcher.immediate())
      .children(() => [a])
      .build();
    group.construct();
    group.dispose();

    expect(() => group.add(extra())).toThrow("disposing");
    expect(() => group.remove(a)).toThrow("disposing");
    expect(() => group.clear()).toThrow("disposing");
    expect(group.count).toBe(1);
  });

  it("a disposed composite refuses index and move changes", () => {
    const d = disposedComposite();
    expect(() => d.composite.insert(0, extra())).toThrow("disposing");
    expect(() => d.composite.removeAt(1)).toThrow("disposing");
    expect(() => d.composite.setAt(1, extra())).toThrow("disposing");
    expect(() => d.composite.move(0, 1)).toThrow("disposing");
    expect([...d.composite]).toEqual([d.a, d.b]);
    expect(d.composite.current).toBe(d.a);
  });

  it("a disposed group refuses index and move changes", () => {
    const hub = new MessageHub();
    const kids = ["a", "b"].map((name) =>
      ComponentVM.builder().name(name).services(hub, RxDispatcher.immediate()).build(),
    );
    const group = GroupVM.builder<ComponentVM>()
      .name("g")
      .services(hub, RxDispatcher.immediate())
      .children(() => kids)
      .build();
    group.construct();
    group.dispose();

    expect(() => group.insert(0, extra())).toThrow("disposing");
    expect(() => group.removeAt(1)).toThrow("disposing");
    expect(() => group.setAt(1, extra())).toThrow("disposing");
    expect(() => group.move(0, 1)).toThrow("disposing");
    expect([...group]).toEqual(kids);
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
