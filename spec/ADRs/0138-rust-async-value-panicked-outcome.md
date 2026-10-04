# ADR 0138 — Settle a Rust `AsyncValue` whose continuation panics

- **Status:** Accepted
- **Date:** 2026-10-04
- **Spec version:** 3.25.0 (Rust mapping; no normative change)
- **Clarifies:** [ADR-0103](0103-rust-owned-hot-stream-facade.md),
  [ADR-0137](0137-rust-typed-command-error-stream.md)

## 1. Context

Rust's executor-neutral `AsyncValue<T>` composes with `map` and `and_then`.
Both ran the callback under `catch_unwind` and discarded a panic, so the
returned handle stayed pending forever. `wait()` loops until a value exists
and `Future::Output` is `T`, so a consumer that awaited the handle hung even
though all related work had finished (#339).

`ConfirmationDecoratorCommand` builds on the same handle. A confirmation
produced by a panicking `map` left `execute_async().join()` blocked forever and
made fire-and-forget execution silently do nothing.

## 2. Decision

- A handle settles exactly once, either with a value through `resolve` or as
  panicked when the `map` or `and_then` callback that produces it panics. The
  first outcome wins; `resolve` on a panicked handle returns `false`.
- A panicked source settles every handle composed from it as panicked without
  running their callbacks, so the failure travels through nested
  compositions. `and_then` also settles as panicked when the handle its mapper
  returns settles as panicked.
- The new `AsyncValuePanic` records the failure. Its message is the panic's
  string payload, or `"AsyncValue continuation panicked"`. Clones share one
  record, so the original payload is handed out once, to the first observer
  that takes or re-raises it.
- `wait_result()` and `try_result()` return `Result<T, AsyncValuePanic>`.
  `wait()` and `.await` re-raise the panic, with the original payload for the
  first observer and the message as a `String` payload for later observers.
  `try_get()` returns `None` for a panicked handle.
- Settling still wakes every registered waker and runs every other
  continuation, and it releases continuation storage.
- `ConfirmationDecoratorCommand::execute_async` completes with the
  confirmation's panic, so `join()` returns `Err(payload)`. Fire-and-forget
  `execute` publishes it on `error_stream()` as
  `VmxError::Other("command panicked: <message>")`, as ADR-0137 does for other
  confirmation panics.
- Under `panic = "abort"` a panicking callback aborts the process. The panicked
  outcome describes unwinding panics only; it is not recovery from aborts or
  application deadlocks.

## 3. Consequences

- Awaiting or waiting on a handle whose producing callback panicked terminates
  instead of hanging. Code that waited forever now observes a panic or an
  `Err`.
- `wait()` and `Future::poll` can now panic. Before, they could only hang in
  that situation, so no successful program changes behavior. The change ships
  in the unreleased Rust 0.31.0 and is listed in its changelog.
- No OS thread is added, and the handle stays executor-neutral.
- Other flavors use native futures, promises, and tasks, which already settle
  a rejected continuation. They need no change.

## 4. Rejected alternatives

Changing `Future::Output` to `Result<T, AsyncValuePanic>` would break every
awaiting caller.

Keeping the handle pending and logging the panic would keep the hang that
#339 reports.

Forwarding the payload to every observer would need a clonable payload, which
Rust does not provide.
