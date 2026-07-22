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

Each language flavor ships an `RxDispatcher` whose defaults are:

| Language   | Foreground                                                                               | Background                                  |
| ---------- | ---------------------------------------------------------------------------------------- | ------------------------------------------- |
| C#         | `SynchronizationContextScheduler` bound to the current thread's `SynchronizationContext` | `TaskPoolScheduler.Default`                 |
| Python     | `AsyncIOScheduler(loop)` for the current event loop                                      | `ThreadPoolScheduler()`                     |
| TypeScript | `queueScheduler` (synchronous trampoline)                                                | `asyncScheduler` (macrotask)                |
| Swift      | `DefaultDispatcher` → main queue (run inline if already on main) — see note              | `DispatchQueue.global(qos: .userInitiated)` |

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

## 4. Background work

VMs MAY perform construction and destruction work on `IDispatcher.Background`. The
builder option `Background(true)` (see `10-builders.md §Default values` for the full
builder API) enables this. With background enabled, `construct()` and `destruct()`
return immediately and complete asynchronously; status transitions are still observable
via the hub. Subscribers that need to await completion should subscribe to
`ConstructionStatusChangedMessage` and filter for the terminal state.

With background disabled (the default), `construct()` and `destruct()` run on the
calling thread and complete before returning.

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

The await primitive for a consumer-defined background wrapper is the
terminal-status subscription above; the hub does not replay the last status to
a late subscriber. C# alone ships first-class outcome tasks and composite
"await all children" orchestration (`ConstructAsync` / `DestructAsync`); those
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

## 6. Conformance

`THR-001` through `THR-004`, plus the null-object IDs `NULL-002`
(NullDispatcher schedules synchronously) and `NULL-003` (paired null variants
exist for the core service contracts), in `12-conformance.md` cover:

- `PropertyChanged` observed on foreground scheduler
- Background construct dispatches on background scheduler
- `CollectionChanged` observed on foreground scheduler
- Subscriber observes on chosen scheduler via `ObserveOn`
