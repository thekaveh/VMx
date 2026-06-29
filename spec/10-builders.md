# 10 — Builders

Every VMx VM and command can be constructed via a fluent immutable builder. This
document describes the shared builder semantics; specific builder fields are
documented in each VM's spec file. The common leaf/container VMs additionally
offer a positional-options construction form (§7) as an additive shortcut over the
builder — the builder remains the canonical, fully-general path.

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
| `FormVM<TM>`                                                                   | `Initial(TM)`, `Persister(Func<TM, Task>)` (the typed `IFormPersister<TM>` overload is offered via a Wither in C#)              |
| `HierarchicalVM<M, VM>`                                                        | `Model(M)`, `ChildrenFactory(self -> children)`, `Services(IMessageHub, IDispatcher)`                                           |
| `RelayCommand`, `RelayCommand<T>`                                              | (no required fields; a no-op command is valid)                                                                                  |

If a required field is missing, `Build()` raises a `BuilderValidationError`
(Python / TS / Swift) / `BuilderValidationException` (C#, sealed subclass of
`InvalidOperationException`) whose message identifies the missing field.

## 4. Default values

Optional fields have these defaults if not set:

- `Hint` → empty string
- `Type` → derived from the VM class (e.g., `Composite` for `CompositeVM.Builder()`)
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

`BLD-001` through `BLD-005` in `12-conformance.md` cover:

- setter returns a new builder instance
- required fields validated on `Build()`
- repeated identical calls produce equivalent VMs
- field defaults applied when not set
- additive setters (e.g., `Triggers` on `RelayCommand`) retain prior values across
  repeated calls (cumulative, not overwriting)

## 7. Additional construction form — positional options (additive)

The fluent builder's four-call-plus-`Build()` happy path is heavy ceremony for the
trivial case. For the **common VM types** — `ComponentVM` / `ComponentVM<M>`,
`CompositeVM<VM>`, and `GroupVM<VM>` — implementations therefore offer an
**additive positional-options construction form** alongside the builder. The
builder is **not** removed or deprecated; it remains the canonical path and the
only form for the less-common VMs (readonly/modeled-composite/aggregate/form/
hierarchical) until each gains an options form of its own.

Each flavor exposes the form idiomatically:

- **C#** — a static `Create(...)` factory taking an options `record` (`new ComponentVMOptions { Name = …, Hub = …, Dispatcher = …, Model = … }`).
- **Python** — a `create(...)` classmethod taking keyword arguments
  (`ComponentVMOf.create(name=…, hub=…, dispatcher=…, model=…)`).
- **TypeScript** — a static `create(options)` factory taking an options object
  (`ComponentVMOf.create({ name, hub, dispatcher, model })`).
- **Swift** — deferred (Phase 3, tracked with the rest of the Swift full-parity
  work in ADR-0037 / the v3 critique).

The form is **semantically identical** to the builder: implementations MUST route
it through the same builder (or shared validation) so that

1. the **same required fields** are validated — a missing `Name`/`Services`
   (and `Children` for `CompositeVM<VM>`/`GroupVM<VM>`) raises the same
   `BuilderValidationError` / `BuilderValidationException` as `Build()` (§3); and
1. the produced VM is **indistinguishable** from one built via the fluent path
   with the same inputs (same `Name`, `Hint`, `Type`, wired services, model,
   children, callbacks, and lifecycle behaviour).

Required vs optional fields follow the §3 table exactly. The model source on the
modeled `ComponentVM<M>` form is supplied as a normal field/parameter (the "must
call `Model(...)`" requirement is a fluent-path concern); all other required
fields are validated identically to the builder.

This is a public-surface addition only (ADR-0055 / VMX-020). No behaviour of the
existing builders changes, and the equivalence above is covered by per-flavor
construction-equivalence tests rather than a new conformance ID.
