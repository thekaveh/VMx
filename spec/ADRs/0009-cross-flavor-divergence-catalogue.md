# ADR 0009 — Cross-flavor divergence catalogue

**Status:** Accepted (2026-05-23)
**Spec version:** introduced in 1.1.0

## Context

ADR-0006 establishes that each language flavor gets an idiomatic public surface:
PascalCase in C#, snake_case in Python, camelCase in TypeScript. In practice
"idiomatic" pulls in more than just casing — exception-vs-error suffixes,
generic-overloading vs name-suffixing, module-level functions vs namespace
classes, BCL event types vs first-class event records. As the implementations
matured, a handful of deliberate divergences accumulated that a cross-flavor
parity audit reasonably flags as drift.

This ADR catalogues those divergences so future audits can distinguish
"deliberate per the spec's idiomatic-flavor stance" from "accidental gap."
Where a divergence is a known asymmetry that will be revisited, it is listed
with a target version.

## Decision

The following asymmetries are **accepted** as direct consequences of
ADR-0006 and require no further action:

| Concept                         | C#                                              | Python                                   | TypeScript                                    | Reason                                                             |
| ------------------------------- | ----------------------------------------------- | ---------------------------------------- | --------------------------------------------- | ------------------------------------------------------------------ |
| Exception suffix                | `…Exception`                                    | `…Error`                                 | `…Error`                                      | `Exception` is the .NET base type; `Error` is Python/JS idiom.     |
| Modeled-variant naming          | `ComponentVM<M>` (generic overload)             | `ComponentVMOf[M]`                       | `ComponentVMOf<M>`                            | C# generics overload by arity; Python/TS lack overloading.         |
| Protocol prefix                 | `IComponentVM` interface                        | `ComponentVMProto` Protocol              | `IComponentVM` interface                      | Python `typing.Protocol` classes conventionally use `…Proto`.      |
| `walk`/`find`                   | `VMx.Tree.Tree.Walk` (static class)             | `vmx.tree.walk` (module function)        | `walk` (top-level)                            | C# lacks free functions; static class is the .NET equivalent.      |
| Lifecycle helper name           | `LifecycleTransitionValidator.Require`          | `vmx.lifecycle.require`                  | `requireTransition`                           | `require` is a reserved global in CommonJS contexts in TS.         |
| `CollectionChanged` event shape | `event NotifyCollectionChangedEventHandler`     | `Observable[CollectionChangedEvent]`     | `Observable<CollectionChangedEvent>`          | C# binds to WPF/MAUI/Avalonia which expect the BCL contract.       |
| `CollectionChangedEvent` record | BCL `NotifyCollectionChangedEventArgs`          | `vmx.collections.CollectionChangedEvent` | `CollectionChangedEvent`                      | Same reason as above; C# defers to the BCL payload.                |
| `MessageHub` parameterisation   | `IMessageHub.Send<TMessage>` (per-call generic) | `MessageHub[Message]` (class-generic)    | `send(message: IMessage)` (no generic)        | Each shape is the most idiomatic for its language's type system.   |
| `BatchUpdate()` return type     | `IDisposable`                                   | `BatchUpdateHandle` (context-manager)    | `BatchUpdateHandle` (TC39 `[Symbol.dispose]`) | `using` in C# accepts any `IDisposable`; named class adds nothing. |
| Async lifecycle methods         | `ConstructAsync()` etc. ship on `IComponentVM`  | Not provided                             | Not provided                                  | See ADR-0008 — TAP is .NET-specific affordance.                    |
| `ViewModelType` casing          | `ViewModelType.Component`                       | `ViewModelType.COMPONENT`                | `ViewModelType.Component`                     | Python convention is ALL_CAPS for enum members.                    |
| `CompositeVM` index-set syntax  | `vm[i] = x` (indexer)                           | `vm[i] = x` (`__setitem__`)              | `setAt(i, x)` (named method)                  | JS lacks operator overloading; named method is the only option.    |
| DI integration                  | `VMx.Extensions.DependencyInjection` companion  | None (manual constructor injection)      | None (manual constructor injection)           | DI ecosystems differ; spec stays unopinionated.                    |

The following are **known gaps to address in a future release** — documented
here so audits don't reopen them prematurely:

- **`RelayCommandOfT` → `RelayCommandOf` rename** in Python. The new name shipped
  as a canonical alias alongside the legacy `RelayCommandOfT` in **vmx v1.2.0**;
  removal of the legacy name is deferred to **vmx v2.0.0** (breaking).
- **`AggregateVMBuilderN` → `AggregateVMNBuilder` rename** in Python (e.g.
  `AggregateVMBuilder1` → `AggregateVM1Builder`). New names shipped alongside
  the legacy ones in **vmx v1.2.0**; removal deferred to **vmx v2.0.0** (breaking).
- **`Type(ViewModelType)` (C#) / `vm_type` (Python) on the modeled
  ComponentVM builder.** Surface intentionally retained as an advanced escape
  hatch — a non-leaf VM (e.g. an aggregate) that internally uses
  `ComponentVMOf<M>` can declare its actual role via this setter. Documented
  here so future audits don't re-flag it as vestigial.

### Resolved in v1.2.0

- C# non-modeled `ComponentVM` class + `ComponentVMBuilder` (additive).
- TypeScript `ConstructionStatusChangedMessage.sender` getter (additive).
- C# `ComponentVMBuilder<M>.AsyncSelection(bool)` removed (dead code; no-op
  on the leaf builder — `CompositeVMBuilder.AsyncSelection` continues to apply).

## Rationale

ADR-0006 already declares the principle; this ADR is its operational catalogue.
Without it, every cross-flavor audit re-discovers the same divergences and asks
"is this a bug?" Locking the deliberate ones into a single table reduces audit
churn. The deferred-rename list keeps known asymmetries visible without forcing
breaking changes in a maintenance pass.

## Consequences

- Future parity audits start with this table as the baseline expectation. Items
  not on it are presumed real drift and worth fixing.
- When a deferred rename comes due, this ADR is updated to remove the moved
  row and a follow-up ADR documents the rename PR.
- Spec text in chapters 03 (messages), 06 (composite-vm), and 13 (tree
  utilities) remains agnostic of these per-flavor shapes — they are framed in
  terms of observable behavior, not method signatures.

## Rejected alternatives

- **Force exact name parity across flavors.** Would either pick a least-common
  denominator (ugly in every flavor) or violate the host language's
  conventions (worse for adoption). Already rejected in ADR-0006.
- **Remove this ADR and rely on per-divergence comments in the code.**
  Inconsistencies would accumulate silently between audits and the rationale
  would scatter across files.
