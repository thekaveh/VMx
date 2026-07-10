# 6.2.8.5. ConfirmationVM

## When To Use It

Use `ConfirmationVM` when the notification should stay visible until the user
explicitly approves, rejects, or dismisses it. It is the render-side sibling of
`NotificationVM` for decision-bearing prompts.

## Shape And Ownership

`ConfirmationVM` extends the notification render contract with:

- `ApproveCommand`
- `RejectCommand`
- longer default lifespan (300 s)
- no auto-resolve on timer expiry

Like `NotificationVM`, it still resolves through `INotificationHub`.

## Lifecycle And Messaging

The key difference from `NotificationVM` is timeout behavior:

- the timer may drive UI decay, but not resolution
- timeout means "user did not decide yet"
- explicit approve/reject flows resolve the underlying notification
- inherited dismiss still resolves with `Approve`

## Cross-Language Surface

| Concept          | C#               | Python           | TypeScript       | Swift            |
| ---------------- | ---------------- | ---------------- | ---------------- | ---------------- |
| Type             | `ConfirmationVM` | `ConfirmationVM` | `ConfirmationVM` | `ConfirmationVM` |
| Default lifespan | 300 s            | 300 s            | 300 s            | 300 s            |
| Reject command   | `RejectCommand`  | `reject_command` | `rejectCommand`  | `rejectCommand`  |

## Example

The flagship Notes Workspace apps currently do not project confirmations through
`ConfirmationVM`. They use command-level confirmation gates plus host dialogs:

- command gating in the note delete flow via `ConfirmationDecoratorCommand`
- host prompts via `IDialogService.Confirm`

That split is intentional. Use `ConfirmationVM` when the confirmation itself
should be part of a rendered notification stream rather than a host modal.

When you do want the confirmation inside the notification stream, the direct
library surface is:

=== "C#"

    ```csharp
    using var vm = new ConfirmationVM(notification, hub, scheduler);
    vm.RejectCommand.Execute(null);
    ```

=== "Python"

    ```python
    vm = ConfirmationVM(notification=notif, hub=hub, scheduler=scheduler)
    vm.reject_command.execute()
    ```

=== "TypeScript"

    ```ts
    const vm = new ConfirmationVM(notif, hub, scheduler);
    vm.rejectCommand.execute();
    ```

=== "Swift"

    ```swift
    let vm = ConfirmationVM(notification: notif, hub: hub, scheduler: scheduler)
    vm.rejectCommand.execute()
    ```

## Common Pitfalls

- Expecting timeout to auto-resolve. It does not.
- Using `ConfirmationVM` when the host already provides the correct blocking
  confirmation via `IDialogService`.
- Forgetting that inherited dismiss resolves with approve semantics.

## Related Primitives

- [NotificationVM](notification-vm.md)
- [Command Families](../../command-families.md)
- [ModalVM](modal-vm.md)
