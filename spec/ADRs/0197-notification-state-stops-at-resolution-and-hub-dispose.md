# ADR 0197 — Notification state stops at resolution and at hub dispose

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 16 §2.3, §6, §7 and §9; `NOTIF-017`,
  `NOTIF-019`, `NOTIF-020` and `DISP-003`)
- **Amends:** [ADR-0031](0031-notification-rendering-vms.md) and
  [ADR-0037](0037-v2.5-maintenance-clarifications.md) §2.4

## 1. Context

Chapter 16 had no rule for two terminal states. The flavors differed in both.

- **Render state after resolution or dispose (#1306).** Chapter 16 §6 and
  ADR-0031 say that `RemainingTime` decays through the injected scheduler and
  that `Opacity` is `RemainingTime / Lifespan`. They give no rule for a
  resolved or disposed VM. C#, Python, TypeScript and Swift compute
  `RemainingTime` from the scheduler clock on each read. Resolution stops the
  decay ticks but not the clock, so each later read returns a smaller value.
  These flavors raise their last change notification for the two properties at
  resolution, so a bound view keeps a value that a poll no longer returns.
  Rust uses a caller-driven clock, and `advance_by_ms` has no effect once the
  VM is resolved or disposed. Take a 10 s `NotificationVM`, dismiss it at 0 s
  and advance the clock by 10 s. C#, Python, TypeScript and Swift report
  `Opacity` 0.0, and Rust reports 1.0. Dispose at 0 s gives the same split.
  Ledger item §2.1 of `docs/maintenance/2026-10-18-open-cross-flavor-decisions.md`
  recorded the gap.
- **`Pending` at hub dispose (#1476).** Chapter 16 §9 and `NOTIF-017` say that
  dispose completes `Pending`. `DISP-003` accepts "completion or terminal
  snapshot publication". Rust sends a final empty snapshot on `pending_stream()`
  and a `pending` message on `pending_changed()`, records it in
  `pending_snapshots()`, and then completes. C#, Python, TypeScript and Swift
  only complete. The Rust parity ledger §12.10 recorded the difference.
- **`Pending` subscription after hub dispose (#1476).** Chapter 16 §2.3 says
  that a new subscriber gets the current snapshot at once. It has no rule for
  a disposed hub. C# and Python dispose the internal `BehaviorSubject` after
  completion, so a later subscription gets a disposed-object error. With no
  error handler, the subscribe call raises, and so does the `NotificationVM`
  constructor. TypeScript and Swift give completion only. Rust replays the
  retained value, which is the final empty snapshot, and then completes.

## 2. Decision

Decided under the owner's 2026-11-07 delegation, with the simplest rule that
all five flavors can share.

### 2.1. Render state stops at the first terminal step

- A `NotificationVM` or `ConfirmationVM` stops its clock at the first of these
  steps: its own resolution, an observed hub resolution, or its disposal. Its
  own resolution includes `DismissCommand`, `ApproveCommand`, `RejectCommand`
  and auto-dismiss at expiry.
- From that step on, `RemainingTime` and `Opacity` keep the values that they
  had at that step. A later clock advance does not change them.
- Auto-dismiss happens at expiry, so the kept values are 0 and 0.0, as
  `NOTIF-016` requires.
- A `ConfirmationVM` that expires without a decision is not resolved. Its
  `RemainingTime` stays at 0 as before.
- The change notifications do not change. Resolution still raises one change
  for `RemainingTime` and `Opacity`, and that change now reports the kept
  value.

This is the Rust behavior. It also matches the disposal inventory, which lists
"last render state" as readable after dispose.

### 2.2. Dispose sends no final `Pending` snapshot

- Dispose clears the pending list, resolves each waiter with `Pending` and
  completes `Pending` once. It sends no snapshot of its own.
- Snapshots queued before dispose are still delivered in order. Completion
  comes after them.
- Rust follows the same rule. Dispose sends nothing on `pending_stream()`,
  sends no `pending` message on `pending_changed()` and adds no entry to
  `pending_snapshots()`. It then disposes both streams.
- `DISP-003` requires one completion and no longer offers a terminal snapshot
  as an alternative.

### 2.3. A later subscription receives completion only

- A `Pending` subscription made after `dispose` returns receives completion
  once. It receives no snapshot, neither a notification posted before dispose
  nor an empty list. It receives no error, and the subscribe call does not
  raise.
- The rule also holds on the thread that called `dispose`, after the call
  returns, when dispose ran inside a `Pending` delivery and queued its
  completion.
- A subscription that races a dispose on another thread receives either this
  result or the current snapshot followed by completion.
- A `NotificationVM` or `ConfirmationVM` built over a disposed hub constructs
  normally. Its pending subscription completes at once. Its own resolution
  paths still set `IsResolved`, and the hub ignores the resolve call.

This is the TypeScript and Swift behavior. It matches a completed
`BehaviorSubject` in Rx.NET, reactivex and RxJS, which gives a late subscriber
completion only.

### 2.4. Choices made under the owner's delegation

- Decided under the owner's 2026-11-07 delegation: one ADR covers #1306 and
  #1476, because both rules state what chapter 16 state reads after a
  terminal step.
- Decided under the owner's 2026-11-07 delegation: the new conformance IDs are
  `NOTIF-019` and `NOTIF-020`. `NOTIF-018` is reserved for other work.
- Decided under the owner's 2026-11-07 delegation: the null hub keeps its
  chapter 16 §3 rule. It never had state, so it sends its empty list once and
  completes. The rules in §2.2 and §2.3 apply to a hub that was disposed.

## 3. Flavor impact

- **C#.** `NotificationVM` keeps the remaining time that it computes when it
  claims resolution or disposal under `_gate`. `RemainingTime` returns the
  kept value once it is set. `NotificationHub.Pending` checks `_disposed` at
  subscribe time and completes the observer at once when it is set. A
  subscription that loses the race with the subject disposal also completes.
- **Python.** `NotificationVM` follows the C# design. `NotificationHub.pending`
  follows the C# design.
- **TypeScript.** `NotificationVM` follows the C# design. The hub already
  follows §2.2 and §2.3.
- **Swift.** `NotificationVM` follows the C# design. The hub already follows
  §2.2 and §2.3.
- **Rust.** The view models already follow §2.1. `NotificationHub::dispose`
  queues a terminal publication with no snapshot. The drainer sends no value
  and no `pending` message for it. Dispose also stops `pending_stream()` from
  accepting new subscriptions, so a later subscription completes at once with
  no replay.

No flavor differs, so ADR-0009 gains no entry.

## 4. Conformance

- `NOTIF-019` covers §2.1: a 10 s `NotificationVM` dismissed at 0 s, one
  disposed at 0 s, and one dismissed at 4 s, each read after the clock passes
  10 s.
- `NOTIF-020` covers §2.3: a subscription made after dispose of a hub with one
  posted notification receives completion only.
- `NOTIF-017` now requires that a current subscriber receives no value from
  the dispose. `DISP-003` requires one completion and no terminal snapshot.

With ADR-0198, the catalog grows from 451 to 454 library IDs (459 in total).

## 5. Consequences

- A view that polls `Opacity` after resolution reads the value that the last
  change notification reported. A host that wants a fade-out after dismissal
  removes the entry or animates it in the view.
- C# and Python code that builds a `NotificationVM` over a disposed hub no
  longer gets an exception.
- A Rust consumer that waited for the final empty snapshot to clear its list
  now reacts to completion instead. A Rust test that counted the terminal
  `pending_snapshots()` entry changes.
- The Rust parity ledger §12.10 is resolved. Item §2.1 of the open
  cross-flavor decisions ledger is removed.

## 6. Rejected alternatives

- **Keep the clock-based decay after resolution.** Four flavors already do it,
  but a bound view and a poll would then read different values, and Rust would
  need a scheduler-driven clock.
- **Drop `Opacity` to 0.0 at resolution.** A resolved notification would
  vanish at once in a view that has no fade. No flavor does this today.
- **Keep the Rust terminal snapshot and add it to the other flavors.** A
  subscriber that renders the list would get one more update for a hub that is
  going away. Four flavors would change instead of one.
- **Replay the empty list to a later subscriber, as the null hub does.** The
  late subscriber would get a value after dispose, which §2.2 forbids for a
  current subscriber. Only Rust behaves this way, and only by accident of the
  terminal snapshot.
- **Raise an error for a later subscriber.** A `NotificationVM` constructor
  would keep raising over a disposed hub, and TypeScript and Swift would have
  to add an error path.
