# NotificationVM

Use `NotificationVM` when a host wants to render pending notifications from
`INotificationHub` as bindable view state with auto-dismiss timing.

## What It Owns

- visible lifespan and remaining time
- derived opacity or fade state
- resolved state
- dismiss command that resolves through the hub

## Related Pages

- [[ConfirmationVM|Framework-Primitives/ViewModel-Families/Specialized/ConfirmationVM]]
- [[Notes Workspace|Examples/Notes-Workspace]]
