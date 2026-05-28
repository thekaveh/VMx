# ADR 0031 — Notification rendering VMs (`NotificationVM`, `ConfirmationVM`)

**Status:** Accepted (2026-05-28)
**Spec version:** introduced in 2.1.0

## 1. Context

The 2012 VMx and My.Architecture.New both ship concrete UI-bindable
`NotificationVM` and `ConfirmationVM` types that consume `Notification` data
from the hub. v2.0 VMx ships only the hub + data primitives; consumers must
reinvent the rendering ViewModel themselves.

The absorption audit (item C5) calls for adding these as render-side companions
to the existing notifications sub-package (ADR-0013). They expose `Opacity`,
`RemainingTime`, dismiss commands, and auto-dismiss lifecycle driven by an
injected scheduler.

## 2. Options considered

1. Skip — consumers continue to invent their own rendering VMs.
1. Ship in core — adds UI-rendering concerns to the always-loaded VMx core.
1. Ship in the notifications sub-package — opt-in alongside the existing hub.

## 3. Decision

Option 3. The new VMs live in the existing notifications sub-package
(per ADR-0013): `VMx.Notifications` (C#), `vmx.notifications` (Python),
`vmx/notifications` (TypeScript subpath export).

The eight locked design decisions are:

1. `NotificationVM` is the base; `ConfirmationVM` extends it.
1. Default lifespans: `NotificationVM` = 60 s; `ConfirmationVM` = 300 s
   (matches VMx.old precedent for confirmation prompts).
1. `Opacity` is a derived property: `RemainingTime / Lifespan`, clamped to
   `[0.0, 1.0]`. Linear decay from 1.0 at construction to 0.0 at expiry.
1. `RemainingTime` decays via an injected scheduler. Tests use `TestScheduler`
   for deterministic virtual-time advancement.
1. `DismissCommand` resolves the hub notification with `NotificationReaction.Approve`
   (the standard "user acknowledged") and cancels the lifespan timer.
1. `ConfirmationVM` adds `ApproveCommand` and `RejectCommand`; each resolves the
   hub notification with the corresponding `NotificationReaction`.
1. `NotificationVM` auto-dismisses (fires `DismissCommand`'s effect) when
   `RemainingTime` reaches zero. `ConfirmationVM` does NOT auto-resolve on
   expiry — timeout means "user did not decide"; the notification remains pending.
1. Manual `DismissCommand` invocation cancels the lifespan timer so the
   auto-fire path cannot double-resolve.

## 4. Consequences

- Chapter 16 gains two new subsections (`NotificationVM`, `ConfirmationVM`) and
  a "Patterns" section with the service-as-VM recipe (composition-only, not a
  normative spec addition).
- A lifespan/opacity timeline `gantt` diagram is added to chapter 16.
- Six new conformance IDs `NOTIF-011..NOTIF-016` are added to the catalog.
- Per-flavor implementation lives in the notifications sub-package alongside the
  existing hub, null variant, and `make_confirm` helper.
