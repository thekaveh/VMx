# ADR 0186 — The container construct walk counts members only

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 02 §2.4 and §6; chapter 06 §5.1; chapter
  07 §4)
- **Clarifies:** [ADR-0175](0175-inline-dispose-cascade-refuses-lifecycle-transitions.md)
  rule 3 for the container commit step. Related:
  [ADR-0165](0165-initial-current-uses-committed-membership.md),
  [ADR-0173](0173-selection-commits-without-a-membership-transaction.md),
  #744, #892, #1313, #1374.

## 1. Context

The construct walk of a `CompositeVM` or `GroupVM` constructs each child of a
membership snapshot. With `AutoConstructOnAdd(true)`, it then joins each *late
child*, a child that an add attached and started after the snapshot (chapter
06 §5.1). A *background child* completes its construction asynchronously
(chapter 02 §6). Two questions had no answer in the spec.

**A removal during the walk (#1313).** All five flavors walk the snapshot as
it was taken. A snapshot child that a removal takes out is still constructed.
When the walk waits on a background child and a removal takes it out, the
walk still waits, and a failure of that child rolls the container back. The
container no longer owns that child. Late children follow another rule: the
walk reads the live membership for them, so it skips a late child that a
removal took out before the walk reached it. A late child that fails while the
walk waits on it still rolls the container back after a removal. A failed add
also takes out its child. C#, Python, Swift and Rust then roll the container
back, because the walk waits on the add's start attempt and then joins the
child. TypeScript reads the live membership and skips that child. Open
decision §2.8 recorded the gap.

**The commit-step window (#1374).** PR #892 added a commit step for
`AutoConstructOnAdd(true)` (#744). Under the membership gate, the step joins a
late child that an add started after the walk's last scan. With none left, it
writes `Status = Constructed` in the same gated section. The `Constructed`
publication follows later, when the transition completes. An add in between
reads `Constructed` and follows the add-after-`Constructed` rule, so the walk
does not join its child. A background child added then can still be
`Constructing` when the container publishes `Constructed`. C#, Python, Swift
and Rust have this window. TypeScript writes and publishes the status with no
consumer code in between. Chapter 02 §2.4 says that a transition writes
`Status` and reserves its publication atomically. It did not say that the
commit step writes now and publishes later.

Python has a related defect, found by code reading (#1374). A construct hook
that raises after it started the walk cancels the walk. The walk checks for
the cancel before the commit step, and the commit step does not check again.
`Status` can then read `Constructed` until the hook's rollback runs. Code
reading shows the same order in C# and Swift. They check for an abandoned walk
before the commit step, but not in the locked section that writes the status.

## 2. Decision

### 2.1. Owner decision

The owner delegated #1313 and #1374 on 2026-11-07. Both are decided under
that delegation: all flavors follow the same rules as far as possible, and the
simplest, most common-sense rule wins.

### 2.2. Rules

Chapter 06 §5.1 states these rules, and chapter 07 §4 applies them to groups.

1. **Members only.** A container's `construct()` waits only for its members.
   A *member* is a child in the container's membership when the walk checks
   it. The rule is the same for snapshot children and late children, with and
   without `AutoConstructOnAdd(true)`.
1. **Check before the start.** Before the walk starts or joins a child, it
   checks under the membership gate that the child is a member. It skips a
   child that is not. A late child whose add is still in its start attempt is
   checked after that attempt.
1. **Check after the settle.** After a child settles, the walk checks again.
   When the child is no longer a member, its result does not change the
   container: a failure does not roll the container back, and the walk goes on
   to the next child. A removal does not stop the wait. The walk goes on when
   the removed child settles.
1. **A removal does not touch the child's lifecycle.** A removal does not
   cancel, destruct or dispose the child. A child that the walk started before
   the removal finishes its own transition and can reach `Constructed`.
1. **The commit step writes and reserves.** The commit step writes
   `Status = Constructed` and reserves the `Constructed` publication, under
   the lifecycle guard, in the section that holds the membership gate. The
   publication follows when the transition completes. Between the two:
   - `Status` reads `Constructed`.
   - The transition is still in flight. `construct()`, `destruct()` and
     `reconstruct()` raise as for an in-flight transition (`LIFE-008`), and
     the `can_*` predicates return `false`.
   - An add follows the add-after-`Constructed` rule. The walk does not join
     its child.
   - Only `Disposed` can replace the reserved publication (ADR-0175 rule 3).
1. **A stopped walk does not commit.** A walk that disposal stopped, or that
   its construct hook abandoned by raising after it started the walk, commits
   nothing. The commit step checks this under the same lock as the status
   write, so no other thread can stop the walk between the check and the
   write.

The four removal cases of #1313 then give these results. In each case the
removed child has a construct hook that fails. In cases 2 to 4 an add or the
walk has started the child, and the hook fails after the removal.

| Case                                                                  | Walk                                             | Removed child                                      | Container                              |
| --------------------------------------------------------------------- | ------------------------------------------------ | -------------------------------------------------- | -------------------------------------- |
| 1. A snapshot child is removed before the walk reaches it.            | Skips it.                                        | Not started, so its hook never runs: `Destructed`. | `Constructed`; `construct()` succeeds. |
| 2. A snapshot background child is removed while the walk waits on it. | Waits until it settles, then ignores the result. | `Destructed` after its own rollback.               | `Constructed`; `construct()` succeeds. |
| 3. A late child is removed while the walk waits on it.                | Waits until it settles, then ignores the result. | `Destructed` after its own rollback.               | `Constructed`; `construct()` succeeds. |
| 4. A late child is removed before the walk reaches it.                | Skips it.                                        | `Destructed` after its own rollback.               | `Constructed`; `construct()` succeeds. |

A child that the add itself takes out, because its own construction failed
during the add, is a case 3 or case 4 removal. The add fails and is undone,
and the container does not roll back.

### 2.3. Choices made under the owner's delegation

- Decided under the owner's 2026-11-07 delegation: #1313 option B, skip
  removed children. The container owns its members only, so its outcome
  depends on its members only. Option A, keep the snapshot, rolls a container
  back for a child that it does not own, and it keeps two rules: one for
  snapshot children and one for late children.
- Decided under the owner's 2026-11-07 delegation: the walk keeps waiting on
  a child that a removal takes out, and ignores the result. A removal does not
  tell a running walk in any flavor. A new signal from the removal to the walk
  adds a step to five flavors. The settle of the child already wakes the walk.
- Decided under the owner's 2026-11-07 delegation: a failed add's own undo is
  a removal. The add reports its failure to its caller. A container that rolls
  back too reports the same failure twice, for a child that it never admitted.
  TypeScript already behaves this way.
- Decided under the owner's 2026-11-07 delegation: #1374, the add follows the
  add-after-`Constructed` rule. The walk cannot join an add in the window
  without one of two changes. Either the publication waits for a background
  child on the publishing thread, which adds a blocking wait. Or `Status`
  stays `Constructing` until the publication, but then an add that reads
  `Constructing` needs a walk that has already ended. The commit step is the
  boundary: an add before it is joined, and an add after it is not.
- Decided under the owner's 2026-11-07 delegation: chapter 02 §2.4 names the
  commit step as a status write whose publication follows, rather than an
  exception to atomicity. The write and the reservation stay one step under
  the guard. Only the delivery comes later, as for any queued lifecycle
  publication.
- Decided under the owner's 2026-11-07 delegation: rule 6 applies to every
  threaded flavor, not only to Python. The same check-then-write order exists
  in C# and Swift. Rust checks the transition generation in the locked
  section, and its implementation PR confirms it with the same test.
- Decided under the owner's 2026-11-07 delegation: `COMP-047` and `GRP-015`
  cover rules 1 to 4, because a host can drive the four cases on one thread
  in every flavor. The commit-step window and rule 6 need test seams that
  differ by flavor, so they stay regression tests, as in ADR-0175.

## 3. Flavor impact

- **C#.** `ContainerConstructWalk.Enumerate` yields a snapshot child only if
  it is still in `_children` under `_membershipGate`. `TransitionChildrenAsync`
  takes a membership predicate from the container. After a child settles, a
  child that is not a member does not fail the walk. A late child's join after
  its add's attempt also checks membership first. `MarkConstructedBeforePublication`
  also checks that the hook scope is not abandoned. `RunLifecycleHook` sets
  `Abandoned` under `_gate`.
- **Python.** `construct_walk` yields a snapshot child only if it is a
  member. `_transition_container_children` takes a membership predicate and
  applies it before the start or join and after the settle. The commit step
  checks under `_lifecycle_lock` that the walk is not cancelled. The hook's
  cancel of the walk is recorded under the same lock.
- **TypeScript.** `constructWalk` yields a snapshot child only if it is in the
  live children. `#walkChildren` takes a membership predicate and ignores the
  settle of a child that is not a member. Late children already follow the
  rule. TypeScript has no commit-step window.
- **Swift.** `ChildTransitionWalker` takes a membership predicate. It skips a
  child that is not a member before it starts or joins it, and it ignores the
  settle of such a child in `childSettled` and `advance()`. `_flipConstructedForSeal`
  also checks that the walker is not cancelled, under `lifecycleLock`.
- **Rust.** `construct_children` checks membership in each snapshot child step.
  `await_child` and `await_add_then_child` take the membership check, so a
  settle of a removed child does not fail the transition. `flip_constructed`
  keeps its generation check. A test confirms that an abandoned walk commits
  nothing.

Tests that assert the old results change. They are the failed-add late-child
tests in C#, Python, Swift and Rust: the add still fails and is undone, and
the container now reaches `Constructed`.

## 4. Conformance

- `COMP-047` covers the four cases of §2.2 for `CompositeVM`.
- `GRP-015` covers the same four cases for `GroupVM`.

The catalog grows from 451 to 453 library IDs (458 in total) with this ADR.
ADR-0187 adds two more.

## 5. Consequences

- A removal during the walk no longer rolls the container back. The
  container's `Constructed` covers the members it has when the walk checks
  them.
- A child removed before the walk reaches it stays `Destructed`. Before, the
  walk constructed it after its removal.
- A late child whose add failed no longer rolls the container back in C#,
  Python, Swift and Rust.
- A subscriber of the container's `Constructed` can still find a member whose
  add came after the commit step and which is still `Constructing`. The spec
  now states this.
- A construct hook that raises after it started the walk never leaves
  `Status` reading `Constructed`.
- Open decision §2.8 in
  `docs/maintenance/2026-10-18-open-cross-flavor-decisions.md` is decided.

## 6. Rejected alternatives

- **Keep the snapshot** (#1313 option A). A container can roll back for a
  child that it does not own, and snapshot and late children keep different
  rules.
- **Stop waiting at the removal.** Each flavor's removal would need to wake a
  running walk. The settle of the child already does this.
- **Join an add in the commit-step window.** It needs a blocking wait on the
  publishing thread, or a `Status` that reads `Constructing` after the walk
  has ended.
