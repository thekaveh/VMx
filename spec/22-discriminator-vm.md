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
last-in-first-out order.

## 2. Shape

```
DiscriminatorVM<TKey>:
    ActiveKey     : TKey
    ActiveChanged : observable<TKey>

    IsActive(key: TKey) -> bool
    SetActiveKey(key: TKey) -> void
    ModalOpen(modalKey: TKey) -> void
    ModalClose() -> void
    Dispose() -> void
```

Per-flavor names follow ADR-0006 (`active_key` / `activeKey`,
`set_active_key` / `setActiveKey`, etc.).

## 3. Semantics

- Construction sets the initial active key.
- Setting the same key is a no-op and emits nothing.
- Setting a different key updates `ActiveKey` and emits the new key.
- `ModalOpen(modalKey)` remembers the previous active key and activates
  `modalKey`.
- `ModalClose()` restores the most recently saved key. Calling it with no open
  modal is a no-op.
- Nested modal opens restore in LIFO order.
- `Dispose()` completes the change stream and makes later mutations no-ops.

This primitive does not own child VMs or routes. Consumers can store route
tables externally and ask `IsActive(routeKey)` when projecting behavior.

## 4. Conformance

- `DISC-001` — initial active key and `IsActive`.
- `DISC-002` — changing the active key emits one change.
- `DISC-003` — setting the same key is a no-op.
- `DISC-004` — opening a modal activates the modal key.
- `DISC-005` — closing a modal restores the prior key.
- `DISC-006` — nested modal precedence restores in LIFO order.
