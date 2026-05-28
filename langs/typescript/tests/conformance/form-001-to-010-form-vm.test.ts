// FORM-001..FORM-010 conformance tests — VMx FormVM<TM> (snapshot/revert edit lifecycle).
// See spec/20-form-vm.md and ADR-0030.

import { describe, expect, it } from "vitest";

import {
  ConfirmationDecoratorCommand,
  FormRevertedMessage,
  FormVM,
  MessageHub,
  NullDialogService,
  PropertyChangedMessage,
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

function makeFormVM(initial: IModel) {
  return new FormVM<IModel>({
    initial,
    persister: async () => {},
  });
}

// ---------------------------------------------------------------------------
// FORM-001
// ---------------------------------------------------------------------------

describe("FORM-001", () => {
  it("Snapshot captured at construct; model == snapshot; isDirty == false", () => {
    const initial = makeModel("Alice", 1);
    const sut = makeFormVM(initial);

    expect(sut.model).toEqual(initial);
    expect(sut.snapshot).toEqual(initial);
    expect(sut.isDirty).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// FORM-002
// ---------------------------------------------------------------------------

describe("FORM-002", () => {
  it("Model mutation reflected in isDirty; snapshot unchanged", () => {
    const initial = makeModel("Alice", 1);
    const sut = makeFormVM(initial);

    sut.setModel(makeModel("Bob", 2));

    expect(sut.isDirty).toBe(true);
    expect(sut.snapshot).toEqual(initial);
    expect(sut.model).toEqual(makeModel("Bob", 2));
  });
});

// ---------------------------------------------------------------------------
// FORM-003
// ---------------------------------------------------------------------------

describe("FORM-003", () => {
  it("IsDirty uses structural inequality (JSON.stringify)", () => {
    const initial = makeModel("Alice", 1);
    const sut = makeFormVM(initial);

    // Value-equal model → not dirty.
    sut.setModel(makeModel("Alice", 1));
    expect(sut.isDirty).toBe(false);

    // Structurally different → dirty.
    sut.setModel(makeModel("Alice", 99));
    expect(sut.isDirty).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// FORM-004
// ---------------------------------------------------------------------------

describe("FORM-004", () => {
  it("DenyCommand reverts model to snapshot; isDirty == false after revert", () => {
    const initial = makeModel("Alice", 1);
    const sut = makeFormVM(initial);

    sut.setModel(makeModel("Bob", 2));
    expect(sut.isDirty).toBe(true);

    sut.denyCommand.execute();

    expect(sut.model).toEqual(initial);
    expect(sut.isDirty).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// FORM-005
// ---------------------------------------------------------------------------

describe("FORM-005", () => {
  it("ApproveCommand invokes persister; snapshot advances on success", async () => {
    const initial = makeModel("Alice", 1);
    const persisted: IModel[] = [];

    const sut = new FormVM<IModel>({
      initial,
      persister: (m) => {
        persisted.push(m);
        return Promise.resolve();
      },
    });

    const updated = makeModel("Bob", 2);
    sut.setModel(updated);

    await sut.approveAsync();

    expect(persisted).toHaveLength(1);
    expect(persisted[0]).toEqual(updated);
    expect(sut.snapshot).toEqual(updated);
    expect(sut.isDirty).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// FORM-006
// ---------------------------------------------------------------------------

describe("FORM-006", () => {
  it("onApproved fires only after successful persist; not when persister throws", async () => {
    const initial = makeModel("Alice", 1);
    const approved: IModel[] = [];

    const sut = new FormVM<IModel>({
      initial,
      persister: async () => {},
    });
    const sub = sut.onApproved.subscribe((m) => approved.push(m));

    expect(approved).toHaveLength(0);

    sut.setModel(makeModel("Bob", 2));
    await sut.approveAsync();

    expect(approved).toHaveLength(1);
    expect(approved[0]).toEqual(makeModel("Bob", 2));

    sub.unsubscribe();
  });
});

// ---------------------------------------------------------------------------
// FORM-007
// ---------------------------------------------------------------------------

describe("FORM-007", () => {
  it("Persist failure leaves Snapshot and Model unchanged; exception propagates", async () => {
    const initial = makeModel("Alice", 1);
    const updated = makeModel("Bob", 2);
    const approved: IModel[] = [];

    const sut = new FormVM<IModel>({
      initial,
      persister: () => Promise.reject(new Error("DB error")),
    });
    const sub = sut.onApproved.subscribe((m) => approved.push(m));

    sut.setModel(updated);

    await expect(sut.approveAsync()).rejects.toThrow("DB error");

    expect(sut.model).toEqual(updated);
    expect(sut.snapshot).toEqual(initial);
    expect(sut.isDirty).toBe(true);
    expect(approved).toHaveLength(0);

    sub.unsubscribe();
  });
});

// ---------------------------------------------------------------------------
// FORM-008
// ---------------------------------------------------------------------------

describe("FORM-008", () => {
  it("DenyCommand publishes FormRevertedMessage and PropertyChangedMessage('model') on hub", () => {
    const hub = new MessageHub();
    const messages: unknown[] = [];
    const sub = hub.messages.subscribe((m) => messages.push(m));

    const initial = makeModel("Alice", 1);
    const sut = new FormVM<IModel>({
      initial,
      persister: async () => {},
      hub,
    });

    sut.setModel(makeModel("Bob", 2));
    sut.denyCommand.execute();

    sub.unsubscribe();

    expect(messages).toHaveLength(2);

    const revertMsg = messages.find(
      (m): m is FormRevertedMessage => m instanceof FormRevertedMessage,
    );
    expect(revertMsg).toBeDefined();
    expect(revertMsg?.sender).toBe(sut);
    expect(revertMsg?.senderName).toBe("FormVM");

    const propMsg = messages.find((m) => m instanceof PropertyChangedMessage) as
      | PropertyChangedMessage<object>
      | undefined;
    expect(propMsg).toBeDefined();
    expect(propMsg?.propertyName).toBe("model");
  });
});

// ---------------------------------------------------------------------------
// FORM-009
// ---------------------------------------------------------------------------

describe("FORM-009", () => {
  it("Strict mode: approveCommand.canExecute is false when isDirty == false", () => {
    const initial = makeModel("Alice", 1);
    const sut = new FormVM<IModel>({
      initial,
      persister: async () => {},
      strict: true,
    });

    expect(sut.isDirty).toBe(false);
    expect(sut.approveCommand.canExecute()).toBe(false);

    sut.setModel(makeModel("Bob", 2));
    expect(sut.approveCommand.canExecute()).toBe(true);

    // Non-strict (default): always true.
    const nonStrict = makeFormVM(initial);
    expect(nonStrict.approveCommand.canExecute()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// FORM-010
// ---------------------------------------------------------------------------

describe("FORM-010", () => {
  it("Integration with IDialogService.Confirm — confirm guard prevents revert on false return", async () => {
    const initial = makeModel("Alice", 1);
    const sut = makeFormVM(initial);

    sut.setModel(makeModel("Bob", 2));
    expect(sut.isDirty).toBe(true);

    // Wrap DenyCommand with NullDialogService.Confirm (returns false → guard blocks revert).
    const guardedDeny = new ConfirmationDecoratorCommand(
      sut.denyCommand,
      () => NullDialogService.INSTANCE.confirm("Discard changes?"),
    );

    await guardedDeny.executeAsync();

    expect(sut.isDirty).toBe(true);
    expect(sut.model).toEqual(makeModel("Bob", 2));

    // Confirm returns true → revert proceeds.
    const confirmingDeny = new ConfirmationDecoratorCommand(
      sut.denyCommand,
      () => Promise.resolve(true),
    );
    await confirmingDeny.executeAsync();

    expect(sut.isDirty).toBe(false);
    expect(sut.model).toEqual(initial);
  });
});
