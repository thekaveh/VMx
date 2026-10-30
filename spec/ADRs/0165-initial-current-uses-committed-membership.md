# ADR 0165 — The initial `Current` assignment uses committed membership and never waits

- **Status:** Accepted
- **Date:** 2026-10-30
- **Spec version:** 3.30.0 (clarification of chapter 06 §3.2)

## 1. Context

Chapter 06 §3.2 assigns the `Current(selector)` result through a non-raising
validated assignment. ADR-0050 fixed that wording. It did not say how the
assignment relates to another thread's membership transaction (§4.2,
ADR-0122).

C# and Python ran the assignment through the strict current-change path. That
path opens a membership transaction. While another thread held one, for
example inside an `Add` `CollectionChanged` handler, the assignment threw. The
construct walk treated the error as a failed construct, and the composite
rolled back to `Destructed` (#1064).

Waiting for the other transaction is not safe. The owner of that transaction
can wait for the construct walk through user code that no wait-for graph
sees, so both threads would deadlock. Deferring the assignment to the end of
the owner's transaction is not safe either: `Current` would then change after
`Constructed`, against §3.2.

## 2. Decision

The construct walk's assignment is a commit under the coordination lane and
the membership gate (§4.2). It opens no membership transaction. Five rules
define it:

1. **Committed membership.** A child that an `Add`, `Insert` or index
   replacement has attached but not yet admitted is not contained yet. Its
   rollback could still remove it, so selecting it is a silent no-op.
1. **Disposal.** While disposal of the composite is requested or deferred, the
   assignment is a silent no-op.
1. **No raise, no wait.** Another thread's open transaction neither fails the
   assignment nor makes it wait. The composite reaches `Constructed` with the
   selected child current, also when that thread waits for the walk.
1. **Publication lease.** The assignment holds the current-publication lease
   while it publishes. A disposal requested from its own `OnCurrentChanged` or
   current-flag callbacks returns at once. The disposal starts after the
   publication and any open membership transaction end. The request does not
   wait for another thread's transaction. The deferral stays set until the
   disposal starts, so no transaction begins in between.
1. **Detach clears only the detached child.** A transaction that detached the
   current child clears `Current` only while that child is still current. It
   never clears a selection made after the detach.

The selector input is unchanged. It can still contain a child that is attached
but not admitted (open decisions §2.7); rule 1 decides the result.

No conformance ID is added. The rules are observable only while another
operation is in flight, so each flavor covers them with its own concurrency
tests. `COMP-025` keeps covering the ordinary selection.

## 3. Flavor status

C# and Python implement all five rules (#1064). They apply the rule 4
deferral to every current-change publication, not only to the walk's
assignment. The other flavors have open gaps, recorded in chapter 06 §3.2:

- **TypeScript:** rules 2 and 3. When the walk resumes on the same thread inside
  an open transaction, or while disposal is deferred, the assignment raises
  and the construct rolls back.
- **Swift:** rule 3 and parts of rules 1, 2, 4 and 5. The assignment waits for
  a foreign transaction, and `dispose()` waits for one before it checks the
  publication lease. On the owner thread, the assignment skips the admission
  and disposal checks. There, a transfer's detach commit also clears `Current`
  when the walk selected another child after the detach.
- **Rust:** rules 1, 2, 4 and 5. The assignment can select an unadmitted child
  and can assign while disposing. A disposal from its callbacks is not
  deferred, and a transfer's detach commit always clears `Current`.

## 4. Consequences

- C# and Python composites no longer roll back when a foreign transaction
  overlaps the walk's selection.
- A disposal from a current-change callback no longer waits for another
  thread's transaction. An add on that thread that has not admitted its child
  when the disposal is requested fails and rolls back. Before, the disposal
  waited for it, which could deadlock.
- Publication order across threads can interleave. A foreign removal can
  commit its clear, then the walk can commit and publish before that removal
  publishes. Two concurrent selections already allow this, because the lane is
  released before publication (§4.2).
- The destruct path still uses the strict clear. Its overlap with a foreign
  transaction is a separate defect.
