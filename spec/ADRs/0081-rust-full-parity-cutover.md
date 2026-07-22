# ADR 0081 — Promote Rust to full library conformance

**Status:** Accepted (2026-07-09)
**Spec version:** introduced in 3.1.0

## 1. Context

ADR-0080 accepted Rust as a planned fifth VMx flavor, but intentionally marked
it experimental until its catalog markers were replaced by behavioral
conformance tests. The Rust crate now implements the full VMx library surface in
source and carries real `#[test]` functions for all 281 library conformance IDs.

## 2. Decision

Rust is a full-parity source flavor for the VMx library catalog. The conformance
coverage gate must require Rust alongside C#, Python, TypeScript, and Swift.
Rust remains unpublished on crates.io until a separate release channel is added;
package availability is distinct from source-level conformance.

## 3. Consequences

- New library conformance IDs require Rust test markers in the same PR.
- Current-facing docs should describe five source flavors, not four stable
  flavors plus a Rust preview.
- Release docs must continue to state that the Rust package is not yet publicly
  published.
