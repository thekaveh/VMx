# 23 — `AsyncResourceVM<T>`

`AsyncResourceVM<T>` is a UI- and transport-neutral component viewmodel for one
asynchronously acquired value. It centralizes loading presentation state,
retry, cancellation, stale-result suppression, and optional value ownership.

## 1. Scope

The primitive owns one loader and at most one current operation. It exposes an
immutable state snapshot plus load, reload, and cancel intents. It composes the
ordinary component hub/property-change surface and existing command types.

It does not own routes, caches, pages, product factories, transport clients, or
child viewmodels. It does not start automatically during component construction
or stop during destruction; terminal `Dispose` controls its lifetime.

## 2. State

```
AsyncResourceStatus = Idle | Loading | Ready | Error

AsyncResourceState<T>:
    Status : AsyncResourceStatus
    Value  : T?          // present only as allowed below
    Error  : HostError?  // present only for Error
```

The status discriminates the legal shape:

| Status    | Value                                       | Error   |
| --------- | ------------------------------------------- | ------- |
| `Idle`    | absent                                      | absent  |
| `Loading` | absent, or the retained last accepted value | absent  |
| `Ready`   | present                                     | absent  |
| `Error`   | absent, or the retained last accepted value | present |

State snapshots are immutable. `State` (`state` outside C#) is the canonical
binding property. Every effective visible transition publishes exactly one
ordinary component property-change pair for that property. There is no second
resource event or mutable status/value/error channel.

## 3. Construction and loader mapping

Construction requires a component name, hub, dispatcher, and loader. Rust
`AsyncResourceVm::new(name, loader)` and `with_options` supply a new
`MessageHub` and the `NullDispatcher` by default; `with_services` takes them
explicitly. Retention defaults to `DiscardPrevious`; cleanup is absent by
default.

| Flavor     | Loader shape                                            |
| ---------- | ------------------------------------------------------- |
| C#         | `Func<CancellationToken, Task<T>>`                      |
| Python     | `Callable[[], Awaitable[T]]`; cancel the asyncio task   |
| TypeScript | `(signal: AbortSignal) => Promise<T>`                   |
| Swift      | `() async throws -> T`; cancel the structured task      |
| Rust       | `Fn(CancellationToken) -> VmxResult<T>` on a VMx thread |

Per-flavor public names follow ADR-0006. The host error is `Exception`,
`BaseException`, `unknown`, `Error`, or `VmxError`, respectively.

## 4. Intents and commands

```
Load / LoadAsync       // admitted only from Idle
Reload / ReloadAsync   // admitted from Ready, Error, or Loading
Cancel                 // effective only while Loading

LoadCommand    : AsyncRelayCommand
ReloadCommand  : AsyncRelayCommand
CancelCommand  : RelayCommand
```

The command predicates mirror intent eligibility. The existing per-command
in-flight guard still applies, so the same async command instance cannot
double-run. `Reload` called directly, or the reload command invoked while the
load command is active, MAY supersede a current load.

Every visible state transition invalidates all three command predicates through
their existing notification surfaces. Async commands pass their idiomatic
cancellation channel into the same operation core as direct calls. `Cancel`
also cancels the command-backed operation; no resource-specific cancellation
protocol is public.

Calls rejected by these predicates and all calls after disposal are silent
no-ops.

## 5. Transitions

| From      | Intent/current completion | To                                   |
| --------- | ------------------------- | ------------------------------------ |
| `Idle`    | Load                      | `Loading`                            |
| `Ready`   | Reload                    | `Loading(previous?)`                 |
| `Error`   | Reload                    | `Loading(previous?)`                 |
| `Loading` | Reload                    | `Loading(previous?)`, new operation  |
| `Loading` | current success           | `Ready(newValue)`                    |
| `Loading` | current failure           | `Error(previous?, error)`            |
| `Loading` | current cancellation      | saved stable state, or `Idle`        |
| any       | stale completion          | unchanged                            |
| any       | Dispose                   | externally unchanged, terminal/inert |

`previous?` is present only under `RetainPrevious`. Current cancellation
covers explicit cancellation, cancellation linked from the async command, and a
current loader that ends with its flavor's native cancellation signal (§7). A
visible `Loading` to
`Loading` replacement that has the same exposed snapshot MAY remain silent; the
internal operation identity still changes and later completion admission uses
the new identity.

## 6. Latest-start-wins

Each admitted start:

1. advances a monotonic operation identity;
1. cancels the previous operation;
1. captures the stable state restored by cancellation; and
1. installs the visible `Loading` snapshot.

Only the current identity may install success, failure, or cancellation state.
An older loader that ignores cancellation MAY return, but its result cannot
mutate state, invalidate commands, publish notifications, or become current.
Identity equality, not numeric ordering, decides currency; flavors use their
normal large-integer or wrapping increment idiom.

## 7. Failure, retry, and cancellation

A current loader failure installs `Error` and the public awaitable intent
completes normally. Fire-and-forget command execution follows the same path:
expected loader failure is represented once by resource state and MUST NOT also
appear on `AsyncRelayCommand.Errors`.

`Reload` from `Error` is retry. Current success installs `Ready` and clears the
error. A retry failure replaces the stored error.

Explicit cancellation and cancellation linked from the async command restore
the operation's saved stable state. An initial cancelled load returns to `Idle`.
A retained reload returns to the prior `Ready` or value-bearing `Error`. A
discard reload that started from a value-less `Error` returns to that `Error`
(ADR-0228). Cancellation never creates `Error` or reaches a command error
channel.

A current loader that ends with its flavor's native cancellation signal is
cancelled in the same way, even when the VM did not request the cancellation
(ADR-0199). It restores the operation's saved stable state, and the awaitable
intent completes normally. A typical source is a shared request that another
owner cancels. The native signals are:

| Flavor     | Native cancellation signal                   |
| ---------- | -------------------------------------------- |
| C#         | `OperationCanceledException`, from any token |
| Python     | `asyncio.CancelledError`                     |
| TypeScript | a rejection whose `name` is `"AbortError"`   |
| Swift      | `CancellationError`                          |
| Rust       | `Err(VmxError::Cancelled)`                   |

A timeout that the flavor reports with a timeout error is a failure and
installs `Error`. These errors are Python `TimeoutError`, TypeScript
`TimeoutError`, Swift `URLError.timedOut`, and a C# `OperationCanceledException`
whose `InnerException` is a `TimeoutException`. A timeout that the loader
implements by cancelling a token ends with the native signal. It is a
cancellation and restores the saved stable state. Any other error installs
`Error`. A superseded loader that ends with the signal is a stale completion
(§6).

## 8. Previous-value policy

`DiscardPrevious` is conservative and is the default. At reload start, the VM
relinquishes an accepted value immediately and installs value-less `Loading`.
The cancellation baseline is `Idle` after a relinquished value, and otherwise
the saved stable state, so a cancelled reload from a value-less `Error` returns
to that `Error` (ADR-0228). A later failure is value-less.

`RetainPrevious` keeps the last accepted value in `Loading` and `Error`, and
keeps its stable state as the cancellation baseline until a newer value is
accepted. Retention is presentation policy only. The loader receives no cached
value, validator, ETag, or retry count.

## 9. Optional value ownership

An optional `CleanupValue(T)` callback defines acquisition-based ownership.
Each successful loader return transfers one ownership unit, even if two returns
are equal or reference-identical. A caller using cleanup MUST NOT transfer the
same independently owned resource twice.

Cleanup runs exactly once when an ownership unit is:

- discarded at reload start;
- replaced by a newer current success;
- produced by a stale or post-dispose success; or
- retained when the VM is disposed.

Without the callback VMx does not inspect or dispose `T`. Cleanup failure is
best-effort and isolated like component-owned cleanup. Stale-result cleanup is
allowed after currency is lost solely to prevent a resource leak; it cannot
publish state or invoke another resource callback.

## 10. Disposal and scheduling

`Dispose` is idempotent. Its first call invalidates the operation identity,
cancels active work and both async commands, relinquishes an accepted value,
and performs normal component teardown. Later completion may only clean its own
newly returned ownership unit; it cannot publish or call an application hook.
All commands and direct intents are inert afterward.

Transitions execute on the host async continuation context. This primitive does
not add a scheduler policy or automatically dispatch loader work. UI adapters
retain their normal host-thread responsibilities.

Python captures the asyncio operation loop for native task cancellation, cancellation
future completion, and late callback registration (ADR-0133). Calls already on
that loop signal directly; foreign calls enqueue to it while resource generation
invalidation remains synchronous. Stopped open loops require restart to make
progress; hosts cancel and drain before closing a loop. This implementation
mapping adds no general VM/observer thread-safety or UI scheduling guarantee.

## 11. Conformance

Chapter 12 §32 holds the `ARES` IDs. The table maps each ID to the rules of
this chapter, and chapter 12 states the behavior of each ID.

| IDs                                | Rules                                              |
| ---------------------------------- | -------------------------------------------------- |
| `ARES-001`                         | §2 state, §3 construction, §4 intents and commands |
| `ARES-002`                         | §5 transitions                                     |
| `ARES-003`..`ARES-005`, `ARES-012` | §7 failure, retry, and cancellation                |
| `ARES-006`, `ARES-007`, `ARES-013` | §8 previous-value policy                           |
| `ARES-008`, `ARES-009`             | §6 latest-start-wins                               |
| `ARES-010`                         | §9 optional value ownership                        |
| `ARES-011`                         | §10 disposal and scheduling                        |
