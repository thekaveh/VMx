# ADR 0180 — Nested `FormVM` updates notify at the outermost update

- **Status:** Accepted
- **Date:** 2026-11-08
- **Spec version:** 3.30.0 (chapter 20 §5.2, §5.3, §5.4, §5.5 and §10)
- **Extends:** [ADR-0174](0174-formvm-queues-updates-during-approval-publication.md)
  and [ADR-0176](0176-form-publication-waits-join-the-wait-for-graph.md).
  Related: [ADR-0143](0143-formvm-single-flight-approval.md), #1057, #1173.

## 1. Context

A preparation callback of `SetModel` or deny can call `SetModel`, deny or an
approve call on the same form (chapter 20 §5.4, `FORM-037`). The spec did not
say when that nested call sends its notifications (#1173). Probes at
`fd5b9e14` gave two results:

- C#, Python, TypeScript and Rust send them before the nested call returns.
  C# and Python send them while the outer call holds the form's state lock.
  ADR-0176 rule 1 left this as the one delivery under a lock.
- Swift queues them for the outermost update on the thread, which sends them
  after it releases the state lock (#1057). Without the queue, a Combine sink on
  another thread could wait for the lock while it held a delivery lock. Swift
  also queues the notifications of an update made from an `errorsChanged` sink
  of `setModel` or deny.

Three related gaps came from the same probes:

- **Disposal before the persister starts.** Python and Swift start the
  command-path persister in a scheduled task. Swift checks for disposal before
  the persister starts, and Python does not. C#, TypeScript and Rust call the
  persister before `Execute()` returns. Chapter 20 §10 did not cover a
  `Dispose()` after admission but before a deferred persister start.
- **Waits from a nested call.** While another thread holds a publication
  scope, a nested call waits in C# and Python, and their waits release the
  outer callback's lock. Swift takes the refused-wait result, and Rust commits
  without waiting (ADR-0176 §3.1).
- **Hub order.** An update made from an `ErrorsChanged` observer sends its
  model message before the outer update sends its own in C#, Python, TypeScript
  and Rust. The two messages then reach the hub out of commit order.

## 2. Decision

### 2.1. Owner decision

The owner delegated #1173 and chose option 2, *queue for the outermost update*,
for all five flavors. A `Dispose()` after admission but before the persister
starts prevents the persister call in every flavor.

### 2.2. Rules

Chapter 20 §5.4 (*Nested updates*) states these rules. Bare section numbers
refer to chapter 20.

1. **Nested calls.** A call is *nested* when its thread is running a
   `SetModel` or deny and the call comes from one of these places:

   - a preparation callback of that update: an equality comparison, a
     validator, or the snapshotter of deny; or
   - an `ErrorsChanged` observer that the outermost update is delivering.

   Nested calls are `SetModel`, deny, `ApproveAsync` and
   `ApproveCommand.Execute()`. The first `SetModel` or deny on the thread is the
   *outermost update*. A call from a `CanExecuteChanged` observer or a hub
   subscriber is not nested. It notifies at once, as §5.2 states.

1. **State work at once.** A nested `SetModel` or deny prepares and commits at
   once, and it wins over the update it interrupted (§5.4). A nested approve
   call is admitted or refused at once (§5.3). A nested call in a
   pre-publication window (§5.3), or one that takes a refused-wait result
   (§5.5), is queued as a call. It has no notifications.

1. **Queue.** A nested call sends no notification before it returns. It adds
   its notifications to the queue of the outermost update on its thread. The
   outermost update adds its own notifications to the same queue.

1. **Send.** The outermost update sends the queue before it returns, with no
   form lock held. First it sends each `ErrorsChanged`, in commit order, inside
   the update scope of its commit (§5.5). Then it sends the other notifications
   in the order the calls committed or were admitted. Each update keeps its
   §5.2 order.

1. **Persister start.** The persister of a nested approval starts after the
   outermost update sends the queue, and before that update returns. A flavor
   that starts the command-path persister in a scheduled task schedules the
   task at that point. The outermost update then replays its §5.5 queue.

1. **Outcome.** A nested approval routes its outcome as §5.3 states, when it
   settles. The awaiter of a nested `ApproveAsync` receives it, and the command
   path uses `ApproveErrors`.

1. **No wait.** A nested call never waits for another thread's publication
   scope. While another thread holds a scope, the call takes the refused-wait
   result of §5.5 for its kind. A `SetModel` or deny prepares and joins that
   publisher's queue. An approve call is admitted without waiting.

1. **Disposal drops queued notifications.** A notification that a nested call
   queued is not sent once the form is disposed. The outermost update checks
   for disposal before it sends each one. This is the rule for queued calls,
   which replay as no-ops after disposal (ADR-0176 rule 5). The outermost
   update's own notifications keep their §5.5 behavior.

1. **Disposal before the persister starts.** A `Dispose()` after an approval's
   admission, but before its persister starts, prevents the persister call
   (§10). This applies to every approval, nested or not. The approval then
   settles silently: it sends no notification and no outcome, and the awaiter
   of `ApproveAsync` completes normally.

### 2.3. Choices made under the owner's delegation

The owner delegated the remaining design questions to one principle. All
flavors follow the same specs as much as possible, with the simplest and most
common-sense approach chosen.

- Decided under the owner's 2026-11-08 delegation: the queue also covers calls
  from an `ErrorsChanged` observer of the outermost update, as in Swift since
  #1057. Model messages then reach the hub in commit order, and no flavor
  delivers an update's notifications inside another update's delivery.
- Decided under the owner's 2026-11-08 delegation: error maps go first, each in
  its update scope. This keeps the ADR-0176 rule that error maps reach
  observers in commit order. It is the Swift order.
- Decided under the owner's 2026-11-08 delegation: the persister of a nested
  approval starts after the whole queue. `CanExecuteChanged` of the admission
  then precedes the persister, as §5.3 requires, in every flavor.
- Decided under the owner's 2026-11-08 delegation: a nested call never waits,
  and takes the refused-wait result. This is the Swift behavior. A wait in C#
  and Python releases the outer callback's lock, so another thread can update
  the form inside that callback. A commit without a wait, as in Rust, can let
  `OnApproved` observers see another thread's edit, which ADR-0174 rule 7
  forbids.
- Decided under the owner's 2026-11-08 delegation: disposal drops the queued
  notifications of nested calls. A disposed form publishes nothing new (chapter
  02 §3 invariant 6, §10), and settlement after disposal is already silent
  (§5.3). Sending them, as Swift does today, was rejected. Observers would
  then see notifications from a form that its owner already disposed.
- Decided under the owner's 2026-11-08 delegation: the outermost update's own
  notifications keep their current §5.5 behavior. This ADR changes only when
  nested calls notify. It does not change a delivery that has started.
- Decided under the owner's 2026-11-08 delegation: a disposal before the
  persister starts settles the approval silently. This is §10 for a disposal
  during persistence, applied one step earlier. The awaiter completes normally,
  as a call on a disposed form does.
- Decided under the owner's 2026-11-08 delegation: Rust `approve()` is
  synchronous, so a nested call cannot wait for its deferred approval. A nested
  `approve()` returns `Ok(())` once it is admitted. The deferred approval
  routes a failure to `approve_errors`, as the command path does. A panic
  resumes from the outermost update after its queue and replays, unless an
  earlier panic wins (#740).
- Decided under the owner's 2026-11-08 delegation: a callback that blocks
  until a nested approval settles never returns, and the spec records this as
  a limitation. The approval's persister cannot start before the callback
  returns without breaking rule 5. A blocking wait inside a preparation
  callback already deadlocks in the §5.5 limitation. Refusing a nested
  awaitable approval was rejected, because a call that does not block would
  then lose its approval.
- Decided under the owner's 2026-11-08 delegation: a nested approval no longer
  commits during the preparation that it interrupts. In C#, TypeScript and Rust
  its persister ran there, and its commit made the outer update stale. The
  outer update now commits, and the approval races it as an edit during
  persistence (§5.3). This is the Swift and Python behavior. No user edit is
  lost.

## 3. Flavor impact

- **C#.** `SetModel`, `Deny` and approval admission count the nested window per
  thread, as Swift does with `preparationDepth` and `scopedDeliveryThreads`.
  A nested call queues its `ErrorsChanged`, `CanExecuteChanged` and hub
  messages, and the outermost update sends them after `_stateGate` is
  released. `ApproveCoreAsync` defers the admission notification and the
  persister call of a nested approval to the outermost update.
  `WaitForForeignScopes` does not wait in the nested window and returns the
  foreign publisher instead.
- **Python.** `set_model`, `_deny` and `_admit_approval` follow the C# design.
  `_approve_fire_and_forget` schedules the task of a nested approval after the
  queue is sent. `_run_admitted_approval` checks for disposal before it calls
  the persister. `_wait_for_other_publication` does not wait in the nested
  window.
- **TypeScript.** `setModel`, `#deny` and `approveAsync` queue the
  notifications of nested calls, and the outermost update sends them before it
  returns. `approveAsync` defers the admission notification and the persister
  call of a nested approval. TypeScript runs on one thread, so rule 7 does not
  apply.
- **Rust.** `set_model`, `revert` and `admit_approval` queue the notifications
  of nested calls. `approve()` defers the persister and the settlement of a
  nested approval to the outermost update, and returns `Ok(())`. `serialize()`
  returns the foreign publisher for a nested call instead of letting it commit.
- **Swift.** `deliver` sends the queue as before, but starts the persister of a
  nested approval after the last notification. It skips the queued notices of
  nested frames once the form is disposed. The other rules already hold.

Tests that assert the old timing change. They are the nested-approval cases of
`FORM-037` in C#, TypeScript and Rust, and any test that expects a nested
call's notifications before it returns. The implementation PRs name each one.

## 4. Conformance

- `FORM-041` covers the timing and order: a nested call returns before its
  notifications, and all of them arrive before the outermost update returns.
  It also covers an update from an `ErrorsChanged` observer.
- `FORM-042` covers disposal: a nested approval followed by `Dispose()` never
  calls the persister, queued notifications are dropped, and a `Dispose()`
  before a scheduled persister start prevents the call.

The catalog grows from 448 to 450 library IDs (455 in total).

## 5. Consequences

- A nested `SetModel` or deny returns before its notifications. Code after the
  nested call reads the committed state, but its observers have not run yet.
- An approval started from a validator persists after the outer update returns
  its notifications, in every flavor.
- A callback that blocks on a nested approval's awaitable, such as Python
  `asyncio.run(form.approve_async())` in a validator, now never returns. The
  Python test that did this changes to the command path.
- No flavor delivers a form notification while it holds the state lock. The
  exception in ADR-0176 rule 1 is closed.
- A nested call never waits, so the §5.5 flavor note about nested waits is
  closed. The state-lock limitation of §5.5 stays.
- Open decision §1.4 in
  `docs/maintenance/2026-10-18-open-cross-flavor-decisions.md` is closed.

## 6. Rejected alternatives

- **Send before the nested call returns** (option 1). Swift would need a second
  per-form serialization to avoid the #1057 deadlock, and C# and Python would
  keep a delivery under the state lock.
- **Leave the timing flavor-defined** (option 3). The flavors would keep three
  timings, and the persister of a nested approval would start at different
  points.
