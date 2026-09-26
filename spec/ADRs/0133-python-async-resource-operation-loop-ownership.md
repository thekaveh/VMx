# ADR 0133 — Preserve Python async resource operation-loop ownership

- **Status:** Accepted
- **Date:** 2026-09-26
- **Spec version:** 3.23.0

## 1. Context

Python `AsyncRelayCommand.execute()` supports callers without a running asyncio
loop by submitting work to the existing shared background loop. A resource's
loader task and cancellation future consequently belong to that loop. Direct
caller-thread cancellation, disposal, and callback registration on a completed
task could raise asyncio debug errors or strand the resource waiter. Linked
command cancellation also incorrectly treated a stopped loop as permission to
mutate its task directly.

Deferred registration exposes a second problem: stale direct completion and a
late callback can both clean the same return. Separately, checking generation
currency before an unlocked ownership assignment allows disposal to win between
those steps and leak a successfully returned value.

## 2. Decision

Capture the operation loop with its task and cancellation future. Register late
completion observation, complete the cancellation future, and cancel the loader
on that loop. Resource calls already executing on the operation loop act
immediately, preserving cancellation from a Loading observer before the loader
body runs. Foreign callers enqueue with `call_soon_threadsafe`, including when
the owner is stopped but open. Linked command cancellation remains deferred on
its recorded loop, including same-loop calls.

Registration and cancellation signalling are idempotent per operation. One
result claim, made before application cleanup, covers accepted success, stale
direct success, and deferred late completion. Accepted ownership then resides
only in stable resource state. Late failures are retrieved without publication.

A short resource metadata gate serializes generation admission, invalidation,
completion currency and result claims, authoritative state assignment, and
accepted-value relinquishment. Cleanup, observers, command methods, awaits, and
custom asyncio task factories execute outside that gate. Admission is checked
again after cleanup and task creation. Old linked commands are cancelled before
rollback observers can start a newer intent.

Each individual notification is admitted under the metadata gate only while its
committed generation and state remain current. The gate is released before
calling observers. An already-admitted ordinary notification may finish after
concurrent invalidation; later notifications recheck admission after user hooks.
This preserves the component's ordinary notification boundary without adding an
observer scheduler or promising arbitrary concurrent observer ordering.

## 3. Loop shutdown and errors

An open stopped owner retains queued work until it restarts. A scheduling
`RuntimeError` is suppressed only when the loop is confirmed closed; unrelated
scheduling failures propagate. The catch encloses enqueue only, never the
application callback.

After confirmed closure, a terminal loader result can still be claimed and
cleaned once on the caller, without native mutation or callback registration.
Pending work cannot be cancelled or drained on a dead loop. Closing a loop may
also discard callbacks whose enqueue succeeded. Hosts must cancel and drain
before closing their loops; no bounded waiter completion or cleanup progress is
promised after premature closure. Independent disposal and accepted-value
cleanup still run, preserving the first unrelated teardown error.

## 4. Consequences and scope

This maps the existing resource cancellation and ownership contract onto Python
asyncio. It adds no public API, thread, loop, dependency, UI dispatch rule, or
general VM/observer thread-safety guarantee. Loader-originated self-cancellation
remains separate issue #334. Spec/minimum-spec version 3.23.0, fixtures, and the
403-library/408-total catalog remain unchanged. Python source 3.23.3 is unreleased;
the release manifest remains 3.23.1.

Source audits of C#, TypeScript, Swift, and Rust found no equivalent asyncio
ownership bridge. Their native signalling mechanisms differ; those conclusions
are source audits, not newly executed runtime verification. Separate C# CTS
cancel/dispose and Swift task-install/cancel race concerns remain unverified and
outside this Python repair.

## 5. Rejected alternatives

- Enqueue only task cancellation: misses future completion, terminal callback
  registration, duplicate cleanup, and atomic completion ownership.
- Queue all resource intents: delays synchronous invalidation and establishes a
  new scheduler policy.
- Hold a lock across callbacks: risks reentrant deadlocks, including custom
  asyncio task factories waiting on another thread.
- Treat stopped or closed loops as caller-owned: stopping never transfers native
  asyncio ownership.
