# ADR 0216 — `FormVM` failed queue sends, nested validator registration and strict-only dirty comparisons

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 20 §5.2, §5.4 and §5.5)
- **Extends:** [ADR-0144](0144-formvm-failure-atomic-model-updates.md) and
  [ADR-0180](0180-nested-formvm-updates-notify-at-the-outermost-update.md).
  Related: [ADR-0176](0176-form-publication-waits-join-the-wait-for-graph.md),
  #1290, #1355, #1415.

## 1. Context

Three `FormVM` rules around the update queue of ADR-0180 were open.

- **#1415 (a failed send).** The outermost update sends its queue (§5.4 rule
  3). A send can fail when an observer or the hub propagates a failure. C#
  and Python then stop the later sends. They release each nested approval
  whose persister has not started, without calling the persister. TypeScript
  catches each send, sends all later notifications and calls every queued
  persister. Rust stops the sends at the first panic, but calls each nested
  persister unless the form is disposed. Swift sinks cannot throw. No rule
  covered this case.
- **#1290 (Rust validator registration).** Only Rust registers a validator on
  a live form, and its revalidation is an update (§5.5). §5.4 did not list
  the registration as a nested call. A registration from a validator of
  `set_model` therefore sent its notifications before it returned. The §5.5
  "Queue and replay" paragraph also left out refused revalidations, which
  the Rust queue holds.
- **#1355 (dirty comparisons).** §5.2 captured the dirty state before and
  after every update. Only strict mode reads it (§9). C#, Python, TypeScript
  and Swift run both comparisons against `Snapshot` for every form. Rust runs
  them only in strict mode, and there only while the form is valid. With an
  injected `equals` that fails only for the candidate against `Snapshot`, a
  non-strict update fails in four flavors and commits in Rust.

## 2. Decision

### 2.1. Rules

Bare section numbers refer to chapter 20.

1. **A failed send stops the queue (§5.4 rule 7).** When a send of the
   outermost update's queue fails, the update sends no later notification of
   that queue. Its update scopes still close.
1. **Unstarted nested approvals are released.** Each nested approval in that
   queue whose persister has not started is released. Its in-flight mark
   clears, and its persister is never called. When its admission
   `CanExecuteChanged` was sent, `CanExecuteChanged` is raised once more. A
   failure from that send is discarded. The awaiter of a nested `ApproveAsync`
   completes normally, and the command path emits nothing on
   `ApproveErrors`.
1. **The failure propagates after the replays.** The outermost update then
   replays its §5.5 queue, each item in isolation. The send failure
   propagates from the outermost update after the last replay, and it wins
   over a replay failure.
1. **A Rust registration can be nested.** A Rust validator registration on a
   live form can come from a preparation callback, or from an
   `errors_changed` observer that the outermost update delivers. It is then a
   nested call (§5.4). Its revalidation commits at once and returns before its
   notifications. The outermost update sends them with the rest of its queue.
   A registration from a preparation callback makes the interrupted update
   stale, so the newest committed state stands. A nested registration never
   waits for another thread's scope.
1. **Refused revalidations are queued.** The §5.5 queue holds refused Rust
   revalidations together with refused `SetModel` and deny calls. Each
   replays as a new revalidation.
1. **Dirty comparisons run only in strict mode (§5.2).** A strict `SetModel`
   runs three equality comparisons: the candidate with the live `Model`, the
   live `Model` with `Snapshot`, and the candidate with `Snapshot`. A strict
   deny runs the last two, with the reverted model as the candidate. A
   non-strict `SetModel` runs only the first, and a non-strict deny runs
   none. Each comparison runs at most once per preparation. `IsDirty` and
   strict `ApproveCommand.CanExecute()` still compare `Model` with `Snapshot`
   when they are read.

### 2.2. Choices made under the owner's delegation

The owner delegated the open design questions to one principle. All flavors
follow the same spec as much as possible, with the simplest and most
common-sense option chosen.

- Decided under the owner's 2026-11-09 delegation: a failed send stops the
  queue, and unstarted nested approvals are released (#1415). This is the C#
  and Python behavior, and Rust already stops its sends. It also matches the
  settlement, where an observer failure stops the later notifications. §5.3
  requires a persister to start only after its admission notification, and
  a stopped queue may not have sent it.
- Decided under the owner's 2026-11-09 delegation: a released nested approval
  completes its awaiter normally. This is the C# and Python behavior, and the
  §10 rule for an approval that disposal stops before its persister starts.
  The caller of the outermost update already receives the failure once.
- Decided under the owner's 2026-11-09 delegation: the §5.5 queue still
  replays after a failed send. Those calls already returned to their callers,
  and §5.3 rule 5 replays each queued call in isolation.
- Decided under the owner's 2026-11-09 delegation: a Rust registration follows
  the nested-call rules of ADR-0180 (#1290). It is an update, so it uses the
  same queue as every other nested update. The stale rule for the interrupted
  update stays as it is: the registration's commit is the newer state.
- Decided under the owner's 2026-11-09 delegation: an update runs the dirty
  comparisons only in strict mode (#1355). Only strict mode reads the result
  (§9). Rust already skips the comparisons for a non-strict form. A
  non-strict update gets faster, and it can no longer fail in a comparison
  that it does not use. A strict update runs both comparisons, also while the
  form is invalid, because a strict update notifies when `IsDirty` changes.

## 3. Flavor impact

| Rule                              | C#      | Python  | TypeScript | Swift   | Rust    |
| --------------------------------- | ------- | ------- | ---------- | ------- | ------- |
| 1-3 Failed send (#1415)           | test    | test    | changes    | test    | changes |
| 4-5 Nested registration (#1290)   | none    | none    | none       | none    | changes |
| 6 Strict-only comparisons (#1355) | changes | changes | changes    | changes | changes |

"test" means no code change, but new tests that pin the behavior.

- **C#.** `SetModel`, `Deny` and their queued call-time preparation compute
  `wasDirty` and `isDirty` only when `_strict` is set.
- **Python.** `set_model` and `_deny` compare against the snapshot only when
  `self._strict` is set. `set_model` reuses its first comparison result
  instead of comparing the live model with the candidate again.
- **TypeScript.** `#deliver` stops at the first failed send and releases each
  nested approval that has not started. `#prepare` runs the dirty comparisons
  only when `#strict` is set.
- **Swift.** `setModel` and `performDeny` compare against the snapshot only
  when `strict` is set. Swift sinks cannot throw, so rules 1 to 3 cannot
  occur.
- **Rust.** `deliver` releases each nested approval after a panic instead of
  running it. `with_field_validator`, `with_model_validator` and
  `with_clearing_model_validator` run their revalidation in the `run_update`
  frame, so a nested registration queues its notifications. `prepare_update`
  runs both dirty comparisons in strict mode also while the form is invalid.
  The open #1327 fix makes the same change.

## 4. Conformance

- `FORM-044` covers rules 1 to 3. A failed send stops the later sends. A
  nested approval that has not started never calls its persister and is no
  longer in flight. The failure propagates from the outermost update.
- `FORM-045` covers rule 6. It counts the equality calls of a `SetModel` and a
  deny in strict and in non-strict mode. A non-strict update commits even when
  the comparison of the candidate with `Snapshot` would fail.

The catalog grows by two library IDs. Rules 4 and 5 are Rust-only and get
Rust regression tests, with no ID.

## 5. Consequences

- A TypeScript or Rust update whose send fails no longer calls the persister
  of an approval started from its validator.
- A non-strict `SetModel` calls the equality once, and a non-strict deny not
  at all. An `equals` that fails only against `Snapshot` no longer fails a
  non-strict update.
- A Rust registration from a validator returns before its notifications, and
  they arrive before the outer `set_model` returns.

## 6. Rejected alternatives

- **Send every notification and start every persister after a failure (the
  TypeScript behavior).** A persister could then start before its admission
  notification reached observers, which §5.3 forbids.
- **Route the send failure to the nested approval's awaiter or to
  `ApproveErrors`.** The caller of the outermost update already receives it,
  so the failure would be reported twice.
- **Keep the dirty comparisons for every form.** They cost time on every
  update, and their result is never read outside strict mode.
