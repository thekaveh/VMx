# ADR 0012 — Command decorators

**Status:** Accepted (2026-05-25)
**Spec version:** introduced in 2.0.0

## 1. Context

The 2012 VMx predecessor exposed three decorator commands:

- `CompositeCommand` — aggregates multiple commands; `CanExecute` if any
  child can; `Execute` invokes every child whose `CanExecute` is true.
- `DecoratorCommand` — wraps a single command with pre/post actions and an
  extra can-execute predicate.
- `ConfirmationDecoratorCommand` — wraps a command, prompting "Are you sure?"
  before invoking.

The current VMx only ships `RelayCommand`. There is no way to express
"execute these three commands as a batch" or "ask before invoking" without
hand-rolling the wiring.

## 2. Options considered

1. **Skip decorators; consumers compose by hand.** Existing reality. Keeps
   surface small but misses a frequently-needed composition pattern.
1. **Three concrete decorator types matching legacy parity.**
   `CompositeCommand`, `DecoratorCommand`, `ConfirmationDecoratorCommand`.
1. **Open-ended `DecoratorCommandBuilder` with optional pre/post/confirm/extra-predicate
   slots.** Fewer types, more configuration. Less discoverable than three
   named types.

## 3. Decision

Option 2. Three concrete decorator types per flavor, matching the legacy
naming. Each is built via a constructor / factory taking the inner command(s)
plus the decorator-specific arguments.

`ConfirmationDecoratorCommand` takes its confirm gate as a generic
delegate-shaped argument (`Func<Task<bool>>` / `Callable[[], Awaitable[bool]]` /
`() => Promise<boolean>`). It deliberately does NOT depend on the notification
service (cycle 5). Consumers wanting a "show a confirmation dialog via the
notification hub" can use a helper in the `vmx-notifications` sub-package
that turns an `INotificationHub` interaction into a `Func<Task<bool>>`.

## 4. Consequences

- An extended chapter `04-commands.md` documents the three decorators.
- Nine conformance IDs `CMDD-001..CMDD-009` cover the per-decorator contract.
- Each flavor exposes the three decorators in its `commands/` directory.
- The confirmation decorator stays UI-agnostic: the delegate shape is the
  only contract — neither the notification service nor any specific
  dialog/toast/modal API is required.
- Decorators are themselves `ICommand` instances, so they compose: a
  `CompositeCommand` of `DecoratorCommand` of `ConfirmationDecoratorCommand`
  of `RelayCommand` is valid.
- `CanExecuteChanged` propagation rules differ per decorator (composite:
  any child; decorator/confirmation: inner only). These are
  conformance-tested.
