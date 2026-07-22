# ADR 0120 — Preserve Rust's ID-based message sender identity

**Status:** Accepted (2026-07-18)
**Spec version:** clarified in 3.22.0
**Clarifies:** [ADR-0009](0009-cross-flavor-divergence-catalogue.md), [ADR-0080](0080-rust-flavor-feasibility.md)

## 1. Context

The message chapter described `Sender` as a runtime object carried by every
flavor, while later Rust-specific contracts and the shipped Rust implementation
use `sender_id: usize`. Retaining an arbitrary sender object in Rust messages
would require ownership, lifetime, trait-object, and thread-safety policy that
the other languages' managed references do not expose.

The observable contract needs stable sender identity for filtering; it does not
require a hot message stream to own or borrow the sender VM.

## 2. Decision

- The language-neutral invariant is one canonical sender identity plus its
  diagnostic sender name.
- C#, Python, TypeScript, and Swift carry the runtime sender object through
  their idiomatic `Sender`/`sender` accessor and may narrow it generically.
- Rust's enum-based messages carry `sender_id: usize` and an owned diagnostic
  `sender_name: String`. They do not retain or borrow a sender object and are
  not generic over its concrete type.
- Rust sender filtering compares `sender_id`; a VM and every message it emits
  use the same stable ID for that VM's lifetime.
- This is a narrow ownership adaptation, not permission for payload, ordering,
  delivery, or lifecycle divergence.

The source line adds the missing `sender_name` field/accessor and strengthens
the existing `PROP-004` coverage. This is an additive pre-publication Rust API
correction; it adds no conformance ID or fixture and does not require a version
bump because the crate has not yet been published.

## 3. Consequences

- Rust messages remain straightforward owned values that can cross the crate's
  supported concurrency boundaries without retaining VM graphs.
- Cross-flavor consumers reason about sender identity uniformly while using the
  idiomatic accessor for their flavor.
- Parity audits treat the Rust field shape as an accepted divergence and still
  require identity-equivalent filtering behavior.

## 4. Rejected alternatives

- Store a Rust sender trait object: this adds lifetime, ownership, object-safety,
  and `Send`/`Sync` constraints without improving the behavioral contract.
- Describe runtime-object carriage as universal: that leaves the normative text
  contradicted by the accepted Rust API.
