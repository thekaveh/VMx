# ADR 0147 — Lifecycle, message-helper, derived-property, and dictionary prose names all five flavors

- **Status:** Accepted
- **Date:** 2026-10-17
- **Spec version:** 3.29.0
- **Related:** [ADR-0009](0009-cross-flavor-divergence-catalogue.md)
  (cross-flavor divergence catalogue, §2.15),
  [ADR-0121](0121-current-five-flavor-contract-clarifications.md) (current
  prose names all five flavors),
  [ADR-0136](0136-align-token-refresh-cursor-with-retained-pages.md) (`COL-065`),
  [ADR-0146](0146-name-all-flavors-in-tree-and-fluent-surfaces.md) (the same
  correction for the tree and fluent surfaces)

## 1. Context

ADR-0121 requires current spec prose either to stay language-neutral or to name
all five flavors. Five per-flavor lists still named only some of them:

- Chapter 02 named the illegal-transition error for C#, Python, TypeScript, and
  Swift, but not the Rust `VmxError::InvalidLifecycleTransition` result.
- Chapter 03 §7.1 listed the message-stream helper for four flavors without
  saying what Rust consumers use. §7.2 already says it.
- Chapter 15 §6 gave the distinct-until-changed equality for C#, Python, and
  TypeScript only.
- Chapter 21 §4.4 (null keys) and §4.7 (hub payload shape) covered C#,
  Python, and TypeScript only.

Chapter 21 §8 also listed `COL-001` through `COL-064`, although `COL-065`
(ADR-0136) belongs to the same chapter.

## 2. Decision

Add the missing flavors as the code ships them:

- Chapter 02: Rust returns `Err(VmxError::InvalidLifecycleTransition)` for an
  illegal call from a live state. A call from `Disposed` returns
  `VmxError::Disposed` and a call during another transition returns
  `VmxError::ConcurrentOperation`; neither names the state and operation, so
  chapter 02 records this as an open Rust gap.
- Chapter 03 §7.1: Rust uses `MessageHub::subscribe_value` or
  `MessageHub::subscribe` with `Message::PropertyChanged`.
- Chapter 15 §6: Swift uses the `valueEquals` closure, which the `fromSources`
  factories supply as `==`; Rust uses `PartialEq`.
- Chapter 21 §4.4: Swift and Rust keys are statically typed and have no
  runtime null check; an optional key type chosen by the caller is accepted.
- Chapter 21 §4.7: Swift publishes a `DictionaryEntry`; Rust publishes the
  non-generic `CollectionChangedMessage` with no entry payload, as ADR-0009
  §2.15 records.
- Chapter 21 §8 lists `COL-001` through `COL-065`.

The change is editorial. It adds no normative behavior and no conformance ID.

## 3. Consequences

- The corrected sections satisfy ADR-0121.
- The Rust lifecycle error variants stay an open gap. Changing them alters the
  public Rust error contract and the aggregates that match on
  `VmxError::Disposed`, so it needs its own decision and change.
- The Rust dictionary payload difference stays a documented divergence under
  ADR-0009 §2.15; this ADR does not change it.
