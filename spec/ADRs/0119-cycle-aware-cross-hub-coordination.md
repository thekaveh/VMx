# ADR 0119 — Coordinate cross-hub waits by actual dependency cycles

**Status:** Accepted (2026-07-18)
**Spec version:** clarified in 3.22.0
**Clarifies:** [ADR-0082](0082-message-hub-transactions.md)

## 1. Context

Concurrent MessageHub implementations serialize each hub's batch and drain.
They previously escaped every foreign-hub wait whenever the caller happened to
be inside any hub callback. That avoided some opposing-callback deadlocks, but
also made unrelated nested sends return before delivery and left opposing batch
callbacks able to deadlock.

Callback context alone does not prove a dependency cycle. The runtime must
distinguish an unrelated busy target from a target whose owner is already
waiting, directly or transitively, for the current thread.

## 2. Decision

- Shared-memory flavors track thread wait-for edges while a producer waits for
  a foreign batch or drain owner.
- If waiting does not close a cycle, the producer waits and retains ordinary
  synchronous delivery and calling-thread semantics, including from a callback.
- If waiting would close a real cycle, a send enqueues and returns to the active
  owner drain; disposal records terminal intent for that owner to finish.
- A batch that closes a cycle enters a borrowed scope: its body runs and may
  enqueue, while the target owner cannot resume draining until the borrowed
  scope exits. Normal and nested batches retain exclusive ownership.
- Wait edges are removed on every wake, cycle escape, error, and exit.

No conformance ID or version bump is added. `HUB-013` is strengthened with
opposing send/dispose/batch and unrelated-busy-target regressions.

## 3. Consequences

- Opposing cross-hub callbacks make progress without broad asynchronous escape.
- An unrelated callback's send remains synchronous and is delivered on the
  producer thread after the target becomes available.
- Implementations with no shared-memory concurrency need no wait graph.

## 4. Rejected alternatives

- Escape every callback wait: unrelated sends cease to be synchronous.
- Always wait: opposing cross-hub callbacks and batches can deadlock.
- Reject every cross-hub batch from a callback: valid finite transactions would
  fail based on incidental callback context rather than an actual cycle.
