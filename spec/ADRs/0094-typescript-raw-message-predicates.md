# ADR 0094 — Add TypeScript raw-message predicates

**Status:** Accepted (2026-07-11)
**Spec version:** introduced in 3.14.0
**Related:** ADR-0006, ADR-0032, ADR-0050, issue #88

## 1. Context

VMx already exposes typed hub helpers for observing one property of one known
sender. Consumers also inspect mixed raw `IMessage` arrays and streams, where
TypeScript needs an explicit type predicate at the `Array.filter` or RxJS
`filter` call site to retain the concrete message type.

DayDreams provided the motivating evidence: nine property-message sites and one
collection-message site repeated local runtime classifiers because a bare
generic message constructor did not provide the required narrowing in every
filter position. The gap is specific to TypeScript's structural typing and
filter overloads; it is not missing language-neutral message behavior.

## 2. Decision

1. TypeScript exports three runner-agnostic predicates from the message barrel
   and package root:
   - `isPropertyChanged(message)` and constrained sender/property forms
   - `isCollectionChanged(message)` and constrained source/action forms
   - `isConstructionStatusChanged(message)` and a sender/status form
1. Each predicate first classifies the corresponding existing concrete message
   with `instanceof`. Every supplied constraint must then match: sender and
   source use strict object identity, while property name, collection action,
   and construction status use exact field equality. A different message family
   or any mismatched constraint returns `false`. Constraint presence is based on
   own properties, so an explicitly supplied `undefined` value compares exactly
   instead of behaving like omission.
1. Unary overloads make the predicates valid direct callbacks for both
   `Array.filter` and RxJS `filter`. Their implementations treat the numeric
   callback index passed as a second runtime argument as absent constraints; no
   public numeric-argument overload is exposed.
1. The property predicate infers its generic sender only from a required sender
   constraint that is checked at runtime. Property-name-only and empty
   constraints retain `PropertyChangedMessage<unknown>`; callers cannot select a
   sender generic without supplying its checked value.
1. The collection predicate always narrows to
   `CollectionChangedMessage<unknown>`, whether unary or constrained by source
   and/or action. Public `CollectionChangedMessage` factories accept sender and
   item types independently, so even a source typed as
   `ServicedObservableCollection<TItem>` cannot prove the payload generic.
   Callers cannot select a collection item generic.
1. These functions only classify existing message objects. They do not mutate a
   message, subscribe to a hub, allocate an observable, catch errors, or change
   publication, ordering, lifecycle, sender, or payload semantics.
1. Existing `whenPropertyChanged` and
   `propertyValueChangedMessagesFor` remain the preferred higher-level helpers
   when a consumer already has the hub, sender, and property. The new predicates
   compose with ordinary array/RxJS filters for mixed raw-message inputs.
1. This is an informative TypeScript-only API under ADR-0006. It adds no
   language-neutral conformance ID and creates no implementation requirement for
   C#, Python, Swift, or Rust.

## 3. Consequences

- TypeScript consumers can replace repeated local classifiers while preserving
  useful, evidence-backed type narrowing and exact runtime matching.
- The package adds no dependency and no RxJS-specific abstraction.
- All five flavors remain at 342 library conformance IDs and five `THEME-00x`
  scenarios (347 total).
- The specification and stable packages advance to 3.14.0. Rust advances to
  0.14.0 while declaring minimum spec 3.14.0; non-TypeScript runtime surfaces
  are unchanged.

## 4. Rejected alternatives

- **One generic `isMessage` matcher:** conditional types or unsafe constructor
  signatures would be required to preserve the three payload shapes, while
  family-specific constraints would become less discoverable.
- **New RxJS operators:** curried operators would couple classification to RxJS
  and overlap the existing hub helpers. Plain predicates already compose with
  RxJS `filter`.
- **Cross-flavor predicate parity:** nominal/runtime type checks are already
  idiomatic in the other languages. Adding artificial public APIs there would
  mistake TypeScript type ergonomics for a shared behavioral contract.
