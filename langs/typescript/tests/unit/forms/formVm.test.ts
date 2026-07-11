// Unit tests for FormVM — edge cases and implementation details.
// Conformance-level tests live in tests/conformance/form-001-to-010-form-vm.test.ts.

import { describe, expect, it, vi } from "vitest";

import {
  FormRevertedMessage,
  FormVM,
  MessageHub,
  PropertyChangedMessage,
} from "../../../src/index.js";

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
