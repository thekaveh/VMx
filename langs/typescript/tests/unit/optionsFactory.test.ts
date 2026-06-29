// Tests for the additive `create(options)` construction form (ADR-0055 / VMX-020).
//
// Each `create` static factory is a one-call alternative to the fluent builder.
// It delegates to the builder internally, so behaviour/validation are identical
// by construction; these tests pin that contract: the `create` path produces a
// VM equivalent to the builder path and validates the same required fields.
import { describe, it, expect } from "vitest";
import {
  MessageHub,
  RxDispatcher,
  ComponentVM,
  ComponentVMOf,
  CompositeVM,
  GroupVM,
  ViewModelType,
  ConstructionStatus,
  BuilderValidationError,
} from "../../src/index.js";
import type {
  ComponentVMOptions,
  ComponentVMOfOptions,
  CompositeVMOptions,
  GroupVMOptions,
} from "../../src/index.js";

function makeHub() {
  return new MessageHub();
}
function makeDisp() {
  return RxDispatcher.immediate();
}

// ── ComponentVM (non-modeled) ────────────────────────────────────────────────

describe("ComponentVM.create", () => {
  it("matches the builder path", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const viaBuilder = ComponentVM.builder().name("vm").hint("h").services(hub, disp).build();
    const viaOptions = ComponentVM.create({ name: "vm", hint: "h", hub, dispatcher: disp });

    expect(viaOptions.name).toBe(viaBuilder.name);
    expect(viaOptions.hint).toBe(viaBuilder.hint);
    expect(viaOptions.type).toBe(viaBuilder.type);
    expect(viaOptions.type).toBe(ViewModelType.Component);
    expect(viaOptions.status).toBe(viaBuilder.status);
  });

  it("constructs like the builder", () => {
    const vm = ComponentVM.create({ name: "vm", hub: makeHub(), dispatcher: makeDisp() });
    vm.construct();
    expect(vm.status).toBe(ConstructionStatus.Constructed);
  });

  it("throws BuilderValidationError on a missing hub", () => {
    expect(() =>
      ComponentVM.create({ name: "vm" } as unknown as ComponentVMOptions),
    ).toThrow(BuilderValidationError);
  });

  it("throws BuilderValidationError on a missing name", () => {
    expect(() =>
      ComponentVM.create({
        hub: makeHub(),
        dispatcher: makeDisp(),
      } as unknown as ComponentVMOptions),
    ).toThrow(BuilderValidationError);
  });
});

// ── ComponentVMOf (modeled) ──────────────────────────────────────────────────

describe("ComponentVMOf.create", () => {
  it("matches the builder path", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const viaBuilder = ComponentVMOf.builder<string>()
      .name("vm")
      .hint("h")
      .model("m")
      .services(hub, disp)
      .build();
    const viaOptions = ComponentVMOf.create<string>({
      name: "vm",
      hint: "h",
      model: "m",
      hub,
      dispatcher: disp,
    });

    expect(viaOptions.name).toBe(viaBuilder.name);
    expect(viaOptions.hint).toBe(viaBuilder.hint);
    expect(viaOptions.model).toBe(viaBuilder.model);
    expect(viaOptions.model).toBe("m");
    expect(viaOptions.type).toBe(viaBuilder.type);
  });

  it("carries optional fields", () => {
    const changes: string[] = [];
    const vm = ComponentVMOf.create<string>({
      name: "vm",
      model: "m0",
      modeledHinter: (m) => `hint:${m}`,
      onModelChanged: (m) => changes.push(m),
      hub: makeHub(),
      dispatcher: makeDisp(),
    });

    expect(vm.modeledHint).toBe("hint:m0");
    vm.model = "m1";
    expect(vm.model).toBe("m1");
    expect(changes).toEqual(["m1"]);
  });

  it("throws BuilderValidationError on a missing hub", () => {
    expect(() =>
      ComponentVMOf.create({ name: "vm", model: "m" } as unknown as ComponentVMOfOptions<string>),
    ).toThrow(BuilderValidationError);
  });
});

// ── CompositeVM (non-modeled) ────────────────────────────────────────────────

describe("CompositeVM.create", () => {
  it("matches the builder path and populates on construct", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const child = () => ComponentVM.create({ name: "child", hub, dispatcher: disp });

    const vm = CompositeVM.create<ComponentVM>({
      name: "comp",
      hint: "h",
      hub,
      dispatcher: disp,
      children: () => [child()],
    });

    expect(vm.name).toBe("comp");
    expect(vm.hint).toBe("h");
    expect(vm.type).toBe(ViewModelType.Composite);
    expect(vm.count).toBe(0); // children factory is lazy: evaluated on construct()

    vm.construct();
    expect(vm.status).toBe(ConstructionStatus.Constructed);
    expect(vm.count).toBe(1);
  });

  it("throws BuilderValidationError on missing children", () => {
    expect(() =>
      CompositeVM.create({
        name: "comp",
        hub: makeHub(),
        dispatcher: makeDisp(),
      } as unknown as CompositeVMOptions<ComponentVM>),
    ).toThrow(BuilderValidationError);
  });

  it("throws BuilderValidationError on a missing hub", () => {
    expect(() =>
      CompositeVM.create({
        name: "comp",
        children: () => [],
      } as unknown as CompositeVMOptions<ComponentVM>),
    ).toThrow(BuilderValidationError);
  });
});

// ── GroupVM (non-modeled) ────────────────────────────────────────────────────

describe("GroupVM.create", () => {
  it("matches the builder path and populates on construct", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const child = () => ComponentVM.create({ name: "child", hub, dispatcher: disp });

    const vm = GroupVM.create<ComponentVM>({
      name: "grp",
      hub,
      dispatcher: disp,
      children: () => [child(), child()],
    });

    expect(vm.name).toBe("grp");
    expect(vm.type).toBe(ViewModelType.Group);

    vm.construct();
    expect(vm.status).toBe(ConstructionStatus.Constructed);
    expect(vm.count).toBe(2);
  });

  it("throws BuilderValidationError on a missing hub", () => {
    expect(() =>
      GroupVM.create({
        name: "grp",
        children: () => [],
      } as unknown as GroupVMOptions<ComponentVM>),
    ).toThrow(BuilderValidationError);
  });
});
