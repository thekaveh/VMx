# 04 — Commands

VMx commands implement an `ICommand`-style interface and use Rx for reactive
re-evaluation of `CanExecute`.

## 1. Command contract

```
ICommand:
    CanExecute() : bool
    Execute() : void
    CanExecuteChanged : event  / IObservable<Unit>
```

A parameterized variant accepts a typed parameter:

```
ICommand<T>:
    CanExecute(parameter: T) : bool
    Execute(parameter: T) : void
    CanExecuteChanged : event  / IObservable<Unit>
```

## 2. Predicate semantics

A command is built with an optional `predicate` (`() -> bool` or `(T) -> bool`):

- If `predicate` is null/absent, `CanExecute` returns `true` unconditionally.
- If `predicate` is present, `CanExecute` returns its result.
- The predicate MUST NOT raise. If it does, the language flavor MAY treat the result
  as `false` (defensive) but MUST NOT propagate the exception to the caller.

## 3. Task semantics

A command is built with an optional `task` (`() -> void` / `Action` or `(T) -> void`):

- If `task` is null/absent, `Execute` is a no-op (returns immediately, does not raise).
- If the configured predicate returns `false`, `Execute` MUST NOT invoke the task and returns
  as a no-op. (This matches `fixtures/command-truthtable.json` row `predicate-false`.)
- If `task` is present, `Execute` invokes it.
- The task MUST NOT raise; if it does, the exception propagates to the caller of
  `Execute`. The exception is the application's responsibility, not the command's.

## 4. Triggers

A command MAY be built with one or more `triggers` (`IObservable<Unit>`). On each
emission of any trigger, the command:

1. Re-evaluates `CanExecute`.
1. Fires `CanExecuteChanged` (the consumer-facing event/observable).

Triggers do NOT carry data — only the fact that re-evaluation should happen. The
typical pattern: derive a trigger from a property's change stream
(`vm.Status.Where(s => s == Constructed).Select(_ => Unit.Default)`).

### 4.1 Recipe: trigger from a hub property change

A common pattern is firing `CanExecuteChanged` whenever a specific ViewModel
property changes. Compose the hub's `Messages` stream (or the per-flavor
`PropertyValueChangedMessagesFor` convenience helper) as the trigger:

```
# C# — filter the hub stream and project to Unit
hub.Messages
   .OfType<PropertyChangedMessage<TSource>>()
   .Where(m => ReferenceEquals(m.Sender, this) && m.PropertyName == nameof(IsValid))
   .Select(_ => Unit.Default)

# Python — triggers accept Observable[object]; any emission suffices
hub.messages.pipe(
    ops.filter(lambda m: isinstance(m, PropertyChangedMessage)
                         and m.sender is self
                         and m.property_name == "is_valid")
)

# TypeScript — same idea
hub.messages.pipe(
    filter(m => m instanceof PropertyChangedMessage
             && m.sender === this
             && m.propertyName === "isValid"),
)
```

No new helper is needed — the existing `triggers` parameter and the
`Messages`/`messages` stream compose naturally.

### 4.2 Recipe: selection-driven `CanExecute` (spec v3, ADR-0049)

A command whose `CanExecute` depends on a mutable provider — most notably one
gated on "is something currently selected" — has no way to refresh a bound
control's enabled state unless a trigger fires `CanExecuteChanged` when that
provider changes. A predicate alone is insufficient: per §4, `CanExecuteChanged`
fires **only** on a trigger emission, never on its own.

The canonical case is `ModeledCrudCommands` (chapter 06 §7): its
`UpdateCurrentCommand` / `DeleteCurrentCommand` predicates read `current != null`,
so they MUST be wired with a current-changed trigger derived from the owning
composite's current-selection stream:

```
# the composite's current-changed stream, projected to Unit, becomes the trigger
currentChanged = composite.OnCurrentChanged.Select(_ => Unit.Default)
update = RelayCommand.Builder()
    .Task(() => update(current()))
    .Predicate(() => current() != null)
    .Triggers(currentChanged)        // ← without this, the button never refreshes
    .Build()
```

Absent the trigger, the predicate's value goes stale: the button enables on
construction (or never) and never tracks the selection. See chapter 06 §7 for
the normative `ModeledCrudCommands` contract.

## 5. RelayCommand

`RelayCommand` is the concrete `ICommand` implementation, built via a fluent
immutable builder:

```
RelayCommand.Builder()
    .Task(() => ...)         // optional
    .Predicate(() => ...)    // optional
    .Triggers(observable)    // optional, multiple calls allowed
    .Build()
```

`RelayCommand<T>` follows the same pattern with parameterized predicate/task.

Disposing a relay command makes it inert. After disposal:

- `CanExecute` returns `false`, even when no predicate was configured.
- `Execute` is a no-op and MUST NOT invoke the task.
- disposal remains idempotent.

This applies equally to parameterized relay commands. A flavor MAY notify
`CanExecuteChanged` during disposal so bound controls can refresh disabled state;
the normative state is the post-disposal `CanExecute == false` result.

## 6. Builder semantics

- Setters return a NEW builder instance (immutability).
- `Triggers` is additive: multiple `.Triggers(obs)` calls combine all observables
  into the trigger set.
- `Build()` succeeds even with no task, no predicate, and no triggers (yielding a
  command whose `CanExecute` returns `true` and whose `Execute` is a no-op).

## 7. Fixture

`fixtures/command-truthtable.json` encodes five canonical command configurations that
`CMD-NNN` conformance tests load. Each row encodes: predicate value, task presence,
trigger behavior, expected `CanExecute` return, whether `Execute` invokes the task,
and whether `CanExecuteChanged` fires.

## 8. Decorators (spec v2.0)

Three decorator commands wrap one or more inner commands, layering additional
behavior on top. All three implement `ICommand` and may themselves be composed
arbitrarily.

### 8.1 `CompositeCommand`

Aggregates N inner commands. The composite's behavior:

- `CanExecute` returns `true` iff at least one inner command's `CanExecute` returns
  `true`.
- `Execute` invokes every inner command whose `CanExecute` currently returns `true`.
  Inner commands whose `CanExecute` returns `false` are skipped.
- `CanExecuteChanged` fires on any inner command's `CanExecuteChanged`.

### 8.2 `DecoratorCommand`

Wraps a single inner command, layering pre/post actions and an extra can-execute
gate.

- `CanExecute` returns `inner.CanExecute() && (extraPredicate?.Invoke() ?? true)`.
- `Execute`:
  1. If `CanExecute` returns `false`, returns immediately (no pre/post invoked).
  1. Invokes the optional pre-execution action.
  1. Invokes `inner.Execute()`.
  1. Invokes the optional post-execution action.
- `CanExecuteChanged` fires when `inner.CanExecuteChanged` fires.

### 8.3 `ConfirmationDecoratorCommand`

Wraps a single inner command, gating `Execute` on a user-confirmation delegate.

- Construction takes the inner command and a `confirm` delegate of shape
  `() -> Task<bool>` (or per-language async-Boolean equivalent).
- `CanExecute` returns `inner.CanExecute()`.
- `Execute` invokes `confirm()`. If the awaited result is `true`, calls
  `inner.Execute()`. If `false`, does nothing.

Per ADR-0012, the confirmation delegate is intentionally generic — it does NOT
depend on the notification service (chapter 16). Consumers may bridge it to
`INotificationHub` via an optional helper in the notifications sub-package.

#### 8.3.1 Async gating and the `errors` channel (spec v3, ADR-0049)

The `confirm` delegate is asynchronous (`() -> Task<bool>`) while the
`ICommand.Execute` contract is synchronous and returns `void` (§1). The
synchronous `Execute` therefore realizes the confirm gate as a **fire-and-forget
continuation**: it schedules the `confirm()` → `inner.Execute()` flow and returns
immediately, before the gate has resolved. Each flavor also exposes an awaitable
`ExecuteAsync()` (`execute_async` / `executeAsync`) entry-point that runs the same
flow and can be awaited to sequence it inline.

Because the synchronous `Execute` has already returned, a `confirm` delegate that
rejects/raises and an `inner.Execute()` that throws have **no caller to propagate
to** — unlike the base `RelayCommand`, whose throwing task propagates to the
caller of `Execute` (§3). Such a failure MUST NOT be silently swallowed. The
decorator surfaces it on an `errors` observable instead:

- `errors` (`Errors` / `errors`) is an `Observable` that emits the exception
  raised by either the `confirm` delegate or the throwing `inner.Execute()`,
  when the failure arrives via the fire-and-forget `Execute` path.
- The awaitable `ExecuteAsync()` path keeps the ordinary throw/reject behavior —
  awaiting it propagates the failure directly, so the error is NOT additionally
  re-emitted on `errors` for callers that await.
- `errors` completes when the decorator is disposed; emitting after dispose is a
  no-op (it MUST NOT raise).

This mirrors the `FormVM` approve-error channel (chapter 20 §8, ADR-0048): a
fire-and-forget command entry-point routes a failure that cannot propagate to a
dedicated error observable rather than discarding it.

> **Cross-flavor parity (ADR-0006/ADR-0049).** The `errors` channel is normative
> in every flavor that ships `ConfirmationDecoratorCommand` (C#, Python,
> TypeScript). Swift does not ship the command decorators and is therefore out of
> scope. The decorator's `errors` channel is exercised by `CMDD-010`.

## 9. Fluent composition (spec v2.1)

Four fluent helper methods provide ergonomic shortcuts over the decorator
constructors introduced in §8. Per ADR-0027, these are normative API in every
active flavor. All four are pure convenience — they produce exactly the same
object graph as the equivalent explicit constructor call.

Per-flavor surface (ADR-0006): C# exposes them as static extension methods on
`ICommand`; Python as module-level functions; TypeScript as named exports.

### 9.1 `Confirm(confirm)`

```
cmd.Confirm(confirm)
  ≡ new ConfirmationDecoratorCommand(cmd, confirm)
```

`confirm` is a delegate of shape `() -> Task<bool>` (async-Boolean per flavor).
An optional second overload accepts an `INotificationHub` and constructs the
delegate via the bridge helper in the notifications sub-package; that
overload is defined in the sub-package, not in the core commands module.
The overload is C#-only; Python and TypeScript use the explicit two-step
composition `command.confirm(make_confirm(hub, prompt))` /
`command.confirm(makeConfirm(hub, prompt))` instead — see ADR-0009
§"Fluent `Confirm` overload with `INotificationHub`".

### 9.2 `PrecedeWith(other)`

```
cmd.PrecedeWith(other)
  ≡ new CompositeCommand(other, cmd)
```

`other` executes first; `cmd` executes second.

### 9.3 `SucceedWith(other)`

```
cmd.SucceedWith(other)
  ≡ new CompositeCommand(cmd, other)
```

`cmd` executes first; `other` executes second.

### 9.4 `WrapWith(predicate?, pre?, post?)`

```
cmd.WrapWith(predicate, pre, post)
  ≡ new DecoratorCommand(cmd, pre, post, predicate)
```

The shipped C# / Python `DecoratorCommand` constructor takes
`(inner, preExecute, postExecute, extraPredicate)`; the fluent extension
keeps the user-facing predicate-first ordering for ergonomic reasons and
maps to the constructor's pre/post/predicate positions.

All three arguments are optional/nullable. Passing all defaults is valid and
yields a semantically transparent decorator (no extra gate, no pre/post hooks).

## 10. Async command cancellation (spec v3, ADR-0056)

The base `RelayCommand` task (§3) is synchronous and uncancellable. A
long-running async task therefore had **no cancellation channel**, even though
`IDialogService` already defines one (chapter 19 §6, `DIA-007`). Spec v3 adds an
**async, cancellable command** so an in-flight operation can be cancelled, with
semantics aligned to the dialog cancellation contract.

### 10.1 Contract

```
IAsyncCommand : ICommand
    IsExecuting : bool
    ExecuteAsync(parameter?, cancellation?) : Task / awaitable
    Cancel() : void
```

`AsyncRelayCommand` is the concrete implementation, built via the same immutable
fluent builder pattern as `RelayCommand` (§5/§6):

```
AsyncRelayCommand.Builder()
    .Task(token => ...)      // a cancellable async task
    .Predicate(() => ...)    // optional
    .Triggers(observable)    // optional, multiple calls allowed
    .ThrowOnCancel()         // optional, opt into the throwing mode (§10.3)
    .Build()
```

The task receives a **cancellation channel** appropriate to the flavor (chapter
11): a `CancellationToken` (C#), idiomatic asyncio task cancellation — a
`CancelledError` raised at the next await point — (Python), an `AbortSignal`
(TypeScript), or Swift `Task` cancellation. The channel is linked to both
`Cancel()` and any cancellation token supplied to `ExecuteAsync` where the
flavor has an explicit caller-supplied token.

### 10.2 In-flight state and `CanExecute`

- While an execution is in flight, `CanExecute` returns `false`. The command
  therefore **cannot double-run**: a second `Execute`/`ExecuteAsync` while one is
  pending is gated out and returns as a no-op (§3).
- `CanExecuteChanged` fires when the in-flight state flips — once when execution
  starts and once when it completes (whether by success, cancellation, or fault) —
  so a bound control's enabled state tracks the in-flight state.
- `IsExecuting` exposes the in-flight flag for direct binding.

### 10.3 Cancellation is non-throwing by default

`Cancel()` requests cancellation of the in-flight task. By default this is
**non-throwing to the caller**, matching `IDialogService` cancellation
(`DIA-007`, chapter 19 §6): the awaited `ExecuteAsync` **completes normally** on
cancel rather than surfacing an `OperationCanceledException` /
`asyncio.CancelledError` / `AbortError`. After a cancel the command returns to a
non-executing state (`IsExecuting == false`, `CanExecute == true` once any
predicate again permits it).

A flavor MAY opt into a **throwing mode** (the builder's `ThrowOnCancel()`):
when enabled, a cancelled `ExecuteAsync` surfaces the flavor's cancellation
exception to the awaiter instead of completing normally. This mirrors the
`DIA-007` opt-in clause: non-throwing is the default, throwing is explicitly
requested. Either way, the command still returns to the non-executing state.

A cancellation requested through the command's own channel is the only failure
swallowed by the default mode. An **externally-originated** cancellation (e.g. the
host event loop tearing down the `ExecuteAsync` call itself) is re-raised so the
flavor's cancellation semantics are preserved.

### 10.4 Task faults vs cancellation

A task that faults for a non-cancellation reason is **not** swallowed:

- Awaiting `ExecuteAsync` propagates the fault directly to the awaiter (parity
  with `RelayCommand`'s throwing task, §3).
- The synchronous fire-and-forget `Execute` (§3) — which has already returned and
  has no caller to propagate to — routes the fault to an **`errors`** observable
  (`Errors` / `errors`) instead of discarding it (an unobserved faulted task /
  unhandled rejection). Cancellations never reach this channel. `errors` completes
  on dispose. This mirrors the `ConfirmationDecoratorCommand` error channel (§8.3.1,
  ADR-0049) and the `FormVM` approve channel (chapter 20 §8, ADR-0048).

### 10.5 Cross-flavor parity (ADR-0006 / ADR-0056)

`AsyncRelayCommand` / `IAsyncCommand` is normative in all four full-parity
flavors (C#, Python, TypeScript, Swift); the cancellation channel is the
idiomatic primitive per flavor (`CancellationToken` / asyncio cancellation /
`AbortSignal` / Swift `Task` cancellation) and the conceptual shape is
identical. Swift's implementation uses Swift structured concurrency for the
cancellable body and Combine for the `canExecuteChanged` / `errors` channels
(ADR-0076).

## 11. Conformance

`CMD-001` through `CMD-013` and `CMDD-001` through `CMDD-010` in
`12-conformance.md` cover:

- `Execute` invokes the configured task
- `CanExecute` returns `true` with no predicate, and the predicate result otherwise
- trigger emissions fire `CanExecuteChanged`
- parameterized variant passes the parameter through
- null task is a no-op (no exception)
- `Execute` is a no-op when the predicate returns `false`
- table-driven configurations from `fixtures/command-truthtable.json`
- `CMD-008..CMD-011` — each fluent method produces an equivalent object graph
- `CMD-012` — `AsyncRelayCommand.Cancel()` cancels an in-flight async task; the
  command returns to a non-executing state (`IsExecuting == false`,
  `CanExecute == true`); no exception surfaces by default (§10, ADR-0056)
- `CMD-013` — disposed relay commands become inert (`CanExecute == false`;
  `Execute` is a no-op) (§5, ADR-0068)
- `CMDD-010` — `ConfirmationDecoratorCommand` surfaces a rejecting `confirm`
  delegate or a throwing inner command on its `errors` channel instead of
  swallowing it (§8.3.1, ADR-0049)
