# ADR 0056 — v3 async command cancellation aligned with the dialog cancellation contract

**Status:** Accepted (2026-06-28)
**Spec version:** 3.0.0

## 1. Context

The v3 framework overhaul reconciles the spec with the command-cluster findings of
the merged framework critique (`docs/audit/2026-06-27-vmx-merged-critique.md`).

**VMX-052** (spec + all flavors) — there is **no async-command cancellation /
`IAsyncCommand`**. The base `RelayCommand` task (chapter 04 §3) is a synchronous
`Action`/`Callable[[], None]`/`() => void`; a long-running async operation kicked
off by a command therefore has **no cancellation channel**. This is asymmetric:
`IDialogService` already defines a cancellation contract (chapter 19 §7, `DIA-007`)
whose defining property is that a cancelled pending call **completes with the safe
default rather than throwing** unless the implementation opts into a throwing mode.
A command's long-running task had no equivalent.

The audit scoped this as effort **L** with the recommendation: "add an
`IAsyncCommand` with cancellation aligned with the dialog story."

## 2. Decision

Add an **async, cancellable command** — `IAsyncCommand` and its concrete
`AsyncRelayCommand` — to the three full-parity flavors (C#, Python, TypeScript),
specified normatively in chapter 04 §10. The existing synchronous, non-cancellable
`RelayCommand` (§5) is unchanged; the async command is **additive**.

### 2.1 Contract and the per-flavor cancellation channel (ADR-0006)

`IAsyncCommand` extends `ICommand` with `IsExecuting`, an awaitable
`ExecuteAsync(parameter?, cancellation?)`, and `Cancel()`. The task receives the
idiomatic cancellation primitive per flavor, keeping the conceptual shape identical
(ADR-0006) while the surface is idiomatic:

| Flavor     | Task shape                            | Cancel channel            | `cancel()` mechanism      |
| ---------- | ------------------------------------- | ------------------------- | ------------------------- |
| C#         | `Func<CancellationToken, Task>`       | `CancellationToken`       | `CancellationTokenSource` |
| Python     | `Callable[[], Awaitable[None]]`       | asyncio task cancellation | `task.cancel()`           |
| TypeScript | `(signal: AbortSignal) => Promise<…>` | `AbortSignal`             | `AbortController.abort()` |

Python threads no explicit token: asyncio delivers cancellation by raising
`CancelledError` at the task's next await point, which is the idiomatic shape. The
channel is linked to both `Cancel()` and any external cancellation token/signal
passed to `ExecuteAsync`.

`AsyncRelayCommand` is built via the same immutable fluent builder (BLD-001) as
`RelayCommand`, with an added `ThrowOnCancel()` setter (§2.3).

### 2.2 In-flight state reflected in `CanExecute`

While an execution is in flight, `CanExecute` returns `false`, so the command
**cannot double-run** — a second `Execute`/`ExecuteAsync` is gated out as a no-op.
`CanExecuteChanged` fires when the in-flight state flips (on start and on
completion — success, cancel, or fault), and `IsExecuting` exposes the flag for
binding. This is the chapter 04 §4 trigger contract applied to the command's own
lifecycle, so a bound control's enabled state tracks the run.

### 2.3 Cancellation is non-throwing by default (DIA-007 alignment)

`Cancel()` cancels the in-flight task. By default the awaited `ExecuteAsync`
**completes normally** rather than surfacing the flavor's cancellation exception
(`OperationCanceledException` / `asyncio.CancelledError` / `AbortError`) — exactly
the `DIA-007` rule (chapter 19 §7): cancellation completes with the safe default,
not a throw. A flavor MAY opt into a throwing mode via the builder's
`ThrowOnCancel()`, mirroring the `DIA-007` opt-in clause. Either way the command
returns to the non-executing state (`IsExecuting == false`).

Only a cancellation requested through the command's own channel is swallowed by the
default mode; an externally-originated cancellation of the `ExecuteAsync` call
itself is re-raised so the flavor's cancellation semantics are preserved.

### 2.4 Task faults route like the existing v3 error channels

A non-cancellation fault is not swallowed. Awaiting `ExecuteAsync` propagates it
to the awaiter (parity with `RelayCommand`'s throwing task, §3); the synchronous
fire-and-forget `Execute` — which has no caller to propagate to — routes it to an
`errors` observable (`Errors` / `errors`) rather than leaving an unobserved
faulted task / unhandled rejection. This reuses the pattern ADR-0049 set for
`ConfirmationDecoratorCommand` and ADR-0048 set for `FormVM`.

## 3. Consequences

- `04-commands.md` gains §10 (async command cancellation); the prior §10
  Conformance is renumbered §11 (the ADR-0049 cross-reference is updated).
- The catalog gains **`CMD-012`** (cancel cancels an in-flight async task; the
  command returns to a non-executing state; no exception surfaces by default),
  implemented as a real passing test in all three full-parity flavors — plus an
  opt-in-throwing assertion carrying the same ID. Catalog library total: 236 → 237
  (241 → 242 including the 5 THEME scenario IDs).
- New public surface (additive): C# `IAsyncCommand` / `AsyncRelayCommand` /
  `AsyncRelayCommandBuilder`; Python `AsyncRelayCommand` / `AsyncRelayCommandBuilder`
  (exported from `vmx.commands` and top-level `vmx`); TypeScript `IAsyncCommand` /
  `AsyncRelayCommand` / `AsyncRelayCommandBuilder`.
- At the time of this ADR Swift was the documented subset (ADR-0037) and shipped
  neither the command decorators nor `AsyncRelayCommand`. **Superseded by ADR-0065**
  (2026-06-30, subset manifest retired) and **ADR-0076** (async-command doc
  reconciliation): Swift now ships `AsyncRelayCommand`, both command decorators, and
  `ModeledCrudCommands`, and `CMD-012` is a full-parity ID covered in all four flavors.
- The coordinated `spec/VERSION` bump to 3.0.0 and per-flavor package version bumps
  are handled by the v3 release task, not here (consistent with ADR-0049); this
  ADR's "Spec version: 3.0.0" records the line the change belongs to.

## 4. Rejected alternatives

- **Add a `CancellationToken` parameter to the synchronous `RelayCommand.Execute`** —
  rejected: `ICommand.Execute` is `void` and synchronous by the chapter 04 §1
  contract; a synchronous body cannot cooperatively observe cancellation of an
  awaited operation. A distinct async command keeps the base contract intact and
  additive.
- **Throw on cancel by default** — rejected: it diverges from `DIA-007`, the
  framework's existing cancellation contract, and forces every caller into a
  try/catch for the ordinary "user cancelled" path. Non-throwing-by-default with an
  explicit opt-in throwing mode matches the dialog story and keeps callers simple.
- **Swallow task faults on the fire-and-forget path** — rejected for the same
  reason ADR-0049 rejected it for `ConfirmationDecoratorCommand`: a swallowed fault
  is invisible to the owner and (in TypeScript) becomes a fatal unhandled rejection.
  The `errors` observable scopes the fault to the command's owner.
- **Ship `AsyncRelayCommand` in Swift now** — deferred: Swift is a documented subset
  (ADR-0037) that ships neither the command decorators nor `ModeledCrudCommands`;
  adding the async command is folded into the Phase 3 Swift full-parity work, not
  this change.
