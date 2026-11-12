# ADR 0227 — Rust container destruct walks join a destruct that another thread started

- **Status:** Accepted
- **Date:** 2026-11-11
- **Spec version:** 3.30.0 (chapter 02 §6). The spec version does not move.
- **Amends:** [ADR-0218](0218-container-rollback-errors-walk-resumption-and-single-start.md)
  §2.3 and §3 (Rust). Related: [ADR-0186](0186-container-construct-walk-counts-members-only.md),
  [ADR-0205](0205-rust-container-children-forwarding-composite-and-hub-settle.md),
  #754, #1370, #1375, #1569.

## 1. Context

ADR-0218 rule 6 says a walk joins a transition of its child that is in flight
in the walk's own direction. This includes one that another thread started
after the walk read the status. The rule covers the construct walk and the
destruct walk.

Rust joins a refused construct start. `construct_member` and
`start_unless_started` catch the `InvalidLifecycleTransition` from a construct
that another thread started, and join it. Rust's destruct walks had no such
join. `run_child_transition` called `destruct()` and failed on any refusal. A
destruct that another thread started between the walk's status read and its
call refused the call with `InvalidLifecycleTransition { from: Destructing }`.
The container destruct then failed and rolled back to `Constructed`.

ADR-0218 §2.3 and §3 deferred this join to the Rust parity backlog (#1375).
C# and Swift already join a destruct that another thread started. Python joins
one that is still in flight, and §5 records its gap for a destruct that
finished first. TypeScript has one thread.

Swapping the walk's call to `transition_or_join_child` does not close the race.
That helper checks the status and then calls `run_child_transition`. The check
and the call are not atomic, so a destruct that starts between them still fails
the walk. A probe of that swap failed the same way for `CompositeVm` and
`GroupVm`.

## 2. Decision

Decided under the owner's 2026-11-07 delegation for open design choices: the
Rust join goes in the shared child-transition helper, next to the construct
join. The rule follows ADR-0218 rule 6.

1. When `run_child_transition` starts a destruct and the child refuses it with
   `InvalidLifecycleTransition`, the walk checks the child's status. If the
   status is `Destructing` or `Destructed`, another starter started the
   destruct. The walk then waits for the child to settle at `Destructed`, as a
   destruct walk does for a destruct in flight. The refusal does not fail the
   walk. §3 gives the outcome when the joined destruct fails.
1. The status check covers a destruct that finishes before the check. The walk
   then joins the finished destruct and succeeds.
1. A refusal at any other status keeps its error. A child in `Constructing`,
   or one that is `Disposed`, is not a destruct in flight. Joining it would
   wait on a transition that nobody started as a destruct.
1. The construct publication-pending flag does not count for a destruct. It
   marks a sealed construct, so joining it would wait for a destruct that no
   starter began.
1. The construct branch of `run_child_transition` does not change.
1. The shared helper serves `CompositeVm`, `GroupVm`, `AggregateVm1` to
   `AggregateVm6` and the `ComponentVm` leaf walk. The call sites do not change.
1. C# and Swift keep their code. Each joins a destruct that another thread
   started, including one that finished before the join check. C# returns a
   completed task for a child already `Destructed` (`DestructOrJoinAsync`), and
   Swift accepts a child already at the target status. Python keeps its code.
   It joins a destruct still `Destructing` at the join check, but it re-raises
   the refusal when the destruct finished first. §5 records that divergence.
   TypeScript has one thread, so the race does not arise.

This amends ADR-0218 §2.3, which deferred the Rust destruct-walk join, and §3,
which said the Rust destruct walks keep their missing join. ADR-0218 rule 6
stays as written.

## 3. Consequences

- A Rust container destruct no longer fails when another thread starts the same
  child's destruct between the status read and the call. The walk joins that
  destruct.
- A joined destruct that fails does not make the call return an error. The walk
  returns `Ok(())`, the container rolls back to `Constructed`, and
  `background_errors()` reports the child's settle as
  `child <id> settled at Constructed instead of Destructed`. The hook's own
  error is not reported there. The walk did not start the failing destruct, so
  it has no synchronous error to return. This follows the background-failure
  path that chapter 02 §6 allows, and the convention that LIFE-017 tests for a
  background child (`background_child_failure_rolls_parent_back`). A walk that
  starts a failing destruct itself still returns that error, as before.
- A refused destruct at any other status still fails the walk, as before.
- The Rust parity ledger closes §12.14.
- The `ComponentVm` leaf walk uses the same helper, so a refused destruct there
  joins as well. ADR-0218 rule 6 already requires this, and it is not a new
  rule.
- The generic `AggregateVm<T>` calls each member's `destruct()` with no walk
  and no join. It is outside the fixed-arity families of `spec/08`, and this
  ADR does not change it. That gap is a separate follow-up.

## 4. Conformance

This ADR adds no conformance ID. The behavior is already normative in ADR-0218
rule 6 and in chapter 02 §6. No catalogued ID covers a container destruct join.
`LIFE-020` covers only the leaf in-transit join, and `COMP-054` and `GRP-017`
cover rule 7 of ADR-0218.

The regression tests in `langs/rust/tests/conformance/destruct_start_race.rs`
cover the join for `CompositeVm`, `GroupVm`, `AggregateVm1` to `AggregateVm6`,
and the `ComponentVm` leaf walk (`ChildTransitions`). Each container has three
cases. In the first, the other destruct is still in flight when the walk
checks. In the second, the other destruct finishes before the walk checks. In
the third, the other destruct fails, so the outcome in §3 applies. The leaf
walk reads the child's status before its call, so its second case pauses the
walk before that call and then reaches the refused call. ADR-0218 §2.3 used
regression tests for rules 3 to 6 in the same way.

## 5. Known divergence

Python's `_destruct_future` in `langs/python/src/vmx/components/base.py`
re-raises a refused destruct when the destruct finished between the refusal and
the join check. C# and Swift accept that case, and so does Rust under this ADR.
A probe on 2026-11-12 confirmed the Python behavior. The root's `destruct()`
raised `StatusTransitionError` and rolled back to `Constructed`. The Python
race test in `langs/python/tests/unit/composites/test_construct_start_race.py`
covers only the in-flight join. Python keeps its behavior in this change.
Closing the gap is a Python change, and it needs its own test. CLAUDE.md §1
requires this divergence to be recorded. The parity ledger (§12.14) cites this
section.

Follow-ups, not in this change:

- Python joins a destruct that finished between its refusal and its join check,
  as C# and Swift do (§5).
- The construct window in the leaf helper has the same refused-start gap, by
  code reading only.
- The generic `AggregateVm<T>` gap in §3.

## 6. Rejected alternatives

- **Swap the walk's call to `transition_or_join_child`** (the issue's proposal).
  The status check and the call are not atomic, so the race remains. The race
  test reproduced the failure.
- **Join on any refusal.** A refusal from `Constructing` or `Disposed` is not a
  destruct in flight. Joining it would wait on the wrong transition.
- **Count the construct publication-pending flag as a destruct in flight.** The
  flag marks a sealed construct, so the join would wait for a destruct that no
  starter began.
- **Bump the spec to 3.31.0.** A spec minor bump moves `MIN_SPEC_VERSION` and
  the version of every flavor (README §6.1, `tools/check-version-consistency.py`).
  The behavior is already normative, and the same in-development line carried
  ADR-0218 and ADR-0226. A release owner can decide the spec version at release
  prep.
- **Return the joined child's error from the walk.** The walk did not start the
  failing destruct. §3 keeps the join on the background-failure path that a
  background child's failure already uses (LIFE-017). A synchronous error would
  make a join differ from that path.
