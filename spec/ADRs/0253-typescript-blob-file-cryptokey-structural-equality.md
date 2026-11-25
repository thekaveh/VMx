# ADR 0253 — Compare TypeScript `Blob`, `File`, and `CryptoKey` form values by the state their clone keeps

- **Status:** Accepted
- **Date:** 2026-11-24
- **Spec version:** 3.30.0 (clarification of chapter 20 §4 and the `FORM-003` note; no conformance ID). The spec version does not move.
- **Clarifies:** [ADR-0113](0113-typescript-binary-structural-equality.md), [ADR-0152](0152-typescript-domexception-structural-equality.md). Issue #1913.

## 1. Context

TypeScript `FormVM` compares its model with its snapshot through `deepEquals`
(`langs/typescript/src/forms/structuralEquality.ts`). The default snapshotter is
`structuredClone`. A `Blob`, a `File`, and a `CryptoKey` have no own enumerable
keys, and `deepEquals` had no branch for them, so its plain-object fallback
compared any two of them as equal. `setModel` returns before the commit when the
equality reports no change, so a replacement was dropped: the model kept the old
value, `isDirty` stayed false, and no model change was published.

A probe on Node 26.12.1, run against the develop build before this change,
showed the drop for each type:

- a `Blob` replaced by a `Blob` of another size and type kept the old value,
  with `isDirty` false;
- a `File` replaced by a `File` of another name, size, type, and `lastModified`
  did the same;
- a `CryptoKey` replaced by a key of another algorithm did the same.

ADR-0113 closed the empty-key gap for `ArrayBuffer` and `DataView`, and ADR-0152
closed it for `DOMException`. Chapter 20 §4 requires the default equality to
compare to the depth the snapshotter clones. These three types are not covered.

## 2. Decision

- **Kinds.** `deepEquals` recognizes a `File`, a `Blob`, and a `CryptoKey` by
  `instanceof`. Each global is guarded with `typeof`, as the `DOMException`
  branch is guarded, so the code runs where a global is absent. `File` is tested
  before `Blob`, because a `File` is a `Blob`.
- **Compared state.** The state is what the clone keeps. A `Blob` compares its
  `size` and `type`. A `File` also compares its `name` and `lastModified` when
  it is compared with a `File`. Against a `Blob` it compares size and type only
  (§2.1). A `CryptoKey` compares its `type`, its `extractable` flag, its
  `algorithm`, and its `usages`, the last two by `deepEquals`.
- **Kind.** A value of one of these kinds is never equal to a value of another
  kind, with one exception: a `File` against a `Blob`, which compares by size and
  type (§2.1). None of them is equal to a plain object.
- **Accessors.** The state is read through the base prototype accessors, as the
  clone reads it. A value whose accessor throws, such as a value that only
  inherits the prototype, is not equal to any other value, and the comparator
  does not throw.
- **Not compared.** The bytes of a `Blob` and the key material of a `CryptoKey`
  are not compared.
- **Out of scope.** `FileList`, `ImageData`, and `ImageBitmap` are not handled.
  They keep the plain-object fallback, so a form that holds one of them should
  inject `equals`. Whether that fallback compares two of them as equal, and
  whether a browser's `structuredClone` keeps each one, is not checked here.
  Their tests would need a browser-like environment, and the Node test suite has
  none of these globals. This choice (option A of the issue) is recorded for the
  owner's confirmation. It is not an owner decision that has already been made.

### 2.1 Why the state, and not identity or a host equality

The orchestrator's first option was identity, with a host equality where one
exists. Neither rule can compare these values correctly, for these reasons:

- **Identity is rejected.** The snapshot is a structured clone, a new object, so
  the snapshot's `Blob` is never the model's `Blob`. The probe showed that with
  identity equality a fresh `FormVM` whose initial model holds a `File` reports
  `isDirty` true before any edit. Identity would dirty every form that holds one
  of these values.
- **A host equality does not exist.** `Blob`, `File`, and `CryptoKey` define no
  `equals` method. Their bytes and key material are read asynchronously
  (`Blob.arrayBuffer()`, `crypto.subtle.exportKey`), and a non-extractable key
  cannot be exported at all, so a synchronous default cannot compare them.
- **The state a clone keeps is chosen.** It is the simplest rule that keeps a
  fresh form clean and that matches chapter 20 §4, which compares to the depth
  the snapshotter clones.
- **A `File` in the model against a `Blob` (File to Blob).** On a runtime whose
  clone degrades a `File` (Node 20.5 and 22), the default snapshot of a `File` is
  a `Blob` that keeps the size and type and drops the name and `lastModified`.
  A form holding a `File` therefore compares it with that `Blob` at construction
  and after each approve. This is the degraded-clone case. A user's replacement
  of a `File` by a `Blob` is compared the same way on every runtime. In both
  cases a `File` against a `Blob` compares by size and type only, so the two are
  equal when those match, and a replacement that differs only in name or
  `lastModified` is not seen as a change to the dirty state.
- **A `Blob` in the model against a `File` (Blob to File).** A user's
  replacement of a `Blob` by a `File` is compared the same way on every runtime,
  so the two are equal when size and type match, and the replacement is not
  committed (§3).

The rule does not depend on the runtime, because the comparator cannot tell a
degraded `Blob` snapshot from a `Blob` that a user put in the model. The probes
in the PR body show which runtimes degrade a `File`: Node 20.5.0 and 22.23.5
clone it as a `Blob`, and Node 24.22.3 and 26.12.1 keep it.

## 3. Consequences

- An edit that replaces one of these values with a value that differs in the
  compared state commits, sets `isDirty`, and publishes one model change. An
  edit whose value has the same state is suppressed, as before. A `File` replaced
  by a `Blob` of the same size and type is suppressed on every runtime, as develop
  suppresses it (§2.1). Without the §2.1 rule, that replacement would commit on
  every runtime, so the suppression is a behavior change from the earlier
  revision of this fix; develop already suppresses it.
- **Residual: a degraded `File` (Node 20.5 and 22).** On a runtime whose clone
  degrades a `File`, the snapshot keeps neither the name nor `lastModified`. A
  replacement that differs only in name or `lastModified` is committed: the model
  takes the new `File`, and one model change is published. `isDirty` stays false,
  because a `File` against a `Blob` compares size and type only. Develop drops
  such a replacement entirely, so the model keeps the old `File` and no change is
  published. In this File-to-Blob direction the gap is therefore a missed dirty
  state, not a dropped model change. The replacement of a `File` by a `Blob` of
  the same size and type is still dropped, as the first bullet records. The unit
  test that builds a `Blob` snapshot pins this limit, and it runs on every
  runtime.
- **Residual: a `Blob` replaced by a `File` (every runtime).** A `File` of the
  same size and type as the model's `Blob` is equal to it, so `setModel` drops
  the replacement. The model keeps the `Blob`, no model change is published, and
  `isDirty` is unchanged, which is false for a clean form, even though the
  `File`'s name or `lastModified` differs. This is a dropped model change, not
  only an undetected dirty state, and it happens on every runtime. Develop also
  drops it, since its plain-object fallback equates any two of these values, so
  relative to develop nothing changes. The earlier revision of this fix committed
  it on every runtime, so this is a behavior change from that revision. The unit
  test named `documented residual (ADR-0253 §3)` pins it.
- **Residual equal case.** Two values of one kind with the same compared state
  and different bytes or key material are equal, so a replacement that differs
  only there is dropped. Examples are two `Blob` values of the same size and type
  with different contents, two `File` values with the same name, size, type, and
  `lastModified` with different contents, and two keys with the same type,
  extractability, algorithm, and usages with different key material. The unit
  tests pin this limit. A domain that needs more keeps a comparable identifier,
  such as a content digest computed when the value is set, in the model and
  injects `equals` on it.
- **Clean start.** A form whose initial model holds a `Blob`, a `File`, or a
  `CryptoKey` starts clean against its default snapshot wherever the runtime's
  `structuredClone` keeps the value's kind. A `File` that the clone degrades to a
  `Blob` also starts clean (§2.1). The `Blob` and `File` clean-start test runs on
  every runtime. The `CryptoKey` clean-start test is skipped where the probe finds
  that the clone does not keep a `CryptoKey`. On a runtime whose clone does not
  keep a `CryptoKey`, the form needs an injected `snapshotter` and `equals`, as
  ADR-0152 §3 records for `DOMException`.
- **Runtime probes.** A one-line `structuredClone` probe, run with
  `npx node@VERSION`, shows that Node 20.5.0 and 22.23.5 clone a `File` as a
  `Blob` (no name or `lastModified`) and keep a `CryptoKey` (type, `extractable`,
  algorithm, and usages). Node 24.22.3 and 26.12.1 keep both kinds. The probe
  results are cited in the PR body. The degraded `File` path is still covered by
  unit tests that build the `Blob` snapshot directly, on every runtime. Those
  tests simulate the clone, and the probe is what reproduces it.
- **C#.** `FormVM` compares with `Equals(model, snapshot)`
  (`langs/csharp/src/VMx/Forms/FormVM.cs`, near line 180), which is the model's
  own equality. C# therefore has no structured-clone gap of this kind. C#,
  Python, Swift, and Rust are otherwise unchanged, since their dirty tracking
  uses the model's own equality (chapter 20 §4).
- This repairs the existing FORM-003 contract. It adds no conformance ID and
  does not change the spec or package versions. The change ships in the
  unreleased TypeScript 3.31.0 source line.

## 4. Rejected alternatives

- **Identity equality for these values.** Rejected: a fresh form would start
  dirty, as §2.1 shows.
- **Byte and key-material comparison inside the default equality.** Rejected:
  reading bytes and exporting keys is asynchronous, and the default equality is
  synchronous.
- **A snapshotter that keeps references to the originals.** Rejected: it changes
  the snapshot semantics of every model, which is out of scope.
- **Branches for `FileList`, `ImageData`, and `ImageBitmap`, with browser-like
  tests.** Rejected for this change. This is option A of the issue. It is
  recorded for the owner's confirmation and is not an owner decision that has
  already been made. Node has none of these globals, so the suite would need a
  new environment. Consumers inject `equals` for them.
