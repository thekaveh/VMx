// Unit tests for ComponentVMOf builder optional setters — paths that no
// conformance test, example, or doc exercised (spec/10 §2 optional setters).

import { describe, expect, it } from "vitest";
import {
  ComponentVMOf,
  MessageHub,
  RxDispatcher,
  ViewModelType,
} from "../../src/index.js";

interface Tab {
  title: string;
}

function services() {
  return { hub: new MessageHub(), disp: RxDispatcher.immediate() };
}

describe("ComponentVMOfBuilder – optional setters", () => {
  it("vmType overrides the reported type", () => {
    const { hub, disp } = services();
    const vm = ComponentVMOf.builder<Tab>()
      .name("typed")
      .model({ title: "home" })
      .vmType(ViewModelType.Aggregate)
      .services(hub, disp)
      .build();

    expect(vm.type).toBe(ViewModelType.Aggregate);
  });

  it("onModelChanged callback fires on model set", () => {
    const { hub, disp } = services();
    const seen: Tab[] = [];
    const vm = ComponentVMOf.builder<Tab>()
      .name("watched")
      .model({ title: "home" })
      .onModelChanged((m) => seen.push(m))
      .services(hub, disp)
      .build();

    vm.model = { title: "settings" };

    expect(seen.map((m) => m.title)).toEqual(["settings"]);
  });
});
