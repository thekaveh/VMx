# ADR 0208 — Rust collection local events, live dictionary key views, hashed dictionary lookup, and paging notifications

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 03 §4.1; chapter 06 §4; chapter 21 §3.2,
  §4.1, §4.2, §4.6, §5.1, §5.2 and §5.5; `COMP-041`, `COMP-042`, `GRP-012`, `COL-005` to
  `COL-009`, `COL-031`, `COL-066` and `COL-067` apply to Rust in full)
- **Related:** [ADR-0009](0009-cross-flavor-divergence-catalogue.md) §2.25 and
  §2.32, [ADR-0026](0026-granular-observable-list.md),
  [ADR-0142](0142-vm-collections-publish-collection-changes-on-the-hub.md),
  [ADR-0168](0168-swift-and-rust-paged-composition-page-a-stored-copy.md),
  [ADR-0172](0172-one-wait-for-graph-per-flavor.md),
  [ADR-0177](0177-dictionary-key-views-update-before-dictionary-events.md),
  [ADR-0193](0193-collection-views-positions-and-python-reverse.md),
  #1256, #1257, #1269, #1296.

## 1. Context

Four Rust gaps were open in the collection chapters.

**Container local stream (#1256).** Chapter 06 §4 says that a composite raises
a local collection event for each mutation, then publishes the equivalent hub
message. Rust `CompositeVm` and `GroupVm` had that stream, but only as the
crate-private `membership_changes()`. The `COMP-041` and `COMP-042` local
recorders applied to Rust through the hub only.

**List and dictionary (#1257).** Rust `ObservableList<T>` required a hub, had no
public `ItemAdded`, `ItemRemoved`, `ItemReplaced` or `Reset` stream, and had no
value `remove(item)`. Rust `ObservableMultiDictionary` required a hub, had no
local event, and returned `Vec` snapshots from `keys1()` and `keys2()`. The
`COL-067` entry exempted Rust from the key-view and dictionary-event checks.

**Dictionary lookup (#1296).** Both Rust dictionaries found a key by a linear
search, so a build of n distinct keys made n(n−1)/2 key comparisons. The other
flavors keep a hash map beside the key order.

**Paging (#1269).** Rust `PagedComposition` published no property change and
could not follow a `CompositeVm`. `COL-031` excluded Rust.

## 2. Decision

Decided under the owner's 2026-11-07 delegation. Each item takes the
cross-flavor shape, in Rust idiom (ADR-0006).

### 2.1 Container local stream

`CompositeVm`, `GroupVm` and `ModeledCompositeVm` gain a public
`collection_changed()`. The name is the name of
`ServicedObservableCollection::collection_changed()`. It returns a
`MessageHub` that receives each `CollectionChangedMessage` before the
container's hub. A hub batch never defers it. A list batch sends one `Reset`.
After disposal, the container sends nothing on it. `ModeledCompositeVm`
forwards the stream of its composite.

### 2.2 `ObservableList<T>`

1. `ObservableList::new(owner_id)` takes no hub. `ObservableList::with_hub(owner_id, hub)`
   takes one, as `ServicedObservableCollection` does. This changes the
   constructor signature. Rust 0.36.0 is not released, so the change rides in
   it.
1. `item_added()`, `item_removed()`, `item_replaced()` and `reset()` return a
   typed `EventStream`. The payloads are `ItemAddedEvent { item, index }`,
   `ItemRemovedEvent { item, index }` (the index before the removal),
   `ItemReplacedEvent { new_item, old_item, index }` and `()`. A stream is hot
   and synchronous. A subscriber panic is isolated. A payload is built only
   when its stream has a subscriber as the mutation starts. A subscriber
   added during that mutation to a stream that had none misses its event.
1. `property_changed()` sends the spec-literal `Count` name after the granular
   event or `Reset` that changed the count (spec/21 §3.3).
1. `remove(&item)` removes the first equal item, sends `ItemRemoved`, and
   returns `true`. With no equal item it returns `false` and sends nothing.
   `PartialEq` runs on a shared snapshot with no lock held, as in the serviced
   collections (#765).
1. A list with a hub also publishes each change as a `CollectionChangedMessage`
   and each `Count` change as a `PropertyChangedMessage`, after the local
   notification.

### 2.3 `ObservableMultiDictionary<K1, K2, V>`

1. `new(owner_id)` takes no hub. `with_hub(owner_id, hub)` takes one. This
   changes the constructor signature in the unreleased 0.36.0.
1. `collection_changed()` returns the local stream. Each mutation sends one
   `CollectionChangedMessage` on it, then the same message to the hub. A
   panicking local subscriber does not stop the hub message (`COL-066`).
1. `keys1()` and `keys2()` return a live `ReadOnlyObservableList<K>`. It has
   the read and subscribe members of `ObservableList` and no mutator and no
   batch member, so a caller cannot desync a view from the entries. A view
   lists each distinct key in the order of its first appearance. A key that
   disappears and appears again goes to the end. Before, a `Vec` snapshot
   listed the keys in entry order.
1. Each mutation commits the entries and the count, then changes the key views
   that change, then sends the local event, then the hub message (ADR-0177).
1. One thread at a time mutates and delivers. Another thread waits until the
   delivery ends. A nested mutation on the delivering thread, from a key
   comparison or a subscriber, commits at once and queues its change. The
   delivering thread then delivers the queued changes in commit order. The
   views therefore change in commit order and stay in step with the entries.
   If the thread unwinds, it applies the queued view changes with no
   notification.
1. The wait for another thread's delivery is a wait between VMx-owned
   resources, so it is recorded in the wait-for graph (spec/03 §4.1,
   ADR-0172). The delivering thread runs user `hash`, `eq` and subscriber code
   and sends to the hub, so it can itself wait for the waiting thread, for
   example for that thread's open hub batch. The wait that would close that
   cycle is refused. The refused mutation then commits and queues its change
   for the delivering thread, as a refused hub `Send` enqueues for the active
   drain. Its call returns before the change is delivered. Each change is
   queued under the entries lock, so the queue order is the commit order. If
   the delivering thread has already ended its delivery, the refused mutation
   delivers the queue itself.
1. An Add or Replace message carries the entry's position when the message
   is sent (spec/21 §2.4 and §4.7, #733, ADR-0193). If a local subscriber
   moved the entry, the hub message carries the new position. If it removed
   the entry, the position is `None`. A Remove message carries the position
   that the entry had just before the removal.

### 2.4 Hashed dictionary lookup

`ObservableDictionary<K, V>` and `ObservableMultiDictionary` keep a hash index
beside the insertion-ordered keys. A key is hashed with no lock held. A
lookup compares only the keys in that hash's bucket. The comparison runs on a
shared key snapshot with no lock held, and the revision check stays, so user
`hash`, `eq` and `drop` code still runs with no VMx mutex held (#765).
A multi-key pair is found by the hash of its two key hashes, and each
key-view axis keeps its own index. A removal stays O(n), because it shifts the
later entries. The single-key `ObservableDictionary<K, V>` keeps its
constructor, which takes a hub.

### 2.5 `PagedComposition<T>`

1. The pager publishes `PropertyChangedMessage`s on a hub. `new` makes a
   private hub. `with_hub` takes one. `hub()` and `id()` return them.
1. The names are snake_case and follow the Swift order. A new page size sends
   `page_size`, `is_paging_enabled`, `page_count`, `current_page_index` and
   `items`. An index change from a setter or a navigation verb sends
   `current_page_index` and `items`. `set_source`, `push`, and a `remove_at`
   that removes an item send `page_count`, then `current_page_index` when the
   index clamps, then `items`. A call that changes nothing sends nothing.
1. `from_composite(&composite, page_size)` and `from_composite_with_hub` page a
   copy of the composite's children. After each local collection change of
   the composite, the pager replaces the copy and publishes the source
   change. The pager does not keep the composite alive.
1. `dispose()` stops the composite observation and all publication.
1. The pager still pages a stored copy (ADR-0168). A caller-owned `Vec` is not
   followed.

## 3. Consequences

- Chapter 06 §4, chapter 21 §3.2, §4.2, §4.6 and §5.5 lose their open Rust gap
  notes. `COL-031` and `COL-067` apply to Rust without an exemption.
- Rust callers of `ObservableList::new(id, hub)` and
  `ObservableMultiDictionary::new(id, hub)` change to `with_hub`. Callers that
  used `keys1()` or `keys2()` as a `Vec` call `.to_vec()`.
- Spec/03 §4.1 gains the dictionary delivery wait. Its refused-wait result is
  the one of a hub `Send`: the change is queued for the delivering thread.
- ADR-0009 §2.32 lists the Rust differences that remain idiomatic, §2.21
  names the Rust read-only key views, and §2.25 adds the Rust paging shape.
- A build of n distinct keys makes O(n) comparisons on average. On one machine
  a release build of 40,000 `u64` keys took 4.4 times as long as 10,000 keys,
  for both dictionaries.
- The Rust capability-parity ledger closes §12.11.

## 4. Rejected alternatives

- **Keep the stream crate-private and test through the hub.** The hub can be
  batched or shared, so it cannot show the local-before-hub order.
- **A `ValueStream<Option<_>>` for the list events.** A hot `ValueStream`
  keeps its last value, so the stream would keep a removed item alive until the
  next event.
- **Return the backing `ObservableList` from `keys1()`.** A caller edit would
  desync the view from the entries. The read-only facade matches the Python
  view and the direction of the other flavors.
- **Let a foreign writer never wait, as a hub `Send` to a draining hub does.**
  A writer's call would then return before its key views change, also when no
  cycle exists. Waiting keeps the views updated when the call returns, and the
  refused wait keeps the cycle case live.
- **Hold the dictionary lock while comparing keys in a `HashMap<K, _>`.** User
  `hash` and `eq` would run under a VMx mutex, against #765.
- **Follow a caller-owned `Vec`.** ADR-0168 keeps it out of scope.
