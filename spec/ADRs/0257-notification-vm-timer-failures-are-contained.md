# ADR 0257 — A notification's timer and decay-tick failures never reach the scheduler

- **Status:** Accepted
- **Date:** 2026-11-26
- **Spec version:** 3.30.0 (chapter 16 §6, a new paragraph; chapter 16 §9; chapter 12 `NOTIF-021`; `NOTIF-019` and `NOTIF-020` are unchanged)
- **Extends:** [ADR-0191](0191-subscriber-failures-do-not-stop-delivery-or-detach.md) (adds the `NotificationVM` timer deliveries to the stream-fed route and keeps its rules). Related: [ADR-0197](0197-notification-state-stops-at-resolution-and-hub-dispose.md) (render state after resolution), [ADR-0219](0219-scheduler-contract-delayed-task-and-rust-timers.md) (§2.4, the `DelayedTask` failure route), issue #1875.

## 1. Context

`NotificationVM` (chapter 16 §6) arms two actions on the injected scheduler. The lifespan timer auto-dismisses the notification when it expires. With a `tickInterval`, a decay tick raises `PropertyChanged` for `RemainingTime` and `Opacity`, then reschedules.

Neither action had an exception boundary in C#. Auto-dismiss resolves through `hub.Resolve`, and `Dismiss` raised the `IsResolved` change only after that call returned. A `Pending` subscriber that throws in that call therefore ended the action before the change was raised. A `PropertyChanged` handler that throws ended a decay tick before it rescheduled. On `DefaultScheduler.Instance`, the real-time scheduler of chapter 11 §6.1, the failure is unhandled on a timer thread, and .NET ends the process. Under a test scheduler, the failure surfaces in the code that advances the clock, and the `IsResolved` change is missing.

Chapter 03 §3.6 defines the failure routes of the library's delivery channels. It states that it does not cover other `PropertyChanged` handlers, and it does not name the `NotificationVM` timer path. A debounce timer and a failing `DelayedTask` action are stream-fed (ADR-0219 §2.4). The timer path of `NotificationVM` is the same kind of delivery: the scheduler, not the caller, runs it.

## 2. Decision

1. **The timer path is stream-fed.** A failure raised by a `Pending` subscriber or a `PropertyChanged` handler during auto-dismiss, or during a decay tick, follows the stream-fed route of chapter 03 §3.6. It never reaches the scheduler. Each flavor contains it by its own route: C# discards it, as `DelayedTask` does (ADR-0219); Python logs it with `logger.exception`; TypeScript reports it through rxjs `config.onUnhandledError`; Rust catches it; Swift has no such failure, because its subscribers cannot throw.
1. **State first, and the change is always raised.** Auto-dismiss, and `DismissCommand` through the same `Dismiss` path, commit the resolved state before the hub call. They raise the `IsResolved` change, then `RemainingTime` and `Opacity`, even when the hub `resolve` raises. A `DismissCommand` hub failure keeps the route that its flavor already gives a command call. `ResolveWith`, which the `ConfirmationVM` approve and reject commands call, keeps its current order.
1. **A decay tick reschedules after a handler failure.** The tick raises each change under its own containment. It then reschedules while `RemainingTime` is positive, so one failing handler does not stop the decay.
1. **The rule is one conformance ID.** `NOTIF-021` tests the timeline in each flavor (§9 of chapter 16 maps it to §6). Its test in a flavor whose subscribers cannot throw asserts the same timeline with no failing subscriber or handler.
1. **Versions and records.** `spec/VERSION` stays at 3.30.0, because no `spec-v3.30.0` tag exists, as ADR-0214 to ADR-0255 did. No public member changes, so the API listings do not change. Each changed package records the fix in its CHANGELOG under its current unreleased source version.

## 3. Consequences

- A `Pending` subscriber or a `PropertyChanged` handler that fails at expiry or during a tick no longer stops the process on `DefaultScheduler.Instance`, and no longer hides the `IsResolved` change under a test scheduler.
- A failure is discarded silently in C# and Rust, as the stream-fed route already does for other deliveries. Python logs it. A diagnostic of a failing handler therefore depends on the flavor.
- Other handlers of the same `PropertyChanged` invocation may still be skipped when one throws, because the change notifications are not fanned out. Chapter 03 §3.6 does not cover these handlers, and this ADR does not change that.
- `ConfirmationVM` keeps its no-op auto-dismiss, so only its decay tick changes.

## 4. Rejected alternatives

- **Leave the failure to the scheduler's unhandled path.** That is the current behavior. It ends a C# process on `DefaultScheduler.Instance` and skips the `IsResolved` change under a test scheduler.
- **Wrap the whole decay tick in one boundary.** A single failure would then skip the reschedule and stop the decay. Each change needs its own containment.
- **Route the failure to a caller.** A timer action has no caller. The scheduler thread is the only place the failure can go, so it is contained there.
- **Roll back `IsResolved` when the hub resolve fails.** The hub has already completed the waiter, so the notification is no longer pending. Rolling back would report an open notification that the hub no longer holds.
