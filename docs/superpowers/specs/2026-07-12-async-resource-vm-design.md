# AsyncResourceVM Design

**Issue:** #139\
**Status:** Approved for implementation by the continuous roadmap directive\
**Target line:** spec/C#/Python/TypeScript/Swift 3.20.0; Rust 0.20.0

## 1. Problem and scope

Route-level views repeatedly implement the same asynchronous presentation
lifecycle: start a load, show progress, publish a value or an error, retry,
cancel on navigation, reject stale completions, and clean up an acquired value.
Those policies belong in a reusable viewmodel rather than in React effects or
transport-specific controllers.

VMx will add `AsyncResourceVM<T>`, a component viewmodel for exactly one
asynchronously acquired value. It composes the existing component notification,
command, cancellation, and owned-cleanup contracts. It does not add routing,
caching, pagination, transport policy, product factories, or child-viewmodel
construction.

## 2. Portable public surface

Every flavor exposes the idiomatic equivalent of:

```text
AsyncResourceStatus = Idle | Loading | Ready | Error
AsyncResourceRetention = DiscardPrevious | RetainPrevious

AsyncResourceState<T> {
    status: AsyncResourceStatus
    value: optional T
    error: optional host error
}

AsyncResourceVM<T>(
    name,
    loader: idiomatic cancellable async function -> T,
    hub,
    dispatcher,
    retention = DiscardPrevious,
    cleanup_value = absent
)

state
load / reload / cancel
load_command / reload_command / cancel_command
dispose
```

The four states are discriminated by `status` and enforce these invariants:

| Status  | Value                                       | Error   |
| ------- | ------------------------------------------- | ------- |
| Idle    | absent                                      | absent  |
| Loading | absent, or the retained last accepted value | absent  |
| Ready   | present                                     | absent  |
| Error   | absent, or the retained last accepted value | present |

The canonical binding property is `state`. Each effective visible transition
publishes one ordinary VMx property change for that property, using the normal
flavor name (`State` in C#, `state` elsewhere). State snapshots are immutable;
there is no separately mutable status/value/error surface.

## 3. Intents and command eligibility

`load` starts only from `Idle`. `reload` starts from `Ready`, `Error`, or
`Loading`; starting it while `Loading` supersedes the active operation. `cancel`
is effective only while `Loading`. Calls that are ineligible or occur after
disposal are inert.

The command predicates mirror those rules:

- `loadCommand`: enabled only in `Idle`;
- `reloadCommand`: enabled in `Ready`, `Error`, and `Loading`, subject to the
  existing per-command in-flight guard; and
- `cancelCommand`: enabled only in `Loading`.

Every visible state transition raises command invalidation through the existing
command surfaces. The async commands delegate to the same methods as direct
callers. Their existing cancellation token, signal, task cancellation, or VMx
Rust token is linked to the resource operation; no second cancellation type is
introduced.

## 4. Operation identity and stale completion

Each admitted start increments a monotonic operation identity, cancels the
previous operation, records the stable state to restore on cancellation, and
publishes `Loading`. Only the current identity may publish success, failure, or
cancellation. A prior operation that ignores cancellation may still return, but
it cannot change state, notify subscribers, or alter command eligibility.

The identity comparison, state replacement, cancellation ownership, and
disposal check are serialized in each flavor with its normal synchronization
primitive. Numeric wrap is handled by the host's wrapping/large-integer idiom;
identity equality, not ordering, decides currency.

## 5. Success, failure, retry, and cancellation

Current success publishes `Ready(value)` and makes it the new stable state.
Current loader failure is captured as `Error(error)` and completes the public
load/reload method normally. The same rule applies to fire-and-forget command
execution: expected loader failure is represented by resource state and is not
also emitted on `AsyncRelayCommand.errors`.

`reload` from `Error` is the retry path. A successful retry replaces the error
with `Ready`; a failed retry replaces it with the new error.

Explicit or linked cancellation restores the stable pre-operation state. An
initial cancelled load therefore returns to `Idle`. A cancelled retained reload
returns to the prior `Ready` or value-bearing `Error`. Cancellation is not an
error state and never reaches a command error channel.

## 6. Previous-value policy

`DiscardPrevious` is the default. Starting a reload relinquishes any accepted
value immediately, sets the cancellation baseline to `Idle`, and publishes a
value-less `Loading` state. A later failure is value-less.

`RetainPrevious` preserves the last accepted value in `Loading` and `Error`.
It remains the cancellation baseline until a newer value succeeds. Retention is
presentation policy only: the loader receives no previous value, and VMx does
not perform caching or conditional requests.

## 7. Value ownership and cleanup

The optional cleanup callback defines acquisition-based ownership. Each loader
success transfers one ownership unit to `AsyncResourceVM`, even if the returned
object compares equal or is reference-identical to another result. Consumers
using cleanup must not transfer the same independently owned resource twice.

When configured, cleanup runs exactly once for each ownership unit when it is:

- discarded at reload start;
- replaced by a newer accepted success;
- returned by a stale or post-dispose completion; or
- still retained when the VM is disposed.

Without the callback VMx never assumes that `T` is disposable. Cleanup failures
are isolated on the same best-effort basis as component-owned teardown, so one
failure cannot prevent cancellation, state finalization, or remaining cleanup.
Stale-result cleanup is the sole permitted callback after an operation loses
currency; it cannot publish VM state.

## 8. Lifecycle and scheduling

The resource state machine is independent of component construction and
destruction. It may load while the component is destructed or constructed;
`dispose` alone is terminal. Disposal invalidates the operation identity,
cancels in-flight work and both async commands, releases the accepted value,
then delegates to ordinary component teardown. It is idempotent.

State transitions execute on the host async continuation context. This ticket
does not add a scheduler policy or silently dispatch loader work. Consumers
whose UI framework requires a particular thread use their normal VMx dispatcher
or adapter boundary.

## 9. Conformance and release

Add `ARES-001..011`:

1. initial state and command eligibility;
1. successful load and ordinary state notification;
1. loader failure becomes error state without command error duplication;
1. retry replaces error with ready;
1. initial cancellation restores idle without error;
1. retained reload exposes/restores the previous value;
1. discard policy releases the previous value at reload start;
1. overlapping starts are latest-start-wins;
1. stale success is cleaned once without state notification;
1. replacement and disposal clean each accepted ownership unit once; and
1. disposal cancels work and makes late completion and every intent inert.

The catalog moves from 380 to 391 library IDs and from 385 to 396 total IDs
including the five `THEME` scenarios. This additive normative/API release is
3.20.0 for the spec and stable flavors, and 0.20.0 for Rust.

## 10. Rejected alternatives

- **React hook or TypeScript-only helper.** Rejected because the state and race
  policy are UI-neutral and recur across VMx consumers and flavors.
- **Boolean `isLoading` plus nullable fields.** Rejected because invalid
  combinations remain representable and consumers cannot exhaustively switch.
- **Throw loader errors.** Rejected because screens need an observable retryable
  error state and fire-and-forget commands would require a second error path.
- **First-completion-wins.** Rejected because navigation/retry intent must make
  the most recently started request authoritative.
- **Always retain previous values.** Rejected because stale data is a product
  choice; discard is the explicit conservative default.
- **Infer disposal from `T`.** Rejected because generic values do not share a
  portable disposal protocol and ownership transfer must be opt-in.
- **Auto-load on construct or cancel on destruct.** Rejected because lifecycle
  attachment and product routing policy are outside this primitive.
