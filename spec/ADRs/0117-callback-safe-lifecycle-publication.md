# ADR 0117 — Separate lifecycle admission from callback delivery

**Status:** Accepted (2026-07-18)
**Spec version:** clarified in 3.22.0
**Clarifies:** [ADR-0047](0047-v3-lifecycle-threading-semantics.md)

## 1. Context

Chapter 02 required the status write and every resulting observer callback to
run under one per-VM lifecycle guard. That prevents resurrection, but it also
creates a lock-order cycle when two VMs publish concurrently and each observer
invokes a lifecycle operation on the other VM. Completing lifecycle waiters
under the same guard exposes the equivalent problem through task/future
continuations.

Terminal admission and publication order must remain atomic without retaining a
VM's private state lock while arbitrary consumer code runs.

## 2. Decision

- A lifecycle operation atomically validates and writes `Status`, reserves its
  place in a per-VM FIFO publication queue, and applies the terminal guard.
- Hub delivery, local property notification, command-trigger delivery, and
  task/future completion run after the state guard is released.
- One drainer serializes each VM's admitted publications. A normal top-level
  lifecycle call remains synchronous through its own publication.
- A lifecycle call made from a callback that is already draining another VM
  normally waits for the target publication too. It may enqueue and return only
  when the wait graph proves that waiting would close an actual cross-VM cycle;
  the target's existing drainer completes that publication. This narrow escape
  prevents callback cycles without weakening ordinary synchronous completion,
  terminal admission, or FIFO order.
- Subject teardown follows delivery of the admitted `Disposed` publication, so
  no queued transition writes to a completed stream.

No conformance ID or version bump is added; existing lifecycle and threading
IDs are strengthened with opposing-callback regression coverage.

## 3. Consequences

- Concurrent cross-disposal cannot deadlock through opposing lifecycle locks.
- `Disposed` remains terminal and no admitted non-terminal publication may
  appear after its terminal publication.
- Implementations need a small publication queue or equivalent serializer in
  flavors with shared-memory concurrency.

## 4. Rejected alternatives

- One process-wide lifecycle lock: opposing callbacks can still wait at a
  rendezvous while preventing the peer from entering its callback.
- Publish while holding per-VM locks: this preserves the deadlock.
- Publish entirely unsynchronized: disposal could overtake an earlier status
  admission and expose a post-terminal event.
