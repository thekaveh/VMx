# ADR 0113 — Compare TypeScript binary form values by constructor and bytes

**Status:** Accepted (2026-07-15)
**Spec version:** clarified in 3.22.0
**Clarifies:** [ADR-0048](0048-v3-form-vm-semantics.md)

## 1. Context

ADR-0048 pairs TypeScript's default `structuredClone` form snapshot with a
structural deep-equal. The comparator handled dates, regular expressions,
collections, arrays, and plain objects, but did not recognize binary values.
Distinct `ArrayBuffer` and `DataView` instances have no enumerable string keys,
so they compared equal regardless of their bytes. Typed-array elements were
enumerable, but different view constructors with the same indexed values also
compared equal.

That mismatch could suppress `FormVM.setModel`, validation, dirty state, and
model publication for a genuine binary edit even though `structuredClone`
faithfully preserved the binary value in the snapshot.

## 2. Decision

- TypeScript's default `deepEquals` compares `ArrayBuffer` and
  `SharedArrayBuffer` values only when their concrete constructors, byte lengths,
  and complete byte sequences match.
- It compares `DataView` and typed-array views only when their concrete view
  constructors, viewed byte lengths, and viewed byte sequences match.
- View offsets and unviewed bytes are not part of the value. The compared value
  is the view's constructor plus its visible byte span.
- Binary values never fall through to plain-object enumerable-key comparison.
- Custom `equals` predicates remain the escape hatch for domain-specific or
  reference-identity semantics.

This repairs the existing FORM-003 structural-equality contract. It adds no
conformance ID and does not change package or specification versions.

## 3. Consequences

- A changed buffer or data view now replaces the live form model and makes it
  dirty relative to an unequal snapshot.
- Separately allocated binary values with the same constructor and bytes remain
  clean and equality-suppressed.
- Equal bytes in different typed-array constructors are unequal, preserving the
  model's binary interpretation rather than only its storage.

## 4. Rejected alternatives

- Compare binary objects by reference: a `structuredClone` snapshot always has a
  different buffer identity, so a freshly constructed form would begin dirty.
- Compare only enumerable keys: buffers and data views expose none, and typed
  arrays lose their constructor semantics.
- Compare an entire backing buffer for views: bytes outside a view are not part
  of that view's value and may be intentionally hidden.
