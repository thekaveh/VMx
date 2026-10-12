# ADR 0145 — Awaited confirmation completes when an asynchronous inner command completes

- **Status:** Accepted
- **Date:** 2026-10-12
- **Spec version:** 3.29.0
- **Related:** [ADR-0049](0049-v3-command-semantics.md) (confirmation `errors`
  channel), [ADR-0056](0056-v3-async-command-cancellation.md) (async command
  cancellation and errors), [ADR-0134](0134-disposed-command-wrappers-are-inert.md)
  (inert disposed wrappers), [ADR-0137](0137-rust-typed-command-error-stream.md) (Rust
  command error streams)

## 1. Context

`ConfirmationDecoratorCommand.ExecuteAsync` awaited the confirmation and then
called the inner command's synchronous `Execute` in C#, Python, TypeScript, and
Rust. For an asynchronous inner command, the awaited call therefore resolved as
soon as the inner operation had started. Swift awaited an `AsyncCommand` inner,
so an awaited result meant different things across flavors (#355). Chapter 04
§8.3.1 said `ExecuteAsync` "can be awaited to sequence it inline" but named
`inner.Execute()`, and no conformance ID covered an asynchronous inner.

## 2. Options considered

1. **Await the inner operation.** When the inner command is asynchronous, the
   awaited call completes when the inner operation completes and its failure
   propagates to the awaiter. A synchronous inner keeps the existing path.
1. **Resolve once the inner operation has started.** Document today's majority
   behavior and change Swift to match. An awaited call would still not mean
   the admitted operation finished.

## 3. Decision

Option 1. Chapter 04 §8.3.2 defines it:

1. **Asynchronous inner.** An inner command is asynchronous when it offers the
   flavor's awaitable execution, or is another `ConfirmationDecoratorCommand`.
   Nested wrappers are therefore awaited end to end.
1. **Awaited path.** After a `true` confirmation the decorator invokes the
   inner exactly once: an asynchronous inner through its awaitable entry point,
   a synchronous inner through `Execute()`. It never calls both. The awaiter
   completes when that invocation completes, and an inner failure propagates to
   it, unchanged and not re-emitted on any `errors` channel.
1. **Fire-and-forget path.** `Execute()` starts an asynchronous inner through
   the inner's own `Execute()`. The inner reports its failures on its own error
   channel; the decorator starts no second task to watch it, and its `errors`
   carries only confirmation failures and synchronous-inner failures. Each
   failure reaches exactly one channel.
1. **No added admission or ownership.** The inner keeps its own busy, disabled,
   and cancellation rules, and the decorator never owns, cancels, or disposes
   it. Disposal during a pending confirmation still starts no inner work
   (ADR-0134).
1. **Rust.** The `Command` trait gains a provided method that exposes a
   command's awaitable entry point when it has one. `AsyncRelayCommand` and
   `ConfirmationDecoratorCommand` provide it, and the decorator uses it to
   detect an asynchronous inner. This is a proposed public addition; the other
   flavors add no public member.

## 4. Consequences

- `CMDD-014..017` cover completion timing and single invocation, failure
  routing on both paths, inner-owned admission and cancellation, nested
  wrappers, and disposal, in all five flavors.
- The misleading TypeScript comment claiming the void `execute()` returns a
  promise is corrected.
- **Compatibility.** Awaiting a confirmation over an asynchronous inner now
  waits for the inner operation, and its failure now reaches the awaiter
  instead of the inner's error channel. On the fire-and-forget path, an
  asynchronous inner's failure arrives on the inner's error channel, as it
  already did in C#, Python, TypeScript, and Rust; Swift, which awaited the
  inner there and reported its failure on the decorator's `errors`, changes to
  match. Synchronous inners are unchanged. This is a minor spec bump to 3.29.0.
