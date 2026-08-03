# ADR 0130 — Rust paired dispatch and background lifecycle

- **Status:** Accepted
- **Date:** 2026-08-03
- **Spec version:** 3.23.0

## 1. Context

The threading contract has required separate foreground and background
scheduling plus builder-controlled background lifecycle work since THR-002 was
introduced. Rust exposed only one dispatch method, and its THR-002 marker tested
deferred publication rather than background construction. That was an
implementation gap, not an authorized flavor divergence.

## 2. Decision

Rust's idiomatic `Dispatcher` keeps `dispatch` as its foreground channel and
adds `dispatch_background`. The new method defaults to `dispatch`, preserving
source compatibility for custom synchronous dispatchers. `NullDispatcher` and
`ImmediateDispatcher` therefore run both channels inline.

`DefaultDispatcher` owns dedicated serial `vmx-foreground` and `vmx-background`
workers. Worker creation happens when the dispatcher is created, before any VM
transition can be admitted. `ManualDispatcher` exposes independently drainable
foreground and background queues for deterministic tests.

`ComponentVmBuilder::background` and `ReadonlyComponentVmBuilder::background`
enable asynchronous construct/destruct hooks; admission remains synchronous,
work runs on the background channel, and terminal or rollback state plus
publication is committed on the foreground channel. The stable reconstruct
command delegates the same atomic two-phase path as direct `reconstruct()`.

`ComponentVm::background_errors()` (also delegated by the read-only wrapper) is
a hot typed stream for failures that occur after the fire-and-forget caller has
returned. Rollback publishes first, then the original `VmxError` is emitted.
An unconstrained Rust panic becomes `VmxError::Other` with a stable diagnostic.
The stream completes when the component is disposed.

## 3. Consequences

Rust now implements genuine THR-002 behavior and the existing lifecycle
atomicity, no-resurrection, concurrent-admission, and rollback guarantees. The
change includes the corresponding read-only builder surface and advances the
unpublished Rust source line to 0.29.0.
The language-neutral contract and conformance catalog are unchanged, so the
spec version and other flavor versions remain unchanged.

## 4. Rejected alternatives

- **Reinterpret THR-002 as deferred publication:** this would contradict the
  explicit background-hook and foreground-terminal requirements.
- **Require every custom dispatcher to add a method immediately:** a default
  foreground fallback provides the same synchronous behavior existing hosts
  already had while allowing paired implementations to opt in.
- **Use a third-party reactive scheduler:** ADR-0103 keeps Rust's runtime
  dependency-neutral; closure dispatch is the established Rust idiom.
