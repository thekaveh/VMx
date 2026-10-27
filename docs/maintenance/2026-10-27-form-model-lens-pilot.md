# 1. Form Model Lens Feasibility

## 1.1. Status

Feasibility record for issue #411, dated 2026-10-27, against `develop` at
`dfd8a50b`. The owner makes the decision.

Recommendation: reject a public lens abstraction. Document the native update
idioms for `FormVM` instead. Section 1.7 lists the evidence that would reopen
the decision.

This record adds no export, dependency, conformance ID, spec change or version
change. The pilot is test-only TypeScript code.

## 1.2. Context

`FormVM` replaces the whole model through `setModel`. Chapter 20 §5.2 fixes
the transaction order. The disposed guard and the equality short-circuit come
first. Validation, command invalidation and one `"model"` hub message follow.

Immutable nested edits therefore repeat spread or `with` code at each call
site. Issue #411 asks for typed, composable lenses that apply through
`setModel` once. A rejection with evidence is a valid outcome.

Constraints from earlier decisions:

- ADR-0040 rejects wrapped backing-field abstractions when language idioms
  cover the use case.
- The #79 review rejects a tree-wide mutation stream and cites ADR-0040.
- A lens must not bypass validation, snapshot semantics, disposed guards or
  command invalidation.
- A lens must not generate undo history.

## 1.3. Pilot

### 1.3.1. Location and scope

The pilot is
`langs/typescript/tests/unit/forms/formModelLensPilot.test.ts`, beside the
`FormVM` tests. Vitest has no `include` override, so its default glob collects
the file. `tsconfig.tests.json` and the
test ESLint block cover `tests/**`.

All lens code is private to the test file. Nothing under `src/` changes.

The domain mirrors the notes-showcase draft: `title`, `body`, `starred` and a
`tags` array. The shipped `NoteModel` is flat. The pilot adds three fields to
exercise the policies:

- `appearance`: a required nested record, for total composition.
- `meta?.reminder?`: an optional nested branch, for the optional policy.
- `checklist`: an array of items with an `id`, for the element policy.

### 1.3.2. Kernel

The kernel has 115 non-comment lines and 1,188 tokens. It contains these
parts:

- `lens(get, set)`: a total lens. Its `set` returns the input reference when
  the focus is already `Object.is`-equal to the new value.
- `prop<S>()(key)`: a typed property lens over `keyof S`.
- `compose(outer, inner)`: total composition.
- `optionalProp(key)`: the optional-branch policy.
- `elementById(id)`: the element-identity policy.
- `thenOptional`, `optionalThen` and `optionalThenOptional`: mixed
  composition.
- `applyLens` and `applyOptional`: each calls `setModel` exactly once.

A partial edit returns an explicit result:

```ts
type EditResult<S> =
  | { readonly outcome: "applied"; readonly model: S }
  | { readonly outcome: "unchanged"; readonly model: S }
  | { readonly outcome: "missing"; readonly model: S };
```

On `"unchanged"` and `"missing"`, `model` is the input reference.

### 1.3.3. Policies

Optional branch: the policy is "skip". A missing branch returns `"missing"`
and the same model. The lens never creates the branch and never throws. A
"create with default" policy is possible but the pilot does not need it.

Array element: the lens finds the element by `id` at edit time. It never
captures an index. A removed element returns `"missing"`. A replacement that
changes the `id` throws before `setModel` runs.

### 1.3.4. Law choice: reference, not structural

The set-current-value law uses reference identity: `set(m, get(m)) === m`.
This is stronger than structural equality. The reasons follow:

- TypeScript `FormVM` defaults to the structural `deepEquals`. The default
  short-circuit therefore hides a new but equal model.
- `FormVM` accepts a custom `equals` predicate. A reference predicate does not
  hide a new but equal model, and `setModel` then publishes.
- Under a reference law, an equal set returns the input model. No equality
  predicate then publishes it.

Get-after-set uses `toBe`, so it is also a reference check. Last-set-wins uses
structural equality. `set(set(m, a), b)` and `set(m, b)` are separate
allocations, so reference equality cannot hold.

### 1.3.5. Acceptance criteria and tests

| Criterion                                                             | Test (describe block)                                                                                       | Result |
| --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------ |
| Laws: get-after-set, set-current-value, last-set-wins                 | `lens laws (total lenses)`: 6 lenses × 3 laws × 5 sample models                                             | Pass   |
| Laws over optional lenses where the focus exists                      | `lens laws (optional lenses, …)`: 4 lenses                                                                  | Pass   |
| One `setModel` entry; one message per unequal set, zero per equal set | `one lens edit enters setModel once`: spy on `setModel`, count `"model"` messages                           | Pass   |
| Equal-value no-op under a reference predicate                         | same block: pilot lens publishes 0; a naive spread lens publishes 1                                         | Pass   |
| No bypass of validation, dirty state or the disposed guard            | same block                                                                                                  | Pass   |
| Missing optional branch                                               | `explicit partial-edit outcomes`: `meta` absent and `meta: {}`                                              | Pass   |
| Removed collection element                                            | same block: a path captured before removal returns `"missing"`                                              | Pass   |
| No resources; no mutation of the prior model                          | `lenses are pure values`: deep-frozen prior equals its `structuredClone`; own keys are only `get` and `set` | Pass   |
| Native baseline equals lens results                                   | `native spread baseline produces the same models`                                                           | Pass   |

The suite has 33 tests. Two mutation checks confirmed that the tests detect
faults:

- Removing the `Object.is` guard in `lens` failed 12 tests.
- An index-capturing element lens failed the removed-element test and the
  id-change test.

### 1.3.6. Pilot findings

- The lens laws hold over the pilot domain. One lens edit enters `setModel`
  once. The `FormVM` transaction stays unchanged.
- The lens adds little type safety in TypeScript. A spread literal in a typed
  position rejects an unknown key (TS2561 or TS2353) and a wrong value type
  (TS2322). A spread in an unannotated helper or local loses the unknown-key
  check. A `keyof` lens keeps it.
- The optional and element policies need three composition operators beyond
  `compose`. `optionalProp` also needs explicit type arguments.
- Native spread over a missing element id allocates a structurally equal copy.
  The default `deepEquals` hides it. A reference predicate publishes it.

## 1.4. Native-syntax comparison

### 1.4.1. Method

Each row is the client code at one call site. A shared regex tokenizer counts
tokens for every flavor. It counts identifiers, literals, multi-character
operators and single punctuation marks. Line counts use code formatted at about
100 columns.

Lens call sites exclude the path definitions. Section 1.4.3 counts the
definitions.

Verified `FormVM` APIs:

| Flavor     | Read                          | Replace                             |
| ---------- | ----------------------------- | ----------------------------------- |
| TypeScript | `form.model`                  | `form.setModel(model: TM): void`    |
| C#         | `form.Model`                  | `form.SetModel(TM model)`           |
| Python     | `form.model`                  | `form.set_model(model: TM) -> None` |
| Swift      | `form.model`                  | `form.setModel(_ newModel: Model)`  |
| Rust       | `form.model() -> M` (a clone) | `form.set_model(&self, model: M)`   |

### 1.4.2. Call-site cost (lines / tokens)

| Edit                                                     | TS spread | TS lens | C# `with` | Python `replace` | Swift `var` | Rust owned |
| -------------------------------------------------------- | --------- | ------- | --------- | ---------------- | ----------- | ---------- |
| A. Flat field (`title`)                                  | 1 / 16    | 1 / 16  | 1 / 15    | 1 / 15           | 3 / 17      | 1 / 19     |
| B. Nested optional (`meta.reminder.at`, skip if missing) | 4 / 51    | 1 / 18  | 3 / 46    | 3 / 55           | 3 / 21      | 5 / 53     |
| C. Array element by id (`checklist[id].done`)            | 5 / 50    | 1 / 21  | 5 / 48    | 4 / 42           | 5 / 45      | 5 / 51     |

The snippets follow. Each snippet is a separate call site, so the snippets do
not share a scope.

```ts
// A
form.setModel({ ...form.model, title: x });
form.setModel(titleL.set(form.model, x));
// B
const m = form.model;
if (m.meta?.reminder) {
  form.setModel({ ...m, meta: { ...m.meta, reminder: { ...m.meta.reminder, at: x } } });
}
form.setModel(reminderAtO.set(form.model, x).model);
// C
const m = form.model;
form.setModel({
  ...m,
  checklist: m.checklist.map((i) => (i.id === id ? { ...i, done: true } : i)),
});
form.setModel(itemDoneO(id).set(form.model, true).model);
```

```csharp
// A
form.SetModel(form.Model with { Title = x });
// B
var m = form.Model;
if (m.Meta?.Reminder is { } r)
    form.SetModel(m with { Meta = m.Meta with { Reminder = r with { At = x } } });
// C
var m = form.Model;
form.SetModel(m with
{
    Checklist = m.Checklist.Select(i => i.Id == id ? i with { Done = true } : i).ToArray(),
});
```

```python
# A
form.set_model(replace(form.model, title=x))
# B
m = form.model
if m.meta is not None and m.meta.reminder is not None:
    form.set_model(replace(m, meta=replace(m.meta, reminder=replace(m.meta.reminder, at=x))))
# C
m = form.model
form.set_model(
    replace(m, checklist=tuple(replace(i, done=True) if i.id == id else i for i in m.checklist))
)
```

```swift
// A
var m = form.model
m.title = x
form.setModel(m)
// B: optional-chaining assignment is a no-op when a branch is nil
var m = form.model
m.meta?.reminder?.at = x
form.setModel(m)
// C
var m = form.model
if let k = m.checklist.firstIndex(where: { $0.id == id }) {
    m.checklist[k].done = true
    form.setModel(m)
}
```

```rust
form.set_model(Draft { title: x, ..form.model() });
let mut m = form.model();
if let Some(r) = m.meta.as_mut().and_then(|t| t.reminder.as_mut()) {
    r.at = x;
    form.set_model(m);
}
let mut m = form.model();
if let Some(i) = m.checklist.iter_mut().find(|i| i.id == id) {
    i.done = true;
    form.set_model(m);
}
```

### 1.4.3. Reusable path across call sites (TypeScript)

The scenario reuses the `meta.reminder` prefix for two leaves, `at` and
`note`.

| Approach                                  | Definition (lines / tokens) | Each call site (tokens) | One-time library cost    |
| ----------------------------------------- | --------------------------- | ----------------------- | ------------------------ |
| Native: one helper per leaf               | 4 / 100                     | 14                      | none                     |
| Native: one prefix helper with an updater | 2 / 54                      | 27                      | none                     |
| Lens: shared prefix plus two leaves       | 6 / 63                      | 18                      | 115 lines / 1,188 tokens |

A plain function already gives native code a reusable path. The lens saves
37 definition tokens against per-leaf helpers. The lens costs 9 definition
tokens more than the prefix helper. A shipped kernel would cost 1,188 tokens in
each of five flavors.

### 1.4.4. Comparison summary

- Flat edits: the lens saves nothing in any flavor.
- Nested optional and element edits: the TypeScript lens call site is 18 to 21
  tokens against 50 to 51 tokens of spread. A per-leaf native helper reduces
  the spread call site to 14 tokens.
- Swift value mutation is already within 3 tokens of the lens call site for
  the nested optional edit. Optional-chaining assignment skips a nil branch.
- Type safety: the lens adds one static check. It rejects an unknown key where
  a TypeScript spread is not a typed literal. An annotated helper return type
  gives the same check. C#, Swift and Rust check field names at compile time.
  Python checks them with mypy.
- The lens adds two behaviors that native code does not give by default: an
  explicit `"missing"` outcome and reference preservation on an equal set.
  Each costs one `if` or one `===` check in native code.

## 1.5. Per-flavor results

No flavor code changed. "Unaffected" means native syntax covers the use case
without a library helper.

| Flavor     | Result                           | Native idiom                                              | Equality note                                                                                                                                                                                                     |
| ---------- | -------------------------------- | --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TypeScript | Unaffected. Pilot only.          | Object spread and `Array.map`                             | Default `deepEquals` is structural. A custom reference `equals` publishes on a new but equal model.                                                                                                               |
| C#         | Unaffected                       | `record` `with`, LINQ `Select`                            | `SetModel` uses `object.Equals`. Records compare collection members by reference. `Select(...).ToArray()` over a missing id publishes. The notes example overrides `Equals` with `SequenceEqual` for this reason. |
| Python     | Unaffected                       | `dataclasses.replace`, tuple comprehension                | `set_model` uses `==`. Frozen dataclasses with tuple fields compare structurally.                                                                                                                                 |
| Swift      | Unaffected; strongest native fit | `var` copy plus property and optional-chaining assignment | `FormVM where Model: Equatable` defaults to `==`. Synthesized `Equatable` is structural. The notes example uses `let` fields and a `with(...)` helper.                                                            |
| Rust       | Unaffected                       | `let mut m = form.model()`, `as_mut`, `iter_mut().find`   | `PartialEq` is structural. `model()` returns an owned clone, so in-place mutation is safe.                                                                                                                        |

## 1.6. Recommendation

Reject a public lens abstraction for `FormVM`.

The reasons follow:

1. The pilot shows no type-safety gain that an annotated native helper does
   not also give.
1. Flat edits, the only edits in the shipped notes example, save nothing.
1. Nested and element savings come from reuse. A plain native helper
   gives the same reuse without a library type.
1. A shipped kernel costs about 115 lines per flavor. It also needs three
   policy types and cross-flavor parity tests in five flavors.
1. ADR-0040 rejected `IProperty<T>` because each flavor's idioms already
   cover the use case. The pilot finds the same pattern for lenses.

Instead, a later documentation change can add a short `FormVM` recipe. The
recipe can show these points:

- Read `model`, build the next value with the native idiom, and call
  `setModel` once.
- An equal model is a no-op only under the configured equality. A reference
  predicate needs the caller to keep the original reference on an equal edit.
- C# records compare collection members by reference. Override `Equals` or
  use a structural comparer for collection fields.
- Edit array elements by identity, not by a stored index.
- In TypeScript, annotate the return type of an update helper. The compiler
  then rejects an unknown key.

This record does not add that recipe. The owner decides its scope.

## 1.7. What would change the decision

Reopen this record if consumer evidence shows one of these conditions:

- Several applications reuse the same deep optional paths at many call sites.
  Plain helpers then become duplicated policy code.
- A schema-descriptor feature (#382) or a field-state feature (#380) needs a
  first-class path value. A lens could then be the shared path type.
- An undo feature (#384) needs a typed path to record a domain inverse. The
  lens itself must still generate no history.

## 1.8. Commands and results

| Command (from `langs/typescript`)                            | Result                                                     |
| ------------------------------------------------------------ | ---------------------------------------------------------- |
| `npm ci`                                                     | Installed. Warnings only about unapproved install scripts. |
| `npx vitest run tests/unit/forms/formModelLensPilot.test.ts` | 1 file, 33 tests passed                                    |
| `npm run typecheck:tests`                                    | No errors                                                  |
| `npm run lint`                                               | No errors                                                  |
| `npx vitest run`                                             | 117 files, 1,355 tests passed                              |
| Mutation: remove the `Object.is` guard in `lens`             | 12 tests failed                                            |
| Mutation: capture the element index                          | 2 tests failed                                             |

Native-idiom checks outside the repository, in a scratch directory:

| Check                                                                         | Result                                                                         |
| ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Python `dataclasses.replace` snippets against the worktree `vmx.forms.FormVM` | 3 model messages for 3 edits; 0 for a missing id                               |
| C# `dotnet run eq.cs` on plain records                                        | Equal `with`: `True`. Missing id via `Select().ToArray()`: `False` (not equal) |
| `swiftc` snippet with a stand-in form                                         | Compiles. Nil branch: no publish; optional assignment reports `false`          |
| `cargo run` snippet with a stand-in form                                      | Compiles. 3 publishes for 3 edits                                              |
| `tsc --strict` on spread with a misspelled and a mistyped key                 | TS2561 and TS2322                                                              |

The Swift and Rust checks use a stand-in form with the same equality
short-circuit. They confirm syntax and equality semantics, not the VMx API.
Section 1.4.1 cites the VMx API signatures from the flavor sources.
