# ADR 0199 — A loader's own cancellation restores the saved stable state

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 23 §5, §7 and §11; adds `ARES-012`)
- **Extends:** [ADR-0100](0100-async-resource-vm.md). Closes the case that
  [ADR-0133](0133-python-async-resource-operation-loop-ownership.md) left to
  #334. Related: #1353, #671.

## 1. Context

A loader can end the current operation with cancellation that the VM did not
request. A typical case is a loader that awaits a shared request, and another
owner cancels that request. Chapter 23 §7 named only explicit and
command-linked cancellation, and said that cancellation never creates `Error`.
It did not say whether a loader's own cancellation counts as cancellation or
as a failure. No ARES ID covered the case (#1353).

The flavors split at `d05d08d7`:

- Python: an `asyncio.CancelledError` from the loader task calls `_rollback`,
  which restores the saved stable state (#334, PR #436, PR #451).
- Swift: a thrown `CancellationError` calls `completeCancellation`, which
  restores the saved stable state.
- C#: an `OperationCanceledException` is cancellation only when the
  operation's own token is cancelled. Otherwise `CompleteFailure` installs
  `Error`.
- TypeScript: only an abort of the operation's own signal is cancellation. Any
  other rejection, an `AbortError` included, installs `Error`.
- Rust: `complete_operation` installs `Error` for every `Err`,
  `VmxError::Cancelled` included.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: a current loader that ends
with its flavor's native cancellation signal restores the operation's saved
stable state, as `Cancel` does. The result is the same as explicit
cancellation:

| Operation                        | Restored state    |
| -------------------------------- | ----------------- |
| Initial load                     | `Idle`            |
| Discard-mode reload from `Ready` | `Idle`            |
| Retained reload from `Ready`     | `Ready(oldValue)` |
| Retained reload from `Error`     | that `Error`      |

The native cancellation signal of each flavor is:

| Flavor     | Signal                                          |
| ---------- | ----------------------------------------------- |
| C#         | an `OperationCanceledException`, from any token |
| Python     | `asyncio.CancelledError`                        |
| TypeScript | a rejection whose `name` is `"AbortError"`      |
| Swift      | `CancellationError`                             |
| Rust       | `Err(VmxError::Cancelled)`                      |

The rules:

1. The restore follows chapter 23 §7. It creates no `Error`, emits nothing on
   a command error channel, and does not clean the restored value. The
   awaitable intent completes normally.
1. A timeout that the flavor reports with a timeout error is a failure and
   installs `Error`. These errors are Python `TimeoutError`, TypeScript
   `TimeoutError`, Swift `URLError.timedOut`, and a C#
   `OperationCanceledException` whose `InnerException` is a
   `TimeoutException`, as `HttpClient` throws on a timeout. A timeout that the
   loader implements by cancelling a token, such as C#
   `CancellationTokenSource.CancelAfter`, ends with the native signal. It is a
   cancellation and restores the saved stable state. Rust has no timeout
   signal, so a Rust loader that reports a timeout returns an error other than
   `VmxError::Cancelled`.
1. A superseded loader that ends with the signal is a stale completion
   (chapter 23 §6). The newer operation stays current, and the state does not
   change.
1. Any other error, including a non-native cancellation type such as Swift
   `URLError.cancelled`, stays a failure and installs `Error` (`ARES-003`).

Reasons:

- Chapter 23 §7 says that cancellation never creates `Error`. The rule keeps
  that sentence true for every source of cancellation.
- The loader that ends with cancellation produced no value and no failure to
  present. Showing a cancellation as an error would ask the user to retry work
  that nobody failed.
- It is the platform idiom. Python makes `CancelledError` a `BaseException`,
  not an `Exception`. Swift structured concurrency treats `CancellationError`
  as a non-error outcome. TanStack Query, a common TypeScript resource cache,
  reverts a cancelled query to its previous state.
- Installing `Error` was rejected. It needs the cancellation source, which
  the loader cannot always know, and it would contradict chapter 23 §7.

The restored baseline of a cancelled discard-mode retry from `Error` stays
under #671. Whatever #671 decides applies to this rule too, because both use
the operation's saved stable state.

## 3. Flavor impact

- **C#.** `StartAsync` treats any `OperationCanceledException` from a current
  loader as cancellation and calls `HandleCancellation`, unless its
  `InnerException` is a `TimeoutException`.
- **TypeScript.** The failure branch of the operation checks for an
  `AbortError` rejection. It then restores the baseline, as the abort
  listener does, instead of installing `Error`.
- **Rust.** `complete_operation` routes `Err(VmxError::Cancelled)` to the
  cancellation path, which restores the baseline.
- **Python and Swift.** No behavior change. Each adds the `ARES-012` test.

## 4. Conformance

`ARES-012` covers a current loader that ends with its native cancellation
signal on an initial load, a discard-mode reload from `Ready` and a retained
reload from `Ready`. It also covers a superseded loader that cancels itself.
The catalog grows from 451 to 452 library IDs (457 in total). `ARES-005` and
`ARES-006` keep their meaning for explicit and command-linked cancellation.

## 5. Consequences

- C#, TypeScript and Rust change behavior. A loader that cancels itself no
  longer shows `Error`. An application that showed that error to the user now
  sees the prior stable state.
- `docs/content/primitives/state-reactive-helpers.md` states one rule in place
  of the per-flavor list.
- No public API changes.
