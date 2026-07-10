# ADR 0082 — Lossless message-hub transactions and iterative delivery

**Status:** Accepted (2026-07-10)
**Spec version:** introduced in 3.2.0

## 1. Context

The v3.1 hub is hot, synchronous, and unbuffered. A logical operation that
mutates several viewmodels therefore causes subscribers to recompute once per
intermediate message. More seriously, a subscriber that publishes while
handling a message re-enters the underlying Rx subject recursively. Tableau's
React store needed a hand-written `refreshing` flag after derived model setters
published back into the subscription and froze the UI.

Collection-local `BatchUpdate` cannot solve this. It suppresses and summarizes
one collection's local notifications, whereas a hub transaction must cover
heterogeneous typed messages from an entire VM graph.

## 2. Decision

### 2.1 Lossless transaction queue

Every shipped real and null hub gains the idiomatic transaction API listed in
`03-messages.md §3.3`. In the interface-based flavors it is an additive
transaction-capability protocol extending the established base hub contract;
custom base-hub implementations therefore remain source-compatible. Sends
inside nested scopes append to one hub-wide FIFO and
delivery begins only after the outermost scope exits. "Batch" means deferral,
not deduplication: every typed message is delivered exactly once.

If the body raises, the hub drains already-queued messages so observers see the
mutated state, then rethrows the original error. Disposing the hub clears the
pending queue and completes the stream. Null hubs execute the body but publish
nothing.

### 2.2 Iterative re-entrancy

All sends enqueue before delivery. A top-level send becomes the drainer;
subscriber-generated sends append behind the in-flight message. The drainer
loops until the queue is empty, so subscribers see message-level FIFO order and
no recursive publish stack develops.

### 2.3 Concurrency and calling threads

C#, Python, Swift, and Rust serialize the transaction and drain. Another
producer waits, then synchronously drains its own send on its calling thread.
This preserves existing per-producer FIFO and calling-thread behavior. A
transaction body must not join a thread blocked on that same hub. TypeScript hub
instances are not transferable between workers, so event-loop serialization is
the equivalent guarantee.

### 2.4 Development overflow diagnostics

A development build bounds one drain cycle and reports the message types seen
when the bound is exceeded. The pending development queue is abandoned after
the diagnostic so a detected cycle cannot freeze a test or UI. Release
configurations disable or compile the bound out and retain an unbounded
iterative drain, so a large but finite valid transaction is not truncated. Swift uses an injectable diagnostic
hook because changing its established non-throwing `send` to `throws` would be
a source-breaking API change; C#, Python, TypeScript, and Rust raise or panic.
TypeScript detects Node development/test mode automatically and exposes an
explicit browser opt-in; browser-default diagnostics are disabled because the
web platform has no standard development flag and release correctness takes
precedence over guessing.

### 2.5 Conformance

`HUB-008..013` cover nested lossless deferral, body-error precedence,
message-level re-entrant FIFO, subscriber isolation during a flush, disposal,
and unchanged ordinary sends. `NULL-001` also verifies that a null transaction
executes its body without publishing.

## 3. Consequences

- Multi-VM operations can expose one stable post-transaction delivery phase
  without erasing typed events.
- Subscriber publication is finite-stack and deterministic at message
  boundaries.
- Collection batching and hub transactions compose: a collection may emit its
  one reset inside a hub transaction alongside other VM messages.
- Transactions are synchronous critical sections in threaded flavors; bodies
  must stay short and must not wait on producers using the same hub.
- The additive contract raises the spec and active flavor minor versions to
  3.2.0; the pre-1.0 Rust flavor moves to 0.2.0.

## 4. Rejected alternatives

- **Merge messages by sender or type.** Rejected because typed messages are
  observable facts and dropping one changes behavior.
- **Deliver recursively and only detect depth.** Rejected because a depth guard
  diagnoses the freeze but does not remove stack growth or define ordering.
- **Make batching collection-only.** Rejected because Tableau's cycle spans
  several derived viewmodels and one shared hub.
- **Apply the overflow limit in release builds.** Rejected because it would
  reject large finite transactions and change production correctness.
