# ADR 0219 — One scheduler contract for delayed work, a `DelayedTask` helper, and Rust timers

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 11 §6, chapter 06 §8, chapter 16 §6 and
  §8.1; `DLY-001`..`DLY-005`)
- **Supersedes:** [ADR-0099](0099-searchable-source-reactivity.md) §2.7, the
  synchronous Rust term notification.
- **Related:** [ADR-0031](0031-notification-rendering-vms.md) decision 4,
  [ADR-0061](0061-swift-hierarchical-threading-divergences.md) §4,
  [ADR-0073](0073-hierarchical-child-cache-invalidation.md) §3,
  [ADR-0084](0084-cross-cutting-disposal-invariant.md),
  [ADR-0178](0178-rust-notification-vms-dispose.md),
  [ADR-0197](0197-notification-state-stops-at-resolution-and-hub-dispose.md),
  #670, #1261, #1265.

## 1. Context

VMx has two kinds of delayed work. `SearchableState` debounces its term
(chapter 06 §8). `NotificationVM` decays and expires over a lifespan (chapter
16 §6). C#, Python and TypeScript take a reactive scheduler for both: an
`IScheduler`, a `SchedulerBase` or a `SchedulerLike`. Swift takes a Combine
`Scheduler`: a `DispatchQueue` for search and a `NotificationScheduler` for
notifications (#1347). Tests pass a virtual-time scheduler and advance it.

Rust has no scheduler type. Its `Dispatcher` takes a closure and no delay.
Rust `SearchableState` therefore has no debounce. Each term change sends one
`Custom("filtered")` message before `set_search_term` returns (#1261). ADR-0099
§2.7 recorded this as the existing facade. Rust `NotificationVm` and
`ConfirmationVm` take no scheduler. Their lifespan moves only when the host
calls `advance_by_ms`, so the Rust notes-showcase notifications never expire
(#1265).

Applications also need delayed work of their own: polling, a short "Copied"
state, autosave, retry back-off and TTL invalidation (#670). Issue #593 item 13
declined a delayed-task primitive and asked for "a recipe over the dispatcher
schedulers" instead
([decline comment](https://github.com/thekaveh/VMx/issues/593#issuecomment-6128740045)).
That recipe is not portable:

- The null dispatchers differ for delayed work. C# `ImmediateScheduler` blocks
  the thread. Python `ImmediateScheduler` raises `WouldBlockException`.
  TypeScript `queueScheduler` defers through `setInterval`.
- Swift and Rust dispatchers take closures with no delay. ADR-0061 §4 rejected
  scheduler-typed dispatcher properties in Swift.
- TypeScript `ManualDispatcher` only flushes its whole queue, so a periodic
  action never ends under it.

ADR-0073 §3 deferred TTL invalidation because no injectable clock existed.

## 2. Decision

Decided under the owner's 2026-11-07 delegation. Each choice is the smallest
one that is the same in every flavor.

### 2.1 The scheduler is the clock

A *scheduler* is the one clock abstraction. It has two operations:

- `now`: the current time of the scheduler.
- `schedule(delay, action)`: run `action` once after `delay`. It returns a
  handle that cancels the action if the action has not started.

C#, Python, TypeScript and Swift keep the types that they already accept. They
gain no new scheduler type. Rust gains the trait and two implementations
(§2.6). Chapter 11 §6.1 lists the types.

### 2.2 One virtual-time test scheduler in each flavor

A virtual-time scheduler starts at its origin, and its `now` changes only when
a test advances it. An advance runs each action that becomes due, in due-time
order, on the thread that advances. Actions with the same due time run in the
order they were scheduled. Work that an action schedules runs in the same
advance when it is due by the end of that advance. A cancelled action never
runs.

The test schedulers are C# `Microsoft.Reactive.Testing.TestScheduler`, Python
`reactivex.testing.TestScheduler`, the TypeScript rxjs `TestScheduler` or any
`SchedulerLike` fake, Swift `VirtualTimeScheduler` and Rust
`VirtualTimeScheduler`. Only Rust adds a type.

### 2.3 The dispatcher stays separate

Delayed work never goes through `IDispatcher`. The dispatchers keep their
channels without a delay, and ADR-0061 §4 stands. An action runs where its
scheduler runs it. VMx does not marshal it to `IDispatcher.Foreground`, as
chapter 11 §3.1 already says for continuations. A host that needs UI-thread
delivery passes a scheduler that runs on the UI thread. This replaces the
#593 item-13 recipe.

### 2.4 `DelayedTask` is the one new primitive

#593 item 13 is revisited. Every flavor gains `DelayedTask`, a disposable
helper that holds at most one pending action on an injected scheduler. It is
the portable form of a timer, a debounce and a polling loop.

- `schedule(delay, action)` cancels the pending action, if any. It then
  schedules `action` after `delay`. A second call therefore restarts the
  delay.
- `cancel()` cancels the pending action. It has no effect when no action is
  pending.
- `isPending` is true from `schedule` until the action starts, `cancel` or
  disposal.
- When the action starts, `isPending` is already false. The action can call
  `schedule` again, which is how a polling loop repeats.
- `dispose()` cancels the pending action. Later `schedule` and `cancel` calls
  have no effect. A second `dispose()` has no effect. Disposal never disposes
  the scheduler.
- A zero or negative delay runs the action at the scheduler's next
  opportunity, never inside `schedule`.
- The helper is safe to call from any thread. After `schedule`, `cancel` or
  `dispose` returns, the replaced action never starts. An action that already
  started runs to its end, and `cancel` does not wait for it.
- A failing action follows the stream-fed route of chapter 03 §3.6. The
  failure never reaches the scheduler, and the helper stays usable.

The delay type is idiomatic (ADR-0006): C# `TimeSpan`, Python seconds as a
`float` or a `timedelta`, TypeScript milliseconds, Swift `TimeInterval`
seconds and Rust `Duration`.

`DelayedTask` joins the reactive-helper disposal family (`DISP-005`) and the
disposal inventory. `DLY-004` covers its disposal.

### 2.5 Rust `SearchableState` debounces its term

Rust `SearchableState` gains `with_debounce(Duration)` and
`with_scheduler(scheduler)`. The defaults are 1 second and `SystemScheduler`,
as in chapter 06 §8. Both methods consume the state and return it, so a caller
sets them before first use.

- A term change schedules one `filtered` message after the debounce. A later
  term change inside the window restarts it. The state uses a `DelayedTask`.
- A zero debounce sends the message before `set_search_term` returns, as the
  C#, Python and TypeScript helpers skip the debounce operator for zero.
- `search()` sends its message at once. It does not cancel a pending term
  delivery, as the Rx and Combine debounce operators in the other flavors do
  not.
- A source-change message sends at once and does not touch the pending term
  delivery (chapter 06 §8.1).
- Disposal cancels the pending term delivery.

`filtered()` stays a pull and always reads the current term. This supersedes
the synchronous term notification in ADR-0099 §2.7.

### 2.6 Rust scheduler types

Rust adds a `Scheduler` trait, a `ScheduledAction` cancel handle, a
`SystemScheduler` and a `VirtualTimeScheduler`. Chapter 11 §6.1 gives the
shape.

- `SystemScheduler` runs actions on one VMx timer thread, in due-time order.
  It starts the thread at its first `schedule`. Its `now` is the time since a
  fixed process origin.
- `VirtualTimeScheduler` is cloneable, and its clones share one clock. Its
  `advance_by(Duration)` follows §2.2.
- Dropping a `ScheduledAction` does not cancel the action. Only `cancel()`
  does, as the Rx disposables in the other flavors cancel only when disposed.

### 2.7 Rust notification VMs take a scheduler

`NotificationVm::with_scheduler(notification, hub, scheduler, lifespan_ms)` and
`ConfirmationVm::with_scheduler(notification, hub, scheduler, lifespan_ms)`
are the new constructors. `new` and `with_hub` keep their signatures and use
`SystemScheduler`, so a notification built with them now expires in real time.

- The VM reads the elapsed time from `scheduler.now()` and measures it from
  construction. `remaining_time_ms()` and `opacity()` keep their meaning.
- `NotificationVm` arms one `DelayedTask` at the lifespan. When it fires, the
  VM stores 0 and resolves the hub with `Approve` (chapter 16 §6).
- `ConfirmationVm` arms no timer. Its remaining time reaches 0 and it stays
  pending (chapter 16 §7). TypeScript and Swift also arm no timer for a
  confirmation.
- Resolution and disposal cancel the timer and keep the render values that
  they had at that step (ADR-0197).
- `advance_by_ms` is removed. Time moves only through the scheduler, as in the
  other flavors, and a VM never has two clocks. A test advances a
  `VirtualTimeScheduler` instead.

### 2.8 Conformance

The new `DLY` prefix covers `DelayedTask` under a virtual-time scheduler in
all five flavors:

- `DLY-001`: one run at the due time, with `isPending` false when the action
  starts.
- `DLY-002`: a second `schedule` replaces the first and restarts the delay.
- `DLY-003`: `cancel` stops the pending action.
- `DLY-004`: disposal cancels, and later calls have no effect.
- `DLY-005`: a failing action stays isolated, and the task stays usable.

The existing `COMP-015`, `COMP-016`, `SRCH-004`, `SRCH-008` and
`NOTIF-011`..`NOTIF-016` tests cover the Rust debounce and notification
changes. `SRCH-004` drops its clause for a flavor with a synchronous term
notification, because no flavor has one now.

## 3. Consequences

- C#, Python, TypeScript and Swift each add `DelayedTask` and its `DLY` tests.
  Their search and notification types do not change.
- Rust adds the scheduler types and `DelayedTask`. `SearchableState` now
  delivers term messages after a 1-second debounce by default, on the timer
  thread. A caller that needs the earlier timing sets a zero debounce.
- Rust notification VMs expire in real time by default. `advance_by_ms` is
  removed, which is a breaking change in the 0.x crate. The Rust notes-showcase
  notifications now expire after their lifespan.
- Chapter 06 §8 drops its "Open Rust gap" note. Chapter 16 §6 and §8.1 no
  longer say that Rust has no scheduler.
- The polling and transient-state recipes in the state-reactive-helpers guide
  use `DelayedTask` in place of the per-flavor timer recipe.
- TTL invalidation (ADR-0073 §3) can now build on an injected scheduler. This
  ADR does not define a TTL contract.
- Swift `SearchableState` still accepts only a `DispatchQueue`, so a Swift
  test cannot drive its debounce with virtual time. This ADR does not change
  it.

## 4. Alternatives considered

- **A new clock interface in every flavor.** Rejected. C#, Python, TypeScript
  and Swift already accept a scheduler with `now` and a delayed `schedule`. A
  second type would duplicate them.
- **Delayed channels on `IDispatcher`.** Rejected. ADR-0061 §4 rejected
  scheduler-typed dispatcher properties in Swift, and the null dispatchers
  cannot delay work in a portable way.
- **Keep `advance_by_ms` as a Rust test path.** Rejected. A VM with two clocks
  can disagree with itself, and no other flavor has a manual advance on the VM.
- **Make the scheduler a required Rust constructor argument.** Rejected. It
  breaks every `with_hub` caller. The other flavors require it, but the Rust
  `new` and `with_hub` conveniences are a recorded Rust divergence (ADR-0009).
