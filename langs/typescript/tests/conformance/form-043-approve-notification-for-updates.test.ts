// FORM-043 conformance test — an update raises the approve notification when
// its gates change. See spec/20-form-vm.md §5.2/§5.3 and ADR-0196.
//
// An accepted unequal setModel or a deny raises
// approveCommand.canExecuteChanged exactly once when isValid changes, or
// isDirty changes in strict mode. An approval in flight does not suppress it.

import { describe, expect, it } from "vitest";

import { FormVM, MessageHub } from "../../src/index.js";

interface Model {
  readonly value: string;
}

const m = (value: string): Model => ({ value });

const validators = {
  value: (model: Model) => (model.value === "bad" ? "rejected" : null),
};

describe("FORM-043", () => {
  it("a strict form raises once per gate change and not otherwise", () => {
    const form = new FormVM<Model>({
      initial: m("snapshot"),
      persister: async () => {},
      hub: new MessageHub(),
      strict: true,
      snapshotter: (value) => value,
      validators,
    });
    form.setModel(m("bad"));
    expect(form.isDirty).toBe(true);
    expect(form.isValid).toBe(false);
    let count = 0;
    form.approveCommand.canExecuteChanged.subscribe(() => (count += 1));

    form.setModel(m("snapshot"));
    expect(count).toBe(1);
    expect(form.approveCommand.canExecute()).toBe(false);

    form.setModel(m("a"));
    expect(count).toBe(2);
    expect(form.approveCommand.canExecute()).toBe(true);

    form.setModel(m("b"));
    expect(count).toBe(2);
  });

  it("an approval in flight does not suppress the notification", async () => {
    let count = 0;
    let countAfterAdmission: number | null = null;
    let readInPersister: number | null = null;
    const form: FormVM<Model> = new FormVM<Model>({
      initial: m("snapshot"),
      persister: () => {
        countAfterAdmission = count;
        form.setModel(m("bad"));
        readInPersister = count;
        return Promise.resolve();
      },
      hub: new MessageHub(),
      snapshotter: (value) => value,
      validators,
    });
    form.approveCommand.canExecuteChanged.subscribe(() => (count += 1));

    await form.approveAsync();

    expect(countAfterAdmission).not.toBeNull();
    expect(readInPersister).toBe(countAfterAdmission! + 1);
    expect(count).toBe(readInPersister! + 1);
  });
});
