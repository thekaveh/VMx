# NotificationVM

## When To Use It

Use `NotificationVM` when a host wants to render pending notifications from
`INotificationHub` as bindable view state with auto-dismiss timing.

This is a render-side VM, not the notification hub itself. In C#, the shipped
type lives in the `VMx.Notifications` package/namespace rather than the core
`VMx` assembly.

## Shape And Ownership

`NotificationVM` wraps one `Notification` value and owns:

- lifespan and remaining time
- derived opacity
- resolved state
- dismiss command that resolves through the hub

It is usually created by a higher-level notifications list VM that subscribes to
`INotificationHub.Pending`.

## Lifecycle And Messaging

The hub still owns the source notification state. `NotificationVM` adds the
render-time lifecycle:

- timer starts at construction
- timer expiry resolves with `Approve`
- manual dismiss resolves immediately and cancels the timer
- external hub resolution updates `IsResolved`
- dispose tears down timer and subscriptions

## Cross-Language Surface

| Concept          | C#               | Python            | TypeScript       | Swift            |
| ---------------- | ---------------- | ----------------- | ---------------- | ---------------- |
| Type             | `NotificationVM` | `NotificationVM`  | `NotificationVM` | `NotificationVM` |
| Lifespan default | 60 s             | 60 s              | 60 s             | 60 s             |
| Dismiss command  | `DismissCommand` | `dismiss_command` | `dismissCommand` | `dismissCommand` |

## Example

The Notes Workspace notifications feature projects pending notifications into
render VMs:

- C#: [NotificationsVM.cs](https://github.com/thekaveh/VMx/blob/main/examples/csharp/avalonia/NotesShowcase/ViewModels/NotificationsVM.cs)
- Python: [notifications_vm.py](https://github.com/thekaveh/VMx/blob/main/examples/python/textual/notes_showcase/src/notes_showcase/viewmodels/notifications_vm.py)
- TypeScript: [notificationsVM.ts](https://github.com/thekaveh/VMx/blob/main/examples/typescript/react/notes-showcase/src/viewmodels/notificationsVM.ts)
- Swift: [NotificationsVM.swift](https://github.com/thekaveh/VMx/blob/main/examples/swift/notes-showcase/Sources/NotesShowcaseCore/ViewModels/NotificationsVM.swift)

Those VMs subscribe to `Pending`, build a bounded visible list, and let each
`NotificationVM` manage its own fade and dismissal timing.

=== "C#"

````
```csharp
var vm = new NotificationVM(n, _notificationHub, _scheduler, _lifespan);
_map[n] = vm;
_visible.Add(vm);
```
````

=== "Python"

````
```python
vm = NotificationVM(
    notification=n,
    hub=self._notification_hub,
    scheduler=self._scheduler,
    lifespan=self._lifespan,
)
self._map[n] = vm
self._visible.append(vm)
```
````

=== "TypeScript"

````
```ts
const vm = new NotificationVM(
  n,
  this.#notificationHub,
  this.#scheduler,
  this.#lifespanMs,
);
this.#map.set(n, vm);
this.#visible.push(vm);
```
````

=== "Swift"

````
```swift
let lifespan = _lifespan ?? 60.0
let vm = NotificationVM(
    notification: n,
    hub: _notificationHub,
    scheduler: _scheduler,
    lifespan: lifespan
)
_map[key] = vm
_visible.append(vm)
```
````

## Common Pitfalls

- Treating the render VM as the source of truth. The hub owns pending state.
- Forgetting to inject a deterministic scheduler in tests.
- Using `NotificationVM` for prompts that require explicit approve/reject
  actions. That is `ConfirmationVM`.

## Related Primitives

- [ConfirmationVM](confirmation-vm.md)
- [Services, Messages & Dispatching](../../services-messages-dispatching.md)
- [Builders, Collections & Tree Utilities](../../builders-collections-tree-utilities.md)
