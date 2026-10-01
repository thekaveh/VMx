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

    // A null value removes a field validator's error.
    const clearing = new FormVM<Model>({
      initial: model("", -1),
      persister: async () => {},
      validators: { name: () => "required" },
      modelValidator: () => ({ name: null, value: "negative" }),
    });
    expect(clearing.errors).toEqual({ value: "negative" });
    expect(clearing.fieldError("name")).toBeUndefined();
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

// ---------------------------------------------------------------------------
// Field names are data (#331). Repairs the existing FORM validation contract for
// JavaScript prototype names; no new conformance ID. `__proto__` is always built
// as a real own property (defineProperty, builder key, or null-prototype input),
// never through an object-literal `__proto__` that would set the prototype.
// ---------------------------------------------------------------------------

const FIELD_NAMES = ["__proto__", "constructor", "toString", "hasOwnProperty", "", "title"];

function ownRecord<V>(entries: ReadonlyArray<readonly [string, V]>): Record<string, V> {
  const record: Record<string, V> = {};
  for (const [key, value] of entries) {
    Object.defineProperty(record, key, { value, enumerable: true, writable: true, configurable: true });
  }
  return record;
}

function ownEntries(errors: Record<string, string>): Array<[string, string]> {
  return Object.keys(errors).map((key): [string, string] => [
    key,
    String(Object.getOwnPropertyDescriptor(errors, key)?.value),
  ]);
}

function expectInvalidFor(sut: FormVM<Model>, field: string, message: string): void {
  expect(sut.isValid).toBe(false);
  expect(sut.fieldError(field)).toBe(message);
  expect(ownEntries(sut.errors)).toEqual([[field, message]]);
  expect(sut.approveCommand.canExecute()).toBe(false);
}

function expectValid(sut: FormVM<Model>, field: string): void {
  expect(sut.isValid).toBe(true);
  expect(sut.fieldError(field)).toBeUndefined();
  expect(Object.keys(sut.errors)).toEqual([]);
  expect(sut.approveCommand.canExecute()).toBe(true);
}

describe("FormVM field names are data", () => {
  it.each(FIELD_NAMES)("field validator keyed %j drives every surface", async (field) => {
    const persister = vi.fn(async (_model: Model) => {});
    const message = `${field}:required`;
    const sut = new FormVM<Model>({
      initial: model("", 1),
      persister,
      validators: ownRecord([[field, (m: Model) => (m.name === "" ? message : null)]]),
    });
    const seen: Array<Array<[string, string]>> = [];
    sut.errorsChanged.subscribe((errors) => seen.push(ownEntries(errors)));

    expectInvalidFor(sut, field, message);
    await sut.approveAsync();
    expect(persister).not.toHaveBeenCalled();

    sut.setModel(model("ok", 1));
    expectValid(sut, field);
    sut.setModel(model("", 1));
    expectInvalidFor(sut, field, message);
    expect(seen).toEqual([[], [[field, message]]]);
  });

  it.each(FIELD_NAMES)("model validator keyed %j drives every surface", (field) => {
    const message = `${field}:negative`;
    const sut = new FormVM<Model>({
      initial: model("x", -1),
      persister: async () => {},
      modelValidator: (m) => ownRecord([[field, m.value < 0 ? message : null]]),
    });

    expectInvalidFor(sut, field, message);
    sut.setModel(model("x", 1));
    expectValid(sut, field);
  });

  it.each(FIELD_NAMES)("builder validator keyed %j registers an own key", (field) => {
    const sut = FormVM.builder<Model>()
      .initial(model("", 1))
      .persister(async () => {})
      .validator(field, () => "required")
      .build();

    expectInvalidFor(sut, field, "required");
  });

  it("null-prototype validator input is accepted", () => {
    const validators = Object.create(null) as Record<string, (m: Model) => string | null>;
    validators["__proto__"] = () => "required";
    const sut = new FormVM<Model>({ initial: model("x", 1), persister: async () => {}, validators });

    expectInvalidFor(sut, "__proto__", "required");
  });

  it("absent prototype names read as absent and nothing inherited leaks", () => {
    const sut = new FormVM<Model>({
      initial: model("", 1),
      persister: async () => {},
      validators: { title: () => "required" },
    });

    for (const field of ["__proto__", "constructor", "toString", "hasOwnProperty", "valueOf", ""]) {
      expect(sut.fieldError(field)).toBeUndefined();
    }
    expect(Object.keys(sut.errors)).toEqual(["title"]);
  });

  it("model validator clears and overrides prototype-named field errors", () => {
    const sut = new FormVM<Model>({
      initial: model("", 1),
      persister: async () => {},
      validators: ownRecord(FIELD_NAMES.map((field) => [field, () => `${field}:field`] as const)),
      modelValidator: () =>
        ownRecord([
          ["__proto__", null],
          ["constructor", "constructor:model"],
          ["toString", undefined],
          ["", "empty:model"],
        ]),
    });

    expect(ownEntries(sut.errors)).toEqual([
      ["constructor", "constructor:model"],
      ["hasOwnProperty", "hasOwnProperty:field"],
      ["", "empty:model"],
      ["title", "title:field"],
    ]);
    expect(sut.fieldError("__proto__")).toBeUndefined();
    expect(sut.fieldError("toString")).toBeUndefined();
  });

  it("deny revalidates prototype-named keys", () => {
    const sut = new FormVM<Model>({
      initial: model("", 1),
      persister: async () => {},
      validators: ownRecord([["__proto__", (m: Model) => (m.name === "" ? "required" : null)]]),
    });
    sut.setModel(model("ok", 1));
    expectValid(sut, "__proto__");

    sut.denyCommand.execute();

    expectInvalidFor(sut, "__proto__", "required");
  });

  it("successful reset-on-approved revalidates prototype-named keys", async () => {
    const sut = new FormVM<Model>({
      initial: model("ok", 1),
      persister: async () => {},
      validators: ownRecord([["__proto__", (m: Model) => (m.name === "" ? "required" : null)]]),
      resetOnApproved: () => model("", 0),
    });

    await sut.approveAsync();

    expectInvalidFor(sut, "__proto__", "required");
  });

  it("unchanged prototype-named errors do not re-emit", () => {
    const sut = new FormVM<Model>({
      initial: model("", 1),
      persister: async () => {},
      validators: ownRecord([["__proto__", (m: Model) => (m.name === "" ? "required" : null)]]),
    });
    const seen: Array<Array<[string, string]>> = [];
    sut.errorsChanged.subscribe((errors) => seen.push(ownEntries(errors)));

    sut.setModel(model("", 2));
    sut.setModel(model("", 3));
    sut.setModel(model("ok", 3));

    expect(seen).toEqual([[]]);
  });

  it("disposal keeps prototype-named errors readable and inert", () => {
    const sut = new FormVM<Model>({
      initial: model("", 1),
      persister: async () => {},
      validators: ownRecord([["__proto__", (m: Model) => (m.name === "" ? "required" : null)]]),
    });
    const seen: Array<Record<string, string>> = [];
    let completed = false;
    sut.errorsChanged.subscribe({ next: (errors) => seen.push(errors), complete: () => (completed = true) });

    sut.dispose();
    sut.setModel(model("ok", 1));

    expect(completed).toBe(true);
    expect(seen).toEqual([]);
    expect(sut.fieldError("__proto__")).toBe("required");
    expect(sut.approveCommand.canExecute()).toBe(false);
  });

  it("error snapshots are fresh plain objects whose keys survive introspection and JSON", () => {
    const sut = new FormVM<Model>({
      initial: model("", 1),
      persister: async () => {},
      validators: ownRecord(FIELD_NAMES.map((field) => [field, () => `${field}:e`] as const)),
    });

    const first = sut.errors;
    expect(sut.errors).not.toBe(first);
    expect(Object.getPrototypeOf(first)).toBe(Object.prototype);
    Object.defineProperty(first, "title", { value: "mutated" });
    expect(sut.fieldError("title")).toBe("title:e");

    const keys = FIELD_NAMES.slice().sort();
    expect(Object.keys(sut.errors).sort()).toEqual(keys);
    const roundTrip = JSON.parse(JSON.stringify(sut.errors)) as Record<string, string>;
    expect(ownEntries(roundTrip).sort()).toEqual(ownEntries(sut.errors).sort());
  });
});
