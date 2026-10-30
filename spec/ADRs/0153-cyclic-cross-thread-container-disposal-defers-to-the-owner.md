# ADR 0153 — A cross-thread container disposal that would close a wait cycle defers to the owner

- **Status:** Accepted (2026-10-25; the Python gap in §3 is closed by ADR-0166)
- **Date:** 2026-10-25
- **Spec version:** 3.30.0 (clarification)
- **Clarifies:** [ADR-0122](0122-defer-container-disposal-through-membership-transactions.md)

## 1. Context

ADR-0122 defers a container disposal that the transaction-owning thread requests,
and makes a disposal requested from another thread wait for the transaction
boundary. Since #553, a Swift membership transaction can wait for a second
container's transaction, and C# groups can do the same (#718). Waits that would
close a cycle are refused for attachment (#551, #718), but a cross-thread
disposal waited without any cycle check (#717).

The reproduction: thread B holds Y's transaction and, from Y's
`collectionChanged` handler, disposes X. (In C#, Y is a group: a C# composite
refuses a concurrent transaction instead of waiting.) Thread A holds X's
transaction and waits for Y's, because it is adding Y's child to X. B waits for
A, A waits for B, and both threads hang. No hub is involved.

## 2. Decision

- A disposal requested from another thread still waits for the transaction
  boundary (ADR-0122), and it registers that wait in the flavor's wait-for
  graph.
- When the wait would close a wait-for cycle, because the transaction owner
  already waits, directly or through other threads, for the requesting thread,
  the disposal does not wait. It records deferred terminal intent and returns,
  and the owner disposes the container when its transaction ends, as for a
  disposal the owner requests itself.
- Once the intent is recorded, the container rejects new structural admission
  as disposal in progress (ADR-0122).

This is the container counterpart of the hub rule in spec/03 §3, where a
disposal that would close a cycle records terminal intent for the owner. It
adds no conformance ID and does not change package or specification versions.

## 3. Consequences

- Swift and C# composites and groups no longer deadlock when a cross-thread
  disposal closes a membership-transaction wait cycle. A C# composite now
  records its transaction owner in the shared wait-for graph, so waits on it
  can see the cycle.
- In a cycle, `dispose()` can return before the container is disposed; the
  owning thread finishes the disposal at its transaction boundary.
- Python and Rust refuse a concurrent membership transaction instead of
  waiting, so the attachment cycle above cannot form there. Their cross-thread
  disposal still waits without a cycle check, though, so two threads that each
  hold one container's transaction and dispose the other's container hang.
  That gap is open and tracked separately; spec/06 records it. TypeScript is
  single-threaded.

## 4. Rejected alternatives

- Fail the disposal: disposal is terminal and has no error channel, and the
  caller cannot retry safely from inside the owner's callback.
- Dispose immediately without the boundary: the snapshot would race the open
  transaction, which ADR-0122 forbids.
