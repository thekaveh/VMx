# ADR 0253 — Compare TypeScript `Blob`, `File`, and `CryptoKey` form values by the state their clone keeps

- **Status:** Accepted
- **Date:** 2026-11-24
- **Spec version:** 3.30.0 (clarification of chapter 20 §4 and the `FORM-003` note; no conformance ID). The spec version does not move.
- **Related:** [ADR-0113](0113-typescript-binary-structural-equality.md), [ADR-0152](0152-typescript-domexception-structural-equality.md), #1913.

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
  `size` and `type`. A `File` also compares its `name` and `lastModified`. A
  `CryptoKey` compares its `type`, its `extractable` flag, its `algorithm`, and
  its `usages`, the last two by `deepEquals`.
- **Kind.** A value of one of these kinds is never equal to a value of another
  kind. A `Blob` is never equal to a `File`, and none of them is equal to a plain
  object.
- **Accessors.** The state is read through the base prototype accessors, as the
  clone reads it. A value whose accessor throws, such as a value that only
  inherits the prototype, is not equal to any other value, and the comparator
  does not throw.
- **Not compared.** The bytes of a `Blob` and the key material of a `CryptoKey`
  are not compared.
- **Out of scope.** `FileList`, `ImageData`, and `ImageBitmap` are not handled.
  They keep the plain-object fallback, and a consumer injects `equals` for them.
  Their tests would need a browser-like environment, and the Node test suite has
  none of these globals.

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

## 3. Consequences

- An edit that replaces one of these values with a value that differs in the
  compared state commits, sets `isDirty`, and publishes one model change. An
  edit whose value has the same state is suppressed, as before.
- **Residual equal case.** Two values of one kind with the same compared state
  and different bytes or key material are equal, so a replacement that differs
  only there is dropped. Examples are two `Blob` values of the same size and type
  with different contents, two `File` values with the same name, size, type, and
  `lastModified` with different contents, and two keys with the same type,
  extractability, algorithm, and usages with different key material. The unit
  tests pin this limit. A domain that needs more keeps a comparable identifier,
  such as a content digest computed when the value is set, in the model and
  injects `equals` on it.
- **Clean start.** A form whose initial model holds these values starts clean
  against its default snapshot wherever the runtime's `structuredClone` keeps
  the type. Node 26 keeps it, and the unit tests check it there. Tests are
  skipped where the probe fails. This environment has only Node 26, so Node 20,
  the package floor, is not checked. As ADR-0152 §3 records for `DOMException`,
  on a runtime whose clone drops the type, a model holding such a value compares
  a kind against a non-matching snapshot and starts dirty unless it injects
  `snapshotter` and `equals`.
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
  tests.** Rejected for this change. Node has none of these globals, so the
  suite would need a new environment. Consumers inject `equals` for them.
