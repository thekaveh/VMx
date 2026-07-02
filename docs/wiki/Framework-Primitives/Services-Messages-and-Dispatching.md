# Services, Messages & Dispatching

Use this layer when the question is coordination rather than structure.

## Core Services

- `MessageHub`
- dispatcher / scheduler pair
- `IDialogService`
- `INotificationHub` in the opt-in notifications package
- null-object variants for headless code and tests

## Core Message Families

- property changed
- construction status changed
- tree structure changed
- form reverted
- observable collection change messages

## Related Pages

- [[NotificationVM|Framework-Primitives/ViewModel-Families/Specialized/NotificationVM]]
- [[ModalVM|Framework-Primitives/ViewModel-Families/Specialized/ModalVM]]
- [[Builders, Collections & Tree Utilities|Framework-Primitives/Builders-Collections-and-Tree-Utilities]]
