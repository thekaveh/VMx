# ADR 0218 — Container rollback errors, walk resumption and single-start children

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 02 §2.4 and §6; chapter 06 §3.2, §4.2
  and §5.1; chapter 07 §1.1 and §4; chapter 11 §4)
- **Extends:** [ADR-0123](0123-preserve-container-causality-and-forwarding-ownership.md)
  §2 and [ADR-0186](0186-container-construct-walk-counts-members-only.md).
  Related: [ADR-0165](0165-initial-current-uses-committed-membership.md),
  [ADR-0175](0175-inline-dispose-cascade-refuses-lifecycle-transitions.md),
  [ADR-0179](0179-foreign-dispose-publishes-disposed-first.md),
  [ADR-0187](0187-membership-changes-never-wait-for-another-thread.md),
  #1305, #1312, #1326, #1369, #1370, #1371, #1372, #1375.

## 1. Context

Eight issues report defects in the container walk and in container rollback.
Each premise was checked again on `develop` at `0de36f35`, after ADR-0186 to
ADR-0190 merged. None of those changes fixed any of the eight.

**The rollback error (#1305).** When a failed add, insert, index replacement
or population also fails its lifecycle compensation, ADR-0123 keeps the first
operation failure as the reported failure. The spec did not say how one error
carries both failures. C# throws an `AggregateException` of the original
failure and every rollback failure. TypeScript throws `ContainerRollbackError`
with the original failure as `cause`. Python raises the first compensation
failure `from` the original failure. Swift returns
`.attachmentFailed(compensationError)`, and Rust returns
`compensation_error.unwrap_or(error)`. Both drop the original failure.

**The selector input (#1312).** Swift passes the walk's pre-walk snapshot to
`Current(selector)` and accepts the pick only when the snapshot contains it.
C#, Python, TypeScript and Rust pass the live membership. So only Swift cannot
select a late child. Chapter 06 §3.2 did not name the input.

**Where a walk resumes (#1326, #1371).** A walk that waits on a background
child resumes in the callback that settles the child. In Python, Swift and
Rust that callback runs on the child's foreground dispatcher. Later sibling
starts, the `Current` change, `IsCurrent` changes and consumer callbacks then
run on the child's foreground, not the container's. C# already resumes on the
container's foreground (#725). A walk that waits on a late child's add
resumes when the add marks its start attempt done. C#, Python, Swift and Rust
mark it done before the add publishes and ends its membership transaction. The
walk can then publish `Constructed` inside that transaction, and a
`Constructed` subscriber that adds a child fails with the "membership
transaction in progress" error. Since ADR-0187, this also holds when the
subscriber runs on another thread.

**Population after a foreign dispose (#1369).** Chapter 02 §2.4 says that a
hook rechecks supersession before any post-hook container action. C#, Python
and Swift call the children factory after the construct callback without that
check. When a foreign `dispose()` superseded the hook, population then fails
with the child-admission error, and `construct()` raises. Rust already checks.
A leaf, and a container with no factory, return without an error.

**Two starters (#1370, #1375).** With `AutoConstructOnAdd(true)`, a child
added while the container is `Constructing` but before the walk's snapshot
has two starters: the add and the walk. Each reads the child status and then
calls `construct()` with no lock held between the two steps. When the other
side starts the child in between, that call fails, and either the add or the
container construct fails although no child construction failed. This holds
in C#, Python, Swift and Rust. The C# destruct walk has the same
check-then-act window (#1375). Python and Swift have it too, by code reading.
Rust container destruct walks never join an in-flight destruct.

**A detached background child (#1372).** Compensation destructs a child only
when it is `Constructed`. When an add fails after it started a background
child, the child is still `Constructing`. The rollback detaches it, and its
scheduled work later makes it `Constructed` with no parent. The same check
exists in all five flavors.

## 2. Decision

### 2.1. Owner decision

The owner delegated these issues on 2026-11-07. They are decided under that
delegation: all flavors follow the same rules as far as possible, and the
simplest, most common-sense rule wins.

### 2.2. Rules

1. **The rollback error carries both failures.** When compensation also
   fails, the reported failure gives access to the original operation failure
   and to the first compensation failure:
   - C#: `AggregateException`. `InnerExceptions[0]` is the original failure,
     and the compensation failures follow in order.
   - Python: the first compensation failure, raised `from` the original
     failure, so `__cause__` is the original failure.
   - TypeScript: `ContainerRollbackError`, with `cause` and `rollbackError`.
   - Swift: `ContainerOwnershipError.attachmentFailed(ContainerRollbackError)`.
     The new public `ContainerRollbackError` has `originalError` and
     `compensationError`.
   - Rust: the new variant `VmxError::ContainerRollback { original, compensation }`, which boxes both errors.
1. **The selector reads the live membership.** `Current(selector)` receives
   the composite's membership when the selector runs, so it sees a late
   child. Its pick goes through the walk's assignment. A pick that is not a
   committed, admitted member stays a silent no-op (chapter 06 §3.2).
1. **A resumed walk runs on the owner's foreground.** A child walk that
   waited, for a child to settle or for an add's start attempt, and did not
   continue at once, continues on the walking VM's own foreground dispatcher.
   This covers the rest of the walk, the `after` step, the commit step and
   the terminal publication. A walk whose waits all end at once runs on the
   calling thread to its end. The rule covers container walks and the
   child-transition helper of chapter 02 §6.1. TypeScript has one thread, so
   it already holds there.
1. **An add's attempt ends with its transaction.** An add marks its start
   attempt done only after it ends its membership transaction: after its
   commit, its local event and its hub message, or after its rollback. A walk
   that waits on the attempt resumes only then, so the container publishes
   `Constructed` outside that transaction.
1. **No population after supersession.** Factory population is a post-hook
   container action. A container whose construct hook a foreign `dispose()`
   superseded does not call its children factory and attaches nothing. Its
   `construct()` returns without an error, as chapter 02 §7.2 says for a
   superseded call. An `add()` during disposal still fails.
1. **One starter for each transition.** A walk, and an add that
   auto-constructs, start a child only when no transition of that child is in
   flight. Each checks this together with its start call, so a start that
   another thread makes between a status read and the call is not repeated.
   - A walk that finds a transition of the child in flight in the walk's
     own direction joins it: a construct for a construct walk, a destruct
     for a destruct walk. This includes one that started after the walk
     read the status.
   - An add that finds a construct of the child in flight does not start it
     again and does not wait for it. The walk joins that construct.
   - A walk that joins a child whose `reconstruct()` is in its destruct phase
     sees the child settle at `Constructed`. The container's `destruct()`
     then fails and rolls back to `Constructed`.
1. **Deferred compensation of a background child.** When a failed attempt
   auto-started a previously `Destructed` child and that child's construct is
   still in flight at the rollback, compensation does not wait. When the
   child's construct settles at `Constructed` and the child has no parent,
   VMx calls the child's `destruct()`. The failed operation and the
   container do not report a failure of that later call. The failure goes
   where a failed fire-and-forget background hook of that child goes
   (chapter 02 §2.5). In TypeScript that is `reportUnhandled`. In Rust it is
   the child's `background_errors()` stream. A
   child that settles anywhere else, or that has a parent by then, is left
   alone. The rollback clears the child's parent before it compensates the
   child, so a child that settles during the compensation call has no
   parent.

### 2.3. Choices made under the owner's delegation

- Decided under the owner's 2026-11-07 delegation: rule 1 requires the
  original failure and the first compensation failure, not every
  compensation failure. Python and TypeScript already carry exactly these
  two. C# keeps its `AggregateException`, which also holds the later
  failures. Swift and Rust add one type each. A list of every failure would
  change three flavors for no caller that needs it.
- Decided under the owner's 2026-11-07 delegation: Swift keeps the
  `attachmentFailed` case and wraps both failures in its `Error` payload. A
  new enum case would break exhaustive `switch` statements in callers, and
  the name matches the TypeScript type. Rust has no `Error` payload variant,
  so it adds one variant.
- Decided under the owner's 2026-11-07 delegation: rule 2 uses the live
  membership, which four flavors already pass. The assignment already refuses
  a pick that is not admitted, so the snapshot check adds no protection.
- Decided under the owner's 2026-11-07 delegation: rule 3 follows C#. A walk
  that never waits stays on the caller, so a synchronous `construct()` keeps
  its synchronous result. Only a walk that already left the caller's call
  stack moves to the foreground.
- Decided under the owner's 2026-11-07 delegation: rule 4 moves the end of
  the start attempt, not the walk's resume point. The walk then needs no new
  wait, and ADR-0186 already marks a failed attempt done after its undo.
- Decided under the owner's 2026-11-07 delegation: rule 6 does not choose a
  fixed starter. Whoever starts the child first starts it, and the other side
  joins or leaves it. A fixed starter needs new state that tells the walk
  which children an add holds before the snapshot. The join already exists.
- Decided under the owner's 2026-11-07 delegation: rule 7 defers the destruct
  rather than waiting for the child. A wait on the adding thread can block
  forever when the background work is queued behind that thread. The
  no-parent check keeps the destruct from hitting a container that adopted
  the child meanwhile.
- Decided under the owner's 2026-11-07 delegation: the Rust destruct-walk
  join stays in the Rust parity backlog, as #1375 asks. Rust container
  destruct walks join no in-flight destruct today, so rule 6 has no window to
  close there yet. The parity ledger records the gap.
- Decided under the owner's 2026-11-07 delegation: `COMP-053` covers rule 2,
  and `COMP-054` and `GRP-017` cover rule 7. A host can drive both on one
  thread in every flavor with a queued background scheduler. Rules 3 to 6
  need thread seams that differ by flavor, so they stay regression tests, as
  in ADR-0186. `COMP-040` now states rule 1, and `LIFE-015` covers rule 5.

## 3. Flavor impact

The implementation PR confirms the exact sites.

- **C#.** Rules 1 to 3: no library change. Rule 4: the add, insert and
  replacement paths of `CompositeVMBase` and `GroupVMBase` mark the start
  record done after `EndMembershipTransaction`, not in
  `ContainerMembership.AutoConstructAttached`. Rule 5: `OnConstruct` of both
  bases skips `PopulateChildren` once disposal is requested. Rule 6:
  `ConstructOrJoinAsync`, `DestructOrJoinAsync` and the add's start call join
  or leave a transition that started in the window. Rule 7: every
  compensation site defers the destruct of a `Constructing` child.
- **Python.** Rule 3: `_transition_container_children` and
  `_transition_children` schedule a resumed `advance()` on the walking VM's
  `_dispatcher.foreground`. Rule 4: `auto_construct_attached` stops marking
  the record done, and each add path marks it done after
  `_end_membership_transaction`. Rule 5: `CompositeVM`, `CompositeVMOf` and
  `GroupVM` skip population once disposal is requested. Rule 6:
  `_construct_future`, `_destruct_future` and the add's start call join or
  leave a transition that started in the window. Rule 7: as in C#.
- **TypeScript.** Rule 7 only: every compensation site defers the destruct of
  a `Constructing` child. TypeScript has one thread, so rules 3 to 6 hold
  already.
- **Swift.** Rule 1: the new public `ContainerRollbackError`. Rule 2:
  `_onConstruct` passes `snapshot()` to the selector and drops its snapshot
  check. Rule 3: `ChildTransitionWalker` resumes `childSettled` and
  `startAttempted` on the walking VM's foreground dispatcher. Rule 4:
  `ContainerSupport.autoConstructAttached` stops finishing the record, and
  each add path finishes it after `endMembershipTransaction()`. Rule 5:
  `CompositeVM` and `GroupVM` skip population once disposal is requested.
  Rules 6 and 7: as in C#.
- **Rust.** Rule 1: the new `VmxError::ContainerRollback` variant, a breaking
  change for an exhaustive `match`. Rule 3: `child_settled` and
  `join_after_add` continue through the container's `Dispatcher::dispatch`.
  Rule 4: `StartAttempt::run` stops finishing the attempt, and each add path
  finishes it after `transaction.finish()`. Rule 5: no change, because
  `populate` already checks disposal. Rule 6: `construct_member` and
  `StartAttempt::run` join or leave a construct that started in the window.
  The destruct walks keep their missing join (§2.3). Rule 7: as in C#.

## 4. Conformance

- `COMP-053` covers rule 2.
- `COMP-054` covers rule 7 for `CompositeVM`, and `GRP-017` covers it for
  `GroupVM`.
- `COMP-040` now requires both failures of rule 1 to be accessible.
- `LIFE-015` now covers rule 5.

This ADR adds three library IDs.

## 5. Consequences

- A caller of a failed container change can read the failure that started
  the rollback in every flavor.
- A Swift selector can pick a late child.
- In Python, Swift and Rust, a walk that waited on another dispatcher's child
  no longer runs consumer code on that dispatcher.
- A `Constructed` subscriber can add a child, also when a late add resumed
  the walk.
- A `construct()` superseded by a foreign `dispose()` returns without an
  error in every flavor, and the factory is not called.
- A race between an add and the walk, or between two walk steps and another
  thread, no longer fails an operation whose child construction succeeded.
- A failed add no longer leaves a background child `Constructed` with no
  parent.
- Open decision §2.7 is decided. Open decision §1.3 is decided for the error
  shape. Its sibling-rollback question stays open.

## 6. Rejected alternatives

- **Every compensation failure** (#1305). It changes Python, TypeScript,
  Swift and Rust for no caller that needs the later failures.
- **Keep the Swift snapshot** (#1312). It keeps one flavor that cannot pick a
  late child, and the assignment already guards the pick.
- **Resume on the child's thread and marshal each emission** (#1326). It
  needs a marshal at every emission site. One hop at the resume point covers
  them all.
- **The add starts, the walk always joins** (#1370). The walk would need the
  add's start record for a snapshot child, which no flavor keeps.
- **Wait for the background child in the rollback** (#1372). It can deadlock
  when the child's work is queued on the adding thread.
