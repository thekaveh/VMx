# 21 — Collection primitives

Collection primitives are **opt-in, standalone helpers** that complement the
core VM hierarchy (`ComponentVM`, `CompositeVM`, `GroupVM`, `AggregateVM`) with
richer observable-collection behaviour. They are not part of the base VM types;
a consumer chooses which primitives to compose into a given VM.

This chapter covers four primitives:

- `ServicedObservableCollection<T>` — hub-aware observable collection
- `ObservableList<T>` — granular per-mutation events
- `ObservableDictionary` — multi-key observable dictionary
- `PagedComposition<TVM>` — paged composition helper

Paging and filtering capabilities (`IPageable` / `IFilterable<T>`) are defined
in `14-capabilities.md`. `PagedComposition<TVM>` implements `IPageable` as
described here.

## 1. Overview

### 1.1 Relationship to capabilities

`IFilterable<T>` (ADR-0022, `CAP-021`) and `IPageable` (ADR-0023, `CAP-022`)
are **interface contracts**. This chapter defines **helper classes** that
implement those contracts and provide the underlying mechanics. Consumers who
only need the interface contract (e.g., to write capability-based dispatch code)
use `14-capabilities.md`. Consumers who want a ready-made implementation use the
primitives here.

### 1.2 Relationship to `CompositeVM.BatchUpdate()`

`CompositeVM.BatchUpdate()` (per `spec/06-composite-vm.md`) suppresses
intermediate `CollectionChanged` notifications and emits a single `Reset` when
the batch completes. `ObservableList<T>` (§3) and `ServicedObservableCollection<T>`
(§2) both participate in this suppression when they are held by a VM that
initiates a batch.

### 1.3 Opt-in scope

None of the primitives in this chapter are instantiated automatically by any
core VM type. Every use is explicit. There are no breaking changes to existing
types.

## 2. `ServicedObservableCollection<T>`

Per ADR-0024.

### 2.1 Shape

```
ServicedObservableCollection<T>:
    constructor(hub?: IMessageHub)     # hub is optional; absence is a safe no-op
    CollectionChanged : event/Observable  # standard per-flavor collection change
    Add(item: T) : void
    Remove(item: T) : bool
    Replace(index: int, item: T) : void
    Clear() : void
    Count : int
    Items : Iterable<T>
```

### 2.2 Hub injection

The `IMessageHub` is injected at construction time. If no hub is provided (or
if `null` / `None` is explicitly passed), the collection behaves exactly like a
plain platform `ObservableCollection<T>`:

- Local `CollectionChanged` events fire normally on every mutation.
- No message is published to any hub.
- No error is raised.

This is the **null-hub fallback**. It preserves backward compatibility and
removes the need for a null-hub guard at every call site.

### 2.3 Mutation ordering

When a hub is injected, every mutation follows this ordering:

1. Perform the mutation on the backing store.
1. Raise the local `CollectionChanged` event.
1. Call `hub.Send(CollectionChangedMessage{…})`.

The two notifications always occur in this order: local subscribers observe the
change before hub subscribers. This is normative.

### 2.4 `CollectionChangedMessage`

A `CollectionChangedMessage` is emitted for each mutation:

```
CollectionChangedMessage:
    Action  : CollectionAction   # Added | Removed | Replaced | Reset
    NewItems : T[]               # items after the change (empty for Remove/Reset)
    OldItems : T[]               # items before the change (empty for Add/Reset)
    StartingIndex : int          # -1 for Reset
```

### 2.5 Threading

Publication happens **on the same thread as the mutation**. The collection does
not marshal to any scheduler and does not observe any `IDispatcher`. Consumers
wanting foreground delivery subscribe via `ObserveOn(dispatcher.Foreground)`
after the fact, as they would for any other hub message
(see [chapter 11 — threading](11-threading.md)).

### 2.6 Conformance

`COL-001` through `COL-004` in `12-conformance.md`.

## 3. `ObservableList<T>`

Per ADR-0026.

### 3.1 Shape

```
ObservableList<T>:
    ItemAdded   : Observable<(item: T, index: int)>
    ItemRemoved : Observable<(item: T, index: int)>
    ItemReplaced: Observable<(newItem: T, oldItem: T, index: int)>
    Reset       : Observable<unit>

    Add(item: T) : void
    Insert(index: int, item: T) : void
    Remove(item: T) : bool
    RemoveAt(index: int) : void
    Replace(index: int, item: T) : void
    Clear() : void
    Count : int
    this[index] : T               # per-flavor indexer
```

### 3.2 Granular events

Each mutation raises exactly one granular event:

| Mutation              | Event          | Payload                             |
| --------------------- | -------------- | ----------------------------------- |
| `Add` / `Insert`      | `ItemAdded`    | `(item, insertionIndex)`            |
| `Remove` / `RemoveAt` | `ItemRemoved`  | `(item, indexBeforeRemoval)`        |
| `Replace`             | `ItemReplaced` | `(newItem, oldItem, replacedIndex)` |
| `Clear`               | `Reset`        | `unit` (no payload)                 |

`Reset` is also emitted for any bulk operation whose change set cannot be
described by a single-item event (e.g., range insertion if a flavor provides
one).

### 3.3 `PropertyChanged("Count")`

After every mutation that changes `Count` (adds and removes, not replace), the
`Count` property change notification is emitted **after** the granular event.
This ordering is normative: a subscriber observing `ItemAdded` is guaranteed to
see the new count if they query `Count` inside the handler.

### 3.4 Platform compatibility

Where the host platform defines `INotifyCollectionChanged` (C# / WPF / .NET),
`ObservableList<T>` also raises the standard `CollectionChanged` event. Platform
binding frameworks (e.g., WPF `ItemsControl`) continue to work without
modification.

Python and TypeScript have no platform standard for collection-changed
notification; they omit the compatibility event. This is a flavor-idiomatic
deviation per ADR-0006 and is catalogued in ADR-0009.

### 3.5 Batch interaction

When a `BatchUpdate()` scope is active on the owning VM:

- Granular events (`ItemAdded`, `ItemRemoved`, `ItemReplaced`) are suppressed
  during the batch.
- A single `Reset` is emitted when the batch completes.
- In C#, the platform `CollectionChanged` event follows the same suppression
  rule.
- When a batch completes, if `Count` changed during the batch, the
  implementation MUST emit a `PropertyChanged("Count")` notification after
  firing `Reset`. When the batch is empty or count-preserving (e.g., only
  replace operations), no `Count` notification is emitted.

Consumers who need per-item granularity inside a batch must collect mutations
themselves.

### 3.6 Conformance

`COL-005` through `COL-009` and `COL-023` in `12-conformance.md`.

## 4. `ObservableDictionary`

Per ADR-0025.

### 4.1 Shape

The documented common case is `ObservableDictionary<TKey1, TKey2, TValue>` (the
two-key form). It is implemented as a thin typed wrapper over a base
`ObservableDictionary<TKey, TValue>` where `TKey` is the per-flavor compound key
(`ValueTuple` in C#, `tuple` in Python, a readonly object literal in TypeScript).

```
ObservableDictionary<TKey1, TKey2, TValue>:
    constructor(hub?: IMessageHub)              # hub is optional; absence is a safe no-op
    this[key1: TKey1, key2: TKey2] : TValue    # per-flavor indexer
    TryGetValue(key1, key2, out value) : bool
    Add(key1: TKey1, key2: TKey2, value: TValue) : void
    Remove(key1: TKey1, key2: TKey2) : bool
    ContainsKey(key1, key2) : bool
    Clear() : void
    Count : int

    Keys1 : ObservableList<TKey1>    # distinct Key1 values, live view
    Keys2 : ObservableList<TKey2>    # distinct Key2 values, live view

    CollectionChanged : event/Observable
```

### 4.2 Distinct-key observable views

`Keys1` and `Keys2` are live `ObservableList<TKey>` views that stay in sync with
mutations:

- `Keys1` holds the set of distinct Key1 values currently present in the
  dictionary, in insertion order of their **first** appearance.
- `Keys2` holds the set of distinct Key2 values currently present, in insertion
  order of their **first** appearance.
- When a key value disappears from all entries (because the last entry for that
  key was removed), it is removed from the corresponding key list.

Consumers can bind to `Keys1` or `Keys2` independently to build category-view
or identifier-view UIs without walking the full dictionary.

### 4.3 No cascading insertion

Adding an entry with a new Key1 does **not** automatically create entries for
other Key2 slots. Consumers insert every entry explicitly. This is a deliberate
departure from the 2012 predecessor (per ADR-0025 §3).

### 4.4 Null keys

Null / `None` keys are not permitted. Passing a null key raises:

- C#: `ArgumentNullException`
- Python: `TypeError`
- TypeScript: `Error`

### 4.5 Enumeration order

Enumeration yields entries in insertion order. Flavors that cannot guarantee
insertion order must document the deviation in
`spec/ADRs/0009-cross-flavor-divergence-catalogue.md`.

### 4.6 Hub integration

If a hub is provided at construction time (following the same pattern as
`ServicedObservableCollection<T>` §2.2), mutations publish a
`CollectionChangedMessage` to the hub after the local `CollectionChanged` event.
Null-hub fallback applies.

### 4.7 Hub message element shape

The `CollectionChangedMessage` element type carries the full dictionary entry —
both keys and the value — so subscribers can recover the full identity of the
mutated entry without additional context. The concrete payload shape is
flavor-idiomatic per ADR-0006:

- **C#**: `KeyValuePair<(TKey1, TKey2), TValue>` — key tuple + value.
- **Python**: `(key1, key2, value)` tuple.
- **TypeScript**: `{ key1: TKey1; key2: TKey2; value: TValue }` object
  (`DictionaryEntry<TKey1, TKey2, TValue>`).

For `Clear()`, the hub message uses action `Reset` with empty `NewItems` and
`OldItems` arrays (no entry data is needed because the entire collection is
cleared). This divergence between flavors is catalogued in ADR-0009.

### 4.8 Conformance

`COL-010` through `COL-015` and `COL-022` in `12-conformance.md`.

## 5. Paging: `PagedComposition<TVM>`

Per ADR-0023 (helper portion).

### 5.1 Shape

```
PagedComposition<TVM>:
    constructor(source)                     # iterable composition source — per-flavor
                                            # idiom: IEnumerable<TVM> (C#),
                                            # Iterable[TVM] or factory callable (Python),
                                            # PagedCompositionSource<TVM> (TS)
    implements IPageable                     # per 14-capabilities.md §2.10

    PageSize         : int     # mutable; 0 = all items on one page
    CurrentPageIndex : int     # mutable; clamped to [0, PageCount-1]
    PageCount        : int     # derived: ceil(source.Count / PageSize), or 1 when PageSize == 0
    IsPagingEnabled  : bool    # derived: PageSize > 0

    move_to_first_page()       # no-op when CurrentPageIndex == 0
    move_to_previous_page()    # no-op at lower bound
    move_to_next_page()        # no-op at upper bound
    move_to_last_page()        # no-op when at last page

    Items : Iterable<TVM>      # read-only; current page slice
    Count : int                # count of items in current page (not total)
```

### 5.2 Decorator semantics

`PagedComposition<TVM>` **decorates** any iterable composition source. It does
not hold the items itself; it computes a slice of the source on demand. The
source is never mutated.

When the source changes (items added or removed), `PageCount` is recomputed and
`CurrentPageIndex` is clamped to `[0, PageCount-1]` if the prior index is now
out of range.

### 5.3 `PageSize = 0` semantics

When `PageSize == 0`:

- `IsPagingEnabled` is `false`.
- `PageCount` is `1`.
- `CurrentPageIndex` is `0`.
- `Items` yields all source items.

This makes `PageSize = 0` the "off" switch for paging: the decorator passes
through the entire source without slicing.

### 5.4 Empty source

When the source is empty:

- `PageCount` is `0` when `PageSize > 0`.
- `CurrentPageIndex` is `0` (stays clamped to `0` even if `PageCount == 0`).
- `Items` yields no items.

Navigation verbs are all no-ops on an empty source.

### 5.5 Conformance

`COL-016` through `COL-021` in `12-conformance.md`.

## 6. Composition with other helpers

### 6.1 Filter-then-page ordering

When both `SearchableState<T>` (ADR-0014) and `PagedComposition<TVM>` wrap the
same composition, the correct ordering is:

```
source: CompositeVM<ItemVM>
  → SearchableState<ItemVM>   (produces: filtered view)
    → PagedComposition<ItemVM>  (source: filtered view)
```

`PagedComposition` takes the filtered view as its source. Paging is applied
**after** filtering. Page arithmetic (page count, current-page slice) is
computed over the filtered item count, not the total source count.

Reversing the order (page first, then filter) is permitted by the spec but is
rarely the desired behaviour and is therefore not the documented idiomatic
pattern.

### 6.2 Batch interaction

When a `BatchUpdate()` scope is active, `ObservableList<T>` suppresses granular
events and emits a single `Reset` on completion (per §3.5). A
`PagedComposition<TVM>` wrapping that list observes the `Reset` and recomputes
its page slice. The recomputation happens once after the batch, not once per
item.

### 6.3 `ServicedObservableCollection<T>` with composition helpers

`ServicedObservableCollection<T>` publishes `CollectionChangedMessage` to the
hub on every mutation, even when wrapped by `SearchableState` or
`PagedComposition`. The hub publication is triggered by the mutation, not by
the downstream view's state. Consumers observing the hub receive the raw change
regardless of what filtering or paging is applied on top.

## 7. Conformance

`COL-001` through `COL-023` in `12-conformance.md`. Applicable ADRs:
ADR-0024 (§2), ADR-0026 (§3), ADR-0025 (§4), ADR-0023 (§5).
