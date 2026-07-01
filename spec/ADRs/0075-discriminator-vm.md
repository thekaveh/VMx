# ADR 0075 — Add DiscriminatorVM active-key coordinator

**Status:** Accepted (2026-07-01)
**Spec version:** introduced in 3.1.0

## 1. Context

The aws-tui adoption feedback identified a recurring coordinator shape: one VM
owns the single active slot/focus target, and modal presentation temporarily
takes precedence before restoring the prior active slot.

No existing VMx primitive represented that state directly. Consumers could model
it with `ComponentVM` plus custom fields, but the change stream and modal stack
behavior were repeated application logic.

## 2. Decision

Add `DiscriminatorVM<TKey>` as a generic state helper:

- stores one active key;
- exposes `ActiveChanged`;
- answers `IsActive(key)`;
- updates via `SetActiveKey(key)`;
- treats re-setting the same key as a no-op;
- provides `ModalOpen(modalKey)` / `ModalClose()` helpers that restore prior
  keys in last-in-first-out order;
- completes the change stream on disposal.

## 3. Consequences

Applications can centralize active-slot/focus-mode state without writing a
custom coordinator for each app shell. The primitive deliberately stores keys
only; route tables, child VMs, widgets, and host focus APIs remain consumer
concerns.

## 4. Rejected alternatives

Making this a full container VM was rejected because the downstream use case only
needs active-key coordination, not lifecycle ownership of child VMs.

Hard-coding a `Modal` enum value was rejected; consumers choose their own key
type and modal key.
