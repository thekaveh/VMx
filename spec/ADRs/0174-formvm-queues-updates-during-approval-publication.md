# ADR 0174 — `FormVM` queues updates made during approval publication and replays them after `OnApproved`

- **Status:** Accepted (Extended by ADR-0176 and ADR-0180)
- **Date:** 2026-11-07
- **Spec version:** 3.30.0 (chapter 20 §5.1, §5.3, and §5.4)

## 1. Context

A successful approval commits its reset or snapshot advance, publishes
`ErrorsChanged` and one `CanExecuteChanged`, and then publishes `OnApproved`
(chapter 20 §5.1 and §5.3). Since a40374cd, every flavor queues a `SetModel`
that the approving thread makes before `OnApproved` and replays it afterwards,
so `OnApproved` observers see the settled state. The spec did not describe that
queue. Open decision §2.6 in
`docs/maintenance/2026-10-18-open-cross-flavor-decisions.md` recorded the gap.
Four defects and gaps came from it:

- **A call from `resetOnApproved` (#1168, question 2).** The queue did not
  cover the reset callback. In Swift, a `setModel` called there delivered its
  notifications while the commit held the form's state lock, and it could
  deadlock against a sink on another thread. The reset then overwrote the
  nested commit, so an `errorsChanged` observer could end on a map that did
  not match `errors`.
- **Swift sink delivery (#1168, question 1).** Swift `FormVM` sent its events
  through Combine `PassthroughSubject`s. A `PassthroughSubject` holds a
  delivery lock while a sink runs. A sink that called `setModel`, deny, or
  `dispose()` during publication could close a wait cycle with the publishing
  thread.
- **Deferred `SetModel` failures (#1050).** The queue stored the candidate
  without preparing it. A validator or equality failure therefore surfaced at
  replay, after `OnApproved`, and failed the settled approval. The failure also
  stopped the replay loop, so later queued models were lost. C#, Python,
  TypeScript, and Rust were affected.
- **Deny was not queued.** A deny from a settlement observer committed at once,
  so `OnApproved` observers could see a reverted model. A `SetModel` from the
  same place was queued.

## 2. Decision

### 2.1. Owner decisions (2026-11-07)

- **#1168 question 2, option 1, all flavors.** A `SetModel` or deny called from
  `resetOnApproved` is queued with the other pre-publication updates and
  replays after `OnApproved`. `OnApproved` observers see the reset state. No
  notification is delivered while the form holds its state lock.
- **#1168 question 1, option 3.** Swift `FormVM` delivers its events through
  `VMxConcurrentSubject`, which Swift `ComponentVMBase` already uses. No
  delivery lock is held while a sink runs. C# and Python do not serialize sink
  delivery either. The spec does not change for this answer.

### 2.2. Rules

Chapter 20 §5.3 (*Updates during approval publication*) states the rules for
every flavor. The *pre-publication window* runs on the approving thread from
the start of the post-persist commit (the `resetOnApproved` call, or the
snapshot advance) until `OnApproved` delivery starts. The *publication scope*
runs from settlement step 1 until the `OnApproved` delivery returns.

1. **Queue.** A `SetModel` or `DenyCommand.Execute()` that the approving thread
   makes inside the window is queued. Approve calls and `Dispose()` are never
   queued.
1. **Call-time preparation.** A call runs the disposal admission, the null
   check, and its §5.4 preparation before it is queued. A failure reaches the
   caller, and nothing is queued. Equality never skips the enqueue, and the
   prepared result is discarded. A re-entrant callback that disposes the form
   or makes another update makes the call stale, so it is not queued.
1. **Nothing published at call time.** A queued call changes nothing and
   publishes nothing until it replays.
1. **Replay.** The queue replays in call order on the approving thread when the
   outermost publication on that thread ends. On success, this is after the
   `OnApproved` delivery returns. After a failed post-persist commit, this is
   after the failed settlement's `CanExecuteChanged` and before the failure
   reaches its channel. Each item replays as a new call: it runs admission and
   preparation again against the state at replay time.
1. **Isolation.** A replay failure does not stop the later replays, and the
   settled approval stays settled.
1. **Failure channel.** After the last replay, the first replay failure
   propagates through the approval's failure route: the `ApproveAsync`
   awaiter, or `ApproveErrors` once on the command path. A failure that the
   approval already carries wins over replay failures. That is a failed
   post-persist commit, or a failure that a settlement `ErrorsChanged`,
   `CanExecuteChanged`, or `OnApproved` observer propagates.
1. **Other threads.** During the publication scope, another thread's
   `SetModel`, deny, or `Dispose()` waits until the scope ends. Only the
   approving thread's calls are queued. The replay runs after the scope ends.

### 2.3. Choices made under the owner's delegation

The owner delegated the remaining design questions to this principle: all
flavors follow the same guidelines and specs as much as possible, with the
simplest and most common-sense approach chosen.

- Decided under the owner's 2026-11-07 delegation: the #1050 failure channel
  is the approval's own failure route (rule 6). Without the queue, a failure in
  the same update would propagate out of the settlement observer and fail the
  approval in the same way. The queue changes only when the update runs. It
  adds no public member, no new channel, and no silent drop. Rust already
  resumes the first replay panic (#740).
- Decided under the owner's 2026-11-07 delegation: a failure from the approval
  itself, including a failure that an `OnApproved` subscriber propagates, wins
  over a replay failure in every flavor. The first failure is the one the
  caller sees, as with the first-error policy of failed settlement.
- Decided under the owner's 2026-11-07 delegation: a deny from a settlement
  observer in the pre-publication window is queued like `SetModel`, so
  `OnApproved` observers never see a reverted model. The queue therefore holds
  operations (set a model, or deny), not only models.
- Decided under the owner's 2026-11-07 delegation: the window starts with the
  post-persist commit, so a `SetModel` or deny from the snapshotter or a
  validator of the reset commit is queued like a call from the reset callback.
- Decided under the owner's 2026-11-07 delegation: when the post-persist commit
  fails, the calls it already queued still replay, after the failed
  settlement's `CanExecuteChanged` and before the failure reaches its channel.
  Each of these calls returned normally, so it takes effect. The commit failure
  wins over any replay failure.
- Decided under the owner's 2026-11-07 delegation: call-time preparation keeps
  the §5.4 staleness rule. A nested update made by a preparation callback wins
  over the interrupted outer call, whether the nested update commits or is
  queued.
- Decided under the owner's 2026-11-07 delegation: another thread's `SetModel`,
  deny, or `Dispose()` waits for the publication scope, as C#, Python, and
  Swift do (#533). This closes open decision §2.6. Queueing calls from other
  threads, as Rust does, was question 1 option 1, which the owner did not
  choose. Rust converges in #1160.
- Decided under the owner's 2026-11-07 delegation: the replay runs after the
  publication scope ends, as C#, Python, and Swift do now. A waiting call from
  another thread can then proceed during the replay, and updates stay
  serialized in either order. Holding other threads until the replay ends
  would put the replayed updates' notifications inside the scope. Without a
  wait-for-graph escape, which C# and Python do not have yet, that would create
  a new hub deadlock.
- Decided under the owner's 2026-11-07 delegation: the Swift change in
  question 1 is scoped to `FormVM`. Its event subjects and its approve and deny
  commands deliver `canExecuteChanged` without a delivery lock. The public
  types of `approveCommand` and `denyCommand` do not change, and other Swift
  commands keep their current delivery. The order of several sinks stays
  unspecified (open decision §2.5).

## 3. Flavor impact

- **C#, Python, TypeScript.** Queue deny and the calls from the reset commit.
  Prepare at call time without the equality short-circuit, replay each item in
  isolation, and apply rule 6. In C#, `ExitApprovalPublication` replays from
  three call sites, so the isolation belongs inside it. Today the reset
  callback runs before the publication scope opens in C# and Python, so the
  queue must open with the commit.
- **Rust.** The same changes, with panics as failures. Each replay runs under
  `catch_unwind`. The first replay panic resumes after the last replay, unless
  a subscriber panic wins (#740). Rule 7 stays open until #1160, which depends
  on #1158: Rust still queues calls from other threads. ADR-0176 resolves
  this: Rust applies rule 7 like the other threaded flavors.
- **Swift.** Queue deny and the calls from the reset commit, which runs under
  `stateGate`. Move the form's event delivery to `VMxConcurrentSubject`
  (§2.1). Swift callbacks cannot throw, so the failure rules do not apply.
  One `VMxConcurrentSubject` send delivers to its sinks in subscription order,
  but no rule requires that order (open decision §2.5). #1169 still needs its
  test fix, because a test must not rely on that order. Without a delivery
  lock, a sink that updates the form on each `canExecuteChanged` while another
  thread edits the form can recurse on its own thread without a bound, as in
  C# and Python.

Call-time preparation adds one validator call for each queued update, so tests
that count validator calls need updating. Examples are the Rust #1061
`assignments_of_nine` assertions and the FORM-035..038 call-count tests. The
implementation PRs name each test that pinned the old behavior.

## 4. Conformance

- `FORM-039` covers the queue: calls from `resetOnApproved` and settlement
  observers, deny included, publish nothing before `OnApproved`, and replay in
  call order after it.
- `FORM-040` covers call-time preparation, replay isolation, and the failure
  channel. Swift tests only the equality and replay-order clauses, because its
  callbacks cannot fail.

The catalog grows from 444 to 446 library IDs (451 in total).

## 5. Consequences

- A `SetModel` or deny from a settlement observer or the reset commit returns
  before it takes effect. Code that reads `Model` right after such a call sees
  the approval state until `OnApproved` delivery returns.
- A replay failure can reach the approval's failure route after `OnApproved`
  was delivered, as a failing `OnApproved` subscriber already can.
- In Swift, one `FormVM` sink can run on two threads at once, as in C# and
  Python.
- Open decision §2.6 is closed. Open decision §1.4, about when an update nested
  in a preparation callback sends its notifications, stays open (#1173).
