# ADR 0018 — Flat VM hierarchy vs. the 2012 inheritance chain

**Status:** Accepted (2026-05-25)
**Spec version:** 2.0.0 (teaching ADR; no code change)

## 1. Context

The 2012 VMx predecessor stacked a deep inheritance chain:

```
Unit                               # lifecycle + finalizer + disposables
  └── ObservableBase               # INotifyPropertyChanged + Expression<>-based RaisePC
        └── Component<C>           # MEF [Import] + RegisterProperty + service locator
              └── VMBase<VM,C,P>   # commands, properties, parent/composition typing
                    └── CompositionBase   # selection / search / IList / iter
```

Three generic type parameters threaded through `VMBase<VM, C, P>` (self,
composition, parent) and four through the modeled variant
`VMBase<M, VM, C, P>`. Every consumer of the framework — including the
test fixtures — inherited some piece of this chain.

The current VMx (v1.x) replaced that chain with a flatter hierarchy:

```
IComponentVM (interface)
  └── ComponentVMBase (abstract)
        ├── ComponentVM
        ├── ComponentVM<M>
        ├── ReadonlyComponentVM<M>
        ├── CompositeVM<VM>
        ├── CompositeVM<M, VM>
        ├── GroupVM<VM>
        └── AggregateVM1..5
```

A single abstract base; no service locator; constructor injection (per
ADR-0003); message hub instead of expression-based `RaisePropertyChanged`.
Capability concerns (cycle 1) layer in additively via opt-in interfaces
rather than via inheritance.

The absorption goal asked for "best-effort" capture of the predecessor's
philosophy. This ADR is that capture — a teaching note explaining what was
intentionally NOT brought forward and why.

## 2. Decision

The flat hierarchy is the v2.0 baseline. The chain is documented here for
historical reference; no code change accompanies this ADR.

### 2.1 What we did NOT bring forward, and why

| Predecessor concept                      | Status in v2.0 | Reason                                                                                                                                                                           |
| ---------------------------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Unit` base class                        | Rejected       | Merged into `ComponentVMBase`. Finalizer is unnecessary in modern .NET / Python / TS.                                                                                            |
| `ObservableBase` with `Expression<Func>` | Rejected       | Replaced by the message hub (ADR-0002). Expression-based notifications add startup cost without runtime benefit when the hub already routes by type.                             |
| `Component<C>` with `[Import]`           | Rejected       | Service locator rejected by ADR-0003. Constructor injection covers every legitimate use.                                                                                         |
| `VMBase<VM, C, P>` generic chain         | Rejected       | Three+ type params per VM made consumer code hard to read. The current `ComponentVMBase` is non-generic; concrete types parameterize only where needed (e.g., `ComponentVM<M>`). |
| `CompositionBase<M, VM, C, P>`           | Replaced       | Modern `CompositeVM<M, VM>` has two type params (model, VM) and no chain. Selection/CRUD/search now compose via cycle 7/8 helpers rather than inheriting from a base.            |

### 2.2 What we DID bring forward, in adapted form

| Predecessor concept                                                  | Modern equivalent                                                                                                                            |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `Construct/Destruct/Reconstruct/Dispose` lifecycle                   | `IComponentVM.Construct/Destruct/Reconstruct/Dispose` (cycle 1 capability interfaces); enforced by the lifecycle state machine in chapter 02 |
| `TransformationProperty` derived values                              | `DerivedProperty<TValue>` (cycle 3) with N source observables                                                                                |
| Capability micro-interfaces (`ISelectable` etc.)                     | Same names, now opt-in additively (cycle 1)                                                                                                  |
| `CompositeCommand`/`DecoratorCommand`/`ConfirmationDecoratorCommand` | Same names, modern semantics (cycle 4)                                                                                                       |
| `NotificationService`                                                | `INotificationHub` in opt-in sub-package (cycle 5)                                                                                           |
| `SearchTerm` / `SearchPredicate` on composite                        | `SearchableState<TItem>` helper, opt-in (cycle 7)                                                                                            |
| `IsExpanded` / `Expand` / `Collapse` on every VM                     | `ExpandableState` helper, opt-in (cycle 6)                                                                                                   |
| `CreateNewCommand` / `DeleteCurrentCommand` etc.                     | `ModeledCrudCommands<M, VM>` helper, opt-in (cycle 8)                                                                                        |
| `NullMessagingService`                                               | `NullMessageHub` + the broader null-object convention (cycle 2)                                                                              |

## 3. Consequences

- No code change in this cycle; the ADR is documentation.
- Consumers migrating from a hypothetical legacy-VMx project can use the
  mapping table to find the modern equivalent of each predecessor concept.
- Future ADRs are free to revisit any individual decision in the "Rejected"
  column if a strong concrete need emerges; the current ADR is descriptive
  of v2.0 reality, not prescriptive against future change.
- The chain-vs-flat decision is the cycle's "best-effort" absorption of
  the predecessor's philosophy — captured rather than restored.
