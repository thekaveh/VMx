// FORM-035..FORM-038 conformance tests — FormVM failure-atomic model updates.
// See spec/20-form-vm.md §5.2/§5.4 and ADR-0144.
//
// setModel and deny prepare before they commit: the equality comparisons, the
// validators, and (for deny) the snapshotter run first. A throwing callback
// propagates unchanged with the form untouched and nothing published. A
// callback that disposes the form or commits another update makes the
// interrupted update commit and publish nothing.

import { describe, expect, it, vi } from "vitest";

import {
  FormRevertedMessage,
  FormVM,
  MessageHub,
  PropertyChangedMessage,
  type FormVMOptions,
} from "../../src/index.js";

interface Model {
  readonly value: string;
}

const m = (value: string): Model => ({ value });

/** A consumer callback's own failure; it must reach the caller unchanged. */
class CallbackFailure extends Error {}

/**
 * A strict form on its own hub. Strict mode makes the dirty state observable
 * through the approve command; the identity snapshotter keeps `snapshot`
 * reference-stable so an unchanged snapshot can be asserted with `toBe`.
 */
function makeForm(options: Partial<FormVMOptions<Model>> = {}) {
  const hub = new MessageHub();
  const form = new FormVM<Model>({
    initial: m("initial"),
    persister: async () => {},
    hub,
    strict: true,
    snapshotter: (value) => value,
    ...options,
  });
  return { form, hub };
}

interface Signals {
  errorsChanged: Array<Record<string, string>>;
  canExecuteChanged: number;
  /** The live model value each hub model message observed. */
  modelMessages: string[];
  revertedMessages: number;
  completed: string[];
}

const NO_SIGNALS: Signals = {
  errorsChanged: [],
  canExecuteChanged: 0,
  modelMessages: [],
  revertedMessages: 0,
  completed: [],
};

/** Records every notification the form publishes from now on. */
function record(form: FormVM<Model>, hub: MessageHub): Signals {
  const signals: Signals = {
    errorsChanged: [],
    canExecuteChanged: 0,
    modelMessages: [],
    revertedMessages: 0,
    completed: [],
  };
  form.errorsChanged.subscribe({
    next: (errors) => signals.errorsChanged.push(errors),
    complete: () => signals.completed.push("errorsChanged"),
  });
  form.approveCommand.canExecuteChanged.subscribe({
    next: () => {
      signals.canExecuteChanged += 1;
    },
    complete: () => signals.completed.push("canExecuteChanged"),
  });
  hub.messages.subscribe((message) => {
    if (message.sender !== form) return;
    if (message instanceof FormRevertedMessage) signals.revertedMessages += 1;
    if (message instanceof PropertyChangedMessage && message.propertyName === "model") {
      signals.modelMessages.push(form.model.value);
    }
  });
  return signals;
}

/**
 * What a bare `dispose()` publishes: the completions, plus the final
 * re-evaluation a disposed RelayCommand raises. A form disposed during
 * preparation publishes exactly this and nothing from the update.
 */
function bareDisposeSignals(): Signals {
  const { form, hub } = makeForm();
  const signals = record(form, hub);
  form.dispose();
  return signals;
}

interface FormState {
  readonly model: Model;
  readonly snapshot: Model;
  readonly errors: Record<string, string>;
  readonly isDirty: boolean;
  readonly isValid: boolean;
  readonly canApprove: boolean;
}

function stateOf(form: FormVM<Model>): FormState {
  return {
    model: form.model,
    snapshot: form.snapshot,
    errors: form.errors,
    isDirty: form.isDirty,
    isValid: form.isValid,
    canApprove: form.approveCommand.canExecute(),
  };
}

/** Model and snapshot keep their identity; every derived value is the same. */
function expectUnchanged(form: FormVM<Model>, before: FormState): void {
  const after = stateOf(form);
  expect(after).toEqual(before);
  expect(after.model).toBe(before.model);
  expect(after.snapshot).toBe(before.snapshot);
}

/** The model, snapshot, errors, and dirty/valid state survive disposal intact. */
function expectUncommitted(form: FormVM<Model>, before: FormState): void {
  const { canApprove: _ignored, ...kept } = before;
  const { canApprove, ...after } = stateOf(form);
  expect(after).toEqual(kept);
  expect(after.model).toBe(before.model);
  expect(after.snapshot).toBe(before.snapshot);
  // The disposed approve command is inert (FORM-014), not a committed change.
  expect(canApprove).toBe(false);
}

/** Runs `action` and returns what it threw, so the identity can be asserted. */
function thrownBy(action: () => void): unknown {
  try {
    action();
  } catch (error: unknown) {
    return error;
  }
  throw new Error("expected the action to throw");
}

const required = (model: Model): string | null =>
  model.value.length === 0 ? "required" : null;

describe("FORM-035", () => {
  function failingFieldValidator() {
    const failure = new CallbackFailure("field validator failed");
    const runs: string[] = [];
    const { form, hub } = makeForm({
      validators: {
        value: (model) => {
          runs.push(model.value);
          if (model.value === "boom") throw failure;
          return required(model);
        },
      },
    });
    return { form, hub, failure, runs };
  }

  it("leaves the form unchanged when the field validator fails on its first run after construction", () => {
    const { form, hub, failure, runs } = failingFieldValidator();
    expect(runs).toEqual(["initial"]); // the construction run
    const before = stateOf(form);
    expect(before).toEqual({
      model: m("initial"),
      snapshot: m("initial"),
      errors: {},
      isDirty: false,
      isValid: true,
      canApprove: false,
    });
    const signals = record(form, hub);

    expect(thrownBy(() => form.setModel(m("boom")))).toBe(failure);

    expect(runs).toEqual(["initial", "boom"]);
    expectUnchanged(form, before);
    expect(signals).toEqual(NO_SIGNALS);

    // A later candidate the validator accepts settles and publishes (FORM-030).
    form.setModel(m("accepted"));

    expect(stateOf(form)).toEqual({
      model: m("accepted"),
      snapshot: m("initial"),
      errors: {},
      isDirty: true,
      isValid: true,
      canApprove: true,
    });
    expect(signals).toEqual({
      ...NO_SIGNALS,
      canExecuteChanged: 1,
      modelMessages: ["accepted"],
    });
  });

  it("leaves the form unchanged when the field validator fails after earlier successful runs", () => {
    const { form, hub, failure, runs } = failingFieldValidator();
    form.setModel(m("first"));
    form.setModel(m(""));
    expect(runs).toEqual(["initial", "first", ""]);
    const before = stateOf(form);
    expect(before).toEqual({
      model: m(""),
      snapshot: m("initial"),
      errors: { value: "required" },
      isDirty: true,
      isValid: false,
      canApprove: false,
    });
    const signals = record(form, hub);

    expect(thrownBy(() => form.setModel(m("boom")))).toBe(failure);
    // A repeated failure is just as atomic.
    expect(thrownBy(() => form.setModel(m("boom")))).toBe(failure);

    expect(runs).toEqual(["initial", "first", "", "boom", "boom"]);
    expectUnchanged(form, before);
    expect(form.fieldError("value")).toBe("required");
    expect(signals).toEqual(NO_SIGNALS);

    form.setModel(m("fixed"));

    expect(stateOf(form)).toEqual({
      model: m("fixed"),
      snapshot: m("initial"),
      errors: {},
      isDirty: true,
      isValid: true,
      canApprove: true,
    });
    expect(signals).toEqual({
      ...NO_SIGNALS,
      errorsChanged: [{}],
      canExecuteChanged: 1,
      modelMessages: ["fixed"],
    });
  });

  it("fails construction when a validator throws, since construction runs the same preparation", () => {
    const fieldFailure = new CallbackFailure("field validator failed");
    const modelFailure = new CallbackFailure("model validator failed");

    expect(
      thrownBy(() =>
        new FormVM<Model>({
          initial: m("initial"),
          persister: async () => {},
          validators: {
            value: () => {
              throw fieldFailure;
            },
          },
        }),
      ),
    ).toBe(fieldFailure);
    expect(
      thrownBy(() =>
        FormVM.builder<Model>()
          .initial(m("initial"))
          .persister(async () => {})
          .modelValidator(() => {
            throw modelFailure;
          })
          .build(),
      ),
    ).toBe(modelFailure);
  });
});

describe("FORM-036", () => {
  it("leaves the form unchanged when the model validator fails", () => {
    const failure = new CallbackFailure("model validator failed");
    const fieldRuns: string[] = [];
    const { form, hub } = makeForm({
      validators: {
        // Runs first and would flag the candidate; its result must be dropped.
        value: (model) => {
          fieldRuns.push(model.value);
          return model.value === "boom" ? "reserved" : null;
        },
      },
      modelValidator: (model) => {
        if (model.value === "boom") throw failure;
        return { value: required(model) };
      },
    });
    form.setModel(m(""));
    const before = stateOf(form);
    expect(before.errors).toEqual({ value: "required" });
    const signals = record(form, hub);

    expect(thrownBy(() => form.setModel(m("boom")))).toBe(failure);

    expect(fieldRuns).toEqual(["initial", "", "boom"]);
    expectUnchanged(form, before);
    expect(signals).toEqual(NO_SIGNALS);

    form.setModel(m("fixed"));

    expect(stateOf(form)).toEqual({
      model: m("fixed"),
      snapshot: m("initial"),
      errors: {},
      isDirty: true,
      isValid: true,
      canApprove: true,
    });
    expect(signals).toEqual({
      ...NO_SIGNALS,
      errorsChanged: [{}],
      canExecuteChanged: 1,
      modelMessages: ["fixed"],
    });
  });

  // The injected `equals` runs three times per assignment: live model against
  // the candidate, live model against the snapshot (previous dirty state), and
  // candidate against the snapshot (next dirty state). The live model is never
  // "boom", so each case below fails exactly one comparison.
  it.each([
    {
      comparison: "live model against the candidate",
      fails: (_a: Model, b: Model) => b.value === "boom",
      validatorRanOnCandidate: false,
    },
    {
      comparison: "candidate against the snapshot",
      fails: (a: Model, _b: Model) => a.value === "boom",
      validatorRanOnCandidate: true,
    },
  ])(
    "leaves the form unchanged when the injected equals fails comparing the $comparison",
    ({ fails, validatorRanOnCandidate }) => {
      const failure = new CallbackFailure("equals failed");
      const runs: string[] = [];
      const { form, hub } = makeForm({
        equals: (a, b) => {
          if (fails(a, b)) throw failure;
          return a.value === b.value;
        },
        validators: {
          value: (model) => {
            runs.push(model.value);
            return model.value === "boom" ? "reserved" : required(model);
          },
        },
      });
      form.setModel(m(""));
      const before = stateOf(form);
      expect(before).toMatchObject({ isDirty: true, isValid: false, canApprove: false });
      const signals = record(form, hub);

      expect(thrownBy(() => form.setModel(m("boom")))).toBe(failure);

      expect(runs).toEqual(
        validatorRanOnCandidate ? ["initial", "", "boom"] : ["initial", ""],
      );
      expectUnchanged(form, before);
      expect(signals).toEqual(NO_SIGNALS);

      form.setModel(m("fixed"));

      expect(stateOf(form)).toEqual({
        model: m("fixed"),
        snapshot: m("initial"),
        errors: {},
        isDirty: true,
        isValid: true,
        canApprove: true,
      });
      expect(signals).toEqual({
        ...NO_SIGNALS,
        errorsChanged: [{}],
        canExecuteChanged: 1,
        modelMessages: ["fixed"],
      });
    },
  );

  it("keeps the edited model and publishes nothing when a validator fails during deny", () => {
    const failure = new CallbackFailure("validator failed on the snapshot value");
    let armed = false;
    const { form, hub } = makeForm({
      validators: {
        value: (model) => {
          if (armed && model.value === "initial") throw failure;
          return required(model);
        },
      },
    });
    form.setModel(m(""));
    armed = true;
    const before = stateOf(form);
    expect(before).toEqual({
      model: m(""),
      snapshot: m("initial"),
      errors: { value: "required" },
      isDirty: true,
      isValid: false,
      canApprove: false,
    });
    const signals = record(form, hub);

    expect(thrownBy(() => form.denyCommand.execute())).toBe(failure);

    expectUnchanged(form, before);
    expect(signals).toEqual(NO_SIGNALS);

    // A later deny whose callbacks succeed reverts and publishes normally.
    armed = false;
    form.denyCommand.execute();

    expect(stateOf(form)).toEqual({
      model: m("initial"),
      snapshot: m("initial"),
      errors: {},
      isDirty: false,
      isValid: true,
      canApprove: false,
    });
    expect(signals).toEqual({
      ...NO_SIGNALS,
      errorsChanged: [{}],
      canExecuteChanged: 1,
      modelMessages: ["initial"],
      revertedMessages: 1,
    });
  });

  it("keeps the edited model and publishes nothing when the snapshotter fails during deny", () => {
    const failure = new CallbackFailure("snapshotter failed");
    let armed = false;
    const runs: string[] = [];
    const { form, hub } = makeForm({
      snapshotter: (model) => {
        if (armed) throw failure;
        return { ...model };
      },
      validators: {
        value: (model) => {
          runs.push(model.value);
          return model.value === "edited" ? "flagged" : null;
        },
      },
    });
    form.setModel(m("edited"));
    armed = true;
    const before = stateOf(form);
    expect(before).toMatchObject({
      errors: { value: "flagged" },
      isDirty: true,
      isValid: false,
    });
    const signals = record(form, hub);

    // A supplied snapshotter's error passes through unwrapped.
    expect(thrownBy(() => form.denyCommand.execute())).toBe(failure);

    expect(runs).toEqual(["initial", "edited"]);
    expectUnchanged(form, before);
    expect(signals).toEqual(NO_SIGNALS);

    armed = false;
    form.denyCommand.execute();

    expect(stateOf(form)).toEqual({
      model: m("initial"),
      snapshot: m("initial"),
      errors: {},
      isDirty: false,
      isValid: true,
      canApprove: false,
    });
    expect(signals).toEqual({
      ...NO_SIGNALS,
      errorsChanged: [{}],
      canExecuteChanged: 1,
      modelMessages: ["initial"],
      revertedMessages: 1,
    });
  });
});

describe("FORM-037", () => {
  it("commits the nested assignment from a validator and abandons the interrupted outer one", () => {
    const hub = new MessageHub();
    const runs: string[] = [];
    const nestedModel = m("b");
    let reentered = false;
    let form: FormVM<Model>;
    form = new FormVM<Model>({
      initial: m("initial"),
      persister: async () => {},
      hub,
      strict: true,
      snapshotter: (value) => value,
      validators: {
        value: (model) => {
          runs.push(model.value);
          if (model.value === "a" && !reentered) {
            reentered = true;
            form.setModel(nestedModel);
          }
          return model.value === "b" ? "taken" : null;
        },
      },
    });
    const signals = record(form, hub);

    form.setModel(m("a"));

    // The outer preparation ran on "a"; the nested call prepared and committed "b".
    expect(runs).toEqual(["initial", "a", "b"]);
    expect(form.model).toBe(nestedModel);
    expect(stateOf(form)).toEqual({
      model: m("b"),
      snapshot: m("initial"),
      errors: { value: "taken" },
      isDirty: true,
      isValid: false,
      canApprove: false,
    });
    // Only the nested assignment published: one model message, and nothing
    // from the outer call after the nested commit.
    expect(signals).toEqual({
      ...NO_SIGNALS,
      errorsChanged: [{ value: "taken" }],
      canExecuteChanged: 1,
      modelMessages: ["b"],
    });

    form.setModel(m("c"));

    expect(stateOf(form)).toEqual({
      model: m("c"),
      snapshot: m("initial"),
      errors: {},
      isDirty: true,
      isValid: true,
      canApprove: true,
    });
    expect(signals).toEqual({
      ...NO_SIGNALS,
      errorsChanged: [{ value: "taken" }, {}],
      canExecuteChanged: 2,
      modelMessages: ["b", "c"],
    });
  });

  it("lets a nested deny from a validator win over the interrupted assignment", () => {
    const hub = new MessageHub();
    let reentered = false;
    let form: FormVM<Model>;
    form = new FormVM<Model>({
      initial: m("initial"),
      persister: async () => {},
      hub,
      strict: true,
      snapshotter: (value) => value,
      validators: {
        value: (model) => {
          if (model.value === "a" && !reentered) {
            reentered = true;
            form.denyCommand.execute();
          }
          return null;
        },
      },
    });
    form.setModel(m("edited"));
    const signals = record(form, hub);

    form.setModel(m("a"));

    expect(form.model).toBe(form.snapshot);
    expect(stateOf(form)).toEqual({
      model: m("initial"),
      snapshot: m("initial"),
      errors: {},
      isDirty: false,
      isValid: true,
      canApprove: false,
    });
    expect(signals).toEqual({
      ...NO_SIGNALS,
      canExecuteChanged: 1,
      modelMessages: ["initial"],
      revertedMessages: 1,
    });
  });

  it("still commits the outer assignment when the nested call commits nothing", () => {
    const hub = new MessageHub();
    let form: FormVM<Model>;
    form = new FormVM<Model>({
      initial: m("initial"),
      persister: async () => {},
      hub,
      strict: true,
      snapshotter: (value) => value,
      validators: {
        value: (model) => {
          // An equal assignment is rejected before preparation and commits nothing.
          if (model.value === "a") form.setModel(m("initial"));
          return null;
        },
      },
    });
    const signals = record(form, hub);

    form.setModel(m("a"));

    expect(stateOf(form)).toEqual({
      model: m("a"),
      snapshot: m("initial"),
      errors: {},
      isDirty: true,
      isValid: true,
      canApprove: true,
    });
    expect(signals).toEqual({
      ...NO_SIGNALS,
      canExecuteChanged: 1,
      modelMessages: ["a"],
    });
  });
});

describe("FORM-038", () => {
  type DisposingCallback = "field validator" | "model validator" | "equals";

  it.each<DisposingCallback>(["field validator", "model validator", "equals"])(
    "commits and publishes nothing when the %s disposes the form during setModel",
    async (callback) => {
      const hub = new MessageHub();
      const persister = vi.fn(async (_model: Model) => {});
      const runs: string[] = [];
      let form: FormVM<Model>;
      const disposeOn = (who: DisposingCallback, model: Model) => {
        if (who === callback && model.value === "doomed") form.dispose();
      };
      form = new FormVM<Model>({
        initial: m("initial"),
        persister,
        hub,
        strict: true,
        snapshotter: (value) => value,
        equals: (a, b) => {
          disposeOn("equals", b);
          return a.value === b.value;
        },
        validators: {
          value: (model) => {
            runs.push(model.value);
            disposeOn("field validator", model);
            return model.value === "doomed" ? "doomed" : null;
          },
        },
        modelValidator: (model) => {
          disposeOn("model validator", model);
          return {};
        },
      });
      form.setModel(m("edited"));
      const before = stateOf(form);
      expect(before).toMatchObject({ isDirty: true, isValid: true, canApprove: true });
      const signals = record(form, hub);

      expect(() => form.setModel(m("doomed"))).not.toThrow();

      expectUncommitted(form, before);
      expect(signals).toEqual(bareDisposeSignals());
      expect(signals.errorsChanged).toEqual([]);
      expect(signals.modelMessages).toEqual([]);

      // The disposed form is inert (FORM-014).
      const runsAfterDisposal = runs.length;
      form.setModel(m("late"));
      form.denyCommand.execute();
      await form.approveAsync();
      form.approveCommand.execute();

      expect(runs).toHaveLength(runsAfterDisposal);
      expect(persister).not.toHaveBeenCalled();
      expectUncommitted(form, before);
      expect(signals).toEqual(bareDisposeSignals());
    },
  );

  it.each(["validator", "snapshotter"] as const)(
    "does not revert or publish when the %s disposes the form during deny",
    async (callback) => {
      const hub = new MessageHub();
      const persister = vi.fn(async (_model: Model) => {});
      let armed = false;
      let form: FormVM<Model>;
      form = new FormVM<Model>({
        initial: m("initial"),
        persister,
        hub,
        strict: true,
        snapshotter: (model) => {
          if (armed && callback === "snapshotter") form.dispose();
          return { ...model };
        },
        validators: {
          value: (model) => {
            if (armed && callback === "validator" && model.value === "initial") {
              form.dispose();
            }
            return model.value === "edited" ? "flagged" : null;
          },
        },
      });
      form.setModel(m("edited"));
      armed = true;
      const before = stateOf(form);
      expect(before).toMatchObject({
        model: m("edited"),
        errors: { value: "flagged" },
        isDirty: true,
        isValid: false,
      });
      const signals = record(form, hub);

      expect(() => form.denyCommand.execute()).not.toThrow();

      expectUncommitted(form, before);
      expect(signals).toEqual(bareDisposeSignals());
      expect(signals.revertedMessages).toBe(0);
      expect(signals.modelMessages).toEqual([]);

      // The disposed form is inert (FORM-014).
      form.denyCommand.execute();
      form.setModel(m("late"));
      await form.approveAsync();

      expect(persister).not.toHaveBeenCalled();
      expectUncommitted(form, before);
      expect(signals).toEqual(bareDisposeSignals());
    },
  );
});
