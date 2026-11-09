# ADR 0189 — A disposed child leaves `Current`, and container walks skip it

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 02 §3, §6 and §6.1; chapter 06 §3, §4.3
  and §5; chapter 07 §2; chapter 08 §3)
- **Extends:** [ADR-0173](0173-selection-commits-without-a-membership-transaction.md)
  §2 rules 2 and 6. Related: #1317, #1383,
  [ADR-0175](0175-inline-dispose-cascade-refuses-lifecycle-transitions.md),
  [ADR-0179](0179-foreign-dispose-publishes-disposed-first.md).

## 1. Context

A consumer can call `dispose()` on a child that is still a member of a
container. Chapter 05 §6.1 clears the child's `Parent` only on removal, so the
child stays a member. Two defects follow.

- **`Current` keeps a disposed child (#1317).** In all five flavors, a direct
  `dispose()` of the `Current` child leaves it `Current`, with `IsCurrent`
  true. `can_select_component` refuses the same child. In Python and TypeScript,
  `a.IsCurrent` stays true even after `Current = null`. Invariant 3 makes a
  selection change on a `Disposed` VM a silent no-op.
  C# and Swift skip the flag change in the same way. Rust commits
  the flag with no disposed check. `TreeSelection` already clears its
  selection when the current node is disposed (`HIER-038`) and refuses a
  disposed node (`HIER-034`).
- **Walks fail on a disposed child (#1383).** A container `destruct()` walk
  calls `destruct()` on every child that is not at the target status. That
  call raises on a `Disposed` child (invariant 3), so every `destruct()` and
  `reconstruct()` of the container fails, and the container stays
  `Constructed`. A composite or group recovers only when the caller removes
  the child. An aggregate cannot remove a slot, so `dispose()` is its only
  exit. Chapter 02 §6 did not say whether a walk skips, detaches or fails on
  a `Disposed` child.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: every flavor follows the
same rule, and the simplest rule wins.

### 2.1. Rules

1. **Walks skip a `Disposed` child.** A container construct or destruct walk
   skips a child that is `Disposed` when the walk reaches it. It also stops
   waiting for a child that reaches `Disposed` while the walk waits for it.
   Neither case fails the walk, and the walk calls no lifecycle operation on
   the child. The rule covers `CompositeVM`, `GroupVM`, the slots of
   `AggregateVM1` to `AggregateVM6`, the joined children of factory
   population, and the child-transition helper of chapter 02 §6.1. A
   container `construct()` or `destruct()` completes when every child that is
   not `Disposed` reaches the target status. A child in its inline dispose
   cascade is not `Disposed` yet. A walk call on that child fails under
   `LIFE-021`, and the container rolls back.
1. **Membership stays.** A composite or group keeps a `Disposed` child as a
   member until a consumer removes it. A disposed child does not remove
   itself.
1. **The aggregate exit.** An `AggregateVM` that holds a `Disposed` slot
   leaves `Constructed` through `destruct()` or `reconstruct()`. Its next
   construct replaces every slot from the slot factories, as chapter 08 §2
   already requires.
1. **A `Disposed` child is not selectable.** For every selection path, a
   `Disposed` child is not a member (chapter 06 §4.3 rule 2). The setter
   raises the non-member error, the walk's assignment and an asynchronous
   delivery are silent no-ops, and `can_select_component` returns `false`.
   The child `select()` path is silent (ADR-0188).
1. **The dispose clear.** When a child publishes `Disposed` from its own
   `dispose()` while it is `Current`, the composite clears `Current` before
   that `dispose()` returns. The clear runs after the child publishes
   `Disposed`, in both disposal orders of ADR-0179. Like the detach clear, it
   clears only while that child is still current and commits under §4.3
   rules 1 and 5. It is not a selection call, so §4.3 rule 4 never refuses
   it. It publishes `PropertyChangedMessage("Current")` once and runs
   `OnCurrentChanged(null)` once.
1. **The composite's own cascade does not clear.** The dispose clear does not
   run while disposal of the composite is requested or deferred, or after the
   composite is `Disposed`. The composite's own dispose cascade therefore
   publishes no `Current` change.
1. **`IsCurrent` of a `Disposed` VM.** When its composite stops making it
   `Current`, a `Disposed` VM's `IsCurrent` becomes `false`. The VM publishes
   no `PropertyChangedMessage` for the change. A change to `true` stays a
   silent no-op. Chapter 02 §3 invariant 3 states this exception.

### 2.2. Decided under the owner's delegation

- **Skip, not detach or fail.** A skip needs one status check in the walk.
  A detach on dispose would add a structural change, with its transaction,
  hub messages and rollback, to every `dispose()`. A failure leaves an
  aggregate with no exit except `dispose()`. A `Disposed` child has no state
  that a walk can change, so skipping it loses nothing.
- **Skip also while waiting.** A child that a concurrent `dispose()` reaches
  during the walk is as final as a child that was `Disposed` before. One rule
  for both is simpler than a skip that applies only before the walk starts
  the child.
- **Clear `Current`, not keep it.** A `Disposed` child cannot be selected,
  shown or edited. Keeping it `Current` leaves a selection that
  `can_select_component` refuses. The clear matches `HIER-038`.
- **Clear after `Disposed`.** A clear before `Disposed` would run
  `OnCurrentChanged(null)` while the child is still selectable, so the
  callback could select it again. After `Disposed`, rule 4 refuses that
  selection. The flag change of rule 7 then needs no child message, which
  invariant 3 forbids.
- **Non-member error for rule 4.** The setter already raises it for a
  child that is not selectable as a member. No flavor adds an error type.
- **Conformance IDs.** `LIFE-022` covers rules 1 to 3 and the helper.
  `COMP-050` covers rules 4 to 7. The wait case of rule 1 needs a background
  child, so it stays a regression test in each flavor.

## 3. Flavor impact

The implementation PR confirms the exact sites.

- **C#.** `TransitionChildrenAsync` skips a `Disposed` child and accepts
  `Disposed` after the await. `CommitIsCurrent(false)` sets the flag on a
  disposed VM and returns `false`. `ComponentVMBase` calls a new
  `IParentCompositeVM.ChildDisposed` after it publishes `Disposed`.
  `SelectionRefusalLocked` treats a `Disposed` value as a non-member.
- **Python.** `_transition_children` and the joined-child settle skip a
  `DISPOSED` child. `_commit_is_current(False)` sets the flag on a disposed
  VM and returns `False`. `_dispose_at_hook_boundary` calls the parent's
  dispose clear after the `DISPOSED` publication. The clear checks the
  composite's own disposal again at its commit.
  `_selection_refusal_locked` treats a disposed value as a non-member.
- **TypeScript.** `#walkChildren` skips a `Disposed` child, and its wait
  settles successfully for one. `_commitIsCurrent(false)` sets the flag on a
  disposed VM and returns `false`. `dispose()` calls the parent's dispose
  clear after `_setStatus(Disposed)`. `#isAdmittedMember` callers refuse a
  disposed value.
- **Swift.** `_transitionChildren` and the container walks skip a
  `.disposed` child. Swift commits a disposal under `lifecycleLock`, but it
  can apply the queued `.disposed` status later, while another thread drains
  the child's lifecycle publications. The walk therefore also skips a child
  whose disposal is committed. During the inline dispose cascade neither
  condition holds, so Swift does not skip the child, as the other flavors do
  not. `_commitIsCurrent(false)` sets the flag once disposal is
  requested and returns `false`. A new internal `ChildDisposalObserver`
  protocol carries the dispose clear. Only `CompositeVM` adopts it, so the
  public `ParentVM` protocol does not change. `isAdmittedMemberLocked`
  callers refuse a disposed value.
- **Rust.** `run_child_transition` returns `Ok(())` for a `Disposed` child,
  and `child_settled_result` accepts `Disposed`. On a `Disposed` node,
  `commit_current_flag(false)` sets the flag and returns `false`, and
  `commit_current_flag(true)` changes nothing. `ParentHandle` gains a dispose-clear closure that the core
  calls after it publishes `Disposed`. `is_selectable_member_locked` refuses a
  disposed node.

## 4. Conformance

`LIFE-022` and `COMP-050` are new. With the two IDs of ADR-0188, the catalog
grows from 451 to 455 library IDs (460 in total).

## 5. Consequences

- A container that holds a directly disposed child still destructs,
  constructs and reconstructs. An aggregate with a disposed slot recovers
  through `destruct()` or `reconstruct()`.
- Disposing the `Current` child clears `Current` in every flavor, and the
  child reads `IsCurrent == false`.
- Setting `Current` to a `Disposed` child raises the non-member error. In
  Swift, the `current` setter traps for it, as for any non-member.
- `construct()` of a composite or group can reach `Constructed` while a
  member is `Disposed`. Consumers that need every member live remove the
  disposed child.
