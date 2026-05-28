# ADR 0027 — Fluent command extension methods

**Status:** Accepted (2026-05-28)
**Spec version:** introduced in 2.1.0

## 1. Context

All four framework-bearing legacy codebases that VMx descends from
(`VMx.old`, `My.Architecture.New`, `GuideArch.Old`, `GuideArch`) exposed
fluent extension or helper methods that constructed decorator commands from
an existing command in a single, readable expression. The three concrete
decorator types introduced in ADR-0012 (`CompositeCommand`,
`DecoratorCommand`, `ConfirmationDecoratorCommand`) require callers to
name the decorator class explicitly and supply arguments in constructor
order. While correct, this is more verbose than necessary for the most
common composition patterns.

Fluent shortcuts add no new behavior — they are pure ergonomic sugar
over the existing constructors. Because they introduce normative API
surface, they require a spec chapter entry and conformance coverage to
keep all three flavors in sync.

The four patterns that appeared consistently across all legacy codebases:

1. Gate a command on a user-confirmation step (`Confirm`).
1. Prepend another command before a command executes (`PrecedeWith`).
1. Append another command after a command executes (`SucceedWith`).
1. Wrap a command with an extra predicate and pre/post hooks (`WrapWith`).

`Confirm` is the only method that can optionally bridge to the
notification sub-package (ADR-0013), because it is the only one whose
delegate argument can be derived from an `INotificationHub` interaction.

## 2. Options considered

1. **Skip.** Keep only the explicit constructors. Consumers write
   `new CompositeCommand(other, cmd)` at call sites. Small surface, but
   every legacy codebase that inherited this pattern found it worth
   abstracting.
1. **Add as informative only** (documentation note in `spec/04-commands.md`,
   no conformance coverage). Preserves consistency across flavors via
   convention, but no CI enforcement. A flavor can silently diverge in
   naming or argument order.
1. **Add as normative API with conformance coverage.** Four methods,
   conformance-tested for equivalence to their explicit constructor
   counterparts. Flavors that cannot model extension methods (Python) may
   expose them as module-level functions. Naming adapts per ADR-0006
   (Pascal/snake/camel).

## 3. Decision

Option 3. Four fluent extension methods are part of the normative
`ICommand`-augmented API in every active flavor:

1. **`Confirm(prompt)`** — returns a `ConfirmationDecoratorCommand`
   wrapping the receiver, with the given `confirm` delegate of shape
   `() -> Task<bool>` (or per-language async-Boolean equivalent).
   An optional overload accepts an `INotificationHub` and constructs the
   delegate from it via the bridge helper in the `vmx-notifications`
   sub-package (ADR-0013). This overload is the only fluent method that
   touches the notifications sub-package and it is therefore optional:
   if the sub-package is absent, only the delegate overload is available.
1. **`PrecedeWith(other)`** — returns `CompositeCommand(other, receiver)`.
   The `other` command executes first.
1. **`SucceedWith(other)`** — returns `CompositeCommand(receiver, other)`.
   The receiver executes first.
1. **`WrapWith(predicate?, pre?, post?)`** — returns a `DecoratorCommand`
   wrapping the receiver with the supplied optional extra predicate and
   pre/post hooks. Passing all nulls/defaults is valid and yields a
   semantically transparent decorator.

Per-flavor surface idiom (ADR-0006):

- **C#**: static extension methods on `ICommand` in namespace `VMx.Commands`.
- **Python**: module-level functions in `vmx.commands` (or `vmx.commands.fluent`);
  imported alongside the decorator classes.
- **TypeScript**: standalone named exports in `vmx/commands` (or
  `vmx/commands/fluent`); re-exported from the package entry point.

## 4. Consequences

1. `spec/04-commands.md` gains a new §9 "Fluent composition" subsection
   documenting the four methods and their explicit-constructor equivalents.
1. Four new conformance IDs `CMD-008..CMD-011` assert that each fluent
   form produces an object whose `CanExecute` / `Execute` graph is
   equivalent to the explicit constructor call.
1. Each flavor adds the four helpers to its `commands/` module.
   Implementation is deferred to the execution phase of Substage 1D.
1. The `Confirm(INotificationHub)` overload lives in the notifications
   sub-package in each flavor (it must not create a hard dependency from
   the core commands module on the sub-package).
1. No existing conformance IDs are changed; existing decorator tests
   (`CMDD-001..CMDD-009`) remain unmodified.
