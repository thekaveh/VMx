# ADR 0152 — Compare TypeScript `DOMException` form values by name and message

- **Status:** Accepted
- **Date:** 2026-10-25
- **Spec version:** 3.30.0 (clarification)
- **Clarifies:** [ADR-0135](0135-typescript-error-structural-equality.md)

## 1. Context

ADR-0135 compares TypeScript `Error` form values by what structured cloning
keeps: the cloneable kind named by `name`, the own `message` data property, and
the own `cause`. A `DOMException` is an `instanceof Error`, so it took that
rule (#734). Its `name`, such as `AbortError`, is not a standard error kind, so
it mapped to `Error`. Its `message` is a prototype accessor, so it compared as
absent. Any two `DOMException` values compared equal, and `setModel` dropped an
edit that replaced one with a different one.

HTML structured serialization handles a `DOMException` as a serializable
platform object, not as an error. The clone is a `DOMException` with the same
`name` and `message`. Its `cause`, custom own properties, and subclass identity
are dropped. Node 22 and later behave this way. Node 20's `structuredClone`
returns a plain empty object for a `DOMException`.

## 2. Decision

- TypeScript's default `deepEquals` treats a value as a `DOMException` when it
  is an `instanceof DOMException` and the `DOMException.prototype` `name` and
  `message` accessors read it without throwing.
- Two `DOMException` values are equal when their `name` and `message` match. A
  `DOMException` never equals another error, because its clone keeps the
  `DOMException` type.
- The `cause`, custom properties, the stack, and subclass identity are not
  compared, because the clone drops them. Unlike a plain error's `cause`
  (ADR-0135), a `DOMException`'s `cause` is not kept. A subclass's overriding
  accessors are not used; the clone reads the internal values.
- A value that only inherits `DOMException.prototype` fails the accessor check
  and takes the ADR-0135 error rule. A throwing inherited `name` reads as no
  kind, so the comparator does not throw.

This repairs the existing FORM-003 structural-equality contract. It adds no
conformance ID and does not change package or specification versions; the
TypeScript change ships in the unreleased source line.

## 3. Consequences

- An edit that changes a `DOMException`'s `name` or `message` replaces the live
  form model and makes it dirty. Equal values stay clean and suppressed.
- On Node 22 and later, a model holding a `DOMException` starts clean against
  its default snapshot. On Node 20 the snapshot is a plain object, so such a
  model starts dirty unless it injects a `snapshotter` and `equals`, as it did
  before this decision.
- C#, Python, Swift, and Rust are unchanged: their dirty tracking uses the
  model's own equality (chapter 20 §4).

## 4. Rejected alternatives

- Add the `DOMException` names to the cloneable error kinds: the set of names
  is open, and a plain `Error` with the same name clones as an `Error`, not as
  a `DOMException`.
- Read `message` through the accessor for every error: a plain error's
  inherited `message` is not cloned, so this would break ADR-0135.
