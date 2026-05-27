# 16 — Notifications (sub-package)

The notifications sub-package provides a UI-agnostic, async notification /
confirmation hub. It is **opt-in**: the core `vmx` package does not depend on
it, and consumers must import the sub-package explicitly to use it.

Per ADR-0013, the distribution shape is per-flavor:

- **C#**: separate assembly `VMx.Notifications` (depends on `VMx`)
- **Python**: subpackage `vmx.notifications` (same distribution as `vmx`)
- **TypeScript**: subpath export `vmx/notifications` (same package as `vmx`)

The asymmetry preserves "opt-in, no core surface impact" without forcing a
TypeScript monorepo restructure.

## Primitives

### `NotificationType`

An enum with three members:

| Value          | Intent                                         |
| -------------- | ---------------------------------------------- |
| `Error`        | Something failed; user attention required.     |
| `Notification` | Informational; user acknowledgement is enough. |
| `Confirmation` | A decision is required (Approve/Reject).       |

### `NotificationReaction`

An enum with three members:

| Value     | Meaning                                              |
| --------- | ---------------------------------------------------- |
| `Pending` | Default; the notification has not been resolved yet. |
| `Approve` | User accepted / acknowledged the notification.       |
| `Reject`  | User declined the notification.                      |

### `Notification`

An immutable value object:

```
Notification:
    Type    : NotificationType
    Message : string
```

Notifications are identity-distinct: two `Notification` values with identical
`Type` and `Message` are still different instances (one user's posting can be
queued and resolved independently of another's).

## `INotificationHub` contract

```
INotificationHub:
    Post(notification: Notification) : Task<NotificationReaction>
    Resolve(notification: Notification, reaction: NotificationReaction) : void
    Pending : Observable<list<Notification>>       # current pending list (BehaviorSubject-like)
```

### `Post` semantics

- Adds `notification` to the pending list.
- Emits a new `Pending` value (the updated list).
- Returns an awaitable that completes when `Resolve(notification, …)` is
  called for this exact instance. The completed value is the
  `NotificationReaction` passed to `Resolve`.
- Posting the same `notification` instance while it is still pending is
  implementation-defined; implementations SHOULD return the existing
  awaitable rather than silently dropping it. Callers wanting two
  independent posts MUST construct two `Notification` instances (see the
  identity-distinctness rule above). A future minor version may strengthen
  this to a normative no-op and add a covering conformance ID.

### `Resolve` semantics

- Removes `notification` from the pending list.
- Emits a new `Pending` value.
- Completes the awaitable returned by the original `Post` call with the
  given `NotificationReaction`.
- Resolving a notification that is not in the pending list is a no-op (it
  was already resolved or never posted).

### `Pending`

- A hot observable that emits the current pending list whenever it changes.
- New subscribers immediately receive the current snapshot (BehaviorSubject-like).
- Implementations MAY emit an immutable copy of the list, or a stable
  reference; consumers MUST NOT mutate the emitted list.

## Null variant — `NullNotificationHub`

Per the convention from ADR-0017, `NullNotificationHub` is the null-object
variant:

- `Post(notification)` returns a task that completes with `Approve` immediately.
- `Resolve(notification, reaction)` is a no-op.
- `Pending` is an observable that emits the empty list once and completes.

## Bridging command decorators

The notifications package SHOULD also expose a small helper that adapts an
`INotificationHub` confirmation flow to the `ConfirmDelegate` shape used by
`ConfirmationDecoratorCommand` (see spec/04-commands.md §Decorators):

```
make_confirm(hub: INotificationHub, prompt: string) -> Func<Task<bool>>
```

The helper posts a `Notification(Confirmation, prompt)`, awaits resolution,
and returns `true` iff the resolution is `Approve`. This is the canonical
way to wire a UI-driven confirmation gate through the notification hub.

## Conformance

`NOTIF-001` through `NOTIF-010` in `12-conformance.md` cover the contract,
the null variant, the type/reaction enums, and the command-decorator bridge.
