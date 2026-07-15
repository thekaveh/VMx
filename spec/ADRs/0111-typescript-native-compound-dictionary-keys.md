# ADR 0111 — Preserve TypeScript compound dictionary key identity

**Status:** Accepted (2026-07-15)
**Spec version:** clarified in 3.22.0
**Supersedes:** the TypeScript serialized-string implementation detail in
[ADR-0038](0038-spec-accuracy-corrections-and-form-014.md) and
[ADR-0060 §2.4(b)](0060-swift-collections-divergences.md)

## 1. Context

`ObservableDictionary<TKey1, TKey2, TValue>` promises a dictionary keyed by an
ordered pair. TypeScript encoded the pair by applying `String()` to each key
and length-prefixing the first result. The prefix prevented separator-boundary
collisions, but string coercion still collapsed distinct keys:

- `1` and `"1"` produced the same token;
- separate object instances both commonly produced `"[object Object]"`;
- distinct symbols with the same description produced the same text.

The key-axis reference-count maps retained JavaScript `Map` identity while the
entry store did not. A colliding insert could therefore replace an unrelated
entry without updating the corresponding key-axis views. This contradicted the
existing COL-010 insert/retrieve contract and ADR-0060's stated guarantee that
distinct key tuples remain distinct.

## 2. Decision

- TypeScript stores entries in nested native maps:
  `Map<TKey1, Map<TKey2, StoredEntry>>`.
- Each axis therefore uses normal JavaScript `Map` equality: SameValueZero for
  primitives and reference identity for objects and symbols.
- A separate ordered list retains entry identity and preserves insertion-order
  enumeration. Replacement updates the existing ordered entry; deletion removes
  that exact entry.
- Distinct-key observable views continue to use native maps for reference
  counts. Axis removal performs the same SameValueZero comparison, including
  `NaN`, so membership and bookkeeping share one equality model.
- C#, Python, Swift, and Rust retain their existing host-standard key equality.

No new conformance ID or version bump is required. This repairs TypeScript's
implementation of COL-010 rather than introducing a new dictionary operation or
observable behavior.

## 3. Consequences

- Primitive keys with different types no longer alias.
- Object and symbol keys follow standard JavaScript identity semantics.
- `NaN` can be retrieved and removed without leaving a stale key-axis entry.
- Separator characters and string formatting are irrelevant to compound-key
  correctness.
- Lookup remains expected O(1); insertion-order deletion remains O(n), matching
  the previous ordered-token removal.

## 4. Rejected alternatives

- Add type tags to serialized strings: object and symbol identities still need
  a separate registry and lifetime policy.
- Serialize objects structurally: changes standard `Map` identity semantics,
  fails on cycles, and makes mutation after insertion ambiguous.
- Store arrays as keys in one map: a new array at lookup time has a different
  identity, so callers could not retrieve an existing pair.
