# ADR 0104 — Complete Rust async-command parity

**Status:** Accepted (2026-07-13)
**Spec version:** 3.20.0 (implementation parity correction; no new normative behavior)
**Related:** ADR-0006, ADR-0056, ADR-0076, ADR-0080, ADR-0081, ADR-0100

## 1. Context

The current command specification makes `AsyncRelayCommand` normative for all
full-parity flavors. Rust had the in-flight flag, cooperative token, cancel
operation, and a join handle, but its surface stopped short of the specified
contract: no immutable builder, additive triggers, throwing cancellation mode,
or fire-and-forget error channel. Dropping the join handle returned by
`execute_async` also discarded ordinary `VmxError` results from `execute()`.

Rust does not require an async runtime for VMx's existing implementation. The
crate already uses a worker thread and `JoinHandle<VmxResult<()>>` as its
idiomatic awaitable boundary. The missing semantics can be completed without
changing that execution model or adding a runtime dependency.

## 2. Decision

### 2.1 Keep the thread-based Rust awaitable

`execute_async()` continues to return `JoinHandle<VmxResult<()>>`. Admission is
atomic, only one body runs at a time, and an unwind guard clears execution state
and publishes the final command-state notification even when the body panics.

### 2.2 Add the immutable async-command builder

`AsyncRelayCommand::builder()` returns `AsyncRelayCommandBuilder`. Consuming
setters configure `task`, `predicate`, additive `trigger` sources, and
`throw_on_cancel`; `build()` owns the trigger subscriptions for the command's
lifetime and disposal clears them.

### 2.3 Distinguish cooperative cancellation

Rust adds `VmxError::Cancelled`. When `cancel()` requests the active VMx token,
the default awaitable result is `Ok(())`; throwing mode returns
`Err(VmxError::Cancelled)`. A non-cancellation `VmxError` remains a fault and is
never rewritten merely because it came from an async body.

Rust currently has no caller-supplied cancellation argument on
`execute_async()`. A future external-cancellation API requires a separate ADR
that preserves the specification's distinction between command-requested and
externally originated cancellation.

### 2.4 Route fire-and-forget faults

`execute_async()` returns ordinary task faults to its joiner. `execute()` has no
joiner, so non-cancellation `VmxError` results publish one `"error"` event on
`errors()`. Cancellation never reaches that channel, and disposal closes the
command's trigger and error delivery boundaries.

## 3. Consequences

- Rust now implements the conceptual async-command surface already required by
  chapter 04 and `CMD-012`, `CMD-016`, `CMD-018`, and `CMD-019`.
- The additive public surface and cancellation error variant advance the Rust
  flavor from 0.20.0 to 0.21.0 while `MIN_SPEC_VERSION` remains 3.20.0.
- No conformance ID, fixture, spec version, or non-Rust flavor API changes.
- The Rust package still has no async-runtime dependency.

## 4. Rejected alternatives

### 4.1 Add Tokio solely for AsyncRelayCommand

Rejected. It would impose a runtime choice on a UI-framework-neutral core when
the existing worker/join model can satisfy the contract.

### 4.2 Treat every VmxError after cancel as cancellation

Rejected. That would hide real faults racing with cancellation. Only the
explicit cooperative cancellation result receives cancellation semantics.

### 4.3 Keep dropping fire-and-forget results

Rejected. It violates the normative error-channel contract and makes command
failures unobservable to hosts.
