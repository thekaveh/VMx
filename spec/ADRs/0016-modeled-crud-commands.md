# ADR 0016 — Modeled CRUD commands

**Status:** Accepted (2026-05-25)
**Spec version:** introduced in 2.0.0

## 1. Context

The 2012 VMx predecessor's modeled composite (`CompositionBase<M, VM, C, P>`)
shipped three CRUD commands: `CreateNewCommand`, `UpdateCurrentCommand`, and
`DeleteCurrentCommand` (the last wrapped in a `.Confirm("Are you sure?")`
decorator). They were always present on the composite, even when the consumer
didn't need them.

The current VMx has no equivalent — consumers wire CRUD commands manually
against `RelayCommand` and the composite's `Current` slot.

## 2. Options considered

1. **Restore CRUD commands on `CompositeVM<M, VM>` directly.** Always
   present, like the legacy predecessor. Grows the surface for consumers
   who don't need them.
1. **Provide a `ModeledCrudCommands<M, VM>` helper that wires the three
   commands against a current-provider + actions.** Opt-in; base composite
   unchanged. Composes naturally with `ConfirmationDecoratorCommand`
   (per ADR-0012) for the legacy `.Confirm(...)` shape.

## 3. Decision

Option 2. The cycle ships `ModeledCrudCommands<M, VM>` per flavor. It
exposes the three commands and takes:

- A `current` provider function.
- Three action callbacks (`create_new`, `update_current`, `delete_current`).
- Two optional async confirm delegates (`confirm_update`, `confirm_delete`).
  When supplied, the corresponding command is wrapped in a
  `ConfirmationDecoratorCommand` and execution awaits the confirm result.

Consumers compose the helper into their modeled composite VM; the base
type is unchanged.

## 4. Consequences

- Six conformance IDs `COMP-019..COMP-024` cover the per-command behavior
  and the confirm-decorator integration.
- Each flavor exposes `ModeledCrudCommands` in its `commands/` directory.
- The CRUD commands implement the capability interfaces from ADR-0010
  where natural: `INewCreatable` is satisfied by the helper's
  `CreateNewCommand` invocation surface; `ICurrentDeletable` and
  `ICurrentUpdatable` are satisfied likewise.
- The legacy `.Confirm("Are you sure?")` shape is preserved via the
  optional confirm delegates; consumers wishing to drive confirmation via
  the notification hub can use the bridge helper from ADR-0013
  (`make_confirm`).
- The helper itself is not an `ICommand`; it owns and exposes three
  separate `ICommand` instances. Consumers can use them individually or
  bundle them as needed (e.g., into a `CompositeCommand` for "do all").
