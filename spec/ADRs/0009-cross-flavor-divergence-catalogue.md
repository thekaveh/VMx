# ADR 0009 — Cross-flavor divergence catalogue

**Status:** Accepted (2026-05-23)
**Spec version:** introduced in 1.1.0

## 1. Context

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

## 2. Decision

The following asymmetries are **accepted** as direct consequences of
ADR-0006 and require no further action:

| Concept                                                        | C#                                                                                 | Python                                                               | TypeScript                                                               | Reason                                                                                                                                                                     |
| -------------------------------------------------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Exception suffix                                               | `…Exception`                                                                       | `…Error`                                                             | `…Error`                                                                 | `Exception` is the .NET base type; `Error` is Python/JS idiom.                                                                                                             |
| Modeled-variant naming                                         | `ComponentVM<M>` (generic overload)                                                | `ComponentVMOf[M]`                                                   | `ComponentVMOf<M>`                                                       | C# generics overload by arity; Python/TS lack overloading.                                                                                                                 |
| Protocol prefix                                                | `IComponentVM` interface                                                           | `ComponentVMProto` Protocol                                          | `IComponentVM` interface                                                 | Python `typing.Protocol` classes conventionally use `…Proto`.                                                                                                              |
| `walk`/`find`                                                  | `VMx.Tree.Tree.Walk` (static class)                                                | `vmx.tree.walk` (module function)                                    | `walk` (top-level)                                                       | C# lacks free functions; static class is the .NET equivalent.                                                                                                              |
| Lifecycle helper name                                          | `LifecycleTransitionValidator.Require`                                             | `vmx.lifecycle.require`                                              | `requireTransition`                                                      | `require` is a reserved global in CommonJS contexts in TS.                                                                                                                 |
| `CollectionChanged` event shape                                | `event NotifyCollectionChangedEventHandler`                                        | `Observable[CollectionChangedEvent]`                                 | `Observable<CollectionChangedEvent>`                                     | C# binds to WPF/MAUI/Avalonia which expect the BCL contract.                                                                                                               |
| `CollectionChangedEvent` record                                | BCL `NotifyCollectionChangedEventArgs`                                             | `vmx.collections.CollectionChangedEvent`                             | `CollectionChangedEvent`                                                 | Same reason as above; C# defers to the BCL payload.                                                                                                                        |
| `MessageHub` parameterisation                                  | `IMessageHub.Send<TMessage>` (per-call generic)                                    | `MessageHub[Message]` (class-generic)                                | `send(message: IMessage)` (no generic)                                   | Each shape is the most idiomatic for its language's type system.                                                                                                           |
| `BatchUpdate()` / batch API                                    | `BatchUpdate(): IDisposable`                                                       | `batch_update()` context-manager (`BatchUpdateHandle`)               | `withBatch(callback: () => void): void` (callback, no return value)      | C# returns a disposable token; Python exposes a context-manager; TS inverts control with a callback — no handle object is returned or needed.                              |
| Async lifecycle methods                                        | `ConstructAsync()` etc. ship on `IComponentVM`                                     | Not provided                                                         | Not provided                                                             | See ADR-0008 — TAP is .NET-specific affordance.                                                                                                                            |
| `ViewModelType` casing                                         | `ViewModelType.Component`                                                          | `ViewModelType.COMPONENT`                                            | `ViewModelType.Component`                                                | Python convention is ALL_CAPS for enum members.                                                                                                                            |
| `CompositeVM` index-set syntax                                 | `vm[i] = x` (indexer)                                                              | `vm[i] = x` (`__setitem__`)                                          | `setAt(i, x)` (named method)                                             | JS lacks operator overloading; named method is the only option.                                                                                                            |
| DI integration                                                 | `VMx.Extensions.DependencyInjection` companion                                     | None (manual constructor injection)                                  | None (manual constructor injection)                                      | DI ecosystems differ; spec stays unopinionated.                                                                                                                            |
| `DerivedProperty` distinct-emit                                | `EqualityComparer<T>.Default.Equals` (structural for value types via `Equals`)     | `==` (structural for built-ins)                                      | `Object.is` (referential, RxJS `distinctUntilChanged` default)           | Each flavor's idiomatic equality operator; consumers needing custom semantics wrap the source or transform.                                                                |
| `ILocalizer.Localize` shape                                    | Two overloads: `Localize(string)` and `Localize(string, IEnumerable<object?>)`     | Single method with optional `args` kwarg                             | Single method with optional `args?` parameter                            | C# method overloading is idiomatic; Python and TypeScript lack it, so they collapse the pair into one signature with an optional second parameter.                         |
| `ObservableDictionary` hub message element type                | `KeyValuePair<(TKey1, TKey2), TValue>` — standard BCL pair of compound key + value | `(key1, key2, value)` 3-tuple                                        | `{ key1, key2, value }` object (`DictionaryEntry<TKey1, TKey2, TValue>`) | All three shapes preserve both keys and the value (spec §4.7); the concrete form is the most idiomatic representation of a key-value pair for each language. Per ADR-0006. |
| LINQ utility helpers (`CartesianProduct`, `Sample`, `Product`) | `LinqHelpers` static class in `VMx.Extensions`                                     | Not provided (use `itertools.product`, slice-with-step, `math.prod`) | Not provided (consumer uses `flatMap`/`filter`+modulo/`reduce`)          | Python and TypeScript cover these natively; adding wrappers would duplicate built-ins. Per ADR-0033.                                                                       |

### `TreeStructureChangedMessage` field name

- **Spec**: §18 defines the field as `Source`.
- **C#**: implements `Source` (faithful to spec text).
- **Python / TypeScript**: use `sender` / `senderName` to match the in-flavor
  convention shared by all other message types (`FormRevertedMessage.sender`,
  `CollectionChangedMessage.sender`, etc.). Subscribers using the
  `sender_name` / `senderName` derived property work uniformly across all
  message types in those flavors.
- **Rationale**: per-flavor internal consistency outweighs spec-name fidelity
  in flavors where every other message uses `sender`.

### `NotificationVM` / `ConfirmationVM` time properties (TypeScript)

- **Spec / C# / Python**: `Lifespan`, `RemainingTime` typed as
  `TimeSpan` / `timedelta`.
- **TypeScript**: `lifespanMs`, `remainingMs` typed as `number` (milliseconds).
- **Rationale**: JavaScript has no native duration type; numbers-as-milliseconds
  is the standard convention (used by `setTimeout`, `Date.now()`, etc.).
  The `Ms` suffix makes the unit explicit.

### `HierarchicalVM` parent property name (C#)

- **Spec / Python / TypeScript**: `Parent` / `parent`.
- **C#**: `HierarchicalParent`.
- **Rationale**: `ComponentVMBase` in C# already exposes a `Parent` property
  (the composite-parent context). Renaming to `HierarchicalParent` avoids
  shadowing/hiding warnings (`CS0108`) and makes the tree-parent semantics
  explicit at the call site.

### `HierarchicalVM` recursive-generic constraint (Python)

- **C#**: `where TVM : HierarchicalVM<TModel, TVM>` — true F-bounded
  generic constraint enforced by the compiler.
- **TypeScript**: `TVM extends HierarchicalVM<TModel, TVM>` — equivalent
  F-bounded constraint enforced by the type checker.
- **Python**: `TVM = TypeVar("TVM", bound="HierarchicalVM[Any, Any]")` —
  weaker bound; `TypeVar` cannot express the self-referential parameter
  binding back to the enclosing class's own type parameters.
- **Rationale**: Python's `typing.TypeVar` `bound=` argument is a single
  type expression evaluated in the enclosing scope; it has no syntax for
  a self-referential, parameter-bound recursion the way the nominal type
  systems do. The runtime/subclass contract is still enforced by
  convention and by `mypy --strict` against concrete subclasses.

### Python interface-prefix convention (v2.0 vs v2.1 split)

- **C# / TypeScript**: all interfaces / Protocols use the canonical `I`-prefix
  (`ISelectable`, `IExpandable`, `IFilterable`, `IPageable`, `IDialogService`,
  `INotificationHub`, `ILocalizer`, …).
- **Python**: split convention. All 20 v2.0 capability ABCs (per ADR-0010)
  and the v2.0 shared services retain the I-prefix for stability:
  `IConstructable`, `IDestructable`, `IReconstructable` (lifecycle);
  `ISelectable`, `IDeselectable`, `ISelectionTogglable` (selection);
  `IExpandable`, `ICollapsible`, `IExpansionTogglable` (expansion);
  `IClosable`, `IApprovable`, `ICancelable` (dialog/form);
  `INewCreatable`, `IDeletable`, `IUpdatable`, `ISavable` (CRUD);
  `ICurrentDeletable`, `ICurrentUpdatable` (container-current CRUD);
  `IManagable` (generic management); `ISearchable` (search); plus shared
  services `INotificationHub` and `ILocalizer`. The v2.1 additions ship
  bare, following modern Python ABC/Protocol idiom: `Filterable`,
  `Pageable` (per ADR-0022 / ADR-0023; CAP-021 / CAP-022) and
  `DialogService` (per ADR-0029).
- **Rationale**: the v2.0 names were established when the Python flavor
  first ported the C# I-prefix convention literally; renaming them on the
  v2.1 minor bump would have been breaking. The v2.1 additions adopt the
  bare-name idiom (matching PEP 8's typical ABC style) and the split is
  preserved going forward — new v2.x Python capabilities ship bare, older
  v2.0 capabilities keep their published I-prefix names.

### Collection size property name

- **C#**: `Count` (matches `ICollection<T>`).
- **Python**: `count` / `len()` via `__len__` (idiomatic).
- **TypeScript**: `length` for list-like types (`ObservableList`, matching
  `Array.prototype.length`), `size` for map-like types
  (`ObservableDictionary`, matching `Map.prototype.size`).
- **Rationale**: pure idiomatic adaptation; no semantic difference across
  flavors.

### `ObservableList` mutation method name

- **Spec / C#**: `Add(item)` / `Add(item)`.
- **Python**: `add(item)` (spec-aligned) and `append(item)` (alias for
  `list`-protocol compatibility — both are public).
- **TypeScript**: `push(item)` (matching `Array.prototype.push`).
- **Rationale**: Pure idiomatic adaptation. Python exposes `append` so the
  type composes with code that targets the standard `list` API; JS code
  reads `list.push(x)` naturally.

### `NotificationVM.NotifyExternalResolve()` visibility

- **C# / Python**: `NotifyExternalResolve()` / `notify_external_resolve()` are
  public methods.
- **TypeScript**: `#notifyExternalResolve()` is a private ES class field.
- **Rationale**: The method handles a hub-side Resolve event propagating into VM
  state (NOTIF-015). C# and Python expose it so that hosts and test harnesses
  can drive external resolution directly; TypeScript keeps it private and routes
  all external resolution exclusively through the hub subscription. Both shapes
  satisfy NOTIF-015; the spec (chapter 16 + ADR-0031) does not mandate a
  particular visibility.

### `ObservableList.pop()` (TypeScript only)

- **TypeScript**: adds `pop(): T | undefined` (mirrors `Array.prototype.pop`),
  emitting an `ItemRemoved` event.
- **C# / Python**: no equivalent; consumers use `RemoveAt(Count - 1)` /
  `del list[-1]` instead.
- **Rationale**: JavaScript code reads `list.pop()` idiomatically. The additive
  method is fully consistent with the spec's `ItemRemoved` event semantics and
  does not alter observable behavior for callers that do not use it. Not
  normative per spec §21 §3.2 (mutation table does not enumerate `pop`).

### `ServicedObservableCollection.splice()` and `setAt()` (TypeScript only)

- **TypeScript**: adds `splice(start, deleteCount?, ...items)` (mirrors
  `Array.prototype.splice`) and `setAt(index, item)` (mirrors bracket-assign).
- **C# / Python**: no equivalents; consumers use `RemoveAt`/`Insert`/the
  indexer.
- **Rationale**: JS idiomatic helpers. Event emission follows spec semantics:
  single-item operations emit `Added`/`Removed`/`Replaced`; multi-item splice
  emits `Reset`. Not normative; the spec does not enumerate these methods.

### `ObservableDictionary` remove/delete naming

- **C#**: `Remove(key1, key2) -> bool`
- **Python**: `remove(key1, key2) -> bool`
- **TypeScript**: `delete(key1, key2): boolean` (matches `Map.prototype.delete`)
- **Rationale**: TS uses the `Map`-idiomatic name; C# and Python follow the BCL/collection
  `Remove` convention.

### `ObservableDictionary` contains-key naming

- **C#**: `ContainsKey(key1, key2) -> bool`
- **Python**: `contains_key(key1, key2) -> bool`
- **TypeScript**: `has(key1, key2): boolean` (matches `Map.prototype.has`)
- **Rationale**: TS uses the `Map`-idiomatic name.

### `ObservableDictionary` upsert path

- **C#**: indexer `this[key1, key2] = value`
- **Python**: `__setitem__` via `dict[key1, key2] = value`
- **TypeScript**: `set(key1, key2, value): void` (matches `Map.prototype.set`)
- `add(key1, key2, value)` (strict-insert, throws on duplicate) uses the same name
  across all three flavors and is already noted in the table above.
- **Rationale**: JS lacks operator overloading; `set` is the idiomatic `Map` name.

### `ObservableDictionary` get / read semantics

- **C#**: indexer `this[key1, key2]` throws `KeyNotFoundException` on miss;
  `TryGetValue` is the safe-read path.
- **Python**: `get(key1, key2)` throws `KeyError` on miss; `__getitem__` also throws.
- **TypeScript**: `get(key1, key2): TValue | undefined` returns `undefined` on miss
  (does NOT throw); a `tryGetValue` helper with a `found` discriminator is provided for
  typed safe-read.
- **Rationale**: TS follows the `Map.prototype.get` no-throw convention. C# and Python
  match the dictionary-throws idiom of their standard libraries.

### `ServicedObservableCollection` append method

- **C#**: `Add(item)` (inherited from `ObservableCollection<T>`)
- **Python**: `append(item)`
- **TypeScript**: `push(item)`
- **Rationale**: Same idiomatic-array rationale as the `ObservableList` `push`
  divergence catalogued above.

### `ObservableList` and `ServicedObservableCollection` array-ergonomic helpers (TypeScript only)

- **TypeScript**: adds `at(index: number): T | undefined` and `toArray(): T[]` on
  both `ObservableList` and `ServicedObservableCollection`.
- **C# / Python**: absent; consumers use the indexer and iteration directly.
- **Rationale**: `Array.prototype.at` and spread/slice patterns are the JS idiomatic
  equivalents. Additive; does not alter spec-observable behavior for callers that
  do not use them.

### `ServicedObservableCollection` mutation observable name

- **C#**: fires the BCL `CollectionChanged` event (`INotifyCollectionChanged`); no
  additional Rx observable is exposed on the public surface.
- **Python**: `on_collection_changed: Observable[CollectionChangedMessage[T]]`
- **TypeScript**: `collectionChanged: Observable<CollectionChangedMessage<T>>`
- **Rationale**: C# uses the .NET-standard event surface expected by WPF/MAUI/Avalonia
  data-binding. Python/TS expose a first-class Rx observable directly (same rationale
  as the `CollectionChanged` row in the table above).

### `PagedComposition` property-changed shape

- **C#**: `INotifyPropertyChanged.PropertyChanged` event
  (`event PropertyChangedEventHandler?`)
- **Python**: `on_property_changed: Observable[str]` (emits the changed property name)
- **TypeScript**: `propertyChanged: Observable<string>` (emits the changed property name)
- **Rationale**: C# implements the .NET-standard `INotifyPropertyChanged` contract
  required by XAML binding. Python/TS expose an Rx observable — same pattern as the
  `CollectionChanged` and `ServicedObservableCollection` observable divergences.

### `FormVM<TM>` persister overload (C# only)

- **C#**: provides a second constructor overload accepting `IFormPersister<TM>`
  alongside the primary `Func<TM, Task>` constructor.
- **Python**: accepts only `Callable[[TM], Awaitable[None]]`.
- **TypeScript**: accepts only a `Persister<TM>` function type.
- **Rationale**: The `IFormPersister<TM>` overload is a DI-ecosystem convenience
  idiomatic to .NET; it wraps the interface into the delegate form internally and
  adds no new behavior. Python and TypeScript have no comparable DI container
  convention that would motivate a parallel interface.

### `NullDialogService` singleton accessor

- **C#**: `NullDialogService.Instance` (static property, PascalCase — .NET convention)
- **Python**: module-level constant `NULL_DIALOG_SERVICE` (Python convention for
  module-level singletons)
- **TypeScript**: `NullDialogService.INSTANCE` (static readonly field, ALL_CAPS —
  JS class-static constant convention)
- **Rationale**: Each flavor uses its language's idiomatic name for a shared stateless
  singleton. The value is identical; only the accessor form differs.

### Fluent `Confirm` overload with `IDialogService`

- **C#**: extension-method overload `Confirm(this ICommand, IDialogService, string)`
  on `FluentCommandExtensions` (same `Confirm` name; C# method overloading
  distinguishes by parameter types).
- **Python**: standalone function `confirm_with_dialog_service(command, dialog_service, prompt)` in `vmx.commands`; distinct name because Python lacks function overloading.
- **TypeScript**: standalone function `confirmWithDialogService(command, dialogService, prompt)` exported from `vmx`; distinct name for the same reason.
- **Rationale**: C# method overloading lets the `IDialogService` variant share the
  `Confirm` name. Python and TypeScript lack overloading with distinct implementations
  and therefore require a distinct function name.

### Fluent `Confirm` overload with `INotificationHub`

- **C#**: extension-method overload `Confirm(this ICommand, INotificationHub, string)`
  on `FluentNotificationExtensions` in the `VMx.Notifications` companion
  assembly (same `Confirm` name; C# method overloading distinguishes by
  parameter types).
- **Python / TypeScript**: no dedicated fluent hub-overload function ships in
  the notifications sub-package. The equivalent composition is the explicit
  two-step form using the bridge helper:
  `command.confirm(make_confirm(hub, prompt))` (Python) /
  `command.confirm(makeConfirm(hub, prompt))` (TypeScript). The bridge
  helpers (`make_confirm` / `makeConfirm`) are already exported from
  `vmx.notifications` / `vmx/notifications`.
- **Rationale**: C# method overloading lets the `INotificationHub` variant
  share the `Confirm` name without polluting the core command surface. In
  Python and TypeScript a single named composition (`confirm(make_confirm(…))`)
  is no less ergonomic than a new function, so a dedicated
  `confirm_with_notification_hub` / `confirmWithNotificationHub` was
  intentionally not introduced for v2.1 — readers should treat the
  two-line composition as the canonical idiom.

The following are **known gaps to address in a future release** — documented
here so audits don't reopen them prematurely:

- **`RelayCommandOfT` → `RelayCommandOf` rename** in Python. The new name shipped
  as a canonical alias alongside the legacy `RelayCommandOfT` in **vmx v1.2.0**.
  The original v1.x plan deferred removal to vmx v2.0.0; that removal slipped
  and the legacy alias still ships in v2.0.0 to preserve downstream code that
  pinned to v1.x. Removal is now deferred to **vmx v3.0.0** (next major).
- **`AggregateVMBuilderN` → `AggregateVMNBuilder` rename** in Python (e.g.
  `AggregateVMBuilder1` → `AggregateVM1Builder`). New names shipped alongside
  the legacy ones in **vmx v1.2.0**; the v2.0.0 removal was likewise deferred
  to **vmx v3.0.0** (next major).
- **`Type(ViewModelType)` (C#) / `vm_type` (Python) on the modeled
  ComponentVM builder.** Surface intentionally retained as an advanced escape
  hatch — a non-leaf VM (e.g. an aggregate) that internally uses
  `ComponentVMOf<M>` can declare its actual role via this setter. Documented
  here so future audits don't re-flag it as vestigial.

### Command property declared types

- **C#**: command properties on `ComponentVMBase`, `FormVM`, `NotificationVM`,
  `ConfirmationVM`, `ModeledCrudCommands` are typed as `ICommand` (the
  interface).
- **Python**: command properties are typed as the concrete `RelayCommand`
  (except `ModeledCrudCommands` which uses the `Command` Protocol).
- **TypeScript**: command properties are typed as the concrete `RelayCommand`
  (except `ModeledCrudCommands` which uses `ICommand`).
- **Rationale**: .NET's strong "code to abstractions" culture leads to
  interface-typed properties; Python/TS communities lean toward exposing the
  concrete return type for IDE assistance and discoverability. Functionally
  equivalent — every concrete command implements the interface.

### `FormVM<TM>` constructor shape

- **C# / Python**: positional constructor parameters
  `(initial, persister, hub?, strict?, snapshotter?)`.
- **TypeScript**: single options-bag parameter `FormVMOptions<TM>` with named
  fields.
- **Rationale**: Idiomatic per language. TS lacks named-argument constructor
  syntax; the options-bag is the standard JS pattern for constructors with
  many optional parameters.

### 2.1 Historical: divergences resolved in v1.2.0 (pre-v2 era)

- C# non-modeled `ComponentVM` class + `ComponentVMBuilder` (additive).
- TypeScript `ConstructionStatusChangedMessage.sender` getter (additive).
- C# `ComponentVMBuilder<M>.AsyncSelection(bool)` removed (dead code; no-op
  on the leaf builder — `CompositeVMBuilder.AsyncSelection` continues to apply).

## 3. Rationale

ADR-0006 already declares the principle; this ADR is its operational catalogue.
Without it, every cross-flavor audit re-discovers the same divergences and asks
"is this a bug?" Locking the deliberate ones into a single table reduces audit
churn. The deferred-rename list keeps known asymmetries visible without forcing
breaking changes in a maintenance pass.

## 4. Consequences

- Future parity audits start with this table as the baseline expectation. Items
  not on it are presumed real drift and worth fixing.
- When a deferred rename comes due, this ADR is updated to remove the moved
  row and a follow-up ADR documents the rename PR.
- Spec text in chapters 03 (messages), 06 (composite-vm), and 13 (tree
  utilities) remains agnostic of these per-flavor shapes — they are framed in
  terms of observable behavior, not method signatures.

## 5. Rejected alternatives

- **Force exact name parity across flavors.** Would either pick a least-common
  denominator (ugly in every flavor) or violate the host language's
  conventions (worse for adoption). Already rejected in ADR-0006.
- **Remove this ADR and rely on per-divergence comments in the code.**
  Inconsistencies would accumulate silently between audits and the rationale
  would scatter across files.
