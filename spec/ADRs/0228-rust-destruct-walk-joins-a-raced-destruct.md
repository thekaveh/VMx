# ADR 0228 — Rust container destruct walks join a destruct that another thread started

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
C#, Python and Swift already join it. TypeScript has one thread.

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
   destruct walk does for a destruct in flight. The walk does not fail.
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
1. C#, Python, TypeScript and Swift keep their code. C#, Python and Swift
   already join a destruct that another thread started, and Swift and C#
   accept a child already at the target status. TypeScript has one thread, so
   the race does not arise.

This amends ADR-0218 §2.3, which deferred the Rust destruct-walk join, and §3,
which said the Rust destruct walks keep their missing join. ADR-0218 rule 6
stays as written.

## 3. Consequences

- A Rust container destruct no longer fails when another thread starts the same
  child's destruct between the status read and the call. The walk joins that
  destruct.
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
cover the join for `CompositeVm`, `GroupVm` and `AggregateVm1` to
`AggregateVm6`. Each arity has two cases: the other destruct is still in flight
when the walk checks, and the other destruct finishes before the walk checks.
ADR-0218 §2.3 used regression tests for rules 3 to 6 in the same way.

## 5. Rejected alternatives

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
