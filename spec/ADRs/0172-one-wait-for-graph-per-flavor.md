# ADR 0172 — One wait-for graph per flavor; borrowed hub scopes are wait-for owners

- **Status:** Accepted
- **Date:** 2026-11-08
- **Spec version:** 3.30.0 (chapter 02 §2.4; chapter 03 §4, §4.1 and §4.2)
- **Extends:** [ADR-0166](0166-python-container-disposal-checks-the-wait-for-graph.md)
  and [ADR-0167](0167-rust-container-disposal-checks-the-wait-for-graph.md)
- **Clarifies:** [ADR-0119](0119-cycle-aware-cross-hub-coordination.md), and the
  cycle rule of ADR-0117 and ADR-0126

## 1. Context

Several rules let a blocking wait avoid waiting only when the wait would close
an actual wait-for cycle. ADR-0119 states the rule for hub waits. ADR-0117 and
ADR-0126 state it for lifecycle publication and hook waits. ADR-0153 states it
for container disposal. Each threaded flavor checks for a cycle in a wait-for
graph. The flavors did not keep one graph each, and some waits recorded no
edge. Thirteen issues came from this.

- **Split graphs.** A cycle with edges in two graphs is invisible to both
  graphs, so both threads hang.
  - C# keeps lifecycle publication and hook-lease waits in a private graph.
    Hub, membership and ownership-gate waits use `WaitForGraph.Shared`
    (#1156).
  - Python keeps three graphs: one for membership waits, one for hub waits and
    one for lifecycle waits (#1157, #1202). Its ownership-lock wait records no
    edge (#1155).
  - Rust keeps hub and hook-owner waits in a map in `runtime.rs`. Membership
    waits use the ADR-0167 graph (#1158).
- **Unrecorded waits.** The Swift ownership-gate wait (#1154) and the
  borrowed-batch waits in C# (#1159), Swift (#1178), Python (#1179) and Rust
  (#1180) record no edge.
- **Stale edges.** A waiter removes its own edge only after it wakes. Between
  the owner's release and the wake-up, another thread's cycle check follows the
  dead edge. It then takes an escape for a cycle that has already ended. A
  send returns before delivery, a batch borrows, or a disposal returns before
  another thread's hook or `Disposed` delivery finishes (#1180, #1181, #1182,
  #1183).
- **Borrowed scopes.** In Python and Rust, a borrower's own send, batch or
  dispose waits for its own borrowed scope (#1179, #1180). Swift's borrower
  send waits for a foreign owner (#1178). A drainer with an empty queue waits
  for a borrowed scope (#1159, #1178, #1179). C# and Rust escape a
  borrowed-scope wait because the caller is inside a hub callback. That
  returns before delivery when no cycle exists, against `HUB-013` (found in
  the #1159 review).

ADR-0166 §2 said that Python hub waits keep a hub-only graph. ADR-0167 §2 said
that Rust hub waits are not in its graph. On 2026-11-07 the owner confirmed
ADR-0167 with one planned extension: all Rust waits move into one graph, and a
new ADR records it (#1175). This ADR is that extension. It applies the same
rule to every threaded flavor.

## 2. Decision

### 2.1. Rules

Chapter 03 §4.1 and §4.2 and chapter 02 §2.4 state these rules for every
threaded flavor (C#, Python, Swift and Rust). TypeScript is single-threaded and
is not affected.

1. **One graph.** Each threaded flavor records every blocking wait between
   VMx-owned resources in one process-wide wait-for graph. The waits are:
   lifecycle publication waits and hook-lease waits, hub drain and
   borrowed-batch waits, container membership-transaction waits, and
   ownership-gate or ownership-lock waits. A wait that would close a cycle
   across any mix of these waits is refused. The operation then takes the
   escape, or raises the error, that its area already uses (chapter 03 §4.1
   lists them). A wait that closes no cycle blocks as before.
1. **Edges per resource instance.** An edge names the waiting thread, the
   resource instance it waits for, and the thread that owns that resource. The
   resource instance is one hub, one lifecycle delivery, one hook lease, one
   container's membership transaction, or one ownership gate or lock object.
   An edge is never keyed by VM identity. A container that is also a child has
   a membership transaction and an ownership gate, and they are two resources.
   Swift keys gate edges on `ObjectIdentifier(ownershipGate)`.
1. **Release before wake.** The thread that ends a wait removes the edges, and
   the ownership records, that name it as the owner of that resource. It does
   this before it wakes the waiters. This applies when a thread finishes a
   hook, delivers a publication, ends a membership transaction, releases an
   ownership gate, ends a batch, releases a drain, and when a borrower ends or
   partially exits its borrowed scopes. A partial borrower exit also wakes the
   waiters. A stale edge never causes a false cycle escape (#1181, #1182,
   #1183) or a hang (#1179, #1180).
1. **Borrowed hub scopes** (chapter 03 §4.2).
   - An open borrowed batch scope is a wait-for owner. A wait on it records an
     edge to a borrower.
   - A drainer whose queue is empty does not wait for a borrowed scope. It
     releases the drain, and the exit of the last borrowed scope drains what
     the bodies enqueued. This is not a new escape: the drainer's outermost
     `Send` returns with an empty queue, as chapter 03 §3.3 requires.
   - A borrower's own send, batch and dispose on the hub it borrowed do not
     wait, as in C#. The send enqueues, the batch nests another borrowed scope,
     and the dispose records terminal intent. The last of the batch owner,
     the drainer, and the borrowers to release the hub finishes that
     disposal.
   - The callback-context borrow escape in C# and Rust is removed. Being
     inside a hub callback does not change a wait.
   - A drainer with queued messages waits for the borrowed scopes. If a
     borrower already waits, directly or through other threads, for that
     drainer, rule 1 refuses whichever wait closes the cycle. When the
     drainer's wait is refused, the drainer releases the drain. The thread that
     exits the last borrowed scope delivers the queued messages. Chapter 03
     §4.2 records this limitation and its observable result.
1. **Lifecycle disposal waits** (chapter 02 §2.4). `dispose()` does not return
   before another thread's admitted hook, or another thread's delivery of the
   view-model's `Disposed` publication, finishes. The one exception is a wait
   that would close a live cycle (#1182, #1183).

### 2.2. Choices made under the owner's delegation

The owner delegated the remaining design questions to this principle: all
flavors follow the same guidelines and specs as much as possible, with the
simplest and most common-sense approach chosen.

- Decided under the owner's 2026-11-07 delegation: one graph per process in
  every threaded flavor, not one graph per family of waits. A second graph
  always hides the cycles that cross the two graphs. Every later blocking wait
  between VMx-owned resources joins the same graph.
- Decided under the owner's 2026-11-07 delegation: the `FormVM`
  publication-scope wait of ADR-0174 is not in this ADR's list. It has no
  escape yet, and the fix for #1170 decides one. When that fix records the
  wait, it records it in the same graph.
- Decided under the owner's 2026-11-07 delegation: a flavor may find the owner
  of a resource at check time (a resource-named edge), or name the owner in
  the edge when the wait starts (an owner-named edge). Both forms are valid
  when the releasing thread follows rule 3. C# already uses both forms, and
  Swift keeps its `redirectWait` for a lifecycle drainer hand-off (#1056).
  Python and Rust choose the form for each wait, like C#.
- Decided under the owner's 2026-11-07 delegation: a live cycle is a cycle in
  which each edge's owner still holds its resource when the check runs. The
  check and the new edge are one atomic step under the graph's own lock. That
  lock is a leaf: a thread that holds it takes no other lock and runs no
  consumer code.
- Decided under the owner's 2026-11-07 delegation: a waiting thread has at
  most one edge, because it blocks in one wait at a time. A hub wait with
  several possible owners names one: the batch owner, then the drainer, then a
  borrower other than the caller. When that owner releases the hub, the
  waiters wake and record their wait again if they must still wait. An edge
  to a set of owners (an AND-wait) was not chosen. It would add a second edge
  model for a case that the re-recording already covers.
- Decided under the owner's 2026-11-07 delegation: C# and Python key a
  lifecycle publication edge per delivery or publication object, and a hook
  edge per hook lease. The releasing thread removes those edges before it sets
  the completion. The C# lifecycle drainer never passes the drain to another
  thread, so C# needs no edge redirect (#1156 review).
- Decided under the owner's 2026-11-07 delegation: Rust uses one key space for
  every resource. A key comes from the resource's address, or the edge type
  names the resource kind. A counter id and an address are never mixed in one
  untyped key.
  Rust keys a hook-lease edge on the address of the component core that holds
  the lease. A core has at most one active hook at a time, so that address
  names its one active lease.
- Decided under the owner's 2026-11-07 delegation: when a borrower disposes
  the hub, the last owner to release the hub finishes the disposal and
  completes the stream. That owner is the batch owner, the drainer, or the
  last borrower, whichever releases the hub last. A drainer stops waiting for
  borrowed scopes once a disposal is requested, so its wait never holds a
  disposal open. A drain that is still delivering a message when the other
  owners exit finishes the disposal at its end. This is what Python and Swift
  did, and what C# did for the drainer. C# and Rust completed the stream at whichever of the
  two exits came first: on the batch owner inside an open borrowed scope, or
  on the borrower while the batch was still open (#1159 review). A Rust
  drainer with queued messages also kept waiting for the borrowers after the
  disposal request, and a Rust borrowed exit completed the stream while
  another thread's drain was still delivering a message. The rule needs no
  knowledge of which exit comes first, and every flavor completes the stream
  only when the hub has no owner left.
- Decided under the owner's 2026-11-07 delegation: a refused ownership-gate
  wait raises the error that each flavor already uses for an ownership
  conflict. C# throws `InvalidOperationException`, as #1095 does. Python
  raises `RuntimeError`. Swift returns the container's attachment failure
  (`.attachmentFailed`) from a result-based call and throws from a throwing
  call. The operation fails before mutation. Rust and TypeScript claim
  ownership without waiting, so they have no gate wait.
- Decided under the owner's 2026-11-07 delegation: the drainer with an empty
  queue releases the drain whether or not a cycle exists. It has nothing to
  deliver, so waiting only delays the borrowed scope's own drain.
- Decided under the owner's 2026-11-07 delegation: a drainer with queued
  messages, whose wait for a borrowed scope would close a cycle, releases the
  drain to the exit of the last borrowed scope. The two other options break a
  rule that does not depend on a cycle. Delivering during the borrow breaks the
  borrowed-scope rule of chapter 03 §4. Waiting hangs. The release matches the
  send escape of ADR-0119: the work goes to another thread's drain, and the
  per-producer FIFO order holds. No reproduced issue needs this case, so it
  stays a documented limitation of `HUB-010`.
- Decided under the owner's 2026-11-07 delegation: the batch owner's own send,
  batch and dispose keep their behavior. A wait that they make while a foreign
  borrowed scope is open records an edge (rule 1), so it is live. No new
  exemption is added for them, because no issue reproduces a defect there.
- Decided under the owner's 2026-11-07 delegation: ADR-0166 and ADR-0167 keep
  their decisions. Their status lines say that this ADR extends them. The
  ADR-0166 registry row and §3 now say that chapter 06 §4.2 records no gap for
  the rule after ADR-0167 (owner correction in #1175).

## 3. Flavor impact

The triage and its reviews of the thirteen issues found these changes. The
implementation PRs confirm the exact sites.

- **C#** (#1156, #1159, #1183). Remove `s_lifecycleWaitGraph` and
  `RegisterLifecycleWait`. Record the lifecycle publication wait per
  `LifecycleDelivery`, and the foreign-dispose hook wait per hook lease, in
  `WaitForGraph.Shared`. Call `ReleaseWaiters` before each `Completed.Set()`.
  In `MessageHub`, record an edge to a borrower on the borrowed-scope waits in
  `Send`, `Batch`, `DrainQueue` and `Dispose`. Keep the edges to current
  borrowers on wake, and wake the waiters on a partial borrower exit. The
  `DrainQueue` borrow wait runs only while `_pending` is not empty. On a
  refused drain wait, release the drain. Delete the `s_deliveryDepth > 0`
  break in `Send`. Update the `WaitForGraph` summary and the reflection seam
  in `ComponentVMLifecycleRaceTests`. A `Batch` exit finishes a requested
  disposal only when no batch owner and no borrowed scope remain. While a
  drain is active, `FinishDisposeLocked` still leaves the subject's completion
  to the drain's end.
- **Python** (#1155, #1157, #1179, #1181, #1182, #1202). Move the hub graph
  (`_thread_waits_for`) and the lifecycle graph (`_lifecycle_thread_waits_for`)
  into `vmx._wait_for_graph.WAITS`. Record ownership-lock holders and waits,
  with a hold count where `_ownership_lock` is created. Raise `RuntimeError`
  on a refused ownership wait. Record borrowers in `MessageHub`, exempt their
  own calls, and record edges on every borrowed-scope wait. Release before
  every `notify_all`, and wake on a partial borrower exit. `_drain` waits for
  a borrow only while `_pending` is not empty, and releases the drain on a
  refused wait. Key lifecycle edges per hook lease and per publication.
  Update the `test_hub.py` monkeypatch of `_register_message_hub_wait`.
- **Swift** (#1154, #1178). Record ownership-gate holders and waits in
  `ThreadWaitGraph`, keyed on `ObjectIdentifier(ownershipGate)`, with a hold
  count. A refused gate wait fails the operation before mutation, so
  `withOwnershipReservationBatch` becomes `throws`. In `MessageHub.drain()`,
  wait for a borrower with an edge only while the queue is not empty, and
  release the drain on a refused wait. The owned-batch exit claims the drain
  only when `borrowedBatchDepth == 0`. A partial borrower exit wakes the
  waiters. A borrower's own send enqueues, and its dispose records completion
  intent without waiting. Check the tests that count the first accepted wait
  in `onWaitDecidedForTesting`, because gate waits now report there too.
- **Rust** (#1158, #1180, #1183). Delete the `WAITS` map in
  `wait_for_message_hub_owner` and record hub and hook-owner waits in the
  `wait_for_graph` graph. A Rust status publication is a hub send, so the hub
  edge covers it. Track borrowers in `MessageHubInner`, exempt their own
  calls, and record edges on every borrowed-scope wait. Release before every
  `notify_all` on `ready` and `hook_ready`, and wake on a partial borrower
  exit. The drain waits for a borrow only while the queue is not empty, and
  releases the drain on a refused wait. Delete the
  `is_delivering_message_hub()` breaks in `send` and `send_prepared`. Give
  tests a seam that reports any recorded wait. `run_scope` finishes a
  requested disposal only when no batch owner, no borrower, and no drainer
  remain. The drainer stops waiting for borrowers once a disposal is
  requested, and a drain that is still delivering finishes the disposal at
  its end.
- **TypeScript.** No change.

## 4. Conformance

This adds no conformance ID and changes no package or specification version.
`HUB-013`, `LIFE-015` and the disposal rule of chapter 06 §4.2 already require
a wait that closes no cycle to wait, and a cyclic wait to escape. Each flavor
adds regression tests for its issues, as ADR-0119 did. A test may carry the ID
of the rule that it guards.

## 5. Consequences

- A cycle that crosses lifecycle, hub, membership and ownership waits no
  longer hangs in any threaded flavor. One wait in it takes its area's escape
  or error.
- A send, batch or disposal no longer takes an escape for a cycle that has
  ended. A send from inside a hub callback stays synchronous unless it closes a
  live cycle.
- A borrower can send, nest a batch and dispose on the hub it borrowed without
  waiting for itself.
- `dispose()` returns before another thread's hook or `Disposed` delivery
  finishes only for a live cycle.
- In the one documented case of chapter 03 §4.2, a drainer's outermost `Send`
  can return before its queued messages are delivered. The borrower's thread
  delivers them, in FIFO order.
- Chapter 06 §4.2 records no gap for the disposal rule, and no chapter records
  a split graph for any flavor.

## 6. Rejected alternatives

- **Keep the graphs apart and add cross-graph checks.** Every pair of graphs
  needs its own check, and a cycle through three graphs still escapes them.
- **Escape every wait from a hub callback.** ADR-0119 §4 already rejects it:
  unrelated sends stop being synchronous.
- **Key lifecycle edges on the view-model.** The drainer stays the owner of the
  view-model after one delivery completes, so a completed waiter keeps its
  edge until it wakes. That is the #1183 window.
