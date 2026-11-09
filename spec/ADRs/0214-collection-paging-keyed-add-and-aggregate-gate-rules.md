# ADR 0214 — Collection paging, keyed-add, dictionary-add and aggregate-gate rules

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 21 §2.10, §4.1, §4.8, §8, §9.4 and §9.8;
  adds `COL-071` and `AGCH-012`)
- **Relates to:** [ADR-0023](0023-paging-capability-and-paged-composition.md),
  [ADR-0025](0025-multi-key-observable-dictionary.md),
  [ADR-0097](0097-keyed-serviced-observable-collection.md),
  [ADR-0098](0098-dynamic-aggregate-change-stream.md),
  [ADR-0117](0117-callback-safe-lifecycle-publication.md),
  [ADR-0123](0123-preserve-container-causality-and-forwarding-ownership.md)

## 1. Context

Five collection behaviors differed between flavors or were not specified:

1. After `dispose()`, `PagedComposition` paging calls changed the page state
   in C#, TypeScript and Swift, and C# still raised `PropertyChanged`
   (#1299). Python ignored them. The disposal contract said that Swift direct
   paging stays available after disposal.
1. Chapter 21 §4 named no failure type for a duplicate `ObservableDictionary`
   `Add` (#1308). Python raised `KeyError` there, but `ValueError` for a
   duplicate key in its keyed collection. The other flavors used the
   keyed-collection type.
1. Python `KeyedServicedObservableCollection.extend` and `+=` came from the
   `MutableSequence` mixin (#1321). They added one value at a time, so a
   duplicate, projector or iteration failure on a later value left the earlier
   values committed and announced.
1. C#, Python and Swift `AggregateChangeStream` held the aggregate gate while
   they called the source's snapshot, the selector, a selected stream's
   subscribe and a subscription's disposal (#1325). A source that raised its
   structural callback under its own lock could deadlock with the aggregate.
   Rust already made these calls with no state lock held.
1. The C# serviced collections derive from the BCL `ObservableCollection<T>`
   (#1343). Its reentrancy check rejected a nested mutation from a
   `CollectionChanged` handler when the event had two or more handlers. An
   observing `AggregateChangeStream` adds a handler, so any other handler was
   the second one. Python accepts the nested mutation, and chapter 21 §2.13
   and `COL-064` define no rejection.

## 2. Decision

Decided under the owner's 2026-11-07 delegation. Each rule takes the
cross-flavor-uniform and simplest option.

1. **Inert paging after disposal.** After `dispose()`, `PagedComposition`
   page-size writes, page-index writes and the four move calls change no state
   and emit nothing in C#, Python, TypeScript and Swift. The Swift
   `setSource(_:)` is inert too. Reads keep the last page size and page index.
   This is the Python behavior, and the `ExpandableState`, `SearchableState`
   and `DiscriminatorVM` rows already make mutations inert. It replaces the
   documented Swift behavior. Rust `PagedComposition` has no public disposal
   member and is unchanged.
1. **Duplicate dictionary `Add`.** `Add` of a present key pair fails with the
   keyed-collection duplicate-key type of §2.10: C# `ArgumentException`,
   Python `ValueError`, TypeScript `Error`, Rust
   `Err(VmxError::InvalidArgument(_))`. Swift keeps its own
   `ObservableDictionaryError.duplicateKey`. The call changes nothing and
   sends no local event or hub message (`COL-071`). Only Python `add` changes,
   from `KeyError`. A Python handler for an absent key in `get` and for a
   duplicate `add` can no longer be the same `except KeyError`.
1. **Atomic Python keyed `extend` and `+=`.** Both behave as the slice
   assignment `collection[len(collection):] = values`, which §2.10 already
   defines. A duplicate, projector or iteration failure changes nothing and
   emits nothing. Success emits one Reset on each channel. Empty input emits
   nothing. One Reset reuses an existing rule instead of a new multi-item Add.
   The other flavors have no multi-value add.
1. **No aggregate gate during calls out.** The aggregate gate guards only the
   aggregate's state. Construction subscribes to the source with no gate held.
   Reconciliation reads the structural version, takes the snapshot, creates
   the new entries under the gate, then calls the selector and subscribes with
   no gate held. It checks the version under the gate before the commit and
   repeats on a change, as Rust does. Setup and later reconciliations also
   check under the gate that the aggregate is still open. If a concurrent
   disposal closed it, they release the staged subscriptions, and
   construction releases the structural subscription that the disposal could
   not see. Removed, staged and disposed
   subscriptions are detached from the state under the gate and disposed after
   it is released. Only the draining thread reconciles, so two
   reconciliations never overlap (`AGCH-012`). TypeScript runs on one thread
   and needs no change.
1. **C# nested mutation from a handler.** `ServicedObservableCollection<T>`
   overrides the `CollectionChanged` event with its own handler list and
   invokes it itself, so the base class never blocks reentrancy. A handler may
   mutate the collection while other handlers are attached. The keyed
   collection commits its captured keys and index before each event, so every
   handler and hub observer reads a consistent state, as `COL-064` requires.
   No chapter text changes.

## 3. Consequences

- The disposal contract (`docs/content/primitives/disposal-contract.md`)
  states the inert paging rule in the C#, Python, TypeScript and Swift
  sections.
- Python callers that catch `KeyError` from a duplicate
  `ObservableDictionary.add` must catch `ValueError`. The Python CHANGELOG
  records the change. The open-decisions ledger drops its item §2.3.
- Python keyed `extend([5, 7])` now emits one Reset instead of two Adds.
- A selector, a source snapshot or a subscription disposal may now run while
  another thread changes the aggregate's queue. The version check keeps the
  committed membership current. After `Dispose()` returns, a subscription that
  a concurrent reconciliation staged but did not commit can stay live until
  that reconciliation sees the disposal. Its values are ignored.
- The C# local `CollectionChanged` event no longer reaches the
  `ObservableCollection<T>` base event, so `BlockReentrancy` in a subclass
  blocks nothing. VMx code did not use it.
