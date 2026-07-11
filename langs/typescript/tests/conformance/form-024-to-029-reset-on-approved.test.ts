import { describe, expect, it, vi } from "vitest";
import { FormVM } from "../../src/index.js";

interface Model {
  readonly value: string;
  readonly nested?: { readonly count: number };
}

const m = (value: string): Model => ({ value });
const noop = (): Promise<void> => Promise.resolve();

describe("FORM-024", () => {
  it("runs reset after persistence and before OnApproved", async () => {
    const order: string[] = [];
    let form!: FormVM<Model>;
    form = FormVM.builder<Model>()
      .initial(m("initial"))
      .persister((approved) => { order.push(`persist:${approved.value}`); return noop(); })
      .resetOnApproved((approved) => {
        order.push(`reset:${approved.value}`);
        return m(`reset:${approved.value}`);
      })
      .build();
    form.onApproved.subscribe((approved) => {
      order.push(`approved:${approved.value}`);
      expect(form.model).toEqual(m("reset:edited"));
      expect(form.snapshot).toEqual(m("reset:edited"));
      expect(form.isDirty).toBe(false);
    });
    form.setModel(m("edited"));

    await form.approveAsync();

    expect(order).toEqual(["persist:edited", "reset:edited", "approved:edited"]);
  });
});

describe("FORM-025", () => {
  it("snapshots reset twice, revalidates, and leaves strict form pristine", async () => {
    const snapshotted: Model[] = [];
    const form = FormVM.builder<Model>()
      .initial(m("initial"))
      .persister(noop)
      .strict(true)
      .snapshotter((model) => {
        snapshotted.push(model);
        return { value: model.value, nested: { count: model.nested?.count ?? 0 } };
      })
      .validator("value", (model) => model.value.length === 0 ? "required" : null)
      .resetOnApproved(() => ({ value: "", nested: { count: 1 } }))
      .build();
    snapshotted.length = 0;
    form.setModel(m("edited"));

    await form.approveAsync();

    expect(snapshotted).toHaveLength(2);
    expect(snapshotted.every((value) => value.value === "")).toBe(true);
    expect(form.model).toEqual({ value: "", nested: { count: 1 } });
    expect(form.snapshot).toEqual(form.model);
    expect(form.model).not.toBe(form.snapshot);
    expect(form.model.nested).not.toBe(form.snapshot.nested);
    expect(form.fieldError("value")).toBe("required");
    expect(form.isDirty).toBe(false);
    expect(form.approveCommand.canExecute()).toBe(false);
  });
});

describe("FORM-026", () => {
  it("routes reset failure to exactly one observer after persistence", async () => {
    const boom = new Error("reset failed after persistence");
    const persisted = vi.fn(noop);
    const approved: Model[] = [];
    const directErrors: unknown[] = [];
    const direct = FormVM.builder<Model>()
      .initial(m("initial"))
      .persister(persisted)
      .resetOnApproved(() => { throw boom; })
      .build();
    direct.setModel(m("edited"));
    direct.onApproved.subscribe((value) => approved.push(value));
    direct.approveErrors.subscribe((error) => directErrors.push(error));

    await expect(direct.approveAsync()).rejects.toBe(boom);
    expect(persisted).toHaveBeenCalledOnce();
    expect(direct.model).toEqual(m("edited"));
    expect(direct.snapshot).toEqual(m("initial"));
    expect(direct.isDirty).toBe(true);
    expect(approved).toEqual([]);
    expect(directErrors).toEqual([]);

    const commandErrors: unknown[] = [];
    const commandPersisted = vi.fn(noop);
    const command = FormVM.builder<Model>()
      .initial(m("initial"))
      .persister(commandPersisted)
      .resetOnApproved(() => { throw boom; })
      .build();
    command.setModel(m("edited"));
    command.approveErrors.subscribe((error) => commandErrors.push(error));
    command.approveCommand.execute();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(commandPersisted).toHaveBeenCalledOnce();
    expect(commandErrors).toEqual([boom]);
  });
});

describe("FORM-027", () => {
  it("skips reset for invalid, failed, cancelled, and deny paths", async () => {
    const reset = vi.fn((model: Model) => model);
    const invalid = FormVM.builder<Model>()
      .initial(m(""))
      .persister(noop)
      .validator("value", (model) => model.value.length === 0 ? "required" : null)
      .resetOnApproved(reset)
      .build();
    await invalid.approveAsync();

    const failed = FormVM.builder<Model>()
      .initial(m("initial"))
      .persister(() => Promise.reject(new Error("persist failed")))
      .resetOnApproved(reset)
      .build();
    await expect(failed.approveAsync()).rejects.toThrow("persist failed");

    const cancelled = FormVM.builder<Model>()
      .initial(m("initial"))
      .persister(() => Promise.reject(new DOMException("cancelled", "AbortError")))
      .resetOnApproved(reset)
      .build();
    await expect(cancelled.approveAsync()).rejects.toMatchObject({ name: "AbortError" });

    const denied = FormVM.builder<Model>()
      .initial(m("initial"))
      .persister(noop)
      .resetOnApproved(reset)
      .build();
    denied.setModel(m("edited"));
    denied.denyCommand.execute();

    expect(reset).not.toHaveBeenCalled();
  });
});

describe("FORM-028", () => {
  it("disposal during persistence suppresses reset and notification", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const reset = vi.fn((model: Model) => model);
    const approved: Model[] = [];
    const form = FormVM.builder<Model>()
      .initial(m("initial"))
      .persister(() => gate)
      .resetOnApproved(reset)
      .build();
    form.setModel(m("edited"));
    form.onApproved.subscribe((value) => approved.push(value));

    const approval = form.approveAsync();
    form.dispose();
    release();
    await approval;

    expect(reset).not.toHaveBeenCalled();
    expect(form.model).toEqual(m("edited"));
    expect(form.snapshot).toEqual(m("initial"));
    expect(approved).toEqual([]);
  });
});

describe("FORM-029", () => {
  it("reset wins a racing setModel and uses captured approved model", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const persisted: Model[] = [];
    const resetInputs: Model[] = [];
    const approved: Model[] = [];
    const form = FormVM.builder<Model>()
      .initial(m("initial"))
      .persister((model) => { persisted.push(model); return gate; })
      .resetOnApproved((model) => {
        resetInputs.push(model);
        return m(`reset:${model.value}`);
      })
      .build();
    form.onApproved.subscribe((value) => approved.push(value));
    form.setModel(m("approved"));

    const approval = form.approveAsync();
    form.setModel(m("racing"));
    release();
    await approval;

    expect(persisted).toEqual([m("approved")]);
    expect(resetInputs).toEqual([m("approved")]);
    expect(approved).toEqual([m("approved")]);
    expect(form.model).toEqual(m("reset:approved"));
    expect(form.snapshot).toEqual(m("reset:approved"));
    expect(form.isDirty).toBe(false);
  });

  it("notifies when a racing invalid edit is replaced by a valid reset", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const form = FormVM.builder<Model>()
      .initial(m("initial"))
      .persister(() => gate)
      .validator("value", (model) => model.value.length === 0 ? "required" : null)
      .resetOnApproved((model) => m(`reset:${model.value}`))
      .build();
    const notifications: boolean[] = [];
    form.approveCommand.canExecuteChanged.subscribe(() => {
      notifications.push(form.approveCommand.canExecute());
    });
    form.setModel(m("approved"));

    const approval = form.approveAsync();
    form.setModel(m(""));
    release();
    await approval;

    expect(notifications).toEqual([false, true]);
    expect(form.approveCommand.canExecute()).toBe(true);
    expect(form.model).toEqual(m("reset:approved"));
  });
});
