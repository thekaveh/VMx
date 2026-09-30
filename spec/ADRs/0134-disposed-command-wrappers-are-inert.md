# ADR 0134 — Disposed command wrappers are inert

- **Status:** Accepted
- **Date:** 2026-09-30
- **Spec version:** 3.24.0

## 1. Context

ADR-0068 made disposed relay commands inert: `CanExecute` returns `false` and
`Execute` does nothing. The command docs promised the same for every command,
but the three wrappers from ADR-0012 never read their disposed state. In C#,
Python, TypeScript, and Swift, a disposed `CompositeCommand`, `DecoratorCommand`,
or `ConfirmationDecoratorCommand` still reported `CanExecute == true` and still
executed. A confirmation that was pending at disposal still ran the inner command
once it resolved `true`. Swift's wrapper `dispose()` methods were empty, and Rust's
`CompositeCommand` and `DecoratorCommand` had no disposal surface. Rust's
confirmation decorator re-checked disposal after confirming, but its
`can_execute` ignored it. No conformance ID covered wrapper disposal (#338).

## 2. Decision

Each policy below extends an existing disposal decision.

1. **Inertness (ADR-0068).** A disposed wrapper reports `CanExecute == false`.
   `Execute` invokes no inner command, extra predicate, pre- or post-execution
   action, or `confirm` delegate. Disposal is idempotent.
1. **Ownership (ADR-0084).** Wrappers stay non-owning: disposal never disposes an
   inner command.
1. **Disposal during execution.** A wrapper checks for disposal after each
   call-out that can dispose it: inner and extra predicates, the pre-execution
   action, an earlier composite child, and a pending confirmation. No inner work
   starts once disposal is observed.
1. **Balanced hooks (ADR-0062 §2.5).** A decorator's pre- and post-execution
   actions are a pair guarded by `finally`/`defer`. Once the pre-action has run,
   the post-action runs exactly once on every exit path, including when disposal
   during the pre-action skips the inner command. Exceptions from an admitted
   pair propagate unchanged. Rust keeps its existing unwinding behavior for
   panics and runs the post-action on the disposal path.
1. **Late confirmations (ADR-0049).** A confirmation that resolves after disposal,
   whether `true`, `false`, or faulted, runs no inner command and emits nothing on
   `errors`, which already completed at disposal. An awaited `ExecuteAsync()` still
   propagates a faulted confirmation to its own caller, because that path never
   used `errors`.
1. **Thread safety (ADR-0084 item 5).** Where a wrapper can be executed and
   disposed on different threads, disposal and the admission checks are atomic:
   once `dispose()` returns, no check admits new inner work. Work admitted
   earlier may finish. No application code runs under a lock.
1. **Change streams (ADR-0068, ADR-0086).** A wrapper never completes or disposes
   an inner command's stream. Wrappers that hold their own subscriptions (C#
   wrappers and Rust's `CompositeCommand`) release them at disposal. Wrappers
   that expose a merged or delegated inner stream (TypeScript, Python, Swift, and
   Rust's decorators) leave it to the inner commands. As for relay commands, a
   flavor may notify `CanExecuteChanged` once during disposal.
1. **Rust surface.** `CompositeCommand` and `DecoratorCommand` gain a `dispose()`
   method. Clones share disposal state, as `ConfirmationDecoratorCommand` clones
   already do.

`CMDD-011`, `CMDD-012`, and `CMDD-013` cover these rules in all five flavors. The
catalog grows from 403 to 406 library IDs. This is a backward-compatible addition,
so the spec moves to 3.24.0 and each flavor takes a minor bump.

## 3. Consequences

- Hosts that dispose a view model's commands during teardown can rely on the
  wrappers being inert, including a delete confirmation still on screen.
- Code that reused a wrapper after disposing it now gets a disabled no-op command.
  That code was already outside the documented contract.
- A pending confirmation that loses a race with `dispose()` is either admitted
  before disposal and runs, or observes disposal and does not. It never runs
  after `dispose()` has returned.
- Rust gains `dispose()` on two wrapper types. The addition is source compatible.

## 4. Rejected alternatives

- **Dispose inner commands with the wrapper.** This contradicts the non-owning rule
  of ADR-0084 and would break graphs that share an inner command between wrappers.
- **Skip the post-action whenever the inner command is skipped.** That would
  unbalance a pre/post pair whose pre-action already acquired something. The
  `finally`/`defer` pairing of ADR-0062 §2.5 already defines the admitted pair.
- **Complete the delegated inner change stream.** The stream belongs to the inner
  command. Completing it would silence other observers of that command.
- **Cancel the pending confirmation.** Cancellable single-flight confirmation is a
  separate proposal (#377). Inertness does not depend on it.
