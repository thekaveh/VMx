// Unit tests for FormVM — edge cases and implementation details.
// Conformance-level tests live in tests/conformance/form-001-to-010-form-vm.test.ts.

import { describe, expect, it, vi } from "vitest";

import {
  FormRevertedMessage,
  FormVM,
  MessageHub,
  PropertyChangedMessage,
} from "../../../src/index.js";
import { deepEquals } from "../../../src/forms/formVm.js";

interface IModel {
  name: string;
  value: number;
}

function m(name: string, value: number): IModel {
  return { name, value };
}

const noop = (): Promise<void> => Promise.resolve();

function make(initial = m("A", 1)) {
  return new FormVM<IModel>({ initial, persister: noop });
}

function captureError(action: () => void): Error & { cause?: unknown } {
  let caught: unknown;
  try {
    action();
  } catch (error: unknown) {
    caught = error;
  }
  expect(caught).toBeInstanceOf(Error);
  return caught as Error & { cause?: unknown };
}

// ---------------------------------------------------------------------------
// Construction guards
// ---------------------------------------------------------------------------

describe("FormVM construction guards", () => {
  it("throws when initial is null", () => {
    expect(
      () =>
        new FormVM<IModel>({ initial: null as unknown as IModel, persister: noop }),
    ).toThrow("initial must not be null or undefined");
  });

  it("throws when persister is undefined", () => {
    expect(
      () =>
        new FormVM<IModel>({
          initial: m("A", 1),
          persister: undefined as unknown as () => Promise<void>,
        }),
    ).toThrow("persister must not be null or undefined");
  });
});

// ---------------------------------------------------------------------------
// Snapshot
// ---------------------------------------------------------------------------

describe("FormVM snapshot", () => {
  it("is structurally equal to initial but a different reference", () => {
    const initial = m("Alice", 1);
    const sut = make(initial);
    expect(sut.snapshot).toEqual(initial);
    expect(sut.snapshot).not.toBe(initial); // structuredClone makes a copy
  });

  it("custom snapshotter called at construction", () => {
    const calls: IModel[] = [];
    const snapshotter = (model: IModel): IModel => {
      calls.push(model);
      return { ...model, name: model.name + "-snap" };
    };
    const initial = m("Alice", 1);
    const sut = new FormVM<IModel>({ initial, persister: noop, snapshotter });

    expect(calls).toHaveLength(1);
    expect(sut.snapshot.name).toBe("Alice-snap");
  });

  it("custom snapshotter applied on deny (restores from snapshot copy)", () => {
    const snapCalls: IModel[] = [];
    const snapshotter = (model: IModel): IModel => {
      snapCalls.push(model);
      return { ...model };
    };
    const sut = new FormVM<IModel>({ initial: m("A", 1), persister: noop, snapshotter });
    snapCalls.length = 0; // reset after construction

    sut.setModel(m("B", 2));
    sut.denyCommand.execute();

    expect(snapCalls).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Default snapshot diagnostics (#102)
// ---------------------------------------------------------------------------

describe("FormVM default snapshot diagnostics", () => {
  type AnyModel = Record<string, unknown>;

  it("names the construction phase and top-level function field without rendering its value", () => {
    const secret = "do-not-render-this-value";
    const error = captureError(() => {
      new FormVM<AnyModel>({
        initial: { title: "safe", callback: () => secret },
        persister: noop,
      });
    });

    expect(error.message).toContain("FormVM");
    expect(error.message).toContain("construction");
    expect(error.message).toContain('field "callback"');
    expect(error.message).toContain("snapshotter");
    expect(error.message).toContain("equals");
    expect(error.message).not.toContain(secret);
    expect(error.cause).toMatchObject({ name: "DataCloneError" });
  });

  it.each([
    ["nested class-owned function", new (class OpaquePayload { readonly run = () => 1; })()],
    ["host object", new WeakMap<object, unknown>()],
  ])("localizes a %s failure to its owning top-level field", (_case, payload) => {
    const error = captureError(() => {
      new FormVM<AnyModel>({ initial: { payload }, persister: noop });
    });

    expect(error.message).toContain('field "payload"');
    expect(error.cause).toBeDefined();
  });

  it("localizes a nested failure to the owning top-level field", () => {
    const error = captureError(() => {
      new FormVM<AnyModel>({
        initial: { settings: { transport: { send: () => undefined } } },
        persister: noop,
      });
    });

    expect(error.message).toContain('field "settings"');
  });

  it("accepts cyclic and BigInt values but diagnoses a symbol-valued field", () => {
    const cyclic: AnyModel = { id: 1n };
    cyclic.self = cyclic;
    expect(() => new FormVM<AnyModel>({ initial: cyclic, persister: noop })).not.toThrow();

    const error = captureError(() => {
      new FormVM<AnyModel>({ initial: { token: Symbol("opaque") }, persister: noop });
    });
    expect(error.message).toContain('field "token"');
  });

  it("does not invoke an accessor again while trying to localize a failure", () => {
    let reads = 0;
    const initial = Object.defineProperty({}, "payload", {
      enumerable: true,
      get: () => {
        reads += 1;
        return () => undefined;
      },
    });

    const error = captureError(() => {
      new FormVM<object>({ initial, persister: noop });
    });

    expect(reads).toBe(1);
    expect(error.message).toContain("construction");
    expect(error.message).not.toContain('field "payload"');
  });

  it("does not invoke a nested accessor again while trying to localize a failure", () => {
    let reads = 0;
    const payload = Object.defineProperty({}, "callback", {
      enumerable: true,
      get: () => {
        reads += 1;
        return () => undefined;
      },
    });

    const error = captureError(() => {
      new FormVM<AnyModel>({ initial: { payload }, persister: noop });
    });

    expect(reads).toBe(1);
    expect(error.message).toContain("construction");
    expect(error.message).not.toContain('field "payload"');
  });

  it("does not blame a symbol-keyed property that structuredClone ignores", () => {
    const decoy = Symbol("decoy");
    const initial = new WeakMap<object, unknown>() as WeakMap<object, unknown> & {
      [decoy]: () => void;
    };
    Object.defineProperty(initial, decoy, {
      enumerable: true,
      value: () => undefined,
    });

    const error = captureError(() => {
      new FormVM<typeof initial>({ initial, persister: noop });
    });

    expect(error.message).toContain("construction");
    expect(error.message).not.toContain("Symbol(decoy)");
  });

  it("does not invoke an accessor inside Error.cause again", () => {
    let reads = 0;
    const cause = Object.defineProperty({}, "callback", {
      enumerable: true,
      get: () => {
        reads += 1;
        return () => undefined;
      },
    });
    const payload = new Error("opaque", { cause });

    const error = captureError(() => {
      new FormVM<AnyModel>({ initial: { payload }, persister: noop });
    });

    expect(reads).toBe(1);
    expect(error.message).toContain("construction");
    expect(error.message).not.toContain('field "payload"');
  });

  it("wraps approve snapshot failure with phase and field while preserving cause", async () => {
    const form = new FormVM<AnyModel>({ initial: { title: "safe" }, persister: noop });
    form.setModel({ title: "changed", callback: () => undefined });

    let caught: unknown;
    try {
      await form.approveAsync();
    } catch (error: unknown) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(Error);
    const error = caught as Error & { cause?: unknown };
    expect(error.message).toContain("approve snapshot advance");
    expect(error.message).toContain('field "callback"');
    expect(error.cause).toMatchObject({ name: "DataCloneError" });
    expect(form.snapshot).toEqual({ title: "safe" });
  });

  it("wraps deny snapshot failure with phase and field while preserving cause", () => {
    const form = new FormVM<AnyModel>({
      initial: { payload: { title: "safe" } },
      persister: noop,
    });
    (form.snapshot.payload as AnyModel).callback = () => undefined;

    const error = captureError(() => form.denyCommand.execute());

    expect(error.message).toContain("deny/revert");
    expect(error.message).toContain('field "payload"');
    expect(error.cause).toMatchObject({ name: "DataCloneError" });
  });

  it("passes a custom snapshotter error through unchanged on every phase", async () => {
    const constructionError = new Error("custom construction failure");
    expect(
      captureError(() => {
        new FormVM<AnyModel>({
          initial: { phase: "construction" },
          persister: noop,
          snapshotter: () => { throw constructionError; },
        });
      }),
    ).toBe(constructionError);

    const approveError = new Error("custom approve failure");
    let approveCalls = 0;
    const approveForm = new FormVM<AnyModel>({
      initial: { phase: "construction" },
      persister: noop,
      snapshotter: (model) => {
        approveCalls += 1;
        if (approveCalls > 1) throw approveError;
        return { ...model };
      },
    });
    await expect(approveForm.approveAsync()).rejects.toBe(approveError);

    const denyError = new Error("custom deny failure");
    let denyCalls = 0;
    const denyForm = new FormVM<AnyModel>({
      initial: { phase: "construction" },
      persister: noop,
      snapshotter: (model) => {
        denyCalls += 1;
        if (denyCalls > 1) throw denyError;
        return { ...model };
      },
    });
    expect(captureError(() => denyForm.denyCommand.execute())).toBe(denyError);
  });
});

// ---------------------------------------------------------------------------
// setModel
// ---------------------------------------------------------------------------

describe("FormVM setModel", () => {
  it("throws when model is null", () => {
    const sut = make();
    expect(() => sut.setModel(null as unknown as IModel)).toThrow(
      "model must not be null or undefined",
    );
  });

  it("tracks latest mutation", () => {
    const sut = make();
    sut.setModel(m("B", 2));
    sut.setModel(m("C", 3));
    expect(sut.model).toEqual(m("C", 3));
    expect(sut.isDirty).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// denyCommand
// ---------------------------------------------------------------------------

describe("FormVM denyCommand", () => {
  it("canExecute is always true", () => {
    const sut = make();
    expect(sut.denyCommand.canExecute()).toBe(true);
  });

  it("publishes hub messages even when model equals snapshot", () => {
    const hub = new MessageHub();
    const messages: unknown[] = [];
    hub.messages.subscribe((m) => messages.push(m));

    const sut = new FormVM<IModel>({ initial: m("A", 1), persister: noop, hub });
    // Not dirty; deny still sends hub messages.
    sut.denyCommand.execute();

    expect(messages).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// approveAsync — multiple rounds
// ---------------------------------------------------------------------------

describe("FormVM approveAsync", () => {
  it("snapshot advances across multiple rounds", async () => {
    const sut = make();

    sut.setModel(m("B", 2));
    await sut.approveAsync();
    expect(sut.snapshot).toEqual(m("B", 2));

    sut.setModel(m("C", 3));
    await sut.approveAsync();
    expect(sut.snapshot).toEqual(m("C", 3));
    expect(sut.isDirty).toBe(false);
  });

  it("non-strict allows re-approve without mutation", async () => {
    const approved: IModel[] = [];
    const sut = make();
    sut.onApproved.subscribe((m) => approved.push(m));

    await sut.approveAsync(); // Not dirty — allowed in non-strict mode.

    expect(approved).toHaveLength(1);
  });

  it("persister receives current model", async () => {
    const received: IModel[] = [];
    const sut = new FormVM<IModel>({
      initial: m("A", 1),
      persister: (model) => {
        received.push(model);
        return Promise.resolve();
      },
    });
    sut.setModel(m("B", 2));
    await sut.approveAsync();

    expect(received).toEqual([m("B", 2)]);
  });
});

// ---------------------------------------------------------------------------
// Strict mode
// ---------------------------------------------------------------------------

describe("FormVM strict mode", () => {
  it("canExecuteChanged fires when isDirty transitions on setModel", () => {
    const sut = new FormVM<IModel>({
      initial: m("A", 1),
      persister: noop,
      strict: true,
    });
    let fired = 0;
    sut.approveCommand.canExecuteChanged.subscribe(() => { fired++; });

    sut.setModel(m("B", 2));
    expect(fired).toBeGreaterThan(0);
  });

  it("canExecuteChanged fires when isDirty transitions on deny", () => {
    const sut = new FormVM<IModel>({
      initial: m("A", 1),
      persister: noop,
      strict: true,
    });
    sut.setModel(m("B", 2)); // make dirty

    let fired = 0;
    sut.approveCommand.canExecuteChanged.subscribe(() => { fired++; });

    sut.denyCommand.execute();
    expect(fired).toBeGreaterThan(0);
  });

  it("canExecuteChanged fires after approve advances snapshot", async () => {
    const sut = new FormVM<IModel>({
      initial: m("A", 1),
      persister: noop,
      strict: true,
    });
    sut.setModel(m("B", 2));

    let fired = 0;
    sut.approveCommand.canExecuteChanged.subscribe(() => { fired++; });

    await sut.approveAsync();
    expect(fired).toBeGreaterThan(0);
    expect(sut.approveCommand.canExecute()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Hub message sender identity
// ---------------------------------------------------------------------------

describe("FormVM hub messages", () => {
  it("sender is the FormVM instance", () => {
    const hub = new MessageHub();
    const messages: unknown[] = [];
    hub.messages.subscribe((m) => messages.push(m));

    const sut = new FormVM<IModel>({ initial: m("A", 1), persister: noop, hub });
    sut.setModel(m("B", 2));
    sut.denyCommand.execute();

    const revertMsg = messages.find((m) => m instanceof FormRevertedMessage);
    expect(revertMsg?.sender).toBe(sut);

    const propMsg = messages.find((m) => m instanceof PropertyChangedMessage) as
      | PropertyChangedMessage<object>
      | undefined;
    expect(propMsg?.sender).toBe(sut);
    expect(propMsg?.propertyName).toBe("model");
  });
});

// ---------------------------------------------------------------------------
// onApproved observable
// ---------------------------------------------------------------------------

describe("FormVM onApproved", () => {
  it("completes after dispose", () => {
    const completed = vi.fn();
    const sut = make();
    sut.onApproved.subscribe({ complete: completed });

    sut.dispose();
    expect(completed).toHaveBeenCalledOnce();
  });
});

// ---------------------------------------------------------------------------
// Post-dispose guards
// ---------------------------------------------------------------------------

describe("FormVM – post-dispose guards", () => {
  it("deny after dispose is a no-op (no throw, no revert)", () => {
    const sut = make();
    sut.setModel(m("B", 2));
    sut.dispose();

    sut.denyCommand.execute();

    expect(sut.model).toEqual(m("B", 2));
  });

  it("approve after dispose does not invoke the persister", async () => {
    // The persister is an external side effect and must not run on a
    // disposed form (symmetric with the deny guard).
    const persisted: IModel[] = [];
    const sut = new FormVM<IModel>({
      initial: m("A", 1),
      persister: (model) => {
        persisted.push(model);
        return Promise.resolve();
      },
    });
    sut.dispose();

    await sut.approveAsync();

    expect(persisted).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Fire-and-forget safety
// ---------------------------------------------------------------------------

describe("FormVM – fire-and-forget approve", () => {
  it("approveCommand.execute does not surface an unhandled rejection", async () => {
    const form = new FormVM<IModel>({
      initial: m("A", 1),
      persister: () => Promise.reject(new Error("boom")),
    });
    form.setModel(m("B", 2));

    form.approveCommand.execute(); // a bare `void` here used to crash Node >= 15

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(form.isDirty).toBe(true); // failed persist must not advance the snapshot
    form.dispose();
  });
});

// ---------------------------------------------------------------------------
// Approve error channel (VMX-008)
//
// The approve COMMAND is fire-and-forget (RelayCommand.execute is void), so a
// rejecting persister cannot propagate to its caller. Previously the rejection
// was swallowed (`.catch(() => undefined)`) — a silent data-loss-class failure
// for any UI bound to the command. The error must now be OBSERVABLE on the
// approveErrors channel. The awaitable approveAsync() path keeps its throw.
// ---------------------------------------------------------------------------

describe("FormVM – approve error channel (VMX-008)", () => {
  it("surfaces a persister rejection on approveErrors when the COMMAND is invoked", async () => {
    const boom = new Error("persist failed");
    const errors: unknown[] = [];
    const form = new FormVM<IModel>({
      initial: m("A", 1),
      persister: () => Promise.reject(boom),
    });
    form.approveErrors.subscribe((e) => errors.push(e));
    form.setModel(m("B", 2));

    form.approveCommand.execute(); // fire-and-forget

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(errors).toEqual([boom]); // observed, not swallowed
    expect(form.isDirty).toBe(true); // failed persist did not advance the snapshot
    form.dispose();
  });

  it("approveErrors completes on dispose", () => {
    const completed = vi.fn();
    const form = make();
    form.approveErrors.subscribe({ complete: completed });
    form.dispose();
    expect(completed).toHaveBeenCalledOnce();
  });
});

// ---------------------------------------------------------------------------
// Builder snapshotter (was ctor-only tested)
// ---------------------------------------------------------------------------

describe("FormVM – builder snapshotter", () => {
  it("the builder's snapshotter setter reaches the FormVM", () => {
    const snaps: IModel[] = [];
    const form = FormVM.builder<IModel>()
      .initial(m("A", 1))
      .persister(noop)
      .snapshotter((model) => {
        snaps.push(model);
        return { ...model };
      })
      .build();

    expect(snaps.length).toBeGreaterThan(0);
    expect(form.snapshot).not.toBe(form.model);
    form.dispose();
  });
});

// ---------------------------------------------------------------------------
// isDirty — structural deep equality (VMX-003)
//
// The previous implementation compared `JSON.stringify(model)` vs
// `JSON.stringify(snapshot)`. That HARD-CRASHES on BigInt/circular models and
// is SILENTLY WRONG for Map/Set (→ `{}`), Date (string-coerced), and
// undefined-vs-missing keys — while the default `structuredClone` snapshotter
// faithfully clones exactly those types. These tests pin the corrected
// behavior: an injectable structural deep-equal that is internally consistent
// with the snapshotter.
// ---------------------------------------------------------------------------

describe("FormVM isDirty – structural deep equality (VMX-003)", () => {
  // Models in this block deliberately carry types JSON.stringify mishandles, so
  // a loose record type is the right shape here.
  type AnyModel = Record<string, unknown>;

  function makeAny(initial: AnyModel) {
    return new FormVM<AnyModel>({ initial, persister: noop });
  }

  // (a) Date — was silently clean under JSON.stringify (string-coercion).
  it("(a) detects a Date replaced by its equivalent ISO string (JSON coerced them equal)", () => {
    const iso = "2020-01-01T00:00:00.000Z";
    const sut = makeAny({ when: new Date(iso) });
    expect(sut.isDirty).toBe(false);

    // A Date and the string holding its ISO value stringify identically, so the
    // old comparison reported this real type change as clean.
    sut.setModel({ when: iso });
    expect(sut.isDirty).toBe(true);
  });

  it("(a') detects a Date changed to a different instant", () => {
    const sut = makeAny({ when: new Date("2020-01-01T00:00:00.000Z") });
    sut.setModel({ when: new Date("2021-06-15T00:00:00.000Z") });
    expect(sut.isDirty).toBe(true);
  });

  it("(a'') treats an equal-instant Date (different object) as clean", () => {
    const sut = makeAny({ when: new Date("2020-01-01T00:00:00.000Z") });
    sut.setModel({ when: new Date("2020-01-01T00:00:00.000Z") });
    expect(sut.isDirty).toBe(false);
  });

  // (b) Map / Set — JSON.stringify renders both as `{}`, hiding every change.
  it("(b) detects a Set change (JSON.stringify renders every Set as {})", () => {
    const sut = makeAny({ tags: new Set(["a"]) });
    expect(sut.isDirty).toBe(false);

    sut.setModel({ tags: new Set(["a", "b"]) });
    expect(sut.isDirty).toBe(true);
  });

  it("(b') detects a Map value change (JSON.stringify renders every Map as {})", () => {
    const sut = makeAny({ m: new Map([["k", 1]]) });
    expect(sut.isDirty).toBe(false);

    sut.setModel({ m: new Map([["k", 2]]) });
    expect(sut.isDirty).toBe(true);
  });

  it("(b'') treats an equal Map (different object) as clean", () => {
    const sut = makeAny({ m: new Map([["k", 1]]) });
    sut.setModel({ m: new Map([["k", 1]]) });
    expect(sut.isDirty).toBe(false);
  });

  // (c) BigInt — JSON.stringify throws a TypeError; structuredClone clones fine.
  it("(c) does not throw on a BigInt model and detects a BigInt change", () => {
    const sut = makeAny({ id: 1n });
    expect(() => sut.isDirty).not.toThrow();
    expect(sut.isDirty).toBe(false);

    sut.setModel({ id: 2n });
    expect(() => sut.isDirty).not.toThrow();
    expect(sut.isDirty).toBe(true);
  });

  // (d) Circular references — JSON.stringify throws "circular structure".
  it("(d) does not throw on a circular model", () => {
    const a: AnyModel = { name: "A" };
    a.self = a; // structuredClone preserves the cycle.
    const sut = makeAny(a);

    expect(() => sut.isDirty).not.toThrow();
    expect(sut.isDirty).toBe(false);

    const b: AnyModel = { name: "B" };
    b.self = b;
    expect(() => {
      sut.setModel(b);
    }).not.toThrow();
    expect(sut.isDirty).toBe(true);
  });

  // (e) undefined vs missing — JSON.stringify drops undefined-valued keys.
  it("(e) detects adding an undefined-valued key (JSON.stringify silently dropped it)", () => {
    // structuredClone preserves `note: undefined`; the comparison must too.
    const sut = makeAny({ name: "A" });
    expect(sut.isDirty).toBe(false);

    sut.setModel({ name: "A", note: undefined });
    expect(sut.isDirty).toBe(true);
  });

  // (f) Plain-object happy path is unchanged.
  it("(f) plain-object change reads dirty and a value-equal revert reads clean", () => {
    const sut = make(m("A", 1));
    expect(sut.isDirty).toBe(false);

    sut.setModel(m("B", 2));
    expect(sut.isDirty).toBe(true);

    // A different object instance with the same field values is clean again.
    sut.setModel(m("A", 1));
    expect(sut.isDirty).toBe(false);
  });

  // Injectable override — mirrors the snapshotter injection point.
  it("honors a custom equals predicate", () => {
    const calls: Array<[IModel, IModel]> = [];
    const sut = new FormVM<IModel>({
      initial: m("A", 1),
      persister: noop,
      // Compare on `name` only — `value` changes are considered clean.
      equals: (x, y) => {
        calls.push([x, y]);
        return x.name === y.name;
      },
    });

    sut.setModel(m("A", 999));
    expect(sut.isDirty).toBe(false); // value differs but name matches → clean
    expect(calls.length).toBeGreaterThan(0);

    sut.setModel(m("Z", 1));
    expect(sut.isDirty).toBe(true); // name differs → dirty
  });

  it("the builder's equals setter reaches the FormVM", () => {
    const form = FormVM.builder<IModel>()
      .initial(m("A", 1))
      .persister(noop)
      .equals((x, y) => x.name === y.name)
      .build();

    form.setModel(m("A", 42));
    expect(form.isDirty).toBe(false);
    form.dispose();
  });
});

// ---------------------------------------------------------------------------
// Default equality mirrors the default snapshotter (#353)
// ---------------------------------------------------------------------------

describe("FormVM default equality – supported snapshot domain", () => {
  type AnyModel = Record<string, unknown>;

  function makeAny(initial: AnyModel, extra: Partial<{ strict: boolean }> = {}) {
    return new FormVM<AnyModel>({ initial, persister: noop, ...extra });
  }

  const cyclic: AnyModel = { name: "cycle" };
  cyclic.self = cyclic;

  class ValidationError extends Error {
    readonly code = 42;
    constructor(message: string) {
      super(message);
      this.name = "ValidationError";
    }
  }

  const supported: Array<[string, unknown]> = [
    ["string", "text"],
    ["number", 42],
    ["NaN", Number.NaN],
    ["negative zero", -0],
    ["bigint", 10n],
    ["boolean", true],
    ["null", null],
    ["undefined-valued key", undefined],
    ["valid Date", new Date("2020-01-01T00:00:00.000Z")],
    ["invalid Date", new Date(Number.NaN)],
    ["RegExp", /ab+c/gi],
    ["ArrayBuffer", new Uint8Array([1, 2, 3]).buffer],
    ["typed array", new Float64Array([1.5, Number.NaN])],
    ["DataView", new DataView(new Uint8Array([4, 5]).buffer)],
    ["array", [1, [2, 3], { deep: true }]],
    ["primitive-key Map", new Map<unknown, unknown>([["k", { v: 1 }], [2, [3]]])],
    ["primitive Set", new Set([1, "two", null])],
    ["nested object", { a: { b: { c: [new Date(0)] } } }],
    ["cycle", cyclic],
    ["Error", new Error("boom")],
    ["TypeError", new TypeError("bad input")],
    ["Error without a message", new Error()],
    ["Error with an empty message", new Error("")],
    ["Error with a non-string message", Object.assign(new Error("x"), { message: 5 })],
    ["Error with a nested cause", new Error("outer", { cause: new RangeError("inner", { cause: 7 }) })],
    ["Error with an undefined cause", new Error("outer", { cause: undefined })],
    ["custom Error subclass", new ValidationError("too short")],
    ["AggregateError", new AggregateError([new Error("first")], "several")],
  ];

  it.each(supported)("a model holding %s starts clean against its snapshot", (_, value) => {
    const sut = makeAny({ value });
    expect(sut.isDirty).toBe(false);
    sut.dispose();
  });

  it("keeps an invalid Date clean through setModel, strict approval, deny, and reset", async () => {
    const approved: AnyModel[] = [];
    const sut = new FormVM<AnyModel>({
      initial: { when: new Date(Number.NaN) },
      persister: noop,
      strict: true,
      resetOnApproved: (current) => ({ ...current, when: new Date(Number.NaN) }),
    });
    sut.onApproved.subscribe((model) => approved.push(model));
    expect(sut.isDirty).toBe(false);
    expect(sut.approveCommand.canExecute()).toBe(false);

    sut.setModel({ when: new Date(Number.NaN) });
    expect(sut.isDirty).toBe(false);
    expect(sut.approveCommand.canExecute()).toBe(false);

    sut.setModel({ when: new Date(0) });
    expect(sut.isDirty).toBe(true);
    expect(sut.approveCommand.canExecute()).toBe(true);
    sut.denyCommand.execute();
    expect(sut.isDirty).toBe(false);

    sut.setModel({ when: new Date(0) });
    await sut.approveAsync();
    expect(approved).toHaveLength(1);
    expect(sut.isDirty).toBe(false);
    expect(Number.isNaN((sut.model.when as Date).getTime())).toBe(true);
    sut.dispose();
  });

  it("still distinguishes an invalid Date from a valid one", () => {
    const sut = makeAny({ when: new Date(Number.NaN) });
    sut.setModel({ when: new Date(0) });
    expect(sut.isDirty).toBe(true);
    sut.setModel({ when: new Date(Number.NaN) });
    expect(sut.isDirty).toBe(false);
    sut.dispose();
  });

  it("compares Error values by kind, message, and cause", () => {
    const equalsCase = (x: unknown, y: unknown) => deepEquals({ value: x }, { value: y });

    // Separately constructed errors with the same kind and message are equal;
    // their stacks differ and are not compared.
    expect(equalsCase(new Error("boom"), new Error("boom"))).toBe(true);
    expect(equalsCase(new Error("boom"), new Error("bang"))).toBe(false);
    expect(equalsCase(new Error("boom"), new TypeError("boom"))).toBe(false);
    expect(equalsCase(new Error(""), new Error())).toBe(false);

    // Causes compare recursively, and an own undefined cause is kept.
    const nested = (inner: string) =>
      new Error("outer", { cause: new RangeError("middle", { cause: new Error(inner) }) });
    expect(equalsCase(nested("deep"), nested("deep"))).toBe(true);
    expect(equalsCase(nested("deep"), nested("deeper"))).toBe(false);
    expect(equalsCase(new Error("x", { cause: 1 }), new Error("x"))).toBe(false);
    expect(equalsCase(new Error("x", { cause: undefined }), new Error("x"))).toBe(false);

    // An error never equals a non-error, even one with the same enumerable keys.
    expect(equalsCase(new Error("boom"), {})).toBe(false);
    expect(equalsCase({}, new Error("boom"))).toBe(false);
  });

  it("compares self-referencing and mutually referencing causes without looping", () => {
    const loop = (message: string) => {
      const error = new Error(message);
      (error as { cause?: unknown }).cause = error;
      return error;
    };
    const pair = (inner: string) => {
      const outer = new Error("outer");
      const innerError = new Error(inner, { cause: outer });
      (outer as { cause?: unknown }).cause = innerError;
      return outer;
    };
    expect(deepEquals(loop("same"), loop("same"))).toBe(true);
    expect(deepEquals(loop("same"), loop("other"))).toBe(false);
    expect(deepEquals(pair("same"), pair("same"))).toBe(true);
    expect(deepEquals(pair("same"), pair("other"))).toBe(false);
  });

  it("ignores what structuredClone drops: subclass identity, custom properties, and stacks", () => {
    class ValidationError extends Error {
      constructor(
        message: string,
        readonly code: number,
      ) {
        super(message);
        this.name = "ValidationError";
      }
    }
    // The clone of a custom subclass is a plain Error with the same message.
    const original = new ValidationError("too short", 42);
    const clone = structuredClone(original);
    expect(Object.getPrototypeOf(clone)).toBe(Error.prototype);
    expect(deepEquals(original, clone)).toBe(true);
    expect(deepEquals(new ValidationError("x", 1), new ValidationError("x", 2))).toBe(true);

    // The kind follows `name`, as the clone does: a renamed Error is a TypeError.
    const renamed = Object.assign(new Error("bad"), { name: "TypeError" });
    expect(Object.getPrototypeOf(structuredClone(renamed))).toBe(TypeError.prototype);
    expect(deepEquals(renamed, new TypeError("bad"))).toBe(true);
  });

  it("never throws on an Error whose message cannot be cloned", () => {
    const symbolic = new Error("x");
    (symbolic as { message: unknown }).message = Symbol("opaque");
    expect(() => deepEquals(symbolic, new Error("x"))).not.toThrow();
    expect(deepEquals(symbolic, new Error("x"))).toBe(false);
  });

  it("tracks a changed Error through setModel, strict approval, deny, and reset", async () => {
    const approved: AnyModel[] = [];
    const sut = new FormVM<AnyModel>({
      initial: { failure: new Error("timeout", { cause: new TypeError("socket") }) },
      persister: noop,
      strict: true,
      resetOnApproved: (current) => ({ ...current, failure: new Error("cleared") }),
    });
    sut.onApproved.subscribe((model) => approved.push(model));
    expect(sut.isDirty).toBe(false);
    expect(sut.approveCommand.canExecute()).toBe(false);

    // Same kind, message, and cause: equality suppresses the assignment.
    sut.setModel({ failure: new Error("timeout", { cause: new TypeError("socket") }) });
    expect(sut.isDirty).toBe(false);
    expect(sut.approveCommand.canExecute()).toBe(false);

    // A different cause is a change.
    sut.setModel({ failure: new Error("timeout", { cause: new TypeError("dns") }) });
    expect(sut.isDirty).toBe(true);
    expect(sut.approveCommand.canExecute()).toBe(true);
    sut.denyCommand.execute();
    expect(sut.isDirty).toBe(false);
    expect(((sut.model.failure as Error).cause as Error).message).toBe("socket");

    sut.setModel({ failure: new Error("refused") });
    await sut.approveAsync();
    expect(approved).toHaveLength(1);
    expect((approved[0]?.failure as Error).message).toBe("refused");
    expect((sut.model.failure as Error).message).toBe("cleared");
    expect(sut.isDirty).toBe(false);
    sut.dispose();
  });

  it("keeps SameValueZero reference membership for object-keyed Map and Set by default", () => {
    const key = { id: 1 };
    const sut = makeAny({ index: new Map([[key, "x"]]), picked: new Set([key]) });

    // structuredClone copies the key objects, so the snapshot's keys are new
    // references and the default comparison reports the form as dirty.
    expect(sut.isDirty).toBe(true);
    sut.dispose();
  });

  it("lets a custom equals compare object-keyed Map and Set structurally", () => {
    type Keyed = { picked: Set<{ id: number }> };
    const ids = (model: Keyed) => [...model.picked].map((entry) => entry.id).sort();
    const sut = new FormVM<Keyed>({
      initial: { picked: new Set([{ id: 1 }, { id: 2 }]) },
      persister: noop,
      equals: (x, y) => JSON.stringify(ids(x)) === JSON.stringify(ids(y)),
    });
    expect(sut.isDirty).toBe(false);

    sut.setModel({ picked: new Set([{ id: 2 }, { id: 1 }]) });
    expect(sut.isDirty).toBe(false);
    sut.setModel({ picked: new Set([{ id: 3 }]) });
    expect(sut.isDirty).toBe(true);
    sut.dispose();
  });
});
