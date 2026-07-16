# ADR 0106 — Make Rust interactions executor-neutral and awaitable

**Status:** Accepted (2026-07-14)
**Spec version:** introduced in 3.20.1

## 1. Context

The Rust flavor exposed the notification waiter as a current-state lookup,
dialog methods as immediate values, modal completion as an immediate
cancellation fallback, and confirmation delegates as synchronous booleans.
Those shapes passed tests that resolved interactions before reading them, but
could not represent the pending request/response contracts in chapters 04, 16,
and 19. Adding Tokio or another executor solely for these primitives would make
the language-neutral core choose a host runtime.

## 2. Decision

Rust ships `AsyncValue<T>`, a cloneable first-wins completion handle that
implements `Future<Output = T>`, wakes registered wakers, and provides blocking
`wait()` for synchronous hosts. It has no executor dependency.

- `NotificationWaiter` is a future and remains pending until `Resolve` or hub
  disposal completes it.
- `DialogService` methods return `AsyncValue` safe-default results.
- `ModalVm::completion()` returns a pending `AsyncValue` resolved by the first
  dismiss/dispose operation.
- `ConfirmationDecoratorCommand` accepts `Fn() -> AsyncValue<bool>`, preserves a
  fire-and-forget `execute`, and exposes `execute_async` for deterministic
  sequencing.
- `make_confirm` adapts a confirmation notification to the async Boolean guard.

## 3. Consequences

- Rust now models genuinely pending UI interactions without coupling VMx to an
  async runtime.
- Async consumers can use `.await`; synchronous consumers can use `.wait()`.
- Existing immediate null behavior remains available through
  `AsyncValue::ready`.
- The Rust 0.x interaction signatures change and require a package-version bump.

## 4. Rejected alternatives

- Add Tokio: imposes a runtime and feature policy on every consumer.
- Return `JoinHandle<T>`: thread-backed only, not awaitable, and unsuitable for
  host callbacks.
- Keep snapshot getters: cannot satisfy unresolved interaction contracts.
