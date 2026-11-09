# ADR 0200 — Each lifecycle failure reaches one reporting route

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 02 §2.4, §6.1 and §7)
- **Extends:** [ADR-0126](0126-coordinate-admitted-hooks-with-disposal.md) and
  [ADR-0108](0108-best-effort-terminal-disposal.md). Follows the
  precedent of
  [ADR-0122](0122-defer-container-disposal-through-membership-transactions.md).
  Related: #1297, #1481, PR #1205, #1052, #1053.

## 1. Context

Two cases let a lifecycle failure happen after the call that started the work
has returned. The spec did not say which caller receives it.

### 1.1. Cycle-deferred disposal (#1297)

A `dispose()` from another thread can close a wait-for cycle with a running
hook. ADR-0126 then defers the VM's terminal cleanup to the hook's thread. The
cleanup runs when the hook ends. Since PR #1120, Rust runs the container's
child cascade in that cleanup before the dispose hook. At `d05d08d7`:

- Rust returns the cleanup's first failure from the hook thread's
  `construct()`, `destruct()` or `reconstruct()`, when the hook succeeded. A
  background hook sends it to `background_errors()`. Rust also defers a
  `dispose()` made on the hook's own thread, and reports that failure in the
  same way.
- C# `FinishLifecycleHook` and Python `_invoke_lifecycle_hook` run the
  deferred cleanup when the hook lease ends, and discard any exception.
- Swift `dispose()` does not throw. TypeScript runs on one thread and cannot
  form the cycle.

Chapter 02 §2.4 kept the earliest failure when deferred cleanup also fails. It
did not say whether a deferred failure alone reaches a caller.

### 1.2. Several failures in one shared-scheduler flush (#1481)

`RxDispatcher.immediate()` and `NullDispatcher` run both TypeScript channels on
rxjs `queueScheduler`, so one synchronous flush can run the lifecycle work of
several calls. PR #1205 chose one error per flush:

- The outermost background `construct()` or `destruct()` keeps the first
  failure of its flush and throws it after the flush. It drops later failures.
- With no active drain, each failure queues a foreground throw. The first throw
  leaves the flush, and the flush error unsubscribes the other throws.
- `recoverDropped` reruns VMx actions that a flush error dropped (#1052). It
  catches every failure of recovered work in an empty `catch`, because a throw
  from an rxjs finalizer would replace the flush error.
- Recovery runs on any unsubscribe of an action that has not run. Only
  `ManualDispatcher` opts out, through an internal mark. A third-party
  scheduler that cancels at teardown therefore runs VMx hooks inside its own
  unsubscribe.

Chapter 02 §6.1 said that a walk failure surfaces through the flavor's
background-failure path. It had no rule for two failures in one flush.

## 2. Decision

### 2.1. The principle

Decided under the owner's 2026-11-07 delegation: each lifecycle failure
reaches exactly one reporting route, and VMx drops none. The first-failure
rule of §2.4 and §7 (ADR-0108, ADR-0126) still holds inside one call: a later
failure of the same call never replaces the first one.

### 2.2. Cycle-deferred disposal

1. The call that runs a deferred terminal cleanup reports the cleanup's first
   failure, when that call has no earlier failure of its own. That call is the
   admitted hook's `construct()`, `destruct()` or `reconstruct()`. The C#
   async methods report it as they report a hook failure. A background hook
   reports it through the flavor's background-failure path.
1. The call has already been superseded by `Disposed`, so it commits nothing
   more (§7.2). It returns the deferred failure as a call that `Disposed`
   superseded returns a failure that was already propagating.
1. A hook failure, or another failure that was already propagating, stays
   first. The deferred failure does not replace it (ADR-0126).
1. The cycle-broken `dispose()` call returns normally. It ran no cleanup.
1. The same rule covers Rust's deferral of a `dispose()` made on the hook's own
   thread. C# and Python run that disposal inline, so their `dispose()` call
   runs the cleanup and raises its failure. In every case, the call that runs
   the cleanup reports it.
1. Swift `dispose()` does not throw, so Swift reports nothing (chapter 02 §2.4).
   TypeScript cannot form the cycle.

Reasons: no other caller remains to receive the failure, and discarding it
hides a failed child disposal. ADR-0122 already makes the call that runs a
deferred disposal propagate its failure. Rust already behaves this way, so C#
and Python change. The option that Rust discards the failure was rejected,
because it loses a failure that the other disposal rules report.

### 2.3. Several failures in one shared-scheduler flush

1. The first failure to leave the flush is thrown to the flush's caller. This
   keeps Option A of #1481: the thrown error does not change. For an outermost
   background `construct()` or `destruct()`, that is the first failure
   recorded in its flush, or the first error that left the flush before any
   was recorded.
1. Every other failure of the flush is reported once through the flavor's
   unhandled-error route, after the flush returns. For TypeScript that route is
   rxjs `config.onUnhandledError`. This covers:
   - a later failure that an active drain records;
   - a queued foreground throw that a scheduler unsubscribed before it ran,
     whether a flush error dropped it or a separate or cancelled scheduler
     unsubscribed it;
   - a failure of recovered work (#1052); and
   - an error that left the flush after the drain had already recorded a
     failure.
1. Independent operations each report their own failure. In C# and Python,
   each of those calls would throw its own failure, so one report for each
   failure is the closest match.
1. A scheduler that cancels its queued work on purpose marks itself first.
   VMx then runs none of the lifecycle work that the scheduler unsubscribes:
   no hook and no status publication. The TypeScript mark becomes public API.
   A failure that already happened is still reported, because cancellation
   stops work, not reports.
1. A scheduler that does not mark itself keeps the #1052 recovery, so a VM
   whose action a flush error dropped still settles.

Reasons: Option A keeps the error type that callers catch. Option B, an
`AggregateError` of every failure, was rejected because it changes that type
and differs from the first-failure rule of §2.4 and §7. Reporting the other
failures removes the silent loss that #1481 describes. The rxjs unhandled-error
route already carries the subscriber failures of `HUB-007`, so it adds no new
channel.

## 3. Flavor impact

- **C#.** `FinishLifecycleHook` returns the deferred cleanup's failure instead
  of discarding it. `RunLifecycleHook` throws it after the lease is released,
  when the hook succeeded. A hook that deferred its completion is abandoned
  first, as for a hook failure (ADR-0109).
- **Python.** `_invoke_lifecycle_hook` keeps the deferred cleanup's failure and
  raises it after the lease is released, when the hook succeeded. A deferred
  lifecycle future is abandoned first, as for a hook failure.
- **TypeScript.** `ComponentVMBase` reports every failure that does not leave
  the flush through rxjs `config.onUnhandledError`. The package exports
  `markSchedulerCancelled(scheduler)` from its root entry point.
- **Rust.** No behavior change. A conformance-suite test pins the rule.
- **Swift.** No change.

## 4. Conformance

No conformance ID is added. TypeScript is the only flavor with a shared flush,
and Swift and TypeScript cannot report a cycle-deferred failure. Regression
tests in C#, Python and Rust cover §2.2. TypeScript unit tests cover §2.3. The
catalog does not change.

## 5. Consequences

- C# and Python `construct()`, `destruct()` and `reconstruct()` can now raise a
  disposal failure of the same VM, after a foreign `dispose()` deferred its
  cleanup. The VM is then `Disposed`.
- TypeScript tests that cause a second failure in one flush now see a report
  on `config.onUnhandledError` and must expect it.
- TypeScript gains one public function. It is additive.
- `docs/content/primitives/disposal-contract.md` states the deferred-failure
  rule and the Swift and TypeScript exceptions.
