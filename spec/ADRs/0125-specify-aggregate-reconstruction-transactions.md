# ADR 0125 — Specify aggregate reconstruction transactions

**Status:** Accepted (2026-07-22)
**Spec version:** clarified in 3.22.0
**Extends:** [ADR-0124](0124-canonicalize-forwarding-ownership-and-callback-boundaries.md)

## 1. Context

All five flavors already treat fixed-slot aggregate reconstruction as a
transaction and have focused tests for exceptional cleanup and concurrent
disposal. Chapter 08 documented construction, destruction, and disposal but
did not state the reconstruction decision boundary. Consumers therefore could
not tell whether a late slot failure preserved old slots, whether cleanup
stopped at the first error, or whether candidates committed after cleanup.

## 2. Decision

- Evaluate and ownership-preflight every replacement candidate before changing
  an existing slot. A factory or preflight failure preserves the exact old
  slots and parent links.
- Dispose every previous slot even if one cleanup fails, retaining the first
  cleanup failure.
- When the aggregate remains viable, commit all candidates together in the
  `Destructed` state, establish their parent links, publish slot changes, and
  then propagate the retained failure where the flavor supports it.
- When re-entrant or concurrent disposal makes the aggregate terminal, dispose
  every candidate and commit none. External disposal waits for the active
  reconstruction decision before taking its terminal child snapshot.
- Add `AGG-007` to compose the constituent factory, slot-publication, complete
  cleanup, and terminal-abort obligations into one explicit reconstruction
  scenario, with coverage in all five flavors.

## 3. Consequences

- Aggregate slots cannot expose a partially replaced ownership graph.
- Cleanup attempts are complete and deterministic while preserving the first
  causal failure.
- Non-throwing disposal flavors retain the same state and ownership outcome
  without inventing a throwing public surface.
- This records already-aligned 3.22.0 behavior; it adds one conformance ID but
  no API, fixture, package version, or minimum-spec change.

## 4. Rejected alternatives

- Dispose old slots while factories are still running: a later invalid
  candidate would destroy the recoverable pre-call state.
- Stop cleanup at the first failure: later old slots and candidates would leak.
- Let concurrent disposal snapshot mid-commit: terminal traversal could miss a
  child or dispose an uncommitted candidate twice.
