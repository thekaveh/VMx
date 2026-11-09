# 11 — Threading and schedulers

VMx is thread-aware but not thread-bound. This document defines the contract every
language flavor MUST satisfy for thread/scheduler dispatch.

## 1. `IDispatcher`

Every VM holds an `IDispatcher`:

```
IDispatcher:
    Foreground : IScheduler   # Rx scheduler for events subscribers expect on the UI thread
    Background : IScheduler   # Rx scheduler for VM lifecycle work
```

The `IDispatcher` is provided via constructor / builder. There is no global
dispatcher. A host application typically creates one dispatcher per VM tree (or
shares one across all trees).

## 2. Default dispatchers

Each flavor ships an idiomatic default dispatcher whose channels are:

| Language   | Foreground                                                                               | Background                                  |
| ---------- | ---------------------------------------------------------------------------------------- | ------------------------------------------- |
| C#         | `SynchronizationContextScheduler` bound to the current thread's `SynchronizationContext` | `TaskPoolScheduler.Default`                 |
| Python     | `AsyncIOThreadSafeScheduler(loop)` for a supplied or factory-created event loop          | `ThreadPoolScheduler()`                     |
| TypeScript | `queueScheduler` (synchronous trampoline)                                                | `asyncScheduler` (macrotask)                |
| Swift      | `DefaultDispatcher` → main queue (run inline if already on main) — see note              | `DispatchQueue.global(qos: .userInitiated)` |
| Rust       | `DefaultDispatcher` → dedicated serial `vmx-foreground` worker                           | dedicated serial `vmx-background` worker    |

> **TypeScript:** `RxDispatcher.default()` uses `asyncScheduler` (a genuine
> macrotask) for background. An earlier `asapScheduler` (Promise microtask) was
> replaced because it drains before the next macrotask and can starve the event
> loop, contradicting the "background" intent (VMX-087).

> **Swift:** Swift's `Dispatcher` protocol is closure-based
> (`scheduleForeground` / `scheduleBackground` over `DispatchQueue`, **not** Combine
> `Scheduler` properties). The shipped `DefaultDispatcher` preset — main-queue
> foreground (run inline when already on the main thread) and a `.userInitiated`
> global background queue — is the Swift equivalent of `RxDispatcher.default()`
> (shipped since v2.4.0). ADR-0061 §4 rejected adding `Scheduler`-typed
> foreground/background properties, making the closure shape final.

> **Rust:** Rust's `Dispatcher` is likewise closure-based. `dispatch` is the
> foreground channel and `dispatch_background` is the background channel.
> `NullDispatcher` and `ImmediateDispatcher` run both inline;
> `ManualDispatcher` provides independently drainable queues for tests. A
> failed fire-and-forget background hook is emitted on the component's hot
> `background_errors()` stream after foreground rollback. Composite, group,
> modeled-composite, and aggregate containers expose the same stream for a
> background child failure that rolls the container back; hook panics use a
> `VmxError::Other` diagnostic because Rust panic payloads are not constrained
> to the error type.

UI integrations (WPF, Avalonia, MAUI, tkinter, PyQt, …) provide their own
foreground scheduler tied to the UI thread.

## 3. Foreground emissions

VMs MUST dispatch the following emissions via `IDispatcher.Foreground`:

- Every `PropertyChangedMessage` they emit.
- Every `INotifyCollectionChanged.CollectionChanged` event (composites and groups).
- The `IsCurrent` property change on every child of a composite whose `Current`
  changed.
- The **terminal** `ConstructionStatusChangedMessage` of a *background*
  construct/destruct — i.e. the `Constructed` / `Destructed` emission, and the
  `02-lifecycle.md §2.5` transactional-rollback emission — which the reference
  implementations marshal onto `IDispatcher.Foreground` rather than publish on the
  background (pool) thread (VMX-025; see §4).

Implementations MAY achieve this either by:

- **(a)** marshalling the `Send` onto `IDispatcher.Foreground` so the publish
  itself runs on the foreground thread; or
- **(b)** calling `Send` on any thread and exposing the hub's `Messages`
  observable so subscribers can apply `.ObserveOn(dispatcher.Foreground)` and get
  a foreground-dispatched delivery.

These two options are **not** observationally equivalent: under (b) a subscriber
that does not apply `ObserveOn` has no thread guarantee. The normative rule is
therefore: a subscriber is guaranteed foreground delivery only when the
implementation marshals via (a) **or** the subscriber opts in via `ObserveOn`;
absent both, no thread guarantee is made (VMX-048). The reference implementations
marshal background lifecycle completions via (a) (§4), so those terminal-status
emissions reach subscribers on the foreground thread regardless of `ObserveOn`.

Message-hub transactions do not introduce a scheduler. The transaction owner
drains its queued messages on the thread that exits the outermost scope. Other
producers are serialized behind that scope and retain ordinary synchronous
delivery on their own calling thread after it exits. Re-entrant sends are
delivered iteratively on the current drainer's thread. See `03-messages.md §3.3`.

### 3.1 Continuations after awaited work (spec v3.30, ADR-0195)

Some VMx operations await work and then continue. A
`ConfirmationDecoratorCommand` awaits `confirm()` and then runs the inner
command (chapter 04 §8.3). An `AsyncRelayCommand` awaits its task and then
raises its completion `CanExecuteChanged` and any `errors` emission (chapter
04 §10). A `TokenPagedComposition` load or refresh awaits its fetch and then
publishes its `CollectionChanged` and property notifications (chapter 21 §6).

VMx does not marshal such a continuation. The continuation runs where the
awaited work completes, not on the caller's thread and not on
`IDispatcher.Foreground`. VMx makes no further thread guarantee for it:

- **C#:** VMx awaits with `ConfigureAwait(false)`. The continuation can run on
  a thread-pool thread, also when the caller has a `SynchronizationContext`.
- **Python:** the continuation runs on the event loop that runs the operation.
  That is the caller's running loop, or the VMx background loop when no loop
  runs.
- **TypeScript:** the continuation runs on the one JavaScript thread.
- **Swift:** the continuation runs on the executor of the Swift task that VMx
  starts. VMx starts these tasks from nonisolated code, so they do not run on
  the main actor.
- **Rust:** the continuation runs on the thread that settles the awaited value,
  or on a VMx worker thread.

A consumer that needs foreground delivery marshals the work itself. It
subscribes through `ObserveOn(dispatcher.Foreground)` or the flavor
equivalent, or it makes the inner command post its work to
`IDispatcher.Foreground`. An inner command that mutates a composite must do
so on the foreground (§3).

## 4. Background work

VMs MAY perform construction and destruction work on `IDispatcher.Background`. The
builder option `Background(true)` (see `10-builders.md §Default values` for the full
builder API) enables this. With background enabled, `construct()` and `destruct()`
return immediately and complete asynchronously; status transitions are still observable
via the hub. Subscribers that need to await completion should subscribe to
`ConstructionStatusChangedMessage` and filter for the terminal state.

With background disabled (the default), `construct()` and `destruct()` run on the
calling thread and complete before returning.

Direct `reconstruct()` on a component remains one synchronous, atomic
destruct-then-construct operation regardless of that component's own `Background`
option. The option governs the component's two standalone operations only. This
does not turn parent orchestration into a synchronous wait for background-enabled
descendants; containers retain their existing child-cascade and failure routes.

The child-transition helper of chapter 02 §6.1 runs inside the parent's hook,
so a background-enabled parent runs it on `IDispatcher.Background`. In Rust,
the walk of a `construct` or `destruct` of a component built with
`background(true)` runs after the hook on the background dispatcher
(ADR-0203). A reconstruct, with stored walks or through
`reconstruct_with_children`, follows the direct-reconstruct rule above and runs
synchronously for every component. Background children of the walk still run
their own hooks on the background dispatcher, and the walk waits for them.

The background form proceeds in three steps:

1. The **intermediate** transition (`Constructing` / `Destructing`) is emitted
   synchronously on the calling thread, so subscribers see the transition start
   immediately.
1. The `OnConstruct` / `OnDestruct` hook runs on `IDispatcher.Background`.
1. The **terminal** transition (`Constructed` / `Destructed`) is marshalled onto
   `IDispatcher.Foreground` (§3, VMX-025) — subscribers observe the completion on
   the foreground thread, not the pool thread.

Three normative guarantees apply to the background completion:

- **Atomicity / no resurrection.** Each transition runs under the per-VM guard of
  `02-lifecycle.md §2.4`. If `dispose()` runs while the background work is queued
  or in flight, the completion observes the terminal `Disposed` state under the
  guard and aborts — it does not run the hook (when disposed before the hook),
  does not resurrect the VM, and does not publish a post-dispose status message
  (VMX-001 / VMX-004; invariant 6).
- **Concurrent re-invocation.** A second `construct()` / `destruct()` /
  `reconstruct()` entered while a background transition is in flight is rejected
  by the in-flight guard and the per-VM primitive (`LIFE-008`; `02-lifecycle.md §2.4`).
- **Transactional rollback.** If the background hook raises, `Status` is rolled
  back to the prior settled state (`02-lifecycle.md §2.5`) with the rollback
  emission marshalled onto `IDispatcher.Foreground`; the in-flight guard is
  cleared so the VM stays recoverable. A C# async lifecycle caller receives the
  original failure through its returned `Task` after rollback (ADR-0109).
  Fire-and-forget and non-C# surfaces follow their documented scheduler error
  route; Swift has no awaiter and its non-throwing scheduler closure cannot
  redeliver the error to the already-returned caller (ADR-0053).

Rust and C# additionally harden their rejectable custom-scheduler APIs: rejection
before closure acceptance restores the prior settled state and clears admission.
Foreground-completion rejection uses the flavor's asynchronous error route and
rolls back on the current worker because the requested foreground channel is
unavailable. This is implementation robustness, not a new cross-flavor normative
requirement; Python and TypeScript scheduler exceptions and Swift's nonthrowing
scheduler closure remain governed by their ecosystem APIs.

The await primitive for a consumer-defined background wrapper is the
terminal-status subscription above; the hub does not replay the last status to a
late subscriber. Every flavor's containers wait at the status level for
background children to settle (chapter 02 §6). In Rust, a container waits for a
child node that forwards `VmNode::when_lifecycle_settled`. For a node that does
not forward it, the container observes its own message hub (ADR-0205). When the
container starts the node and, by the time the start call returns, the hub
delivered or queued the node's transient status, the container waits on that
hub for a status of the node that arrives once the node is no longer in flight,
and a node that settles anywhere else rolls the container back. In every other case (the node publishes on another hub, or the
container joins a node already in flight), the container accepts the node while
it is still in flight rather than wait without limit. C# alone ships
first-class outcome tasks for awaiting a transition (`ConstructAsync` /
`DestructAsync`); those
tasks preserve hook and child-cascade failures per ADR-0109. Equivalent async
lifecycle entry points remain deliberately absent from the other flavors under
ADR-0008/ADR-0009 rather than an active parity requirement.

## 5. Null variant — `NullDispatcher` (spec v2.0)

Every service contract in VMx has a **null-object** variant per ADR-0017. For
`IDispatcher`, the variant is `NullDispatcher`:

- `Foreground` returns an immediate scheduler — work scheduled on it runs
  synchronously on the calling thread.
- `Background` returns the same kind of immediate scheduler.

In effect, every `Schedule(action)` call executes `action()` inline. The null
dispatcher does NOT defer, queue, or thread-hop. Typical uses: tests, headless
hosts, or any code path where async dispatch is not required.

The null variant is conformance-tested by `NULL-002`.

## 6. Delayed work: the scheduler and `DelayedTask` (spec v3.30, ADR-0219)

Some work runs after a delay: a search-term debounce (chapter 06 §8), a
notification lifespan (chapter 16 §6), and application timers such as polling
or a short "Copied" state. This section defines the one clock that all such
work uses and the `DelayedTask` helper over it.

### 6.1 The scheduler

A *scheduler* is the clock for delayed work:

```
Scheduler:
    now : Time                                  # current scheduler time
    schedule(delay, action) : Cancellation      # run action once after delay
```

Cancelling the returned handle before the action starts prevents the action.
Each delayed-work consumer takes its scheduler at construction. There is no
global scheduler. `SearchableState` uses the real-time scheduler below when the
caller passes none; `DelayedTask` and the notification VMs take one
explicitly. The Rust `new` and `with_hub` notification conveniences use
`SystemScheduler`.

| Language   | Scheduler type                                           | Real-time scheduler         | Virtual-time test scheduler                       |
| ---------- | -------------------------------------------------------- | --------------------------- | ------------------------------------------------- |
| C#         | `IScheduler`                                             | `DefaultScheduler.Instance` | `Microsoft.Reactive.Testing.TestScheduler`        |
| Python     | `SchedulerBase`                                          | `TimeoutScheduler()`        | `reactivex.testing.TestScheduler`                 |
| TypeScript | `SchedulerLike`                                          | `asyncScheduler`            | rxjs `TestScheduler`, or any `SchedulerLike` fake |
| Swift      | Combine `Scheduler` (`NotificationScheduler` for ch. 16) | `DispatchQueue.main`        | `VirtualTimeScheduler`                            |
| Rust       | `Scheduler` trait                                        | `SystemScheduler`           | `VirtualTimeScheduler`                            |

Rust has no reactive scheduler (ADR-0103), so it defines the trait:

```rust
pub trait Scheduler: Send + Sync + 'static {
    fn now(&self) -> Duration;
    fn schedule(&self, delay: Duration, action: Box<dyn FnOnce() + Send>) -> ScheduledAction;
}
```

`ScheduledAction::cancel()` cancels the action, and a second call has no
effect. Dropping a `ScheduledAction` does not cancel it. `SystemScheduler`
runs actions in due-time order on one VMx timer thread, which it starts at its
first `schedule`. Its `now` is the time since a fixed process origin.
`VirtualTimeScheduler` is cloneable; its clones share one clock, which
`advance_by(Duration)` moves.

A *virtual-time* scheduler starts at its origin. Its `now` changes only when a
test advances it. An advance runs each action that becomes due, in due-time
order, on the thread that advances. Actions with the same due time run in the
order they were scheduled. Work that an action schedules runs in the same
advance when it is due by the end of that advance. A cancelled action never
runs.

### 6.2 Relation to `IDispatcher`

Delayed work never goes through `IDispatcher`. The dispatcher channels take
work without a delay, and their null variants cannot delay work in a portable
way (§5). An action runs where its scheduler runs it. VMx does not marshal it
to `IDispatcher.Foreground`, as §3.1 says for continuations. A host that needs
UI-thread delivery passes a scheduler that runs on the UI thread, such as a C#
`SynchronizationContextScheduler` or Swift `DispatchQueue.main`.

### 6.3 `DelayedTask`

`DelayedTask` holds at most one pending action on an injected scheduler. It is
the portable form of a timer, a debounce and a polling loop.

```
DelayedTask(scheduler):
    schedule(delay, action) : void   # replace the pending action; restart the delay
    cancel() : void                  # cancel the pending action, if any
    IsPending : bool                 # an action is scheduled and has not started
    dispose() : void                 # cancel; later calls have no effect
```

- `schedule` cancels the pending action, if any, and then schedules `action`
  after `delay`. A second call therefore restarts the delay.
- `cancel` cancels the pending action. It has no effect when no action is
  pending.
- `IsPending` is true from `schedule` until the action starts, `cancel` or
  `dispose`. When the action starts, `IsPending` is already false. The action
  can call `schedule` again, which repeats a polling loop.
- A zero or negative delay runs the action at the scheduler's next
  opportunity. `schedule` never runs the action itself.
- `dispose` cancels the pending action. Later `schedule` and `cancel` calls
  have no effect, and `IsPending` stays false. A second `dispose` has no
  effect. Disposal never disposes the scheduler.
- The helper is safe to call from any thread. After `schedule`, `cancel` or
  `dispose` returns, the replaced or cancelled action never starts. An action
  that already started runs to its end, and `cancel` does not wait for it.
- A failing action follows the stream-fed route of chapter 03 §3.6. The
  failure never reaches the scheduler. The task stays usable, and a later
  `schedule` runs. Swift actions cannot fail.

The delay type is idiomatic (ADR-0006): C# `TimeSpan`, Python seconds as a
`float` or a `timedelta`, TypeScript milliseconds, Swift `TimeInterval`
seconds and Rust `Duration`.

`DelayedTask` is a reactive helper for the disposal invariant (chapter 01 §4,
`DISP-005`).

## 7. Conformance

`THR-001` through `THR-004`, plus the null-object IDs `NULL-002`
(NullDispatcher schedules synchronously) and `NULL-003` (paired null variants
exist for the core service contracts), in `12-conformance.md` cover:

- `PropertyChanged` observed on foreground scheduler
- Background construct dispatches on background scheduler
- `CollectionChanged` observed on foreground scheduler
- Subscriber observes on chosen scheduler via `ObserveOn`

`DLY-001` through `DLY-005` cover `DelayedTask` under a virtual-time
scheduler (§6.3):

- one run at the due time, with `IsPending` false when the action starts
- a second `schedule` replaces the pending action and restarts the delay
- `cancel` prevents the pending action
- disposal cancels the pending action, and later calls have no effect
- a failing action stays isolated, and the task stays usable
