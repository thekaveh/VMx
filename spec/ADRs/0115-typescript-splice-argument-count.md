# ADR 0115 — Preserve TypeScript splice argument-count semantics

**Status:** Accepted (2026-07-15)
**Spec version:** clarified in 3.22.0
**Clarifies:** [ADR-0024](0024-hub-aware-observable-collection.md)

## 1. Context

TypeScript retains `splice` as a source-compatible array convenience on
`ServicedObservableCollection`. Native JavaScript distinguishes an omitted
`deleteCount` from a second argument whose value is `undefined`: omission
removes through the end, while explicit `undefined` converts to zero.

The unkeyed implementation used nullish fallback for `deleteCount`, conflating
those two calls. Explicit `undefined` therefore removed the tail and could also
replace it when the caller intended insertion-only behavior. The keyed serviced
collection already used argument count and preserved the native distinction.

## 2. Decision

- `ServicedObservableCollection.splice` selects omitted-delete behavior from
  the number of supplied arguments, not from the `deleteCount` value.
- An omitted `deleteCount` removes from the normalized start through the end.
- Explicit `undefined` supplies a delete count of zero; following items are
  inserted without removals.
- Existing notification rules apply to the effective mutation: no work emits
  nothing, while insertion-only and bulk operations emit Reset.

This repairs the established native-compatible TypeScript convenience. It adds
no conformance ID and does not change package or specification versions.

## 3. Consequences

- Unkeyed and keyed TypeScript serviced collections agree on splice argument
  admission.
- Callers can express insertion-only splice using explicit `undefined` without
  losing the collection tail.
- Calls that omit `deleteCount` retain their established remove-through-end
  behavior.

## 4. Rejected alternatives

- Continue using nullish fallback: it cannot observe whether the argument was
  omitted and contradicts native JavaScript semantics.
- Remove the `splice` convenience: that would break the source-compatible
  TypeScript surface preserved by ADR-0009.
- Treat explicit `undefined` as an error: the public optional parameter permits
  it and native splice defines the behavior precisely.
