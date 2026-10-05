# ADR 0140 — Start Rust command workers only for admitted work and wake resource waits on signals

- **Status:** Accepted
- **Date:** 2026-10-05
- **Spec version:** 3.25.0 (Rust mapping; no normative change)
- **Clarifies:** [ADR-0103](0103-rust-owned-hot-stream-facade.md),
  [ADR-0104](0104-rust-async-command-parity.md)

## 1. Context

ADR-0104 keeps `JoinHandle<VmxResult<()>>` as the Rust awaitable for
`AsyncRelayCommand::execute_async()`. Every call path returned a spawned
thread, so a rejected `execute()` (no action, an execution already running, a
false predicate, or a disposed command) also started an OS thread that did
nothing. 100 rejected calls started 100 threads.

An `AsyncResourceVm` load runs on a waiting worker (the `load_async` thread or
the command worker) and a loader worker. The waiting worker polled the loader
channel every millisecond while it checked two cancellation tokens, so a
100 ms load woke it about 90 times (#356).

## 2. Decision

- `AsyncRelayCommand::execute()` starts a worker only for an admitted
  execution. A rejected call returns without a thread. Admission,
  `can_execute_changed` ordering, error routing, and cancellation of admitted
  work are unchanged.
- `execute_async()` keeps returning `JoinHandle<VmxResult<()>>`. A rejected call
  still returns a handle that completes with `Ok(())` at once, on a
  short-lived thread, because a `JoinHandle` can only come from a spawned
  thread. Returning an already-completed handle type would change the public
  signature; an additive completion API belongs with the host-executor work
  (#401).
- Library code that waits on a command, such as `TokenPagedComposition`'s
  `refresh()` and `load_next()`, starts no thread for a rejected call.
- An `AsyncResourceVm` load keeps its two workers. The loader needs its own
  worker so the waiting worker can return as soon as the load is cancelled,
  superseded, or disposed, even while the loader ignores its token. The
  waiting worker now blocks until the loader reports or a token it watches is
  cancelled, instead of polling.
- `CancellationToken` gains a crate-private cancellation listener, so
  `cancel()` on the resource or its commands, a superseding load, and disposal
  each wake the waiting worker. The token's public API is unchanged.
- Late results keep their existing ownership rules: a stale or post-disposal
  value is cleaned exactly once and publishes nothing.

## 3. Consequences

- 100 rejected `execute()` calls start no thread (100 before), whether the
  command has no action, is busy, has a false predicate, or is disposed.
- A 100 ms load wakes its waiting worker once (about 90 times before), and a
  cancellation 100 ms into an uncooperative load wakes it once (about 90 times
  before). Each load still uses two workers.
- No public type or signature changes, and no dependency is added. The crate
  keeps its owned runtime without Tokio (ADR-0103).

## 4. Rejected alternatives

Returning an already-completed handle from `execute_async()` would break
every caller that names `JoinHandle`.

Running the loader on the waiting worker would save a thread, but an
uncooperative loader would then hold the awaited load until it returned,
instead of completing it on cancellation.

A longer poll interval would still wake idle workers and would delay
cancellation by up to that interval.

An async runtime would contradict ADR-0103 and move blocking loaders onto an
event-loop thread.
