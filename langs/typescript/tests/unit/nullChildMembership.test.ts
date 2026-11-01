// A null or undefined child is rejected before the container opens its
// membership transaction, so later adds and disposal still proceed (#1048).

import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  CompositeVM,
  ConstructionStatus,
  GroupVM,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";

type Container = GroupVM<ComponentVM> | CompositeVM<ComponentVM>;

function child(name: string): ComponentVM {
  return ComponentVM.builder().name(name).services(new MessageHub(), RxDispatcher.immediate()).build();
}

function container(kind: "group" | "composite"): Container {
  const builder = kind === "group" ? GroupVM.builder<ComponentVM>() : CompositeVM.builder<ComponentVM>();
  return builder
    .name(kind)
    .services(new MessageHub(), RxDispatcher.immediate())
    .children(() => [])
    .build();
}

function mutate(target: Container, mutation: "add" | "insert" | "setAt", item: null | undefined): void {
  const missing = item as unknown as ComponentVM;
  if (mutation === "add") target.add(missing);
  else if (mutation === "insert") target.insert(0, missing);
  else target.setAt(0, missing);
}

const cases = (["group", "composite"] as const).flatMap((kind) =>
  (["add", "insert", "setAt"] as const).flatMap((mutation) =>
    ([null, undefined] as const).map((item) => [kind, mutation, item] as const),
  ),
);

describe("containers reject a missing child before the membership transaction", () => {
  it.each(cases)("%s.%s(%s) throws and leaves the children unchanged", (kind, mutation, item) => {
    const target = container(kind);
    const seed = child("seed");
    target.add(seed);

    expect(() => mutate(target, mutation, item)).toThrow("child must not be null");

    expect(target.snapshot()).toEqual([seed]);
  });

  it.each(cases)("%s.%s(%s) leaves no open transaction for a later add or dispose", (kind, mutation, item) => {
    const target = container(kind);
    target.add(child("seed"));
    expect(() => mutate(target, mutation, item)).toThrow();

    const later = child("later");
    target.add(later);
    expect(target.snapshot()).toContain(later);

    target.dispose();
    expect(target.status).toBe(ConstructionStatus.Disposed);
  });
});
