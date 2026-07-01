# ADR 0068 — Disposed relay commands are inert

**Status:** Accepted (2026-07-01)
**Spec version:** introduced in 3.1.0

## 1. Context

`RelayCommand` and its parameterized variant already exposed idempotent disposal
to tear down trigger subscriptions. Before this ADR, disposal did not affect
`CanExecute` or `Execute`: a command with no predicate still reported executable
and could still invoke its task after disposal.

That made disposal a partial resource cleanup operation rather than an observable
command lifecycle boundary. Consumers that dispose commands during VM teardown
reasonably expect later UI or host calls to be harmless.

## 2. Decision

Disposed relay commands are inert:

- `CanExecute` returns `false`.
- `Execute` returns immediately and does not invoke the configured task.
- disposal remains idempotent.

The rule applies to both non-parameterized and parameterized relay commands in
every supported flavor. A flavor may notify `CanExecuteChanged` during disposal
before completing or tearing down its reactive stream, but the conformance
contract is the post-disposal state and no-op execution behavior.

## 3. Consequences

Consumers can dispose commands during view-model teardown without guarding every
late command invocation. Bound controls also have a consistent disabled state
after disposal.

This is a behavior tightening, not a new command type. Builders, predicates,
task exception propagation before disposal, trigger semantics, and async command
cancellation remain unchanged.

## 4. Rejected alternatives

Leaving `CanExecute` unchanged after disposal was rejected because it makes a
disposed command appear usable.

Throwing from `Execute` after disposal was rejected because VMx command teardown
is intentionally idempotent and late host calls should be harmless.
