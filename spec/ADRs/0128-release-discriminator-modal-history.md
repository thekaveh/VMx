# ADR 0128 — Release DiscriminatorVM modal history on non-modal transitions

- **Status:** Accepted
- **Date:** 2026-07-25
- **Spec version:** 3.23.0

## 1. Context

`DiscriminatorVM` stores prior active keys when `ModalOpen` enters nested modal
states. Before this decision, `SetActiveKey` changed the active key without
releasing that private history. A consumer that left a modal through an
ordinary navigation action could not inspect or drain the retained frames, so a
later `ModalClose` restored stale state and repeated transitions grew the stack
without bound.

The modal stack is internal ownership state. Consumers must not need a parallel
depth counter or a loop of synthetic closes merely to abandon it.

## 2. Decision

1. Public non-modal active-key setters release all saved modal frames before
   evaluating whether the requested key changes the active key. A same-key call
   remains notification-free but still abandons modal history.
1. Modal open and close use an internal active-key transition that preserves
   the remaining stack. Nested modal close therefore retains LIFO restoration.
1. `ModalDepth` exposes the number of saved frames as a read-only value.
1. `ClearModals` releases every saved frame without changing the active key or
   publishing an active-key change.
1. Disposal releases modal frames before completing the change stream.

Per-flavor names remain idiomatic. This decision adds `DISC-007..DISC-009`.

## 3. Consequences

Non-modal navigation cannot leave stale restoration history. Consumers can
assert modal-state ownership and explicitly abandon history without reaching
into implementation details. Existing key-only modal open/close calls remain
source-compatible, and nested modal behavior is unchanged.

The optional payload-bearing modal-frame proposal remains separate. Adding
payload storage changes generic surface and close-result shape; it is not
required to correct history ownership.

## 4. Rejected alternatives

- **Only expose depth:** observation would detect the leak but still require a
  consumer drain loop.
- **Only add `ClearModals`:** callers could still unknowingly retain history on
  an ordinary non-modal transition.
- **Implement `ModalClose` through the public setter:** the public setter must
  abandon history, so using it for modal restoration would destroy older nested
  frames.
