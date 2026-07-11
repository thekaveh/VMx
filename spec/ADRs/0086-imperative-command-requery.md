# ADR 0086 — Expose imperative command re-evaluation notifications

**Status:** Accepted (2026-07-10)
**Spec version:** introduced in 3.6.0

## 1. Context

Relay commands already expose `CanExecuteChanged` and accept reactive trigger
streams. Trigger wiring is the preferred declarative path when predicate inputs
are observable. A predicate may also close over host state that has no reactive
stream, however. In that case a binding layer can only poll `CanExecute` during
unrelated renders or rebuild the command.

Rust exposes `trigger_can_execute_changed` on synchronous relay commands, but
the name differs from the classic MVVM raise terminology and the other four
flavors have no public equivalent. The C# built-in relay builders also erase
their build result to `ICommand`, which would hide a concrete-only method.

## 2. Decision

The concrete notification-owning command types expose one flavor-idiomatic
imperative re-evaluation method:

| Concept                         | C#                         | Python                        | TypeScript                 | Swift                      | Rust                          |
| ------------------------------- | -------------------------- | ----------------------------- | -------------------------- | -------------------------- | ----------------------------- |
| Imperative re-evaluation notice | `RaiseCanExecuteChanged()` | `raise_can_execute_changed()` | `raiseCanExecuteChanged()` | `raiseCanExecuteChanged()` | `raise_can_execute_changed()` |

The method is present on `RelayCommand`, the parameterized relay command, and
`AsyncRelayCommand`. One live call publishes exactly one notification on the
existing `CanExecuteChanged` channel. It does not invoke or pre-evaluate the
predicate, invoke the task, start an execution, or carry a value. Repeated calls
are additive. A call after disposal is a no-op and MUST NOT publish or raise.

An async command accepts the call while idle or in flight. An in-flight call is
one additional notification between the existing execution-start and
execution-completion notifications; all three use the same channel. Rust gains
the already-normative async execution-state notifications as part of proving
this additive sequence.

Triggers remain the preferred representation for observable dependencies. The
imperative method is the escape valve for non-observable host state or explicit
binding invalidation. Trigger, execution-state, and imperative notifications do
not coalesce one another.

Core command interfaces and protocols do not gain the method. Composite and
decorator commands continue to forward inner notification streams but do not
claim ownership of an imperative raise operation. A caller that decorates a
relay and needs imperative invalidation retains the owning relay reference.

Rust keeps `trigger_can_execute_changed()` on both synchronous relay variants as
a source-compatible alias to `raise_can_execute_changed()`. C# keeps the public
`ICommandBuilder` interfaces unchanged; the built-in builders return concrete
relay commands covariantly so the new method is available without a cast.

Six conformance IDs (`CMD-014..019`) cover live, repeated/trigger-additive,
disposed, parameterized, async-idle, and async-in-flight calls.

## 3. Consequences

- Binding layers can subscribe precisely instead of polling all predicates on
  unrelated renders.
- Existing trigger-based applications remain source- and behavior-compatible.
- Decorators and composites retain a truthful minimal command contract rather
  than exposing a method they cannot independently honor.
- The specification and stable flavors advance to 3.6.0; pre-1.0 Rust advances
  to 0.6.0.

## 4. Rejected alternatives

### 4.1 Add the method to every command interface

Rejected. A decorator or composite forwards a channel owned by its inner
commands but cannot identify which closed-over predicate dependency changed.
Adding the method would advertise synthetic behavior with unclear ownership.

### 4.2 Add a separate optional capability interface

Rejected for now. The three concrete relay families already form a small,
discoverable ownership boundary. A new cross-cutting capability would add casts
and protocol surface without improving the normal builder result.

### 4.3 Rebuild commands when host state changes

Rejected. Rebuilding replaces subscription identity and lifecycle ownership for
what is only a re-evaluation notification.

### 4.4 Poll `CanExecute` from every render

Rejected. Polling couples command correctness to a global refresh mechanism and
scales with commands multiplied by renders rather than actual dependency
changes.
