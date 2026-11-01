# ADR 0167 — Rust container disposal checks a wait-for graph

- **Status:** Accepted
- **Date:** 2026-10-30
- **Spec version:** 3.30.0 (flavor status update in chapter 06 §4.2)
- **Implements:** [ADR-0153](0153-cyclic-cross-thread-container-disposal-defers-to-the-owner.md)
  in Rust

## 1. Context

ADR-0153 requires a cross-thread container disposal to record deferred
terminal intent instead of waiting when the wait would close a wait-for cycle.
Swift and C# implement it, and ADR-0166 added Python. Chapter 06 §4.2 still
recorded an open gap for Rust (#1058).

A Rust membership transaction refuses a concurrent one instead of waiting, so
only disposal waits for another thread's transaction. `CompositeVm`, `GroupVm`
and the fixed aggregates waited with no cycle check. Thread A holds X's
transaction and, from a child's construct hook, disposes Z. Thread B holds Z's
transaction and disposes X the same way. Each disposal waits for the other
thread, and both threads hang.

## 2. Decision

- Rust keeps one process-wide wait-for graph for container membership waits.
  Each container's transaction control records its owner in it. A thread that
  finishes a transaction, and runs its deferred disposal, stays the owner
  until the transaction clears.
- A cross-thread disposal records its wait in the graph before it blocks. The
  owner of the container is looked up when a cycle is checked, so a released
  transaction stops counting at once.
- When the wait would close a cycle, the disposal records deferred terminal
  intent and returns. The transaction owner disposes the container when its
  transaction ends, as ADR-0153 states. If the owner is already finishing, it
  is running that disposal, so nothing more is recorded.
- A disposal that closes no cycle still waits for the transaction boundary
  (ADR-0122).

The graph covers container membership waits only. Rust message-hub waits are
not recorded in it.

This adds no conformance ID and changes no package or specification version.

## 3. Consequences

- Two Rust threads that each hold one container's transaction and dispose the
  other's container no longer hang. Both containers reach `Disposed`.
- In such a cycle, one disposal returns before its container is disposed. When
  the owner's add has not admitted its child yet, that add fails with
  `VmxError::Disposed` and rolls the child back (ADR-0122).
- Chapter 06 §4.2 no longer records an open gap for this rule.
