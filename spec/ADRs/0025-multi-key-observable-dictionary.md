# ADR 0025 — `ObservableDictionary` (multi-key observable dictionary)

**Status:** Accepted (2026-05-27)
**Spec version:** introduced in 2.1.0

## 1. Context

The 2012 VMx predecessor included a `Dictionary<TKey1, TKey2, TValue>` (in
`Collections/`) that supported two independent key axes — for example, a
two-dimensional data model keyed by (category, identifier). It also provided
observable views of each key axis (`Keys1`, `Keys2`) so that consumers could
bind list views to distinct key sets without walking the full dictionary.

The current VMx has no equivalent. Consumers needing multi-key lookup with
observable change events build ad hoc structures, losing the per-key observable
views and the normalized change notifications.

ADR-0024 introduced `ServicedObservableCollection<T>`. This ADR is its sibling
for the dictionary case.

## 2. Options considered

1. **Skip — remain consumer-owned.** Consumers implement their own multi-key
   structures.
1. **`ObservableDictionary<TKey1, TKey2, TValue>` only.** Exposes the two-key
   case as the single concrete type. Three-key case requires a new type.
1. **Base `ObservableDictionary<TKey, TValue>` plus thin two-key and three-key
   wrappers.** The base type uses a per-flavor tuple as the key (e.g.,
   `(TKey1, TKey2)` in C#/Python, a keyed-tuple in TypeScript). Thin typed
   wrappers expose `Key1`/`Key2` accessors. The two-key wrapper is the
   documented common case; a three-key wrapper is provided for completeness.
1. **Generic `ObservableDictionary<TKey, TValue>` only (no multi-key).** Adds
   observable change events but drops the per-key observable views.

## 3. Decision

Option 3. `ObservableDictionary<TKey1, TKey2, TValue>` is the documented common
case. It is implemented as a thin wrapper over a base
`ObservableDictionary<TKey, TValue>` where `TKey` is the per-flavor compound key
(`ValueTuple` in C#, `tuple` in Python, `readonly` object literal in TypeScript).
A corresponding three-key wrapper may be provided by flavors but is not required
by the spec.

Key rules:

1. **Distinct-key observable views.** `Keys1` and `Keys2` each expose an
   `ObservableList<TKeyN>` (per ADR-0026) that stays in sync with mutations.
   Consumers can bind to `Keys1` or `Keys2` independently.
1. **No cascading insertion.** Unlike the 2012 predecessor, adding a value for
   a new Key1 does NOT automatically create entries for missing Key2 slots.
   Consumers insert explicitly with both key parts.
1. **Change notifications.** Every mutation (insert, remove, replace, clear)
   raises a `CollectionChangedMessage`-style notification. If a hub is provided
   (per ADR-0024 pattern), the notification is also published to the hub.
1. **Null keys.** Null keys are not permitted (matches the standard dictionary
   convention). A null-key insert raises `ArgumentNullException` /
   `TypeError` / `Error` per flavor idiom.

## 4. Consequences

- `spec/21-collections.md` §4 defines `ObservableDictionary` shape and key
  rules, including the optional `hub` constructor parameter in §4.1.
- Conformance IDs `COL-010..COL-015` cover: insert, remove, replace,
  distinct-key observable views, enumeration order, and clear.
  `COL-022` covers hub injection: when a hub is provided, every mutation
  publishes a `CollectionChangedMessage` to the hub after the local event
  fires; with no hub, mutations succeed silently (null-hub fallback, mirroring
  ADR-0024 pattern).
- The cascading-insertion pattern from the 2012 predecessor is explicitly
  rejected. Any consumer needing that behavior must implement it in their
  domain layer.
- Per-flavor placement: C# `VMx.Collections/`, Python `vmx.collections`,
  TypeScript `vmx/collections`.
- `ObservableList<TKey>` (per ADR-0026) is the type of each key-axis view,
  ensuring consumers get granular add/remove events on the key sets.
- Enumeration order is insertion order (matches `LinkedHashMap`/`OrderedDict`
  semantics). Flavors that cannot guarantee insertion order MUST document the
  deviation in `spec/ADRs/0009-cross-flavor-divergence-catalogue.md`.

## 5. Amendments

- **ADR-0038** (2026-06-11, spec v2.5.0) corrected the §3 implementation
  description: no base `ObservableDictionary<TKey, TValue>` type exists in any
  flavor (the multi-key dictionary is implemented directly, not as a thin
  wrapper over a base type), and TypeScript's internal compound key is a
  serialized string, not a `readonly` object literal. The §3 decision text is
  retained as the original record; see ADR-0038 for the corrected wording.
- **ADR-0111** (2026-07-15, clarified in spec v3.22.0) supersedes the
  serialized-string implementation detail for TypeScript. Nested native `Map`
  storage preserves standard key equality without coercing types or object
  identities.
