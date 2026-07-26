# 22 — `DiscriminatorVM<TKey>`

A small **single-active-key coordinator**. Use it when a VM needs one source of
truth for an active slot, pane, route, mode, or focus target.

## 1. Overview

`DiscriminatorVM<TKey>` owns one `ActiveKey` and emits changes when that key
changes. It is intentionally generic over the key type: strings, enums, and small
domain value objects are all valid as long as the flavor can compare them for
equality.

The primitive also includes modal precedence helpers. Opening a modal pushes the
current active key and activates the modal key; closing restores the prior key in
last-in-first-out order. An ordinary non-modal active-key transition abandons
all saved modal history.

## 2. Shape

```
DiscriminatorVM<TKey>:
    ActiveKey     : TKey
    ActiveChanged : observable<TKey>
    ModalDepth    : integer

    IsActive(key: TKey) -> bool
    SetActiveKey(key: TKey) -> void
    ModalOpen(modalKey: TKey) -> void
    ModalClose() -> void
    ClearModals() -> void
    Dispose() -> void
```

Per-flavor names follow ADR-0006 (`active_key` / `activeKey`,
`set_active_key` / `setActiveKey`, etc.).

## 3. Semantics

- Construction sets the initial active key.
- `SetActiveKey` is a non-modal transition. It releases every saved modal frame
  before comparing keys.
- Setting the same key emits nothing but still releases modal history.
- Setting a different key updates `ActiveKey`, emits the new key, and leaves
  `ModalDepth == 0`.
- `ModalOpen(modalKey)` remembers the previous active key and activates
  `modalKey`; `ModalDepth` increases by one.
- `ModalClose()` restores the most recently saved key. Calling it with no open
  modal is a no-op; a successful close decreases `ModalDepth` by one.
- Nested modal opens restore in LIFO order.
- `ClearModals()` releases every saved frame without changing `ActiveKey` or
  emitting through `ActiveChanged`.
- `Dispose()` releases saved frames, completes the change stream, and makes
  later mutations no-ops.

This primitive does not own child VMs or routes. Consumers can store route
tables externally and ask `IsActive(routeKey)` when projecting behavior.

## 4. Conformance

- `DISC-001` — initial active key and `IsActive`.
- `DISC-002` — changing the active key emits one change.
- `DISC-003` — setting the same key is a no-op.
- `DISC-004` — opening a modal activates the modal key.
- `DISC-005` — closing a modal restores the prior key.
- `DISC-006` — nested modal precedence restores in LIFO order.
- `DISC-007` — modal depth tracks frames and disposal releases them.
- `DISC-008` — explicit clear drains without changing the active key.
- `DISC-009` — a non-modal set abandons history, including for the active key.

Repeated disposal follows the framework-wide invariant in `01-concepts.md`
§4: the change stream completes at most once and later mutations remain no-ops.
