// Feasibility pilot for issue #411: typed immutable model lenses applied
// through FormVM.setModel. Test-only code. Nothing here is exported from
// src/, adds a dependency, or claims a conformance ID.
//
// Decision record: docs/maintenance/2026-10-27-form-model-lens-pilot.md
//
// The domain mirrors the notes-showcase draft (title, body, starred, tags)
// and adds an optional nested branch (meta.reminder) and an id-keyed
// collection (checklist). The shipped NoteModel has neither; the pilot adds
// them to exercise the optional-branch and element-identity policies. A
// required nested record (appearance) exercises total composition.

import { describe, expect, it, vi } from "vitest";

import { FormVM, MessageHub, PropertyChangedMessage } from "../../../src/index.js";

// ---------------------------------------------------------------------------
// Pilot domain
// ---------------------------------------------------------------------------

interface ChecklistItem {
  readonly id: string;
  readonly text: string;
  readonly done: boolean;
}

interface Reminder {
  readonly at: string;
  readonly note: string;
}

interface Appearance {
  readonly color: string;
  readonly pinned: boolean;
}

interface DraftMeta {
  readonly reminder?: Reminder;
}

interface PilotDraft {
  readonly id: string;
  readonly title: string;
  readonly body: string;
  readonly starred: boolean;
  readonly tags: readonly string[];
  readonly appearance: Appearance;
  readonly meta?: DraftMeta;
  readonly checklist: readonly ChecklistItem[];
}

// ---------------------------------------------------------------------------
// Pilot lens kernel (private to this file)
// ---------------------------------------------------------------------------

/** A total lens: `get` always succeeds; `set` returns a new or the same model. */
interface Lens<S, A> {
  readonly get: (model: S) => A;
  readonly set: (model: S, value: A) => S;
}

/**
 * Explicit outcome of a partial edit. `model` is always the next model to
 * hand to `setModel`; on `"unchanged"` and `"missing"` it is the input
 * reference.
 */
type EditResult<S> =
  | { readonly outcome: "applied"; readonly model: S }
  | { readonly outcome: "unchanged"; readonly model: S }
  | { readonly outcome: "missing"; readonly model: S };

/** A partial lens (affine): the focus may be absent. */
interface OptionalLens<S, A> {
  readonly get: (model: S) => A | undefined;
  readonly set: (model: S, value: A) => EditResult<S>;
}

/**
 * Builds a total lens. The `set` wrapper returns the input reference when the
 * focused value is already `Object.is`-equal, so an equal set allocates
 * nothing and survives a reference-equality `equals` predicate.
 */
function lens<S, A>(get: (m: S) => A, set: (m: S, v: A) => S): Lens<S, A> {
  return {
    get,
    set: (model, value) => (Object.is(get(model), value) ? model : set(model, value)),
  };
}

/** Typed property lens: `prop<PilotDraft>()("title")`. */
function prop<S>() {
  return <K extends keyof S>(key: K): Lens<S, S[K]> =>
    lens(
      (m) => m[key],
      (m, v) => ({ ...m, [key]: v }),
    );
}

/** Composes two total lenses. */
function compose<S, A, B>(outer: Lens<S, A>, inner: Lens<A, B>): Lens<S, B> {
  return lens(
    (m) => inner.get(outer.get(m)),
    (m, v) => outer.set(m, inner.set(outer.get(m), v)),
  );
}

/**
 * Optional-branch policy: focus an optional property. The policy is "skip":
 * a missing branch reports `"missing"` and returns the input model. It never
 * creates the branch and never throws.
 */
function optionalProp<S, K extends keyof S>(key: K): OptionalLens<S, NonNullable<S[K]>> {
  return {
    get: (m) => m[key] ?? undefined,
    set: (m, v) => {
      const current = m[key];
      if (current === undefined || current === null) return { outcome: "missing", model: m };
      if (Object.is(current, v)) return { outcome: "unchanged", model: m };
      return { outcome: "applied", model: { ...m, [key]: v } };
    },
  };
}

/**
 * Element-identity policy: focus the element whose `id` matches at the time
 * of the edit. It never captures an index, so a removed element reports
 * `"missing"` instead of writing to whatever now sits at the old index.
 */
function elementById<T extends { readonly id: string }>(
  id: string,
): OptionalLens<readonly T[], T> {
  return {
    get: (items) => items.find((item) => item.id === id),
    set: (items, value) => {
      const index = items.findIndex((item) => item.id === id);
      if (index < 0) return { outcome: "missing", model: items };
      if (Object.is(items[index], value)) return { outcome: "unchanged", model: items };
      if (value.id !== id) throw new Error("elementById: the replacement must keep its id");
      const next = items.slice();
      next[index] = value;
      return { outcome: "applied", model: next };
    },
  };
}

/** Total then optional. */
function thenOptional<S, A, B>(outer: Lens<S, A>, inner: OptionalLens<A, B>): OptionalLens<S, B> {
  return {
    get: (m) => inner.get(outer.get(m)),
    set: (m, v) => {
      const result = inner.set(outer.get(m), v);
      return result.outcome === "applied"
        ? { outcome: "applied", model: outer.set(m, result.model) }
        : { outcome: result.outcome, model: m };
    },
  };
}

/** Optional then total. */
function optionalThen<S, A, B>(outer: OptionalLens<S, A>, inner: Lens<A, B>): OptionalLens<S, B> {
  return {
    get: (m) => {
      const focus = outer.get(m);
      return focus === undefined ? undefined : inner.get(focus);
    },
    set: (m, v) => {
      const focus = outer.get(m);
      if (focus === undefined) return { outcome: "missing", model: m };
      const next = inner.set(focus, v);
      if (next === focus) return { outcome: "unchanged", model: m };
      return outer.set(m, next);
    },
  };
}

/** Optional then optional. */
function optionalThenOptional<S, A, B>(
  outer: OptionalLens<S, A>,
  inner: OptionalLens<A, B>,
): OptionalLens<S, B> {
  return {
    get: (m) => {
      const focus = outer.get(m);
      return focus === undefined ? undefined : inner.get(focus);
    },
    set: (m, v) => {
      const focus = outer.get(m);
      if (focus === undefined) return { outcome: "missing", model: m };
      const result = inner.set(focus, v);
      return result.outcome === "applied"
        ? outer.set(m, result.model)
        : { outcome: result.outcome, model: m };
    },
  };
}

/** The single mutation boundary: one lens edit enters `setModel` once. */
function applyLens<S, A>(form: FormVM<S>, l: Lens<S, A>, value: A): void {
  form.setModel(l.set(form.model, value));
}

/** Partial edit through `setModel` once; the outcome goes back to the caller. */
function applyOptional<S, A>(
  form: FormVM<S>,
  l: OptionalLens<S, A>,
  value: A,
): EditResult<S>["outcome"] {
  const result = l.set(form.model, value);
  form.setModel(result.model);
  return result.outcome;
}

// ---------------------------------------------------------------------------
// Reusable paths
// ---------------------------------------------------------------------------

const draft = prop<PilotDraft>();
const reminder = prop<Reminder>();
const item = prop<ChecklistItem>();
const appearance = prop<Appearance>();

const titleL = draft("title");
const bodyL = draft("body");
const starredL = draft("starred");
const tagsL = draft("tags");
const checklistL = draft("checklist");
const colorL = compose(draft("appearance"), appearance("color"));
const pinnedL = compose(draft("appearance"), appearance("pinned"));
const reminderO = optionalThenOptional(
  optionalProp<PilotDraft, "meta">("meta"),
  optionalProp<DraftMeta, "reminder">("reminder"),
);
const reminderAtO = optionalThen(reminderO, reminder("at"));
const reminderNoteO = optionalThen(reminderO, reminder("note"));
const itemDoneO = (id: string) =>
  optionalThen(thenOptional(checklistL, elementById<ChecklistItem>(id)), item("done"));
const itemTextO = (id: string) =>
  optionalThen(thenOptional(checklistL, elementById<ChecklistItem>(id)), item("text"));

// ---------------------------------------------------------------------------
// Fixtures and helpers
// ---------------------------------------------------------------------------

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const key of Reflect.ownKeys(value)) {
      deepFreeze((value as Record<PropertyKey, unknown>)[key]);
    }
  }
  return value;
}

function sampleDraft(overrides: Partial<PilotDraft> = {}): PilotDraft {
  return deepFreeze({
    id: "n1",
    title: "Groceries",
    body: "Milk",
    starred: false,
    tags: ["home", "errands"],
    appearance: { color: "#336699", pinned: false },
    meta: { reminder: { at: "2026-10-27T09:00:00Z", note: "before work" } },
    checklist: [
      { id: "c1", text: "Milk", done: false },
      { id: "c2", text: "Eggs", done: false },
      { id: "c3", text: "Bread", done: true },
    ],
    ...overrides,
  });
}

/** The sample draft with the optional `meta` branch absent. */
function draftWithoutMeta(): PilotDraft {
  const { meta: _absent, ...rest } = sampleDraft();
  return deepFreeze({ ...rest });
}

/** Sample models over the supported domains: full, empty, and missing branches. */
function sampleModels(): PilotDraft[] {
  return [
    sampleDraft(),
    sampleDraft({ title: "", body: "", tags: [], checklist: [] }),
    draftWithoutMeta(),
    sampleDraft({ meta: {} }),
    sampleDraft({ title: "Ünïcødé ✓", starred: true }),
  ];
}

const noop = (): Promise<void> => Promise.resolve();

function makeForm(
  initial: PilotDraft,
  options: { readonly equals?: (a: PilotDraft, b: PilotDraft) => boolean } = {},
) {
  const hub = new MessageHub();
  const modelMessages: unknown[] = [];
  const subscription = hub.messages.subscribe((message) => {
    if (message instanceof PropertyChangedMessage && message.propertyName === "model") {
      modelMessages.push(message);
    }
  });
  const form = new FormVM<PilotDraft>({
    initial,
    persister: noop,
    hub,
    validators: { title: (m) => (m.title.trim().length === 0 ? "Title is required." : null) },
    ...(options.equals ? { equals: options.equals } : {}),
  });
  const setModel = vi.spyOn(form, "setModel");
  return { form, modelMessages, setModel, dispose: () => { subscription.unsubscribe(); form.dispose(); } };
}

const referenceEquals = (a: PilotDraft, b: PilotDraft): boolean => a === b;

// ---------------------------------------------------------------------------
// Criterion 1: lens laws
// ---------------------------------------------------------------------------

describe("pilot #411 lens laws (total lenses)", () => {
  const cases: { name: string; lens: Lens<PilotDraft, unknown>; values: unknown[] }[] = [
    { name: "title", lens: titleL as Lens<PilotDraft, unknown>, values: ["", "A", "Ünïcødé ✓", "  "] },
    { name: "body", lens: bodyL as Lens<PilotDraft, unknown>, values: ["", "x\ny"] },
    { name: "starred", lens: starredL as Lens<PilotDraft, unknown>, values: [true, false] },
    { name: "tags", lens: tagsL as Lens<PilotDraft, unknown>, values: [[], ["a"], ["a", "b"]] },
    { name: "appearance.color", lens: colorL as Lens<PilotDraft, unknown>, values: ["", "#000000"] },
    { name: "appearance.pinned", lens: pinnedL as Lens<PilotDraft, unknown>, values: [true, false] },
  ];

  for (const { name, lens: l, values } of cases) {
    it(`${name}: get-after-set returns the value that was set`, () => {
      for (const model of sampleModels()) {
        for (const value of values) {
          expect(l.get(l.set(model, value))).toBe(value);
        }
      }
    });

    it(`${name}: set-current-value returns the same reference`, () => {
      for (const model of sampleModels()) {
        // Reference law (stronger than structural): set(m, get(m)) === m.
        expect(l.set(model, l.get(model))).toBe(model);
      }
    });

    it(`${name}: last-set-wins`, () => {
      for (const model of sampleModels()) {
        for (const a of values) {
          for (const b of values) {
            expect(l.set(l.set(model, a), b)).toStrictEqual(l.set(model, b));
          }
        }
      }
    });
  }
});

describe("pilot #411 lens laws (optional lenses, where the focus exists)", () => {
  const present = sampleDraft();
  const cases: { name: string; lens: OptionalLens<PilotDraft, unknown>; values: unknown[] }[] = [
    { name: "meta.reminder.at", lens: reminderAtO as OptionalLens<PilotDraft, unknown>, values: ["", "2026-11-01T00:00:00Z"] },
    { name: "meta.reminder.note", lens: reminderNoteO as OptionalLens<PilotDraft, unknown>, values: ["", "call"] },
    { name: "checklist[c2].done", lens: itemDoneO("c2") as OptionalLens<PilotDraft, unknown>, values: [true, false] },
    { name: "checklist[c3].text", lens: itemTextO("c3") as OptionalLens<PilotDraft, unknown>, values: ["", "Rye"] },
  ];

  for (const { name, lens: l, values } of cases) {
    it(`${name}: get-after-set, set-current-value, last-set-wins`, () => {
      for (const value of values) {
        expect(l.get(l.set(present, value).model)).toBe(value);
      }
      const current = l.get(present);
      const same = l.set(present, current);
      expect(same.outcome).toBe("unchanged");
      expect(same.model).toBe(present);
      for (const a of values) {
        for (const b of values) {
          const ab = l.set(l.set(present, a).model, b).model;
          expect(ab).toStrictEqual(l.set(present, b).model);
        }
      }
    });
  }
});

// ---------------------------------------------------------------------------
// Criterion 2: one lens edit enters setModel once; equal-value no-op holds
// ---------------------------------------------------------------------------

describe("pilot #411 one lens edit enters setModel once", () => {
  it("publishes one model message per unequal set and none per equal set (default deepEquals)", () => {
    const { form, modelMessages, setModel, dispose } = makeForm(sampleDraft());

    applyLens(form, titleL, "Groceries v2");
    expect(setModel).toHaveBeenCalledTimes(1);
    expect(modelMessages).toHaveLength(1);

    applyLens(form, titleL, "Groceries v2");
    expect(setModel).toHaveBeenCalledTimes(2);
    expect(modelMessages).toHaveLength(1);

    expect(applyOptional(form, reminderAtO, "2026-11-01T00:00:00Z")).toBe("applied");
    expect(setModel).toHaveBeenCalledTimes(3);
    expect(modelMessages).toHaveLength(2);

    expect(applyOptional(form, itemDoneO("c1"), true)).toBe("applied");
    expect(applyOptional(form, itemDoneO("c1"), true)).toBe("unchanged");
    expect(setModel).toHaveBeenCalledTimes(5);
    expect(modelMessages).toHaveLength(3);
    dispose();
  });

  it("keeps the equal-value no-op under a reference-equality predicate", () => {
    const { form, modelMessages, dispose } = makeForm(sampleDraft(), { equals: referenceEquals });

    applyLens(form, titleL, form.model.title);
    applyLens(form, colorL, form.model.appearance.color);
    applyOptional(form, reminderAtO, form.model.meta!.reminder!.at);
    applyOptional(form, itemDoneO("c3"), true);
    expect(modelMessages).toHaveLength(0);

    applyLens(form, titleL, "changed");
    expect(modelMessages).toHaveLength(1);
    dispose();
  });

  it("a naive spread lens publishes a spurious message under reference equality", () => {
    // Contrast: a lens without the Object.is guard builds a new model on an
    // equal set. deepEquals hides that; a reference predicate does not.
    const naiveTitle: Lens<PilotDraft, string> = {
      get: (m) => m.title,
      set: (m, v) => ({ ...m, title: v }),
    };
    const structural = makeForm(sampleDraft());
    applyLens(structural.form, naiveTitle, structural.form.model.title);
    expect(structural.modelMessages).toHaveLength(0);
    structural.dispose();

    const byReference = makeForm(sampleDraft(), { equals: referenceEquals });
    applyLens(byReference.form, naiveTitle, byReference.form.model.title);
    expect(byReference.modelMessages).toHaveLength(1);
    byReference.dispose();
  });

  it("does not bypass validation, dirty tracking or the disposed guard", () => {
    const { form, modelMessages, setModel, dispose } = makeForm(sampleDraft());

    applyLens(form, titleL, "   ");
    expect(form.isValid).toBe(false);
    expect(form.fieldError("title")).toBe("Title is required.");
    expect(form.isDirty).toBe(true);

    applyLens(form, titleL, "Groceries");
    expect(form.isValid).toBe(true);
    expect(form.isDirty).toBe(false);
    expect(modelMessages).toHaveLength(2);

    form.dispose();
    applyLens(form, titleL, "after dispose");
    expect(setModel).toHaveBeenCalledTimes(3);
    expect(form.model.title).toBe("Groceries");
    expect(modelMessages).toHaveLength(2);
    dispose();
  });
});

// ---------------------------------------------------------------------------
// Criterion 3: explicit outcomes for missing branches and removed elements
// ---------------------------------------------------------------------------

describe("pilot #411 explicit partial-edit outcomes", () => {
  it("a missing optional branch reports missing and returns the same model", () => {
    for (const model of [draftWithoutMeta(), sampleDraft({ meta: {} })]) {
      const { form, modelMessages, setModel, dispose } = makeForm(model);
      const before = form.model;

      expect(() => applyOptional(form, reminderAtO, "2026-11-01T00:00:00Z")).not.toThrow();
      const outcome = reminderAtO.set(before, "2026-11-01T00:00:00Z");
      expect(outcome.outcome).toBe("missing");
      expect(outcome.model).toBe(before);
      expect(form.model).toBe(before);
      expect(reminderAtO.get(before)).toBeUndefined();
      expect(setModel).toHaveBeenCalledTimes(1);
      expect(modelMessages).toHaveLength(0);
      dispose();
    }
  });

  it("a removed collection element reports missing and never writes to its old index", () => {
    const { form, modelMessages, dispose } = makeForm(sampleDraft());
    const doneC2 = itemDoneO("c2"); // a path captured before the removal

    // Another edit removes c2; c3 now sits at c2's old index (1).
    applyLens(form, checklistL, form.model.checklist.filter((i) => i.id !== "c2"));
    expect(modelMessages).toHaveLength(1);
    const afterRemoval = form.model;
    expect(afterRemoval.checklist[1]!.id).toBe("c3");

    expect(applyOptional(form, doneC2, true)).toBe("missing");
    expect(form.model).toBe(afterRemoval);
    expect(form.model.checklist[1]).toStrictEqual({ id: "c3", text: "Bread", done: true });
    expect(modelMessages).toHaveLength(1);

    // Writing `done: false` would expose a stale index write on c3.
    expect(applyOptional(form, doneC2, false)).toBe("missing");
    expect(form.model.checklist.find((i) => i.id === "c3")!.done).toBe(true);
    expect(modelMessages).toHaveLength(1);
    dispose();
  });

  it("an element replacement that changes the id is rejected before setModel", () => {
    const byId = elementById<ChecklistItem>("c1");
    const items = sampleDraft().checklist;
    expect(() => byId.set(items, { id: "other", text: "x", done: false })).toThrow(
      "elementById: the replacement must keep its id",
    );
  });
});

// ---------------------------------------------------------------------------
// Criterion 4: no resources, no mutation of the prior model graph
// ---------------------------------------------------------------------------

describe("pilot #411 lenses are pure values", () => {
  it("never mutates the prior model graph", () => {
    const { form, dispose } = makeForm(sampleDraft());
    const edits: (() => void)[] = [
      () => applyLens(form, titleL, "T2"),
      () => applyLens(form, colorL, "#ffffff"),
      () => applyLens(form, tagsL, [...form.model.tags, "new"]),
      () => applyOptional(form, reminderAtO, "2026-12-01T00:00:00Z"),
      () => applyOptional(form, reminderNoteO, "n2"),
      () => applyOptional(form, itemDoneO("c2"), true),
      () => applyOptional(form, itemTextO("c1"), "Oat milk"),
      () => applyOptional(form, itemDoneO("gone"), true),
    ];
    for (const edit of edits) {
      const prior = deepFreeze(form.model);
      const priorCopy = structuredClone(prior);
      edit(); // a write to a frozen graph would throw in strict-mode modules
      expect(prior).toStrictEqual(priorCopy);
    }
    dispose();
  });

  it("shares untouched branches structurally with the prior model", () => {
    const prior = sampleDraft();
    const next = itemDoneO("c2").set(prior, true).model;
    expect(next).not.toBe(prior);
    expect(next.meta).toBe(prior.meta);
    expect(next.tags).toBe(prior.tags);
    expect(next.appearance).toBe(prior.appearance);
    expect(next.checklist[0]).toBe(prior.checklist[0]);
    expect(next.checklist[2]).toBe(prior.checklist[2]);
  });

  it("owns no subscriptions or disposable resources", () => {
    const lenses: object[] = [
      titleL, bodyL, starredL, tagsL, checklistL, colorL, pinnedL,
      reminderO, reminderAtO, reminderNoteO, itemDoneO("c1"), itemTextO("c1"),
    ];
    for (const l of lenses) {
      // Own keys include symbols, so a Symbol.dispose member would show here.
      expect(Reflect.ownKeys(l).sort()).toStrictEqual(["get", "set"]);
      for (const member of ["subscribe", "unsubscribe", "dispose", "close"]) {
        expect(member in l).toBe(false);
      }
    }
  });
});

// ---------------------------------------------------------------------------
// Native-syntax baseline for the comparison table
// ---------------------------------------------------------------------------

describe("pilot #411 native spread baseline produces the same models", () => {
  it("flat, nested-optional and element-by-id edits match the lens results", () => {
    const m = sampleDraft();

    // flat: native spread
    const flatNative = { ...m, title: "T" };
    expect(flatNative).toStrictEqual(titleL.set(m, "T"));

    // nested optional: native spread with an explicit branch
    const nestedNative = m.meta?.reminder
      ? { ...m, meta: { ...m.meta, reminder: { ...m.meta.reminder, at: "X" } } }
      : m;
    expect(nestedNative).toStrictEqual(reminderAtO.set(m, "X").model);

    // element by id: native map
    const itemNative = {
      ...m,
      checklist: m.checklist.map((i) => (i.id === "c2" ? { ...i, done: true } : i)),
    };
    expect(itemNative).toStrictEqual(itemDoneO("c2").set(m, true).model);

    // element by id, id missing: native map allocates an equal copy
    const missingNative = {
      ...m,
      checklist: m.checklist.map((i) => (i.id === "gone" ? { ...i, done: true } : i)),
    };
    expect(missingNative).toStrictEqual(m);
    expect(missingNative).not.toBe(m);
    expect(itemDoneO("gone").set(m, true).model).toBe(m);
  });
});
