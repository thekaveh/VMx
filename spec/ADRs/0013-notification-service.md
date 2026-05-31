# ADR 0013 — Notification / confirmation sub-package

**Status:** Accepted (2026-05-25)
**Spec version:** introduced in 2.0.0

## 1. Context

The 2012 VMx predecessor included a `NotificationService` that handled
user-facing notifications and confirmations via an async pattern: post a
notification, await a reaction. The service stored a queue of pending
notifications and exposed a hot observable of new ones.

The current VMx has no notification primitive. Consumers who need
notifications either build their own or pull a third-party library. The
absence is felt most acutely when implementing a confirmation flow for the
modeled-CRUD `DeleteCurrentCommand` (see ADR-0016): there is no canonical
way to ask "are you sure?" via the message hub.

## 2. Options considered

1. **Skip — no notification primitive in v2.** Same as today. Consumers
   keep building their own.
1. **Ship `INotificationHub` in the core `vmx` package.** Core surface
   grows; users who don't want it carry it anyway.
1. **Ship `INotificationHub` in an opt-in sub-package.** Core stays
   headless; consumers explicitly opt in via import path.

## 3. Decision

Option 3. The notification primitives ship in a separate sub-package per
flavor, with the per-flavor distribution shape chosen for minimum friction:

- **C#**: separate assembly `VMx.Notifications` (depends on `VMx`).
  Natural .NET boundary; mirrors the existing
  `VMx.Extensions.DependencyInjection` pattern.
- **Python**: subpackage `vmx.notifications` (same wheel as `vmx`).
  Avoids an extra packaging pipeline; opt-in via `import vmx.notifications`.
- **TypeScript**: subpath export `vmx/notifications` (same npm package
  as `vmx`). Avoids forcing a workspace restructure.

The asymmetry is intentional: it preserves "opt-in, no core surface impact"
in all three without spinning up extra packaging infrastructure for Python
and TypeScript.

The confirmation-decorator bridge (ADR-0012's
`ConfirmationDecoratorCommand` is delegate-shaped) lives in the
notification sub-package as a helper function — keeping the core
`commands` chapter UI-agnostic.

## 4. Consequences

- A new spec chapter `16-notifications.md` defines the contract.
- Ten conformance IDs `NOTIF-001..NOTIF-010` cover the contract surface,
  the null variant (`NullNotificationHub` per ADR-0017), and the
  command-decorator bridge.
- Three new per-flavor sub-packages:
  - `langs/csharp/src/VMx.Notifications/` (new csproj added to the
    solution)
  - `langs/python/src/vmx/notifications/`
  - `langs/typescript/src/notifications/` + a subpath export entry in
    `langs/typescript/package.json`
- Each sub-package starts at version 1.0.0 (independent versioning).
- The core `vmx` package surface is unchanged; consumers who don't import
  the sub-package see no difference.
- `Post` returns a per-flavor awaitable (C# `Task<NotificationReaction>`,
  Python `Awaitable[NotificationReaction]`, TS `Promise<NotificationReaction>`).
- The hub holds notifications until resolved. There is no built-in
  cap or timeout; the consumer is responsible for resolving in a
  bounded time.
