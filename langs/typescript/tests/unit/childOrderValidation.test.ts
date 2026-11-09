/**
 * An unknown destruct-order value throws a `TypeError` (#1397). `destructWalk`
 * reverses only for `"reverse"`, so an untyped caller's `"Reverse"` would
 * otherwise give insertion order with no error.
 */
import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  CompositeVM,
  CompositeVMOf,
  GroupVM,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";
import type { ChildOrder } from "../../src/index.js";

const hub = new MessageHub();
const dispatcher = RxDispatcher.immediate();
const unknown = "Reverse" as ChildOrder;

describe("unknown ChildOrder", () => {
  it.each([
    ["GroupVMBuilder", () => GroupVM.builder<ComponentVM>().destructOrder(unknown)],
    ["CompositeVMBuilder", () => CompositeVM.builder<ComponentVM>().destructOrder(unknown)],
    [
      "CompositeVMOfBuilder",
      () => CompositeVMOf.builder<string, ComponentVM>().destructOrder(unknown),
    ],
  ])("%s.destructOrder throws a TypeError", (_name, act) => {
    expect(act).toThrow(TypeError);
  });

  it.each([
    [
      "GroupVM.create",
      () => GroupVM.create<ComponentVM>({
        name: "g", hub, dispatcher, children: () => [], destructOrder: unknown,
      }),
    ],
    [
      "CompositeVM.create",
      () => CompositeVM.create<ComponentVM>({
        name: "c", hub, dispatcher, children: () => [], destructOrder: unknown,
      }),
    ],
    [
      "GroupVM constructor",
      () => new GroupVM<ComponentVM>({ name: "g", hub, dispatcher, destructOrder: unknown }),
    ],
    [
      "CompositeVM constructor",
      () => new CompositeVM<ComponentVM>({ name: "c", hub, dispatcher, destructOrder: unknown }),
    ],
    [
      "CompositeVMOf constructor",
      () => new CompositeVMOf<string, ComponentVM>({
        name: "c",
        hub,
        dispatcher,
        childrenModels: () => [],
        childModelToChildViewModel: (model) => ComponentVM.builder().name(model)
          .services(hub, dispatcher).build(),
        destructOrder: unknown,
      }),
    ],
  ])("%s throws a TypeError", (_name, act) => {
    expect(act).toThrow(TypeError);
  });

  it.each(["insertion", "reverse"] as const)("accepts %s", (order) => {
    expect(() => GroupVM.builder<ComponentVM>().destructOrder(order)).not.toThrow();
  });
});
