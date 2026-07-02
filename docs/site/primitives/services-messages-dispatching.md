# Services, Messages & Dispatching

## When To Use It

Use this layer when the question is coordination rather than structure:
cross-VM messages, scheduler choice, host dialogs, notification routing, or
null-object defaults for headless code and tests.

## Shape And Ownership

The core services are:

- `IMessageHub` / `MessageHub`
- `IDispatcher` / `RxDispatcher`
- `IDialogService`
- `INotificationHub` in the opt-in notifications package
- null variants for the service contracts

The core message families are:

- `PropertyChangedMessage`
- `ConstructionStatusChangedMessage`
- `TreeStructureChangedMessage`
- `FormRevertedMessage`
- collection-changed messages from the collections area

## Lifecycle And Messaging

Important runtime rules from the spec:

- the message hub is hot and non-replaying
- single-producer send order is FIFO
- subscriber exceptions do not break the hub
- property-changed and collection-changed emissions are foreground-dispatched by
  contract when the implementation marshals them that way
- background lifecycle work publishes intermediate state immediately and
  foreground-marshals terminal completion

## Cross-Language Surface

| Service            | Purpose                                              |
| ------------------ | ---------------------------------------------------- |
| `IMessageHub`      | hot pub/sub for framework messages                   |
| `IDispatcher`      | foreground/background scheduler pair                 |
| `IDialogService`   | request/response host dialogs and modal presentation |
| `INotificationHub` | fire-and-forget notification stream                  |

## Example

The Quickstart flow shows the minimal service pair every VM needs:

=== "Python"

    ```python
    hub = MessageHub()
    dispatcher = RxDispatcher.immediate()
    ```

From there, higher-level examples add `INotificationHub` and `IDialogService`
only where the workflow requires them.

## Common Pitfalls

- Treating the hub like a replaying event store. It is hot and current-subscriber
  only.
- Assuming background lifecycle completion arrives on a background thread in
  consumers. Terminal completion is foreground-marshalled by the reference
  implementations.
- Using dialogs for fire-and-forget notifications or using notification hubs for
  blocking user decisions.

## Related Primitives

- [NotificationVM](viewmodel-families/specialized/notification-vm.md)
- [ModalVM](viewmodel-families/specialized/modal-vm.md)
- [Builders, Collections & Tree Utilities](builders-collections-tree-utilities.md)
