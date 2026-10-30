# ADR 0166 — Python container disposal checks a wait-for graph

- **Status:** Accepted
- **Date:** 2026-10-30
- **Spec version:** 3.30.0 (flavor status update in chapter 06 §4.2)
- **Implements:** [ADR-0153](0153-cyclic-cross-thread-container-disposal-defers-to-the-owner.md)
  in Python

## 1. Context

ADR-0153 requires a cross-thread container disposal to record deferred
terminal intent instead of waiting when the wait would close a wait-for cycle.
Swift and C# implement it. ADR-0153 §3 and chapter 06 recorded an open gap
for Python and Rust (#1059).

Python had no wait-for graph for container membership transactions. A Python
membership transaction refuses a concurrent one instead of waiting, so only
`dispose()` waits for another thread's transaction. That wait had no cycle
check. Thread A holds X's transaction and, from X's `on_collection_changed`
handler, disposes Z. Thread B holds Z's transaction and disposes X the same
way. Each `dispose()` waits for the other thread, and both threads hang.

## 2. Decision

- Python keeps one process-wide wait-for graph for container membership
  waits. `CompositeVM` and `GroupVM` record the owner of each membership
  transaction in it.
- A cross-thread `dispose()` records its wait in the graph before it blocks.
  The owner of the container is looked up when a cycle is checked, so a
  released transaction stops counting at once.
- When the wait would close a cycle, `dispose()` records deferred terminal
  intent and returns. The transaction owner disposes the container when its
  transaction ends, as ADR-0153 states.
- A disposal that closes no cycle still waits for the transaction boundary
  (ADR-0122).

The graph covers container membership waits only. Python hub waits keep their
own hub-only graph, so a cycle through a hub drain and a container wait is not
yet visible in Python.

This adds no conformance ID and changes no package or specification version.

## 3. Consequences

- Two Python threads that each hold one container's transaction and dispose
  the other's container no longer hang. Both containers reach `DISPOSED`.
- In such a cycle, one `dispose()` returns before its container is disposed.
  The owning thread finishes the disposal when its transaction ends.
- Chapter 06 §4.2 now records the gap for Rust only.
