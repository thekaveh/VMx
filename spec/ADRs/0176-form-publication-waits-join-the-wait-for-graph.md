# ADR 0176 — `FormVM` publication waits join the wait-for graph

- **Status:** Accepted
- **Date:** 2026-11-08
- **Spec version:** 3.30.0 (chapter 20 §5.3, §5.4 and §5.5; chapter 03 §4.1)
- **Extends:** [ADR-0172](0172-one-wait-for-graph-per-flavor.md) and
  [ADR-0174](0174-formvm-queues-updates-during-approval-publication.md)

## 1. Context

ADR-0174 rule 7 makes another thread's `SetModel`, deny or `Dispose()` wait
while a form publishes an approval. ADR-0172 put every blocking wait between
VMx-owned resources in one wait-for graph per flavor. It left the form wait out,
because that wait had no escape yet (ADR-0172 §2.2). Two issues came from this.

- **#1170 (Swift; C# and Python by inspection).** Thread X publishes a form
  notification, and a sink on X sends on hub `H`. Thread Y drains `H`, and a
  subscriber on Y calls `setModel`, deny or `dispose()` on the form. Y waits
  for X's publication, and X's send waits for Y's drain. The graph never sees
  Y's wait, so neither thread escapes. Nine Swift rows stalled in 3 of 3
  runs. The C# `WaitForApprovalPublisher` and the Python
  `_wait_for_other_publication` wait the same way.
- **The state lock (C# and Python, by inspection).** C# and Python deliver an
  update's `ErrorsChanged` while they hold the form's state lock. C# also
  delivers `ApproveErrors` under a second lock. Another thread's call then
  waits for a lock, not a recorded wait. The `errorsChanged` rows of #1170
  therefore stall in C# and Python through the lock. Swift delivers an
  update's error map inside a publication scope, so its wait is the scope
  wait (#704, #1057).
- **#1160 (Rust).** Rust has no publication wait. Another thread's `approve()`,
  `set_model` and `revert()` run during an approval's publication. A call
  from another thread in the pre-publication window is queued, and another
  thread's settlement replays it. ADR-0174 §3 left rule 7 open for Rust.
  Case 3 of #1160, a nested approval's subscriber edit, was already fixed
  on the base branch.

The flavors also disagree on which spans make other threads wait. C# holds a
scope over an approval's admission notification. C# and Python hold one over
a failed settlement, and Python one over `ApproveErrors`. Swift holds one over
each update's error map. Swift admits another thread's approval during a
publication, and only its commit waits.

## 2. Decision

### 2.1. Rules

Chapter 20 §5.5 states these rules for C#, Python, Swift and Rust. TypeScript
runs on one thread, and no call waits for another thread. Bare section numbers
below refer to chapter 20.

1. **No delivery under a lock.** A form delivers no notification while it
   holds its state lock, or another lock that a form call or `Dispose()`
   waits for. An update nested in a preparation callback keeps its flavor's
   timing until #1173 decides it.
1. **Two scope kinds.** A *publication scope* is a span in which one thread,
   the *publisher*, delivers form notifications while other threads' form
   calls wait. Scopes nest on the publisher's thread. A call never waits for
   a scope that its own thread holds.
   - An **update scope** opens when a `SetModel` or deny commits. The update
     delivers its `ErrorsChanged` in it, then closes it. Its
     `CanExecuteChanged` and hub messages follow, in the §5.2 order. Error maps
     therefore reach observers in commit order.
   - A **settlement scope** opens at settlement step 1 (§5.3). A successful
     settlement closes it when the `OnApproved` delivery returns. This is the
     ADR-0174 publication scope. A failed settlement closes it when its step 3
     `CanExecuteChanged` delivery returns.
   - An approval's admission notification and the `ApproveErrors` delivery
     open no scope.
1. **Waits.** Five calls wait while another thread holds a scope on the form.
   They are `SetModel`, deny, an approve call's admission, a settlement before
   its step 1, and `Dispose()`. Each waits until no other thread holds one.
1. **In the graph.** Each wait in rule 3 records an edge in the flavor's one
   wait-for graph (ADR-0172 rule 1). The resource is the form's publication
   scope, one resource per form. The owner is a publisher. When two threads
   hold scopes, the edge names one, and the waiter records again on wake. A
   publisher removes the edges that name it before it wakes the waiters
   (ADR-0172 rule 3). A wait that closes no cycle blocks.
1. **Refused waits.** A wait that would close a live cycle is refused. The
   call then does not wait, and no call is lost:
   - `SetModel` or deny runs its call-time preparation (ADR-0174 rule 2).
     It then joins the queue of the publisher that its edge named, and
     returns. A call in its own thread's pre-publication window joins that
     thread's queue instead. It changes nothing until it replays, so it
     returns before it takes effect.
   - An approve call is admitted without waiting, under the §5.3 admission
     rules. Its settlement then waits like any other settlement.
   - A settlement commits at once and opens its own scope. Two threads then
     hold scopes, and other calls wait for both. Their notifications can
     interleave, so error maps can reach an observer out of commit order.
   - `Dispose()` marks the form disposed and returns. Later calls follow §10,
     and queued calls replay as no-ops. The publisher continues as if one of
     its own observers had disposed the form at that moment. The §10
     teardown runs once no thread holds a scope on the form. With one
     publisher, that is when its outermost scope ends. The channels complete,
     and the commands are disposed, only then.
1. **Queue and replay.** Each publisher has its own queue. It holds that
   thread's pre-publication calls (ADR-0174 rule 1) and other threads' refused
   updates, in the order they joined it. The publisher replays its queue when
   its outermost scope ends.
   - A settlement replays as ADR-0174 rule 4 states.
   - An update replays after its last notification and before it returns.
   - Each item replays as a new call, in isolation (ADR-0174 rules 4 and 5).
   - After a settlement, the first replay failure follows ADR-0174 rule 6.
     After an update, it propagates from that update after the last replay.
     A failure that the update already carries wins.
1. **Nested approvals.** The pre-publication window belongs to one approval.
   An approval that starts in an outer approval's settlement notifications
   suspends the outer window while it delivers `OnApproved`. An update from
   its subscriber therefore commits at once. The outer window resumes when
   the nested settlement scope closes. The outermost scope replays the queue.

### 2.2. Choices made under the owner's delegation

The owner delegated the remaining design questions to one principle. All
flavors follow the same guidelines and specs as much as possible, with the
simplest and most common-sense approach chosen.

- Decided under the owner's 2026-11-07 delegation: the form wait joins the
  one graph of ADR-0172, keyed per form. A form's scopes release their edges
  before they wake the waiters, so a per-form key leaves no stale edge.
- Decided under the owner's 2026-11-07 delegation: a refused `SetModel` or
  deny is queued, exactly like the publisher's own pre-publication calls. This
  reuses ADR-0174. `OnApproved` observers still see the committed approval
  state, which rule 7 of ADR-0174 promises.
- Decided under the owner's 2026-11-07 delegation: a refused `Dispose()`
  follows ADR-0172 rule 5. It returns before the publication ends only when
  its wait would close a live cycle. The publisher finishes the teardown, so
  no channel completes during another thread's delivery.
- Decided under the owner's 2026-11-07 delegation: another thread's approve
  call waits at admission, as in C# and Python. Swift and Rust change. A
  refused admission admits the call, because a refusal would drop a user's
  approval for a reason the user cannot see.
- Decided under the owner's 2026-11-07 delegation: a refused settlement opens
  a second scope. A persisted approval cannot be refused, and handing its
  settlement to the publisher would hide its failures. ADR-0119 lets a cyclic
  hub batch borrow a scope in the same way.
- Decided under the owner's 2026-11-07 delegation: every threaded flavor uses
  the Swift update scope. It keeps error maps in commit order without a lock
  held during delivery. C#, Python and Rust add it.
- Decided under the owner's 2026-11-07 delegation: the scope set is the same
  in every flavor. C# drops its admission scope. Python drops its
  `ApproveErrors` scope. Swift and Rust add a failed-settlement scope. A
  flavor defers a teardown that would race a delivery outside a scope. C# and
  Python already do this, and Rust and Swift follow (#1228).
- Decided under the owner's 2026-11-07 delegation: a `Dispose()` during a
  delivery outside a scope does not wait for it (#1228). It marks the form
  disposed and returns, and the delivering thread runs the teardown when the
  delivery returns. This is the C# and Python behavior. The deliveries are an
  admission notification, an `ApproveErrors` send, and an update's
  notifications after its `ErrorsChanged`. A `Dispose()` from such a
  delivery's own observer defers in the same way.
- Decided under the owner's 2026-11-07 delegation: a Rust validator
  registration on a live form revalidates as an update (#1231). It waits like
  `SetModel`, sends `errors_changed` in an update scope, and counts as a
  delivery until it returns. A refused revalidation joins the publisher's
  queue, as a refused `SetModel` does. It replays as a new revalidation, so
  neither the registration nor its errors are lost. Committing it at once in
  a second scope was rejected. `OnApproved` observers could then see another
  thread's edit, which ADR-0174 rule 7 forbids.
- Decided under the owner's 2026-11-07 delegation: in its own thread's
  pre-publication window, a Rust revalidation commits at once, as before. It
  is not queued like `SetModel`. The registration is not a model edit, and
  queueing it would change behavior that no ticket reports.
- Decided under the owner's 2026-11-07 delegation: a refused update replays on
  the publisher, and its replay failure takes the publisher's failure route.
  This is ADR-0174 rule 6 applied to one more caller. The call already ran its
  preparation, so a replay failure needs a state change in between.
- Decided under the owner's 2026-11-07 delegation: a nested approval suspends
  the outer window only while it delivers `OnApproved` (#1160 case 3). Rust
  already did so on the base branch. A nested failed settlement keeps the
  outer window, so Python changes.
- Decided under the owner's 2026-11-07 delegation: a refused call in its own
  thread's pre-publication window joins its own queue. That queue holds the
  window's calls (rule 6). C# changes; it used the refused publisher's queue.
- Decided under the owner's 2026-11-07 delegation: the Rust test
  `disposal_during_an_emission_skips_the_callbacks_not_yet_invoked` changes.
  Its dispose now waits for the `OnApproved` delivery, as in the other
  flavors. The #1160 criterion that keeps it unchanged is superseded.
- Decided under the owner's 2026-11-07 delegation: waits for the state lock
  stay outside the graph. The lock is held only while preparation callbacks
  run (§5.4). Chapter 20 §5.5 records the limitation, and no reproduced issue
  needs more.

## 3. Flavor impact

- **C#.** `WaitForForeignScopes` (formerly `WaitForApprovalPublisher`) records
  an edge in `WaitForGraph.Shared`. Each caller takes its rule 5 result when the
  graph refuses the edge. `SetModel` and `Deny` deliver `ErrorsChanged` in an
  update scope, outside `_stateGate`. They deliver `CanExecuteChanged` after the
  scope, without the lock. `ApproveCoreAsync` drops the admission scope but
  keeps its wait. `EmitApproveError` stops delivering under `_approveErrorGate`.
  The publisher state becomes per thread, so two threads can hold scopes. Each
  publisher keeps its own queue, and `Dispose` can defer the teardown to it.
  A call in its own pre-publication window joins its own queue, even when its
  wait was refused.
- **Python.** `_wait_for_other_publication` records its wait in
  `vmx._wait_for_graph.WAITS`, with the same results. `set_model` and `_deny`
  deliver `errors_changed` in an update scope and `can_execute_changed` after
  it, without the lock. `_emit_approve_error` opens no scope and uses the
  mutation count. The publisher state and queues become per thread.
  `_settle_failed_approval` keeps an enclosing approval's window.
- **Swift.** `awaitForeignScopesLocked` (formerly `awaitForeignApprovalLocked`)
  records its wait in `ThreadWaitGraph`, with the same results. `admitApproval`
  waits for another thread's scope. `settleFailedApproval` waits like
  `commitApproval` and opens a scope over its `canExecuteChanged`. The publisher
  state and queues become per thread. `admitApproval` and `emitApproveError`
  count their delivery in `activeMutations`, so `dispose()` defers its
  teardown until it returns (#1228).
- **Rust (#1160).** `approve()` admission and settlement, `set_model`,
  `revert()` and `dispose()` wait for another thread's scope. Each wait
  records an edge in `wait_for_graph`. An update
  holds a scope over its `errors_changed` send. A failed settlement holds a
  scope over its eligibility change. Each publisher keeps its own queue, so
  another thread's settlement never replays it. The `ApprovalPublication` doc
  comment changes. So do the tests
  `another_threads_approval_replays_its_own_deferred_edit` and
  `disposal_during_an_emission_skips_the_callbacks_not_yet_invoked`.
  A `Delivery` span counts the admission notification, an update from its
  commit until it returns, and the command path's `approve_errors` send.
  `dispose()` defers its teardown while one is open (#1228). `revalidate()`
  waits through `serialize()`, opens an update scope, and queues a refused
  run as `QueuedUpdate::Revalidate` (#1231).
- **TypeScript.** No change.

### 3.1. Known differences

Each difference needs two scopes open at once, a preparation callback, or a
disposal, or it cannot be observed. No flavor deadlocks, and the end state is
the same. Chapter 20 §5.5 lists them as flavor notes.

- A call nested in a preparation callback, while another thread holds a
  scope, waits in C# and Python. Swift takes the refused result instead.
  Rust proceeds without waiting. This stays under the §5.5 limitation until
  #1173 decides it.
- A Swift call in its own pre-publication window joins its own queue without
  waiting. C#, Python and Rust wait for another thread's scope first.
- After a refused `Dispose()`, C# and Rust wake the scope waiters at once,
  and they find the form disposed. Python and Swift waiters wake when the
  publisher's scope closes.
- C#, Python and Rust open an update scope only when the update changes the
  error map. Swift opens one at every commit. A scope with no `ErrorsChanged`
  delivery cannot be observed.

## 4. Conformance

This adds no conformance ID and changes no package or specification version.
Every rule is observable only while another thread publishes. `FORM-034`,
`FORM-039` and `FORM-040` keep covering the ordinary paths. Each flavor adds
regression tests for its issue, as ADR-0172 did.

## 5. Consequences

- The #1170 rows finish in every threaded flavor, in both arrival orders.
  When X's send records its wait first, Y's form wait is refused, and Y's
  call is queued or deferred. When Y's form wait comes first, X's send is
  refused and enqueues for Y's drain (ADR-0119). Y's call then proceeds when
  X's scope ends.
- A `SetModel`, deny or `Dispose()` from another thread returns before it
  takes effect only when its wait would close a live cycle.
- In that case, a settlement's notifications can interleave with another
  thread's scope. Error maps can then reach an observer out of commit order.
- A `Dispose()` during a delivery outside a scope returns before the channels
  complete. The delivering thread completes them when that delivery returns,
  in every threaded flavor (#1228).
- Rust applies ADR-0174 rule 7 like the other threaded flavors.
- C# and Python no longer hold a lock while an observer runs, except during
  an update nested in a preparation callback (#1173).
- A preparation callback that waits for another thread, which then calls the
  same form, still deadlocks on the state lock.

## 6. Rejected alternatives

- **Refuse a cyclic `SetModel` or deny.** The caller would lose an update
  that it cannot retry at a better time.
- **Let a cyclic `SetModel` or deny commit at once.** `OnApproved` observers
  could then see another thread's edit, which ADR-0174 rule 7 forbids.
- **Record the C# and Python state lock in the graph.** A lock wait cannot
  take an escape after the lock is taken, and the lock would still be held
  across observers. The update scope removes the lock from delivery instead.
- **Keep each flavor's own scope set.** Another thread's call would wait in
  one flavor and run in another. #1160 shows that difference.
