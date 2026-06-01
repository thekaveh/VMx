// FORM-011..FORM-013 conformance tests — FormVMBuilder<TM>.
// See spec/10-builders.md §3 and ADR-0035 §2 FV1 / FV2.

import { describe, expect, it } from "vitest";

import {
  BuilderValidationError,
  FormVM,
  FormVMBuilder,
  NullMessageHub,
} from "../../src/index.js";

// ---------------------------------------------------------------------------
// Shared model helpers
// ---------------------------------------------------------------------------

interface IModel {
  name: string;
  value: number;
}

function makeModel(name: string, value: number): IModel {
  return { name, value };
}

const noopPersister = async (_m: IModel): Promise<void> => {};

// ---------------------------------------------------------------------------
// FORM-011 — build() validates required initial + persister
// ---------------------------------------------------------------------------

describe("FORM-011", () => {
  it("throws BuilderValidationError('initial') when initial not set", () => {
    const builder = FormVM.builder<IModel>().persister(noopPersister);
    expect(() => builder.build()).toThrow(BuilderValidationError);
    try {
      builder.build();
    } catch (e) {
      expect(e).toBeInstanceOf(BuilderValidationError);
      expect((e as BuilderValidationError).missingField).toBe("initial");
    }
  });

  it("throws BuilderValidationError('persister') when persister not set", () => {
    const builder = FormVM.builder<IModel>().initial(makeModel("Alice", 1));
    expect(() => builder.build()).toThrow(BuilderValidationError);
    try {
      builder.build();
    } catch (e) {
      expect(e).toBeInstanceOf(BuilderValidationError);
      expect((e as BuilderValidationError).missingField).toBe("persister");
    }
  });

  it("FormVM.builder() returns a FormVMBuilder<TM> instance", () => {
    const b = FormVM.builder<IModel>();
    expect(b).toBeInstanceOf(FormVMBuilder);
  });

  it("builds successfully when both required fields are set", () => {
    const vm = FormVM.builder<IModel>()
      .initial(makeModel("Alice", 1))
      .persister(noopPersister)
      .build();
    expect(vm).toBeInstanceOf(FormVM);
    vm.dispose();
  });

  it("setters return new builder instances (BLD-001)", () => {
    const b1 = FormVM.builder<IModel>();
    const b2 = b1.initial(makeModel("Alice", 1));
    const b3 = b2.persister(noopPersister);
    expect(b1).not.toBe(b2);
    expect(b2).not.toBe(b3);
    expect(b1).not.toBe(b3);
  });
});

// ---------------------------------------------------------------------------
// FORM-012 — Repeated build() calls produce distinct-but-equivalent forms
// ---------------------------------------------------------------------------

describe("FORM-012", () => {
  it("repeated build() calls produce distinct-but-equivalent FormVMs", () => {
    const initial = makeModel("Alice", 1);
    const builder = FormVM.builder<IModel>()
      .initial(initial)
      .persister(noopPersister);

    const vmA = builder.build();
    const vmB = builder.build();

    // Distinct instances
    expect(vmA).not.toBe(vmB);

    // Equivalent state
    expect(vmA.model).toEqual(vmB.model);
    expect(vmA.snapshot).toEqual(vmB.snapshot);
    expect(vmA.isDirty).toBe(false);
    expect(vmB.isDirty).toBe(false);

    vmA.dispose();
    vmB.dispose();
  });
});

// ---------------------------------------------------------------------------
// FORM-013 — Field defaults applied when not set
// ---------------------------------------------------------------------------

describe("FORM-013", () => {
  it("hub defaults to NullMessageHub.INSTANCE when not set", () => {
    // No public getter for the hub; observe behavior — denyCommand sends
    // messages through the hub, and the null hub is a no-op (does not throw,
    // does not retain). We assert the default by confirming construction +
    // a deny() round-trip succeed without any wired hub.
    const vm = FormVM.builder<IModel>()
      .initial(makeModel("Alice", 1))
      .persister(noopPersister)
      .build();

    // Mutate then revert via denyCommand; should not throw even though no
    // hub was wired (proving the default null hub is in place).
    vm.setModel(makeModel("Bob", 2));
    expect(vm.isDirty).toBe(true);
    vm.denyCommand.execute();
    expect(vm.isDirty).toBe(false);

    vm.dispose();
  });

  it("strict defaults to false (approveCommand.canExecute() true when not dirty)", () => {
    const vm = FormVM.builder<IModel>()
      .initial(makeModel("Alice", 1))
      .persister(noopPersister)
      .build();

    expect(vm.isDirty).toBe(false);
    // With strict default (false), approveCommand.canExecute() must be true.
    expect(vm.approveCommand.canExecute()).toBe(true);

    vm.dispose();
  });

  it("explicit hub override is honored when set", () => {
    // Sanity: setting hub should still produce a working FormVM.
    const vm = FormVM.builder<IModel>()
      .initial(makeModel("Alice", 1))
      .persister(noopPersister)
      .hub(NullMessageHub.INSTANCE)
      .build();
    expect(vm).toBeInstanceOf(FormVM);
    vm.dispose();
  });

  it("explicit strict(true) gates approveCommand.canExecute() on isDirty", () => {
    const vm = FormVM.builder<IModel>()
      .initial(makeModel("Alice", 1))
      .persister(noopPersister)
      .strict(true)
      .build();

    expect(vm.isDirty).toBe(false);
    expect(vm.approveCommand.canExecute()).toBe(false);

    vm.dispose();
  });
});
