# ADR 0215 — `FormVM` callbacks run with no form lock held

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 20 §5.1, §5.3, §5.4, §5.5 and §10)
- **Extends:** [ADR-0144](0144-formvm-failure-atomic-model-updates.md),
  [ADR-0174](0174-formvm-queues-updates-during-approval-publication.md),
  [ADR-0176](0176-form-publication-waits-join-the-wait-for-graph.md) and
  [ADR-0180](0180-nested-formvm-updates-notify-at-the-outermost-update.md).
  Related: [ADR-0143](0143-formvm-single-flight-approval.md),
  [ADR-0172](0172-one-wait-for-graph-per-flavor.md), #1426, #1427, #1452.

## 1. Context

Chapter 20 §5.4 serialized updates "by holding the form's re-entrant state
lock across preparation, or by an equivalent per-form serialization". Three
issues come from that lock and from the waits around it.

- **#1427 (deadlock).** C#, Python and Swift hold the state lock while the
  equality comparisons and the validators run. Rust holds its update lock. A
  validator that joins thread B deadlocks when B calls the same form. In C#,
  Python and Swift, B also blocks when it only reads `Model`. The wait-for
  graph (ADR-0172) cannot see the cycle, because the validator's join is
  consumer code. ADR-0176 kept this as the §5.5 limitation.
- **#1452 (another thread during the post-persist commit).** Swift runs
  `resetOnApproved`, the snapshotter and the validators under `stateGate`.
  Thread B's `setModel` waits for the gate, then for the settlement scope, and
  commits after `OnApproved`. B's model stands. C# and Python run these
  callbacks with no lock held, so B commits at once and the reset overwrites
  it. Rust runs the reset and the snapshotter with no lock, but the
  validators under its update lock. The Rust outcome depends on the callback
  that B meets. No rule chose an outcome.
- **#1426 (three publication-wait notes).** ADR-0176 §3.1 left four flavor
  differences, and ADR-0180 closed one. Three remain in §5.5:
  1. A Swift `SetModel` or deny in its own thread's pre-publication window
     joins its own queue at once. C#, Python and Rust first wait for another
     thread's scope.
  1. After a refused `Dispose()`, C# and Rust wake the scope waiters at once.
     Python and Swift wake them when the publisher's scope closes.
  1. C#, Python and Rust open an update scope only when the error map
     changes. Swift opens one at every commit.

## 2. Decision

### 2.1. Rules

Chapter 20 states these rules. They apply to C#, Python, Swift and Rust.
TypeScript runs on one thread, so only the single-thread parts apply to it.
Bare section numbers refer to chapter 20.

1. **No lock across a callback.** A form holds no lock while a consumer
   callback runs. The callbacks are the equality comparisons, the validators,
   the snapshotter and `resetOnApproved`. This covers the preparation of an
   update, the call-time preparation of a queued call, a Rust revalidation,
   and the post-persist commit.
1. **Reads do not wait.** Another thread's read of `Model`, `Snapshot`,
   `Errors`, `IsValid`, `FieldError`, `IsDirty` or
   `ApproveCommand.CanExecute()` never waits for a callback. It returns the
   committed state. `IsDirty` and strict `CanExecute()` run their equality
   comparison after they release the lock.
1. **Other calls do not wait for a preparation.** Another thread's
   `SetModel`, deny, approve call or `Dispose()` follows its own rules while a
   preparation runs. It waits only for a publication scope (§5.5).
1. **Commit only against the state that was read.** When a preparation
   completes, the update checks three cases in this order:
   - The form was disposed. The call returns without committing.
   - A callback on the preparing thread committed or queued another update.
     The prepared result is stale, and the call returns without committing
     (§5.4).
   - Another thread committed since the preparation started: an update, a
     deny, an approval commit or a Rust revalidation. The call runs again as
     a new call against the new state. Its admission rule, its waits and its
     callbacks run again.
1. **Queued calls are placed anyway.** A call whose call-time preparation
   completes (§5.3 rule 2, §5.5) discards its result. Another thread's commit
   does not stop it from joining its queue.
1. **`Dispose()` during a preparation.** A `Dispose()` from another thread
   during a preparation marks the form disposed and returns. The preparing
   call commits nothing. The §10 teardown runs when that call returns.
1. **Another thread during the post-persist commit.** A `SetModel` or deny
   from another thread, after the persister succeeds and before settlement
   step 1, is an edit that races the persistence (§5.3). It commits at once
   and publishes. A configured reset then overwrites it (§5.1). Without a
   reset, its model stands, and the snapshot advances to the captured value.
   The approval commit itself never runs again: it is authoritative.
1. **Own pre-publication window.** A `SetModel` or deny in its own thread's
   pre-publication window does not wait for another thread's scope. It runs
   its call-time preparation and joins its own thread's queue (§5.3 rule 1).
1. **Refused `Dispose()`.** A `Dispose()` whose wait is refused marks the form
   disposed. It removes the wait-for edges that name the form's scope, and it
   wakes every call that waits for a scope on the form. Those calls find the
   form disposed and follow §10. The teardown still waits for the publisher.
1. **Update scope only for an error-map change.** An update opens an update
   scope at its commit only when the commit changes the effective error map.
   An update that leaves the map unchanged opens no scope.

### 2.2. Choices made under the owner's delegation

The owner delegated the open design questions to one principle. All flavors
follow the same spec as much as possible, with the simplest and most
common-sense option chosen.

- Decided under the owner's 2026-11-09 delegation: the form holds no lock
  across a callback (#1427). A callback can wait for any thread, so no form
  lock may be held across one. Recording the lock wait in the wait-for graph
  cannot help, because the callback's own wait is consumer code. ADR-0176 §6
  already rejected that option.
- Decided under the owner's 2026-11-09 delegation: another thread's call
  proceeds during a preparation. Refusing it, by queueing it for the
  preparing thread, was rejected. A call from another thread would then
  return before it takes effect in an ordinary race. ADR-0176 allows that
  only when a wait would close a cycle.
- Decided under the owner's 2026-11-09 delegation: an update that another
  thread overtakes runs again. Abandoning it was rejected. An abandoned edit
  would be lost when another thread's approval only advanced the snapshot,
  because no serial order loses that edit. Running again keeps every call, as
  ADR-0176 requires: the overtaking commit comes first, and this one second.
- Decided under the owner's 2026-11-09 delegation: a same-thread commit or
  queued call still makes the outer preparation stale (§5.4). That nested
  call comes from the outer call's own callback, so it is the newer intent.
  `FORM-037` and `FORM-038` keep their behavior.
- Decided under the owner's 2026-11-09 delegation: another thread's call
  during the post-persist commit commits at once, and the reset overwrites it
  (#1452). C#, Python and, for the reset callback, Rust already behave this
  way. It is §5.1 applied to the whole span before settlement step 1, and
  rule 1 leaves no lock that could make the call wait.
- Decided under the owner's 2026-11-09 delegation: a call in its own
  pre-publication window does not wait (#1426 case 1). It changes nothing
  until it replays, so a wait adds only delay and a deadlock risk. ADR-0180
  rule 7 already queues a nested call without a wait. Swift already behaves
  this way.
- Decided under the owner's 2026-11-09 delegation: a refused `Dispose()` wakes
  the waiters at once (#1426 case 2). They find the form disposed, which is
  their exit condition. C# and Rust already behave this way.
- Decided under the owner's 2026-11-09 delegation: an update opens a scope only
  when its error map changes (#1426 case 3). A scope with no `ErrorsChanged`
  delivery protects nothing. C#, Python and Rust already behave this way.
- Decided under the owner's 2026-11-09 delegation: the §5.5 limitation is
  narrowed, not removed. A callback that runs inside a publication scope on
  its thread, and waits for a thread that calls the same form, still
  deadlocks. That thread waits for the scope, and the callback's wait is
  consumer code. Such callbacks are `ErrorsChanged`, `CanExecuteChanged` and
  `OnApproved` observers, and the preparation callbacks of an update that one
  of them makes.

## 3. Flavor impact

| Rule                                    | C#      | Python  | TypeScript | Swift   | Rust    |
| --------------------------------------- | ------- | ------- | ---------- | ------- | ------- |
| 1-6 No lock across a callback (#1427)   | changes | changes | none       | changes | changes |
| 7 Post-persist commit (#1452)           | test    | test    | none       | changes | changes |
| 8 Own window does not wait (#1426.1)    | changes | changes | none       | none    | changes |
| 9 Refused `Dispose()` wakes (#1426.2)   | none    | changes | none       | changes | none    |
| 10 Scope only on error change (#1426.3) | none    | none    | none       | changes | none    |

"test" means no code change, but new tests that pin the behavior.

- **C#.** `SetModel` and `Deny` release `_stateGate` while the preparation
  callbacks run, and take it again to place or commit. The nested-call state
  (`_preparationDepth`, `_pendingNotices`) and the same-thread commit and
  queue counts become per thread. An update that another thread overtook runs
  again. `IsDirty` and `CanApprove` call `Equals` after they release the gate.
  `ApplySetModel` and `ApplyDeny` skip `WaitForForeignScopes` in the caller's
  own pre-publication window.
- **Python.** `set_model` and `_deny` follow the C# design, with
  `_state_changed`. `is_dirty` and `_can_approve` compare after they release
  the lock. `dispose()` wakes the waiters after a refused wait.
- **Swift.** `setModel` and `performDeny` follow the C# design, with
  `stateGate`. `commitApproval` runs `resetOnApproved`, the snapshotter and the
  validators with the gate released, and then waits for other scopes and
  commits. `dispose()` wakes the waiters after a refused wait. An update opens
  a scope only when its error map changes.
- **Rust.** `set_model`, `revert` and `revalidate` run their callbacks with no
  update lock held, and take it to place or commit. The nested-call state
  becomes per thread. `commit_approval` validates the reset model before it
  takes the update lock. `serialize` skips the scope wait in the caller's own
  pre-publication window. An update counts as a delivery from its admission,
  so a `dispose()` meanwhile defers its teardown.
- **TypeScript.** No change. One thread runs every call.

## 4. Conformance

This adds no conformance ID. Each rule needs a second thread to observe, so
TypeScript cannot test it, as with ADR-0176. Each threaded flavor adds
regression tests for #1426, #1427 and #1452. `FORM-029`, `FORM-034`,
`FORM-037` and `FORM-038` keep covering the single-thread paths.

## 5. Consequences

- The #1427 reproduction completes in every threaded flavor. Thread B commits
  `2`, and the validator's update then runs again and commits `1`.
- A read from another thread never blocks on a slow validator.
- A preparation that another thread overtakes runs its callbacks again. A
  validator can therefore run more than once for one call during a race.
- A `SetModel` or deny from another thread during the post-persist commit is
  overwritten by the reset in every threaded flavor.
- The three §5.5 flavor notes are gone. The §5.5 limitation covers only
  callbacks that run inside a publication scope.

## 6. Rejected alternatives

- **Record the state-lock wait in the wait-for graph.** The callback's wait for
  the other thread is consumer code, so the graph never sees the cycle.
- **Queue another thread's call for the preparing thread.** The call would
  return before it takes effect in an ordinary race, and a read would still
  need its own rule.
- **Abandon an update that another thread overtakes.** A snapshot-only
  approval commit would then drop a user's edit with no serial order that
  explains it.
- **Keep the Swift outcome for #1452.** Swift would need its gate held across
  the reset callback, which rule 1 forbids, and three flavors would change.
