// Root exports used by public signatures (#1888). The type-only imports are erased,
// so this file checks the types through `npm run typecheck:tests`. It runs the
// runtime class through the root barrel as well.

import { describe, expect, it } from "vitest";
import { ContainerRollbackError } from "../../src/index.js";
import type {
  AsyncTask,
  FieldValidator,
  ModelEquals,
  ModelValidator,
} from "../../src/index.js";

interface Account {
  readonly name: string;
  readonly limit: number;
}

describe("root type exports (#1888)", () => {
  it("FieldValidator and ModelValidator type a form's validators", () => {
    const requiredName: FieldValidator<Account> = (model) => (model.name ? null : "required");
    const perModel: ModelValidator<Account> = (model) => ({
      name: requiredName(model),
      limit: model.limit >= 0 ? null : "negative",
    });

    expect(requiredName({ name: "", limit: 1 })).toBe("required");
    expect(perModel({ name: "a", limit: -1 })).toEqual({ name: null, limit: "negative" });
  });

  it("ModelEquals compares two models for a form", () => {
    const sameName: ModelEquals<Account> = (a, b) => a.name === b.name;

    expect(sameName({ name: "a", limit: 1 }, { name: "a", limit: 2 })).toBe(true);
  });

  it("AsyncTask types the work an AsyncRelayCommand runs", async () => {
    const seen: boolean[] = [];
    const task: AsyncTask = (signal) => {
      seen.push(signal.aborted);
      return Promise.resolve();
    };

    await task(new AbortController().signal);
    expect(seen).toEqual([false]);
  });

  it("ContainerRollbackError is a root class with its two failure fields", () => {
    const original = new Error("original");
    const compensation = new Error("compensation");
    const error = new ContainerRollbackError(original, compensation);

    expect(error).toBeInstanceOf(ContainerRollbackError);
    expect(error.name).toBe("ContainerRollbackError");
    expect(error.cause).toBe(original);
    expect(error.rollbackError).toBe(compensation);
  });
});
