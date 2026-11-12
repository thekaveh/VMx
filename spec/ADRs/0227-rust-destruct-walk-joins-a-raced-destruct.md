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
   `InvalidLifecycleTransition { from: Destructing }`, the walk checks the
   child's status. If the status is `Destructing` or `Destructed`, another
   starter started the destruct. The walk then waits for the child to settle at
   `Destructed`, as a destruct walk does for a destruct in flight. The refusal
   does not fail the walk. §3 gives the outcome when the joined destruct fails.
1. The status check covers a destruct that finishes before the check. The walk
   then joins the finished destruct and succeeds.
1. A refusal at any other status keeps its error. A child in `Constructing`,
   or one that is `Disposed`, is not a destruct in flight. Joining it would
   wait on a transition that nobody started as a destruct. The source of the
   refusal matters: a refusal from `Disposed` is the inline dispose cascade
   (spec/02 §7.2, LIFE-021). The child reads `Destructed` during that cascade,
   so the status check alone would join it. The walk keeps that error, and the
   outer container rolls back.
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
1. **The settle check cannot lose a failure to a walk that is ending.**
   `child_settled` keeps the child's wait marked while its check runs, and
   clears the wait only when the check succeeds. A failed check is recorded by
   `fail_children`, which marks the wait failed. So a walk that ends its own
   action during the check finds the failure and rolls the container back.
   Before this, `child_settled` cleared the wait first. A walk that ended its
   action in that gap published `Destructed` over a `Constructed` child, and
   the check's failure was dropped. The settle path is shared by every walk
   that waits on a child, so the window is not specific to the join. The join's
   failing case reaches it. With the walk paused as the regression tests pause
   it, the develop body of `child_settled` failed 7 times in 300 runs of
   `destruct_start_race`, and the body in this ADR failed 0 times in 300.

This amends ADR-0218 §2.3, which deferred the Rust destruct-walk join, and §3,
which said the Rust destruct walks keep their missing join. ADR-0218 rule 6
stays as written.

## 3. Consequences

- A Rust container destruct no longer fails when another thread starts the same
  child's destruct between the status read and the call. The walk joins that
  destruct.
- A joined destruct that is still in flight at the join check does not fail the
  call. The call returns `Ok(())` and the walk waits. If the joined destruct
  then fails, the container rolls back to `Constructed`, and
  `background_errors()` reports the child's settle as
  `child <id> settled at Constructed instead of Destructed`. The hook's own
  error is not reported there. The call had already returned when the failure
  became known, so it has no error to return. Blocking the caller until the
  join settles would return it, and §6 rejects that. The failure follows the
  same path as a background child that fails after its call returned, which
  the background-child tests cover (`background_child_failure_rolls_parent_back`).
  A walk that starts a failing destruct itself still returns that error, as
  before.
- The channel depends on whether the walk learns of the failure before its
  call returns. A failure that lands between the join's status read and its
  registration is seen by the walk at once, and the call returns the settle
  message as an `Err`. When the join is registered first, the call returns
  `Ok`, and the failure is reported as above. The rollback to `Constructed`
  is the same in both cases.
- A destruct refused from `Destructing` whose child fails before the check is
  not joined, because the check sees `Constructed`. The walk keeps the refusal,
  `InvalidLifecycleTransition { from: Destructing }`, and the call fails with
  the container rolled back. The error names the refusal, not the settle.
  Python re-raises the refusal in the analogous case where the destruct
  finished first (§5).
- A refused destruct at any other status still fails the walk, as before. A
  refusal from `Disposed` (the inline dispose cascade) keeps its error.
- The Rust parity ledger closes §12.14.
- The `ComponentVm` leaf walk uses the same helper, so a refused destruct there
  joins as well. ADR-0218 rule 6 already requires this, and it is not a new
  rule.
- The generic `AggregateVm<T>` calls each member's `destruct()` with no walk
  and no join. It is outside the fixed-arity families of `spec/08`, and this
  ADR does not change it. That gap is a separate follow-up.

## 4. Conformance

This ADR adds no conformance ID. Three reasons apply to this change:

- ADR-0218 rule 6 and chapter 02 §6 already require the join. The join is not a
  new normative rule.
- The timing rule and the background channel in §3 are how Rust reports a
  failure that its non-blocking call cannot return. No other flavor reports a
  deferred join failure in that form, so a shared ID would describe behavior
  that only Rust exhibits.
- The refusal from `Disposed` is covered by LIFE-021.

The regression tests in `langs/rust/tests/conformance/destruct_start_race.rs`
cover the join for `CompositeVm`, `GroupVm`, `AggregateVm1` to `AggregateVm6`,
and the `ComponentVm` leaf walk (`ChildTransitions`). Each container has three
cases. In the first, the other destruct is still in flight when the walk
checks. In the second, the other destruct finishes before the walk checks. In
the third, the other destruct fails, so the outcome in §3 applies. The harness
pauses the walk at three points. It pauses before the walk's call (`Entry`),
at the refused call (`Refusal`), and after the walk registers its join
(`Settle`). The in-flight and failing cases release the other destruct only
after the walk has registered its join, so the join is in flight when the
other destruct ends. The composite and group cascade tests cover item 3 of §2,
the refusal from the inline dispose cascade. ADR-0218 §2.3 used regression
tests for rules 3 to 6 in the same way.

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

Swift's deferred join failure differs in one more way. Its walker resolves a
child failure that arrives after the walk's call returned to a rollback, with no
error at the call. Its comment says it has no caller to rethrow to
(`ChildTransitionWalker.childSettled`). C# delivers the same failure through the
walk's returned task. Python fails the walk's future. This ADR does not change
Swift.

Follow-ups, not in this change:

- Python joins a destruct that finished between its refusal and its join check,
  as C# and Swift do (§5).
- Swift reports a deferred join failure as a rollback only (§5).
- The construct window in the leaf helper has the same refused-start gap, by
  code reading only.
- The generic `AggregateVm<T>` gap in §3.

## 6. Rejected alternatives

- **Swap the walk's call to `transition_or_join_child`** (the issue's proposal).
  The status check and the call are not atomic, so the race remains. The race
  test reproduced the failure.
- **Join on any refusal.** A refusal from `Constructing` or `Disposed` is not a
  destruct in flight. Joining it would wait on the wrong transition. A refusal
  from `Disposed` is the inline dispose cascade, and that case must keep its
  error (LIFE-021).
- **Count the construct publication-pending flag as a destruct in flight.** The
  flag marks a sealed construct, so the join would wait for a destruct that no
  starter began.
- **Bump the spec to 3.31.0.** A spec minor bump moves `MIN_SPEC_VERSION` and
  the version of every flavor (README §6.1, `tools/check-version-consistency.py`).
  The behavior is already normative, and the same in-development line carried
  ADR-0218 and ADR-0226. A release owner can decide the spec version at release
  prep.
- **Refuse a join that is still in flight.** That reproduces the reported
  failure for the in-flight case. The race tests require that case to succeed
  when the other destruct succeeds.
- **Block the caller until a joined destruct settles, so the call can return
  the failure.** A Rust walk does not block its caller. A walk that waits
  returns, and it resumes on the owner's foreground dispatcher (ADR-0218 rule 3,
  ADR-0187). A joined destruct can need the blocked thread. A destruct hook can
  call the container's `destruct()` from inside the child's own destruct. The
  joined destruct then runs on the caller's stack, and blocking deadlocks. C#
  and Python deliver a deferred failure through the walk's returned task or
  future. Swift resolves it to a rollback, as §5 records. So the in-flight
  failure is reported on `background_errors()`, and the call returns `Ok`.
