import { describe, expect, it, vi } from "vitest";
import { FormVM } from "../../src/index.js";

interface Model { name: string; value: number }
const model = (name: string, value: number): Model => ({ name, value });

describe("FORM-016", () => {
  it("FORM-016 field validator populates field error", () => {
    const sut = new FormVM<Model>({
      initial: model("", 1),
      persister: async () => {},
      validators: { name: (m) => m.name === "" ? "required" : null },
    });
    expect(sut.fieldError("name")).toBe("required");
    expect(sut.errors).toEqual({ name: "required" });
  });
});

describe("FORM-017", () => {
  it("FORM-017 model validator populates errors", () => {
    const sut = new FormVM<Model>({
      initial: model("x", -1),
      persister: async () => {},
      modelValidator: () => ({ value: "negative" }),
    });
    expect(sut.errors).toEqual({ value: "negative" });
  });
});

describe("FORM-018", () => {
  it("FORM-018 isValid reflects errors", () => {
    const sut = new FormVM<Model>({
      initial: model("", 1),
      persister: async () => {},
      validators: { name: () => "required" },
    });
    expect(sut.isValid).toBe(false);
  });
});

describe("FORM-019", () => {
  it("FORM-019 invalid form blocks approval", async () => {
    const persister = vi.fn(async (_model: Model) => {});
    const sut = new FormVM<Model>({
      initial: model("", 1),
      persister,
      validators: { name: () => "required" },
    });
    expect(sut.approveCommand.canExecute()).toBe(false);
    await sut.approveAsync();
    expect(persister).not.toHaveBeenCalled();
  });
});

describe("FORM-020", () => {
  it("FORM-020 validation reruns after model mutation", () => {
    const sut = new FormVM<Model>({
      initial: model("", 1),
      persister: async () => {},
      validators: { name: (m) => m.name === "" ? "required" : null },
    });
    sut.setModel(model("ok", 1));
    expect(sut.errors).toEqual({});
    expect(sut.isValid).toBe(true);
  });
});

describe("FORM-021", () => {
  it("FORM-021 errorsChanged fires only on effective changes", () => {
    const sut = new FormVM<Model>({
      initial: model("", 1),
      persister: async () => {},
      validators: { name: (m) => m.name === "" ? "required" : null },
    });
    const seen: Array<Record<string, string>> = [];
    sut.errorsChanged.subscribe((errors) => seen.push(errors));
    sut.setModel(model("", 2));
    sut.setModel(model("ok", 2));
    expect(seen).toEqual([{}]);
  });
});

describe("FORM-022", () => {
  it("FORM-022 builder registers validators immutably", () => {
    const base = FormVM.builder<Model>().initial(model("", 1)).persister(async () => {});
    const withValidator = base.validator("name", () => "required");
    expect(withValidator).not.toBe(base);
    expect(withValidator.build().fieldError("name")).toBe("required");
  });
});

describe("FORM-023", () => {
  it("FORM-023 clearing errors enables approval when other gates pass", () => {
    const sut = new FormVM<Model>({
      initial: model("", 1),
      persister: async () => {},
      strict: true,
      validators: { name: (m) => m.name === "" ? "required" : null },
    });
    sut.setModel(model("ok", 2));
    expect(sut.approveCommand.canExecute()).toBe(true);
  });
});
