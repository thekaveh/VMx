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

| Language   | Foreground                                                                               | Background                  |
| ---------- | ---------------------------------------------------------------------------------------- | --------------------------- |
| C#         | `SynchronizationContextScheduler` bound to the current thread's `SynchronizationContext` | `TaskPoolScheduler.Default` |
| Python     | `AsyncIOScheduler(loop)` for the current event loop                                      | `ThreadPoolScheduler()`     |
| TypeScript | `queueScheduler` (microtask)                                                             | `asapScheduler`             |

UI integrations (WPF, Avalonia, MAUI, tkinter, PyQt, …) provide their own
foreground scheduler tied to the UI thread.

## 3. Foreground emissions

VMs MUST dispatch the following emissions via `IDispatcher.Foreground`:

- Every `PropertyChangedMessage` they emit.
- Every `INotifyCollectionChanged.CollectionChanged` event (composites and groups).
- The `IsCurrent` property change on every child of a composite whose `Current`
  changed.

Implementations MAY achieve this either by:

- Calling `Send` on the hub from the foreground thread (synchronous dispatch); or
- Calling `Send` on any thread and having the hub's `Messages` observable
  `.ObserveOn(dispatcher.Foreground)` so subscribers get a foreground-dispatched
  delivery. The spec does not prescribe which; only that subscribers can opt in
  via `ObserveOn` and see foreground delivery.

## 4. Background work

VMs MAY perform construction and destruction work on `IDispatcher.Background`. The
builder option `Background(true)` (see `10-builders.md §Default values` for the full
builder API) enables this. With background enabled, `construct()` and `destruct()`
return immediately and complete asynchronously; status transitions are still observable
via the hub. Subscribers that need to await completion should subscribe to
`ConstructionStatusChangedMessage` and filter for the terminal state.

With background disabled (the default), `construct()` and `destruct()` run on the
calling thread and complete before returning.

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

`THR-001` through `THR-004` in `12-conformance.md` cover:

- `PropertyChanged` observed on foreground scheduler
- Background construct dispatches on background scheduler
- `CollectionChanged` observed on foreground scheduler
- Subscriber observes on chosen scheduler via `ObserveOn`
