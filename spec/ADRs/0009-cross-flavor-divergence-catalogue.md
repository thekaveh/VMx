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

The following are **known gaps to address in a future minor/major release** —
documented here so audits don't reopen them prematurely:

- **C# non-modeled `ComponentVM`** (spec/05-component-vm.md §Variants). The
  Python and TypeScript flavors ship both `ComponentVM` (no model) and
  `ComponentVMOf<M>` (modeled). C# only ships `ComponentVM<M>`. C# users wanting
  a model-less leaf currently parameterise as `ComponentVM<object>` or roll
  their own subclass of `ComponentVMBase`. **Target:** add a sealed non-generic
  `ComponentVM` class + builder in C# v1.2.0 (additive, non-breaking).
- **`RelayCommandOfT` rename to `RelayCommandOf`** in Python. The trailing `T`
  is a transliteration of the C# generic parameter that reads awkwardly in
  Python (and is inconsistent with TypeScript's `RelayCommandOf<T>`). Renaming
  is breaking and is deferred to **Python v2.0.0**.
- **`AggregateVMBuilderN` rename to `AggregateVMNBuilder`** in Python (e.g.
  `AggregateVMBuilder1` → `AggregateVM1Builder`). The current name reads as
  "Builder of AggregateVM 1" rather than "Builder for AggregateVM1". Breaking;
  deferred to **Python v2.0.0**.
- **`ConstructionStatusChangedMessage.sender` (typed) vs `senderObject`** —
  C# and Python expose both; TypeScript exposes only `senderObject`. **Target:**
  add `sender` typed field to TS v1.2.0 (additive).
- **Vestigial `AsyncSelection` and `Type(ViewModelType)` setters** on
  `ComponentVMBuilder<M>` in C# (and `vm_type` in Python). These are
  per-flavor leftovers from prior iterations; review for removal or move into
  the common surface in v1.2.0.

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
