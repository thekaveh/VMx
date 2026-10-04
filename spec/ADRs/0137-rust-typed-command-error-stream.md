# ADR 0137 — Deliver Rust command failures as the original `VmxError`

- **Status:** Accepted
- **Date:** 2026-10-04
- **Spec version:** 3.25.0 (Rust mapping; no normative change)
- **Clarifies:** [ADR-0049](0049-v3-command-semantics.md),
  [ADR-0103](0103-rust-owned-hot-stream-facade.md)

## 1. Context

Chapter 4 routes the fault of a fire-and-forget `Execute` to the command's
`errors` channel (§10.4), and a fire-and-forget `ConfirmationDecoratorCommand`
reports a failing confirmation or a failing inner command there too (§8.3.1).
C#, Python, TypeScript, and Swift deliver the thrown value itself.

Rust's `AsyncRelayCommand::errors()` and
`ConfirmationDecoratorCommand::errors()` return a `MessageHub`. Each failure
arrived as `Message::Custom { name: "error" }`, which has no payload, so a
subscriber could count failures but could not see what failed (#330).

## 2. Decision

- Rust adds `CommandErrorStream`, a hot typed stream built on the VMx-owned
  `ValueStream` (ADR-0103). It does not replay earlier failures, isolates
  subscriber panics, and completes when its command is disposed.
- `AsyncRelayCommand::error_stream()` delivers each non-cancellation failure of
  a fire-and-forget `execute` once, as the original `VmxError`. An awaited
  `execute_async` returns the failure and publishes nothing. Cancellation and a
  failure that completes after disposal publish nothing.
- `ConfirmationDecoratorCommand::error_stream()` delivers a panic from
  fire-and-forget `confirm` or from the confirmed inner `execute` as
  `VmxError::Other("command panicked: <message>")`, or
  `VmxError::Other("command panicked")` when the payload is not a string. A
  panic payload is `Box<dyn Any + Send>`: it is neither a `VmxError` nor
  clonable, so the stream carries only its message. The payload itself stays
  available through `execute_async`, whose `join` returns it unchanged.
- Both `errors()` hubs keep announcing the marker, so existing subscribers keep
  working, and are deprecated in favour of `error_stream()`.

## 3. Consequences

- A Rust subscriber can inspect the cause of a fire-and-forget failure, as in
  the other flavors.
- Failure ordering, post-disposal suppression, and cancellation handling are
  unchanged. Admission is still released after the error subscribers return.
- Callers of `errors()` see a deprecation warning. The marker hub can be removed
  in a later breaking Rust release.
- This is a Rust-only, additive change. Other flavors already deliver the thrown
  value and need no change.

## 4. Rejected alternatives

Changing the return type of `errors()` would break every caller.

Adding a payload field to `Message::Custom` would change a shared message type
for one channel, and it would need a type-erased payload.

Forwarding the panic payload itself would require a clonable payload that Rust
does not provide.
