# ADR 0135 — Compare TypeScript `Error` form values by what structured cloning keeps

- **Status:** Accepted
- **Date:** 2026-10-01
- **Spec version:** 3.24.0 (clarification)
- **Clarifies:** [ADR-0048](0048-v3-form-vm-semantics.md),
  [ADR-0113](0113-typescript-binary-structural-equality.md)

## 1. Context

ADR-0048 pairs TypeScript's default `structuredClone` form snapshot with a
structural deep-equal that compares "to the same depth the snapshotter clones".
`Error` values fell through to the plain-object branch, which compares own
enumerable string keys. An error's `message` and `cause` are non-enumerable, so
two errors with different messages compared equal (#353). The same branch also
made some models dirty against their own snapshot: structured cloning drops a
custom subclass's prototype and its own properties, so a model holding a
`ValidationError` with an enumerable `code` started dirty.

HTML structured serialization keeps exactly these parts of an error:

- the kind, rebuilt from the error's `name`. `Error`, `EvalError`, `RangeError`,
  `ReferenceError`, `SyntaxError`, `TypeError`, and `URIError` keep their kind;
  any other name, such as a custom subclass or `AggregateError`, comes back as a
  plain `Error`;
- the own `message`, as a string, when it is a data property;
- the own `cause`, cloned, when it is a data property. Engines that implement
  `cause` keep cycles through it.

The stack is copied as an implementation detail, and custom properties, the
`errors` of an `AggregateError`, and subclass identity are dropped.

## 2. Decision

- TypeScript's default `deepEquals` treats a value as an error when it is an
  `instanceof Error`. An error never equals a non-error.
- Two errors are equal when their cloneable kinds match, their own `message`
  data properties match after string conversion (absent stays distinct from
  `""`), and their own `cause` data properties are both absent or deep-equal.
  Inherited and accessor `message` or `cause` values are not cloned, so they
  compare as absent.
- The stack, custom properties, and subclass identity are not compared. They
  are environment-specific or not kept by the clone, and comparing them would
  make a model dirty against its own snapshot.
- Causes compare recursively under the existing visited-pair guard, so
  self-referencing and mutually referencing causes terminate. A message that
  cannot be converted by cloning, such as a `Symbol`, does not make the
  comparator throw.
- Domains that need subclass identity, custom properties, or stacks inject a
  matching `snapshotter` and `equals`.

This repairs the existing FORM-003 structural-equality contract. It adds no
conformance ID and does not change package or specification versions; the
TypeScript change ships in the unreleased 3.25.0 source line.

## 3. Consequences

- An edit that changes an error's kind, message, or cause replaces the live
  form model and makes it dirty. Equal errors stay clean and suppressed.
- A model holding any cloneable error, including a custom subclass, an
  `AggregateError`, or a self-caused error, starts clean against its snapshot.
- C#, Python, Swift, and Rust are unchanged: their dirty tracking uses the
  model's own equality (chapter 20 §4).

## 4. Rejected alternatives

- Compare errors by reference: every snapshot is a new error, so a freshly
  constructed form would begin dirty.
- Compare prototype or constructor identity: a custom subclass's snapshot is a
  plain `Error`, so its form would begin dirty.
- Compare the stack: two separately constructed, otherwise equal errors would
  differ, and stack text varies by engine.
- Keep enumerable-key comparison: it misses `message` and `cause` and compares
  properties the clone drops.
