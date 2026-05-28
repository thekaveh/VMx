# ADR 0026 — `ObservableList<T>` (granular collection notifications)

**Status:** Accepted (2026-05-27)
**Spec version:** introduced in 2.1.0

## 1. Context

Platform observable-collection contracts (e.g., .NET `INotifyCollectionChanged`,
`ObservableCollection<T>`) report mutations through a single `CollectionChanged`
event carrying a `NotifyCollectionChangedEventArgs` discriminated union. This is
adequate for simple cases but forces every handler to switch on the action kind,
unpack old/new items manually, and handle edge cases (e.g., a `Reset` action
carrying no item data).

The 2012 VMx predecessor did not address this; it relied directly on
`ObservableCollection<T>`. Current VMx inherits that pattern.

Consumers building reactive pipelines with `rxjs` / `reactivex` / `System.Reactive`
find the discriminated-union event awkward to work with in a strongly typed Rx
chain. A type-per-mutation design lets each mutation kind be a distinct observable
stream, enabling operators like `combineLatest` without a `where action == Add`
filter.

ADR-0025 depends on this ADR: `ObservableList<TKey>` is the type of each
key-axis view in `ObservableDictionary`.

## 2. Options considered

1. **Skip — use platform `ObservableCollection<T>` as-is.** No new abstraction.
   Consumers filter and unpack the discriminated union themselves.
1. **Add per-mutation events to `ObservableCollection<T>`.** Subclass or wrap
   the platform type. Keeps compatibility with platform binding infrastructure.
1. **Introduce `ObservableList<T>` as a standalone type** with strongly typed,
   per-mutation observable streams (`ItemAdded`, `ItemRemoved`, `ItemReplaced`,
   `Reset`). Raise the platform `CollectionChanged` event as well (for
   compatibility with platform bindings), where the host platform has that
   interface.
1. **Introduce `ObservableList<T>` with per-mutation events only** (no
   `CollectionChanged` compatibility). Breaks platform binding infrastructure
   in flavors that rely on it.

## 3. Decision

Option 3. `ObservableList<T>` is a standalone opt-in primitive with four
strongly typed mutation events and platform-event compatibility. Key rules:

1. **Granular events.** `ObservableList<T>` exposes:
   - `ItemAdded` — carries `(item: T, index: int)`.
   - `ItemRemoved` — carries `(item: T, index: int)` (index is the position
     before removal).
   - `ItemReplaced` — carries `(newItem: T, oldItem: T, index: int)`.
   - `Reset` — carries no payload; fired on bulk operations (e.g., `Clear`,
     or any mutation whose change set cannot be described by single-item events).
1. **Platform compatibility.** Where the host platform defines
   `INotifyCollectionChanged` (C#), `ObservableList<T>` also raises the
   standard `CollectionChanged` event. This allows platform binding frameworks
   to continue working without modification. Python and TypeScript have no
   platform standard for this; they omit the compatibility event.
1. **Batch interaction.** When a `BatchUpdate()` scope (per `spec/06-composite-vm.md`)
   is active on the owning VM, granular events (`ItemAdded`, `ItemRemoved`,
   `ItemReplaced`) are suppressed during the batch. Only a single `Reset` is
   emitted when the batch completes. The platform `CollectionChanged` event
   follows the same suppression rule in C#.
1. **`PropertyChanged("Count")`.** The `Count` property change notification is
   emitted **after** the granular event for every mutation that changes the
   count (add and remove; not replace). This ordering is normative.

## 4. Consequences

- `spec/21-collections.md` §3 defines `ObservableList<T>` shape and semantics.
- Conformance IDs `COL-005..COL-009` cover:
  - `COL-005` — `ItemAdded` payload shape (item and insertion index).
  - `COL-006` — `ItemRemoved` payload shape (item and pre-removal index).
  - `COL-007` — `ItemReplaced` payload shape (new item, old item, index).
  - `COL-008` — `Count`/`PropertyChanged` ordering after add (granular event
    fires before `PropertyChanged("Count")`).
  - `COL-009` — batch suppression: granular events suppressed during
    `BatchUpdate()`; a single `Reset` fires on completion.
- ADR-0025 (`ObservableDictionary`) depends on this ADR for its key-axis
  observable views (`Keys1`, `Keys2`).
- Per-flavor placement: C# `VMx.Collections/`, Python `vmx.collections`,
  TypeScript `vmx/collections`. Implementation is deferred to Substage 1C.
- The platform-compatibility rule is flavor-idiomatic per ADR-0006: C# raises
  `INotifyCollectionChanged.CollectionChanged`; Python and TypeScript have no
  equivalent platform contract and therefore omit it.
