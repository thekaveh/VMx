# Specialized ViewModels & Coordinators

## When To Use It

These primitives are not alternate container shapes. They solve specific
workflow problems that show up repeatedly across apps:

- `FormVM` for snapshot/revert/approve edit flows
- `DiscriminatorVM` for active-mode or active-pane coordination
- `NotificationVM` and `ConfirmationVM` for render-side notification state
- `ModalVM` for VM-backed modal completion

Use them when the workflow itself is the reusable primitive. If the need is
just "a leaf with one more property", stay on the core hierarchy and compose the
smaller helpers instead.

## Shape And Ownership

These types typically wrap or coordinate other VM state rather than replacing
the core ownership hierarchy:

- `FormVM` owns edit snapshots and approval/revert flow around a target VM
- `DiscriminatorVM` owns active-case switching
- `NotificationVM` and `ConfirmationVM` own render-ready notification state
- `ModalVM` owns completion state around a presented modal workflow

## Lifecycle And Messaging

Specialized primitives matter when a recurring workflow has its own lifecycle
or message flow:

- forms track dirty/valid/approve/revert transitions
- discriminators switch active cases while keeping case selection observable
- notification and confirmation VMs mirror host notification streams
- modal VMs bridge VM state with dialog completion

The dedicated pages cover the exact hooks and host seams each workflow uses.

## Cross-Language Surface

All four flavors ship the same conceptual set of specialized primitives, with
idiomatic naming differences only. The dedicated pages call out where example
apps currently exercise them and where a flavor surfaces helper APIs
idiomatically.

## Example

In the Notes Workspace examples, the editor flow composes `FormVM` with
`DiscriminatorVM`, while notifications and dialogs use the render-oriented
primitives instead of growing ad hoc state on unrelated container VMs.

The flagship examples are especially useful here:

- the editor pane composes `FormVM` and `DiscriminatorVM`
- the notifications pane projects `INotificationHub.Pending` into
  `NotificationVM` instances
- the dialog adapters show where `ModalVM` fits when `IDialogService.Present`
  is the right host seam

The dedicated pages below call out the relevant example files directly.

## Common Pitfalls

- Reaching for a specialized primitive when a plain `ComponentVM` plus a command
  or property would do.
- Treating these pages as alternatives to the core container families.
- Assuming every example app must use every specialized primitive directly.

## Related Primitives

- [ViewModel Families](../index.md)
- [Command Families](../../command-families.md)
- [Services, Messages & Dispatching](../../services-messages-dispatching.md)
