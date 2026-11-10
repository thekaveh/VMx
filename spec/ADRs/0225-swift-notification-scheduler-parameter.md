# ADR 0225 — Swift notification VMs take any `NotificationScheduler`

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 16 §6, chapter 11 §6.1)
- **Amends:** [ADR-0063](0063-swift-notifications-dialogs-divergences.md) §2.4.
  Related: [ADR-0219](0219-scheduler-contract-delayed-task-and-rust-timers.md),
  [ADR-0009](0009-cross-flavor-divergence-catalogue.md),
  [ADR-0006](0006-idiomatic-api-per-language.md), #1347, #1518, #670.

## 1. Context

Chapter 16 §6 says that production code passes the default system scheduler to
`NotificationVM`, and tests pass a fake clock. C#, Python and TypeScript accept
any scheduler from their reactive library.

Swift `NotificationVM` and `ConfirmationVM` took only the concrete
`VirtualTimeScheduler`. That scheduler runs work only when a caller calls
`advance(to:)` or `advance(by:)`, so an app could not give these VMs real time
(#1347). The Swift notes showcase advanced a virtual clock by one second from a
one-second `Timer`, so a toast could dismiss up to one second late.

A Combine `Scheduler` can arm timers, but its `Stride` has no generic
conversion to seconds. The VM needs that conversion to read the time since its
construction.

ADR-0063 §2.4 describes `VirtualTimeScheduler` as the scheduler for the
notification timers. It says that `NotificationVM` needs no lock because the
virtual scheduler runs work on the calling thread. ADR-0219 names
`NotificationScheduler` as the Swift notification scheduler in its context, but
it does not record the parameter type, the source break or the timer thread.

PR #1518 made the change in the Swift source, tests and showcase.

## 2. Decision

Decided under the owner's 2026-11-07 delegation, with the owner review that
#1347 requires.

1. Swift adds the public protocol `NotificationScheduler: Scheduler`. Its one
   requirement is `seconds(from:to:) -> TimeInterval`, the interval between two
   of the scheduler's instants. VMx conforms `VirtualTimeScheduler`,
   `DispatchQueue`, `RunLoop` and `OperationQueue`. A custom scheduler
   conforms by implementing `seconds(from:to:)`.
1. The designated initializers of `NotificationVM` and `ConfirmationVM` are
   generic over `S: NotificationScheduler`. An app passes a real-time scheduler
   such as `DispatchQueue.main`. A test passes a `VirtualTimeScheduler`.
1. The lifespan and decay-tick timers run on the injected scheduler. The VM
   keeps no lock. The caller therefore passes a serial scheduler that runs on
   the thread that uses the VM, for example `DispatchQueue.main` for a VM that
   a SwiftUI view binds. The commands, `dismiss()`, the timers and the
   external-resolve sink then run on that one thread and cannot interleave.
1. The change is source-breaking only for a subclass of the `open` class
   `NotificationVM` that overrides
   `init(notification:hub:scheduler:lifespan:tickInterval:)` with a
   `VirtualTimeScheduler` parameter. Such an override must become generic over
   `NotificationScheduler`. Callers that only construct the VMs compile
   unchanged.
1. Version consequence: the change ships in Swift 4.0.0. That release is
   already a major release for the throwing tree walks (ADR-0212), as README
   §6.1 requires for a flavor's own source break. The spec version stays
   3.30.0, because the cross-flavor contract does not change.
1. No conformance ID is added. `NOTIF-011` to `NOTIF-016` keep the virtual
   scheduler, and Swift tests on `DispatchQueue.main` cover real-time expiry,
   decay ticks and a pending `ConfirmationVM`.
1. This amends ADR-0063 §2.4. `VirtualTimeScheduler` is the Swift test
   scheduler for notifications, not the only scheduler the VMs accept, and a
   real-time scheduler runs the timer work on its own thread.

## 3. Consequences

- A Swift app drives notification VMs in real time, as the other flavors do.
  The notes showcase passes `DispatchQueue.main` and needs no clock-advance
  `Timer`.
- Swift meets the chapter 16 §6 rule for production schedulers.
- A Swift caller that passes a concurrent scheduler, or that uses the VM on a
  thread other than the scheduler's, can race. Chapter 16 §6 states the serial
  scheduler requirement.
- Rust is unchanged. Its notification VMs take a Rust `Scheduler` (ADR-0219).

## 4. Rejected alternatives

- **Take `AnyScheduler` or a type-erased wrapper in the public signature.**
  Combine has no `AnyScheduler`, and a VMx wrapper would add a type that
  callers must build by hand.
- **Take a closure clock instead of a scheduler.** The other flavors take a
  scheduler, and a closure does not arm timers.
- **Add a lock to `NotificationVM`.** The VM is a UI binding object that runs
  on one thread. A lock would not order the timer callbacks against the view's
  own reads.
- **Keep `VirtualTimeScheduler` only and advance it from the host.** That is
  the workaround #1347 removes. The toast dismisses late, and every host must
  own a timer.
