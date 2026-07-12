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

Construction requires a component name, hub, dispatcher, and loader. Retention
defaults to `DiscardPrevious`; cleanup is absent by default.

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

`previous?` is present only under `RetainPrevious`. A visible `Loading` to
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
A retained reload returns to the prior `Ready` or value-bearing `Error`.
Cancellation never creates `Error` or reaches a command error channel.

## 8. Previous-value policy

`DiscardPrevious` is conservative and is the default. At reload start, the VM
relinquishes an accepted value immediately, uses `Idle` as the cancellation
baseline, and installs value-less `Loading`; a later failure is value-less.

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

## 11. Conformance

- `ARES-001` — initial state and command eligibility.
- `ARES-002` — successful load and ordinary state notification.
- `ARES-003` — loader failure becomes error state without command error duplication.
- `ARES-004` — retry replaces error with ready.
- `ARES-005` — initial cancellation restores idle without error.
- `ARES-006` — retained reload exposes and restores the previous value.
- `ARES-007` — discard policy releases the previous value at reload start.
- `ARES-008` — overlapping starts are latest-start-wins.
- `ARES-009` — stale success is cleaned once without state notification.
- `ARES-010` — replacement and disposal clean each ownership unit once.
- `ARES-011` — disposal cancels work and makes late completion/intents inert.
