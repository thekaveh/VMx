# Specialized ViewModels & Coordinators

These primitives are not alternate container shapes. They solve specific
workflow problems that show up repeatedly across apps:

- `FormVM` for snapshot/revert/approve edit flows
- `DiscriminatorVM` for active-mode or active-pane coordination
- `NotificationVM` and `ConfirmationVM` for render-side notification state
- `ModalVM` for VM-backed modal completion

Use them when the workflow itself is the reusable primitive. If the need is
just "a leaf with one more property", stay on the core hierarchy and compose the
smaller helpers instead.

## Notes Workspace Pointers

The flagship examples are especially useful here:

- the editor pane composes `FormVM` and `DiscriminatorVM`
- the notifications pane projects `INotificationHub.Pending` into
  `NotificationVM` instances
- the dialog adapters show where `ModalVM` fits when `IDialogService.Present`
  is the right host seam

The dedicated pages below call out the relevant example files directly.
