# 10 — Builders

Every VMx VM and command is constructed via a fluent immutable builder. This document
describes the shared builder semantics; specific builder fields are documented in
each VM's spec file.

## 1. Immutability

A builder is immutable. Every setter returns a NEW builder instance with the updated
field. Example pseudo-code:

```
b1 = ComponentVM<M>.Builder()
b2 = b1.Name("user-vm")
b1 == b2  ?  # false; b2 is a different instance with Name set
```

Implementations MAY use a "frozen dataclass" pattern (Python), a `record`-like value
type (C#), or any structurally-immutable construct.

## 2. Fluent flow

```
ComponentVM<M>.Builder()
    .Name("user-vm")
    .Hint("Logged-in user")
    .Type(ViewModelType.Component)   // optional; derived from VM class if omitted
    .Parent(parentComposite)
    .Model(currentUser)
    .ModeledHinter(u => $"User: {u.DisplayName}")
    .OnModelChanged(m => Console.WriteLine($"model changed to {m.Id}"))
    .Services(messageHub, dispatcher)
    .Build()
```

Order of fluent calls is irrelevant. Repeated calls to the same setter overwrite
the prior value (e.g., calling `.Name("a").Name("b")` results in `Name == "b"`).
The one exception is additive setters like `Triggers` on `RelayCommand` — see
`04-commands.md`.

## 3. Validation

`Build()` MUST validate required fields:

| VM type                                                                        | Required fields                                                                                                                 |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| `ComponentVM`, `ReadonlyComponentVM`, `CompositeVM`, `GroupVM`, `AggregateVMN` | `Name`, `Services(IMessageHub, IDispatcher)`                                                                                    |
| `ComponentVM<M>`, `ReadonlyComponentVM<M>`, `CompositeVM<M, VM>`               | additionally: a model source (model setter for modeled; `Model(...)` for readonly; `ChildrenModels(...)` for modeled composite) |
| `CompositeVM<VM>`, `GroupVM<VM>`                                               | additionally: `Children(() -> ...)` factory                                                                                     |
| `AggregateVMN`                                                                 | additionally: every `ComponentI` factory for `I = 1..N`                                                                         |
| `RelayCommand`, `RelayCommand<T>`                                              | (no required fields; a no-op command is valid)                                                                                  |

If a required field is missing, `Build()` raises a `BuilderValidationError`
(Python / TS) / `BuilderValidationException` (C#, sealed subclass of
`InvalidOperationException`) whose message identifies the missing field.

## 4. Default values

Optional fields have these defaults if not set:

- `Hint` → empty string
- `Type` → derived from the VM class (e.g., `Composite` for `CompositeVM.Builder()`)
- `Parent` → null
- `AsyncSelection` → false (composites only)
- `Background` → `false` (any VM; enables async `construct()`/`destruct()` on `IDispatcher.Background`)
- `OnConstruct`, `OnDestruct` → no-op callbacks
- `ModeledHinter` → `(m) -> ""` (modeled variants only)
- `OnModelChanged` → no-op callback (modeled variants only)
- `Predicate` (commands) → returns `true`
- `Task` (commands) → no-op
- `Triggers` (commands) → empty set

## 5. Repeated identical calls

Calling `Build()` twice on the same fully-configured builder MUST produce two VMs
that are functionally equivalent (the SAME `Name`, same `Hint`, same wired services,
etc.) but DISTINCT instances. Builders themselves are reusable.

## 6. Conformance

`BLD-001` through `BLD-004` in `12-conformance.md` cover:

- setter returns a new builder instance
- required fields validated on `Build()`
- repeated identical calls produce equivalent VMs
- field defaults applied when not set
