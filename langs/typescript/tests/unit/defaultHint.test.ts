/**
 * Raw constructors default `hint` to "" and modeled constructors default
 * `modeledHinter` to a hinter that returns "", as the builders do (spec/10 §4,
 * BLD-004). No conformance ID (TypeScript constructor ergonomics, #663).
 */
import { describe, expect, it } from "vitest";
import {
  AggregateVM1,
  AggregateVM2,
  AggregateVM3,
  AggregateVM4,
  AggregateVM5,
  AggregateVM6,
  ComponentVMBase,
  ComponentVMOf,
  CompositeVM,
  CompositeVMOf,
  GroupVM,
  MessageHub,
  ReadonlyComponentVMOf,
  RxDispatcher,
  ViewModelType,
} from "../../src/index.js";

const services = () => ({ hub: new MessageHub(), dispatcher: RxDispatcher.immediate() });

class PanelVM extends ComponentVMBase {
  constructor() {
    super({ name: "panel", ...services() });
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

describe("raw constructors default hint to an empty string", () => {
  it("ComponentVMBase subclass", () => {
    expect(new PanelVM().hint).toBe("");
  });

  it("ComponentVMOf, with the modeled hint defaulting to an empty string", () => {
    const vm = new ComponentVMOf<number>({ name: "count", initialModel: 1, ...services() });

    expect([vm.hint, vm.modeledHint]).toEqual(["", ""]);
    vm.model = 2;
    expect(vm.modeledHint).toBe("");
  });

  it("ComponentVMOf keeps a supplied modeled hinter", () => {
    const vm = new ComponentVMOf<number>({
      name: "count",
      initialModel: 1,
      modeledHinter: (m) => `#${m}`,
      ...services(),
    });

    expect([vm.hint, vm.modeledHint]).toEqual(["", "#1"]);
  });

  it("ReadonlyComponentVMOf", () => {
    const vm = new ReadonlyComponentVMOf<string>({ name: "title", model: "draft", ...services() });

    expect([vm.hint, vm.modeledHint]).toEqual(["", ""]);
  });

  it("CompositeVM, CompositeVMOf and GroupVM", () => {
    const composite = new CompositeVM<PanelVM>({ name: "composite", ...services() });
    const modeled = new CompositeVMOf<number, PanelVM>({
      name: "modeled",
      childrenModels: () => [],
      childModelToChildViewModel: () => new PanelVM(),
      ...services(),
    });
    const group = new GroupVM<PanelVM>({ name: "group", ...services() });

    expect([composite.hint, modeled.hint, group.hint]).toEqual(["", "", ""]);
  });

  it("AggregateVM1 to AggregateVM6", () => {
    const f = () => new PanelVM();
    const aggregates = [
      new AggregateVM1<PanelVM>({ name: "a1", factory1: f, ...services() }),
      new AggregateVM2<PanelVM, PanelVM>({ name: "a2", factory1: f, factory2: f, ...services() }),
      new AggregateVM3<PanelVM, PanelVM, PanelVM>({
        name: "a3", factory1: f, factory2: f, factory3: f, ...services(),
      }),
      new AggregateVM4<PanelVM, PanelVM, PanelVM, PanelVM>({
        name: "a4", factory1: f, factory2: f, factory3: f, factory4: f, ...services(),
      }),
      new AggregateVM5<PanelVM, PanelVM, PanelVM, PanelVM, PanelVM>({
        name: "a5", factory1: f, factory2: f, factory3: f, factory4: f, factory5: f, ...services(),
      }),
      new AggregateVM6<PanelVM, PanelVM, PanelVM, PanelVM, PanelVM, PanelVM>({
        name: "a6", factory1: f, factory2: f, factory3: f, factory4: f, factory5: f, factory6: f,
        ...services(),
      }),
    ];

    expect(aggregates.map((vm) => vm.hint)).toEqual(["", "", "", "", "", ""]);
  });

  it("keeps a supplied hint", () => {
    const vm = new ComponentVMOf<number>({ name: "count", hint: "Count", initialModel: 1, ...services() });

    expect(vm.hint).toBe("Count");
  });
});
