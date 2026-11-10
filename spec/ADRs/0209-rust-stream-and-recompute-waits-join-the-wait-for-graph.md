# ADR 0209 — Rust stream delivery and recompute gate waits join the wait-for graph

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 03 §4.1)
- **Extends:** [ADR-0172](0172-one-wait-for-graph-per-flavor.md)

## 1. Context

ADR-0172 requires each threaded flavor to record every blocking wait between
VMx-owned resources in one wait-for graph. A wait that would close a cycle is
refused, and the operation takes a refused-wait result instead of blocking.
Two Rust waits between VMx-owned resources were not in the graph.

- **#1298, `ValueStream` delivery.** A `send` or `dispose()` on a stream that
  another thread drains waits until that thread delivers the value or the
  terminal. ADR-0103 makes `ValueStream` a VMx-owned type. Thread A sends on
  hub H, and the H subscriber sends on stream S. Thread B sends on S, and the
  S subscriber sends on H. A waits for B's drain of S with no edge, and B
  waits for A's drain of H with an edge. Neither thread returned. The same
  cycle between two hubs completes.
- **#1463, `DerivedProperty::recompute`.** PR #906 serializes `recompute`
  calls with a re-entrant gate that covers the snapshot, the transform and
  the commit. A second thread waits for the gate with no edge. Thread A's
  transform sends on a hub that thread B drains, and B's handler recomputes
  the same property. A waits for drainer B with an edge, and B waits for A's
  gate with no edge. Neither thread returned. The rustdoc told callers to
  avoid this cycle, but a transform cannot see what a drainer on another
  thread does.

C#, Python, TypeScript and Swift have no `ValueStream`, and their
`DerivedProperty` types have no `recompute` method.

## 2. Decision

1. **Stream delivery wait.** A Rust `ValueStream` `send` or `dispose()` that
   waits for another thread to deliver its value or terminal records an edge.
   The resource is that one accepted value or terminal. The owner is the
   thread that drains the stream. The drainer removes the edges before it
   wakes the waiters.
1. **Refused stream wait.** A refused stream wait returns at once. The value
   or terminal stays queued, and the drainer delivers it in order. This is the
   result that a send from inside a stream drain already takes, and it matches
   a refused hub `send`, which enqueues for the active drain (ADR-0119).
1. **Recompute gate wait.** A Rust `DerivedProperty::recompute` that waits for
   another thread's recompute gate records an edge. The resource is the
   property's gate. The owner is the thread that holds it. The holder removes
   the edges before it wakes the waiters.
1. **Refused gate wait.** A refused gate wait does not enter the gate. The
   call runs its transform at once, from its own snapshot. Its commit follows
   the rule that already holds for a transform's nested `recompute`: the
   result is discarded if another commit lands after the snapshot. So the
   last value that `value_changes` publishes is still the stored value.
1. **Application waits stay outside.** A transform or subscriber that blocks
   on application code, such as a channel, is outside the graph. The
   `recompute` rustdoc keeps that one restriction.

### 2.1. Choices made under the owner's delegation

- Decided under the owner's 2026-11-07 delegation: each stream delivery wait
  names one value or terminal, not the stream. The drainer releases each
  delivery as it finishes it, so a waiter for a delivered value never keeps
  an edge to the drainer.
- Decided under the owner's 2026-11-07 delegation: a refused gate wait runs
  the transform without the gate. Running it later on the holder's thread
  would need a second copy of a one-shot transform, and skipping it would
  drop the caller's update.

## 3. Consequences

- Chapter 03 §4.1 has a row for each wait, with its refused-wait result.
- A stream send or dispose that closes no cycle still returns only after the
  drainer delivers its value or terminal.
- A refused recompute can run while another thread's transform runs, so its
  transform does not always receive the previous transform's result. The
  snapshot check keeps the stored value consistent.
- The Rust `NotificationHub` publication and dispose waits use the same
  unrecorded pattern. No test has shown a cycle through them, so #1298 left
  them out of scope.
