# ADR 0029 — Dialog service in core

**Status:** Accepted (2026-05-28)
**Spec version:** introduced in 2.1.0

## 1. Context

Both GuideArch versions (Silverlight and current) invented their own `DialogService`
for file pickers, confirmation prompts, and toast-style notify. `My.Architecture.View`
has an empty `IDialogueFactory` stub. v2.0 VMx has `INotificationHub` for
fire-and-forget toast/banner but no contract for **modal** host interactions: file
pick, confirm prompt, notify with severity.

`ConfirmationDecoratorCommand` (ADR-0012) takes a delegate-shaped `Func<Task<bool>>`;
that pattern composes naturally with `IDialogService.Confirm`, but the audit proposal
requires a first-class dialog contract too.

## 2. Options considered

1. Skip — consumers continue to invent their own.
1. Opt-in subpackage (`VMx.Dialogs`) — mirrors the notification sub-package
   (ADR-0013).
1. In core — small contract surface, no extra packaging, discoverable.

## 3. Decision

Option 3 (user decision in audit proposal). `IDialogService` lands in core with four
members:

- `PickFileToOpen(filter?, title?) -> Task<Path?>` — null on cancel
- `PickFileToSave(filter?, title?, suggestedName?) -> Task<Path?>` — null on cancel
- `Confirm(message, title?) -> Task<bool>` — false on cancel
- `Notify(message, title?, severity?) -> Task` — severity Info/Warning/Error

`NullDialogService` follows ADR-0017 convention: `PickFile*` returns null; `Confirm`
returns `false` (safest default — non-destructive); `Notify` is no-op.

Host adapters (WPF/Avalonia/console/test) live downstream. Reentrancy is
implementation-defined.

## 4. Consequences

1. New chapter `spec/19-dialogs.md` defines the contract.
1. Eight conformance IDs `DIA-001..DIA-008`.
1. Per-flavor `dialogs/` directory: contract + null implementation only.
1. `spec/16-notifications.md` extended with a paragraph distinguishing
   `INotificationHub` (toast/banner) from `IDialogService` (modal).
1. New fluent command extension `cmd.Confirm(dialogService, prompt)` overload
   alongside the existing `cmd.Confirm(hub, prompt)` (ADR-0027); both construct
   the same `Func<Task<bool>>`-shaped delegate.
