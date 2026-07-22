# ADR 0121 — Clarify the current five-flavor contract surface

**Status:** Accepted (2026-07-18)
**Spec version:** clarified in 3.22.0
**Clarifies:** [ADR-0006](0006-idiomatic-api-per-language.md), [ADR-0009](0009-cross-flavor-divergence-catalogue.md), [ADR-0054](0054-v3-typescript-uniform-message-sender.md)

## 1. Context

Several current-facing chapters retained wording from the three- and
four-flavor eras. The resulting text omitted Swift or Rust from lifecycle,
command, derived-property, and form contracts. It also treated all 400 catalog
IDs as library-suite requirements even though five `THEME-00x` IDs are
application scenarios implemented by the four UI-backed flagships.

The message chapter additionally projected the eventual canonical `sender`
accessor onto the untyped C#, Python, and Swift base interfaces. Those bases
still expose their source-compatible `senderObject` aliases; only typed
messages expose the canonical object sender in those flavors. Adding a new
base-interface member would be a breaking change for third-party implementers.

## 2. Decision

- The stable library gate is 395 IDs in each of the five flavor suites. The
  five `THEME-00x` IDs are scenario contracts for UI-backed applications and
  are implemented by the C#, Python, TypeScript, and Swift flagships.
- Current prose enumerates all five flavors or uses language-neutral wording.
  Swift and Rust confirmation composition, write-back rejection, and snapshot
  behavior are part of the documented contract.
- The language-neutral message invariant is one sender identity and one
  diagnostic sender name. TypeScript exposes `sender` on its untyped base;
  C#, Python, and Swift expose the canonical object sender on typed messages
  while retaining the legacy untyped base alias until a future major; Rust
  exposes stable `sender_id` identity per ADR-0120.
- No new API, behavior, conformance ID, fixture, or version bump is introduced.

## 3. Consequences

- The catalog wording matches the coverage tool and the shipped test trees.
- Implementers can compare all five idiomatic surfaces without interpreting
  stale flavor counts.
- The spec no longer requires a breaking base-interface addition that the
  current source does not provide.
- ADR-0054 remains the historical TypeScript v3 decision; its claim that the
  other untyped bases already exposed canonical `sender` is narrowed by this
  clarification.

## 4. Rejected alternatives

- Add `sender` to every untyped base immediately: this would break external
  implementations in C#, Python, and Swift during a clarification release.
- Move `THEME-00x` into Rust's library suite: Rust intentionally has no UI
  flagship, and application scenarios are not library primitives.
