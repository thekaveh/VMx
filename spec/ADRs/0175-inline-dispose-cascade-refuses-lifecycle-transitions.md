# ADR 0175 — The inline dispose cascade refuses lifecycle transitions

- **Status:** Accepted
- **Date:** 2026-11-08
- **Spec version:** 3.30.0 (chapter 02 §2.4, §2.5, §3, §4, §7.1, §7.2, and §9)

## 1. Context

A container disposes its children, and a leaf view-model disposes its
registered members, before it publishes `Disposed` (`LIFE-013`, `LIFE-018`).
When no construct or destruct hook of the view-model is admitted on another
thread, this cascade runs inline, inside the first `dispose()` call. Until the
cascade ends, `Status` does not read `Disposed`. Chapter 02 §2.4 and `LIFE-015`
cover a hook that is already admitted when disposal starts. They did not cover
the inline cascade window. Two defects came from that gap:

- **A new call during the cascade (#1174).** A child's or member's dispose hook
  can call `construct()` or `destruct()` on the view-model that is disposing
  it. The five flavors gave three results. C#, Python, and Swift published the
  transient status, ran no hook, and returned. Rust returned
  `VmxError::Disposed` and published nothing. TypeScript ran the hook against
  disposed children. Its fixed aggregates called the slot factory again and
  left a new `Constructed` slot behind a `Disposed` aggregate, against
  `LIFE-013`. Open decision §2.11 in
  `docs/maintenance/2026-10-18-open-cross-flavor-decisions.md` recorded the
  split.
- **A commit after the cascade started (#1167).** A `construct()` or
  `destruct()` whose hook returned before the cascade started could still
  commit `Constructed` or `Destructed` while the cascade ran. Subscribers then
  saw a `Constructed` container whose children were `Disposed`, followed by
  `Disposed`. C#, Python, Swift, and Rust containers did this, and so did
  background leaves with members in C#, Python, and Swift. The commit checked
  only for `Disposed`, which the cascade had not published yet.

## 2. Decision

### 2.1. Owner decision (2026-11-07)

#1174, option A, refuse. A `construct()` or `destruct()` call on a container
during its own inline dispose cascade fails with the flavor's lifecycle error.
The call publishes no status and runs no hook. The same rule covers the member
cascade of chapter 02 §7.1: a member dispose hook that calls `construct()` or
`destruct()` on its leaf gets the error.

### 2.2. Rules

Chapter 02 §7.2 (*Lifecycle calls during the inline cascade*) states the rules
for every flavor. The *inline cascade* of a view-model is the part of its first
`dispose()` call that disposes its children (§7) and its registered members
(§7.1) while no construct or destruct hook of the view-model is admitted on
another thread. It starts when that call, under the §2.4 guard, closes hook
admission. It ends when the view-model publishes `Disposed`. A view-model with
no children and no members has no inline cascade. When a hook is admitted on
another thread, disposal publishes `Disposed` first (§2.4), so invariant 3
already applies.

1. **Refuse a new call.** A `construct()`, `destruct()`, or `reconstruct()`
   call that starts during the inline cascade fails with the error that the
   same call raises on a `Disposed` view-model. The call can come from a child
   or member dispose hook, a subscriber, or another thread. The error names
   `Disposed` and the attempted operation: `StatusTransitionException` in C#,
   `StatusTransitionError` in Python, TypeScript, and Swift, and
   `VmxError::Disposed` in Rust. The call publishes no status, admits no hook,
   starts no child work, and calls no slot factory. Every entry point is
   covered: the synchronous call, the background form, and the C# async
   methods. Each delivers the error the way it delivers the error for a call
   from `Disposed`.
1. **The refusal comes first.** The check runs before the idempotent no-op of
   §4, the transition-legality check, and the concurrent-operation check
   (`LIFE-008`). A `construct()` while `Status == Constructed` fails in the
   same way.
1. **No commit after the cascade starts.** Once the inline cascade has
   started, the view-model admits no construct or destruct hook and commits no
   status other than `Disposed`. This covers a transition that started before
   the cascade: its settled commit (`Constructed` or `Destructed`), its
   rollback to the prior settled status after a failed hook, child step, or
   `after` callback, the restore after a failed transient publication, a
   commit that a background transition queued on the foreground scheduler, a
   deferred child-walk completion (#755), and the second phase of
   `reconstruct()`. A dropped commit publishes nothing.
1. **The superseded caller.** A call whose commit rule 3 drops returns as a
   call that `Disposed` superseded returns (§2.4, invariant 6). The
   supersession itself raises nothing. A hook, child, or `after` failure that
   was already propagating still propagates, and Rust returns the hook's own
   result. The in-flight guard is cleared. Until the cascade publishes
   `Disposed`, `Status` can still read the transient or prior status after
   the call returns.
1. **Members.** Rules 1 to 4 apply to the member cascade of a leaf view-model
   in the same way as to a container's child cascade.

### 2.3. Choices made under the owner's delegation

The owner delegated the remaining design questions to this principle: all
flavors follow the same guidelines and specs as much as possible, with the
simplest and most common-sense approach chosen.

- Decided under the owner's 2026-11-07 delegation: a call that #1167 covers
  returns without a supersession error (rule 4). It does not raise the
  lifecycle error, which the #1174 triage review suggested. The line between
  rules 1 and 4 is when the call started. A call that starts during the
  cascade never started any work, so it fails, as a call on a `Disposed`
  view-model does. A call that started earlier ran its hook, and disposal then
  superseded it. Its caller cannot tell whether the dispose call came during
  the hook (`LIFE-015`) or after it (#1167). In every flavor, a call that
  `Disposed` superseded already returns without error (invariant 6: it
  "aborts"). Raising only in the #1167 window would give two results for one
  race. Raising in both windows would change `LIFE-015` in five flavors.
  Neither form would reach a background transition, because its caller has
  already returned.
- Decided under the owner's 2026-11-07 delegation: `reconstruct()` follows the
  same rules as `construct()` and `destruct()`. It is one call that runs both,
  so a `reconstruct()` that starts during the cascade fails (rule 1). A
  `reconstruct()` whose destruct phase ended before the cascade started, for
  example through a `Destructed` subscriber that disposes the view-model,
  starts no construct phase. It publishes no `Constructing`, runs no construct
  hook, and returns as rule 4 says.
- Decided under the owner's 2026-11-07 delegation: the refusal precedes the
  idempotent no-op and the concurrent-operation check (rule 2). For lifecycle
  calls, the view-model then behaves as `Disposed` from the moment the cascade
  starts. A `Disposed` view-model raises on every call, whatever state it had
  before, and the cascade already belongs to `dispose()`.
- Decided under the owner's 2026-11-07 delegation: the error is the exact
  error of a call on a `Disposed` view-model. It names `Disposed`, although
  `Status` still reads the pre-disposal value. A caller that already handles
  the `Disposed` error needs no new case.
- Decided under the owner's 2026-11-07 delegation: the predicates of §2.1
  (`can_construct()`, `can_destruct()`, `can_reconstruct()`) do not change.
  They read `Status`, as they do for an in-flight transition, and `Status`
  does not read `Disposed` during the cascade.
- Decided under the owner's 2026-11-07 delegation: rule 1 covers a call from
  any source, not only from a child's dispose hook. A subscriber or another
  thread that calls during the window gets the same result. One check at the
  start of the call serves every source.
- Decided under the owner's 2026-11-07 delegation: rule 3 covers every status
  commit except `Disposed`, not only `Constructed`. A rollback, a publication
  restore, or a queued foreground commit would show the same contradiction
  as `Constructed`: a status that is not `Disposed` over disposed children.
  C# and Python already set the child-transition abandonment flag when a
  `dispose()` call starts, before the cascade, so an implementation can gate
  on that flag. Disposal publishes `Disposed` at once on the foreign-hook
  path, so the earlier flag has no other observable effect.
- Decided under the owner's 2026-11-07 delegation: rule 3 applies to
  TypeScript too. #1167 excluded it as single-threaded, but a dispose hook can
  drain the foreground scheduler on the same thread. That drain runs a queued
  background commit inside the cascade. `LIFE-021` tests this case in every
  flavor.
- Decided under the owner's 2026-11-07 delegation: ADR-0175 governs hook
  admission and status commits. It does not change when an admitted hook's
  child walk stops (§2.4, `LIFE-015`). #1163 keeps the predicate that C#,
  Swift, and Rust use: the walk stops when the owner is `Disposed` or the
  deferred walk was abandoned.
- Decided under the owner's 2026-11-07 delegation: one new ID, `LIFE-021`,
  covers rules 1 to 5, rather than an amended `LIFE-013`. `LIFE-013` stays the
  depth-first disposal test that it is in every flavor. The cross-thread
  reproductions of #1167 need test seams that differ by flavor, so they stay
  regression tests. Each flavor can tag them `LIFE-021`.

## 3. Flavor impact

The triage of #1174 and #1167 found these changes. The implementation PRs
confirm the exact sites.

- **C#.** `Construct`, `Destruct`, `Reconstruct`, their async forms, and the
  background forms check `_hookAdmissionClosed` under `_gate` before the
  idempotent check and before the transient publication is queued. They throw
  `StatusTransitionException` for `Disposed`. Post-hook commits, including
  rollbacks and the queued background commit, go through the
  abandonment-aware commit (`TrySetDeferredStatus`, which can be renamed).
  `AggregateVM1` to `AggregateVM6` follow the rules once their slots use the
  base cascade (#1166).
- **Python.** `construct()`, `destruct()`, and `reconstruct()` check
  `_hook_admission_closed` under `_lifecycle_lock` before the idempotent
  check, and raise `StatusTransitionError`. Every post-hook commit, the
  background foreground commits, and `_restore_status_after_publication_failure`
  use `unless_abandoned=True`.
- **TypeScript.** Add hook-admission closure to the inline cascade of
  `ComponentVMBase` disposal. That covers composites, groups, `AggregateVM1` to
  `AggregateVM6`, and leaves with members. `construct()`, `destruct()`, and
  `reconstruct()` then throw `StatusTransitionError` for `Disposed`. No slot
  factory runs. A commit after the cascade starts publishes nothing.
- **Swift.** `construct()`, `destruct()`, and `reconstruct()` throw
  `StatusTransitionError` for `.disposed` while `hookAdmissionClosed` is set,
  before the idempotent check. `_commitStatus` and the rollback commit also
  check `hookAdmissionClosed`.
- **Rust.** In `transition_with_body`, move the `hook_admission_closed` check
  ahead of the idempotent arms. The supersession check, the rollback branch,
  and the final commit treat `hook_admission_closed` as superseded. Leaf
  members join the cascade, and the leaf-only paths check admission (#1164).

## 4. Conformance

`LIFE-021` covers rules 1 to 5. A child's dispose hook calls `construct()` or
`destruct()` on a `CompositeVM`, a `GroupVM`, and an `AggregateVM1`. The call
fails with the `Disposed` lifecycle error, no hook or slot factory runs, and
the container publishes only `Disposed`. A member's dispose hook calls
`construct()` on its leaf. A background leaf with a member drains its queued
`Constructed` commit from the member's dispose hook, and the leaf publishes no
`Constructed`. TypeScript runs the aggregate `construct()` case for
`AggregateVM1` to `AggregateVM6`, because each arity has its own dispose
steps.

The catalog grows from 446 to 447 library IDs (452 in total).

## 5. Consequences

- A child's dispose hook that calls `construct()` or `destruct()` on its
  disposing parent now gets an error in C#, Python, Swift, and TypeScript. A
  hook that does not catch it fails, and `dispose()` reports the first
  failure after the mandatory teardown (§7).
- In Rust, `construct()` from `Constructed`, or `destruct()` from
  `Destructed`, during the cascade returns `VmxError::Disposed` instead of
  `Ok(())`.
- Subscribers never see `Constructing`, `Destructing`, `Constructed`, or
  `Destructed` from a view-model after its inline cascade starts.
- TypeScript fixed aggregates no longer leave a new slot behind a `Disposed`
  aggregate.
- Open decision §2.11 is closed.
