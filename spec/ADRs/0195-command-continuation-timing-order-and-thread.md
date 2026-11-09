# ADR 0195 — Command continuations: confirm-gate timing, fault order and thread

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 04 §8.3.1, §10.2 and §10.4; chapter 11
  §3.1; chapter 21 §6.2)
- **Related:** [ADR-0049](0049-v3-command-semantics.md),
  [ADR-0056](0056-v3-async-command-cancellation.md),
  [ADR-0145](0145-confirmation-awaits-async-inner.md), #1327, #1345.

## 1. Context

Three behaviors of commands that continue after awaited work differ across
flavors, and no rule settles them.

- **Confirm-gate timing (#1327).** Chapter 04 §8.3.1 says that the
  synchronous `Execute()` of `ConfirmationDecoratorCommand` "returns
  immediately, before the gate has resolved". When `confirm()` returns a
  result that is already complete, C# and Rust run the inner command before
  `Execute()` returns. C# calls the async `RunAsync` directly, and an `await`
  on a completed task continues on the same stack. Rust passes its
  continuation to `AsyncValue::when_settled`, which runs it at once on a
  settled value. Python and Swift schedule the flow as a task, and
  TypeScript awaits a promise, so the inner command never runs inside the
  `execute()` call.
- **Fault order (#1327).** A fire-and-forget `AsyncRelayCommand` fault reaches
  `errors`, and the completion raises `CanExecuteChanged`. Chapter 04 §10.2
  and §10.4 require both and set no order. C#, Python, TypeScript and Swift
  clear the in-flight state and raise `CanExecuteChanged` first, and then
  emit the fault. Rust publishes the fault inside its run closure, before the
  execution guard drops. Only a Rust `errors` subscriber reads
  `is_executing()` as `true`.
- **Continuation thread (#1345).** In C#, a confirmed inner command and the
  completion of an `AsyncRelayCommand` run on a thread-pool thread, also when
  the caller has a `SynchronizationContext`. `TokenPagedComposition` loads
  continue the same way. VMx C# awaits with `ConfigureAwait(false)`
  throughout, also in `FormVM` approval and `AsyncResourceVM`. No chapter
  states the thread of such a continuation. Python continues on the event
  loop that runs the operation. Swift continues on the executor of a task
  that VMx starts from nonisolated code. Rust continues on the thread that
  settles the awaited value, or on a command worker thread.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: each rule takes the simplest
option that is uniform across the five flavors.

### 2.1 `Execute()` never runs the inner command inside its own call

The fire-and-forget `Execute()` of `ConfirmationDecoratorCommand` never
invokes the inner command inside its own call. This holds also when
`confirm()` returns a result that is already complete. The inner command runs
after `Execute()` returns, or on another thread. `Execute()` MAY call
`confirm()` before it returns. The awaitable `ExecuteAsync()` path has no such
rule.

This keeps the existing chapter 04 text and the behavior of three flavors. It
is the only uniform option: TypeScript and Python cannot run a continuation
before the current call returns, because a resolved promise or a scheduled
task always continues later.

- C# moves the fire-and-forget flow to a thread-pool thread before it awaits
  the confirmation. It uses an awaiter that does not capture the
  `SynchronizationContext`. The move is unconditional, because another thread
  can complete the confirmation between a completion check and the await. It
  does not use `Task.Yield()`, because that posts to the caller's context
  (§2.3).
- Rust runs the continuation of an already settled confirmation on a VMx
  worker thread. A pending confirmation keeps its continuation on the thread
  that settles it, as before. The decorator still starts no task that
  observes the inner operation (chapter 04 §8.3.2).

### 2.2 The completion notification precedes the fault

On the fire-and-forget path, an `AsyncRelayCommand` clears its in-flight state
and raises the completion `CanExecuteChanged` first. Only then does it emit the
fault on `errors`. An `errors` subscriber therefore reads `IsExecuting == false`, and its `Execute` call can start a new execution.

This is the four-flavor order. It also matches chapter 20 §5.3, where an
approval settles before its failure reaches `ApproveErrors`. Rust drops its
execution guard before it publishes the fault.

### 2.3 VMx does not marshal continuations

A continuation after awaited work runs where that work completes. VMx does not
marshal it to the caller's thread or to `IDispatcher.Foreground`, and it makes
no further thread guarantee. This covers the confirmed inner command, the
completion `CanExecuteChanged` and `errors` emissions of an `AsyncRelayCommand`,
and the notifications of a `TokenPagedComposition` load or refresh. A consumer
that needs foreground delivery marshals the work itself (chapter 11 §3.1).

Every flavor already behaves this way, so no code changes. The rule matches
chapter 11 §3 option (b), where a subscriber has no thread guarantee without
`ObserveOn`, and chapter 21 §2.5, where collections publish on the mutation
thread and do not marshal. C# keeps `ConfigureAwait(false)`, the usual .NET
library practice. Resuming on the caller's context in C# alone would leave
Swift and Rust without the same guarantee, and C# `FormVM` and
`AsyncResourceVM` would still differ from C# commands.

## 3. Flavor impact

| Rule                     | C#         | Python     | TypeScript | Swift      | Rust       |
| ------------------------ | ---------- | ---------- | ---------- | ---------- | ---------- |
| §2.1 confirm-gate timing | changes    | no change  | no change  | no change  | changes    |
| §2.2 fault order         | no change  | no change  | no change  | no change  | changes    |
| §2.3 continuation thread | documented | documented | documented | documented | documented |

The C# README states that a confirmed inner command and async completions can
run on a thread-pool thread.

## 4. Conformance

- `CMDD-018` — the fire-and-forget `Execute()` never invokes the inner command
  inside its own call, also when `confirm()` is already complete.
- `CMD-020` — a fire-and-forget `AsyncRelayCommand` fault reaches `errors`
  after the completion `CanExecuteChanged`, so an `errors` subscriber reads
  `IsExecuting == false`.

§2.3 adds no conformance ID, because it makes no thread guarantee to test.
The catalog grows from 451 to 453 library IDs with this ADR.

## 5. Consequences

- A C# or Rust caller that relied on the inner command having run when
  `Execute()` returns must wait for it, or call `ExecuteAsync()`.
- In C# and Rust, the post hook of an outer decorator and a successor command
  (`SucceedWith` / `succeed_with`) now run before a confirmed inner command,
  as in the other flavors.
- Rust uses one short-lived worker thread for each fire-and-forget `execute()`
  whose confirmation is already settled.
- A Rust `errors` subscriber now sees the command idle and can start the next
  execution from its handler.
- A UI consumer must marshal a confirmed inner command that mutates a view
  model bound to the UI thread, in every flavor. Issue #398 tracks host
  dispatcher adapters.

## 6. Rejected alternatives

- **Allow `Execute()` to run the inner command inline.** It would keep C# and
  Rust unchanged, but a caller could not rely on one order in every flavor.
- **Resume C# continuations on the caller's `SynchronizationContext`.** It is
  common in .NET MVVM toolkits. But it would change only C#, it would differ
  from C# `FormVM` and `AsyncResourceVM`, and a caller that blocks on the task
  from the UI thread would deadlock.
- **Marshal continuations to `IDispatcher.Foreground`.** Commands hold no
  dispatcher, and no flavor marshals them today.
