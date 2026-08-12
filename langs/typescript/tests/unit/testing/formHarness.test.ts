import { describe, expect, it } from "vitest";
import {
  createFormHarness,
  type FormHarness,
} from "../../../src/testing/index.js";

interface Model {
  readonly name: string;
}

const model = (name: string): Model => ({ name });

describe("FormHarness", () => {
  it("drives set, approve, and deny through a real FormVM", async () => {
    const harness = createFormHarness({ initial: model("initial"), strict: true });

    harness.set(model("edited"));
    expect(harness.form.isDirty).toBe(true);
    expect(harness.propertyChanges.propertyNames).toEqual(["model"]);

    await harness.approve();
    expect(harness.persistAttempts).toEqual([model("edited")]);
    expect(harness.approved).toEqual([model("edited")]);
    expect(harness.form.isDirty).toBe(false);

    harness.set(model("again"));
    harness.deny();
    expect(harness.form.model).toEqual(model("edited"));
    expect(harness.form.isDirty).toBe(false);
    harness.dispose();
  });

  it("exposes validation state and preserves failed approval state", async () => {
    const harness = createFormHarness({
      initial: model("valid"),
      validators: { name: (value) => value.name === "" ? "required" : null },
    });
    harness.set(model(""));
    expect(harness.form.errors).toEqual({ name: "required" });
    expect(harness.form.isValid).toBe(false);

    harness.set(model("changed"));
    const fault = new Error("persist failed");
    harness.failNext(fault);
    await expect(harness.approve()).rejects.toBe(fault);

    expect(harness.persistAttempts).toEqual([model("changed")]);
    expect(harness.approved).toEqual([]);
    expect(harness.form.isDirty).toBe(true);
    harness.dispose();
  });

  it("records command-path approval errors without an unhandled rejection", async () => {
    const harness = createFormHarness({ initial: model("initial") });
    const fault = new Error("reported");
    harness.set(model("changed"));
    harness.failNext(fault);

    harness.form.approveCommand.execute();
    await new Promise<void>((resolve) => setImmediate(resolve));

    expect(harness.approveErrors).toEqual([fault]);
    expect(harness.form.isDirty).toBe(true);
    harness.dispose();
  });

  it("clears records and disposes idempotently, including reentrant disposal", async () => {
    const harness: FormHarness<Model> = createFormHarness({ initial: model("initial") });
    harness.form.onApproved.subscribe(() => harness.dispose());
    harness.set(model("changed"));

    await harness.approve();
    harness.clear();
    harness.dispose();

    expect(harness.persistAttempts).toEqual([]);
    expect(harness.approved).toEqual([]);
    expect(harness.approveErrors).toEqual([]);
    expect(harness.propertyChanges.records).toEqual([]);
    harness.set(model("ignored"));
    expect(harness.form.model).toEqual(model("changed"));
  });
});
