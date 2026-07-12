# 21 — Collection primitives

Collection primitives are **opt-in, standalone helpers** that complement the
core VM hierarchy (`ComponentVM`, `CompositeVM`, `GroupVM`, `AggregateVM`) with
richer observable-collection behaviour. They are not part of the base VM types;
a consumer chooses which primitives to compose into a given VM.

The shared `CompositeVM` / `GroupVM` child-collection capability and its atomic
identity-preserving `Move` operation are core hierarchy contracts, not
standalone helpers; see chapter 01 §1.4, chapters 06–07, and ADR-0085.

This chapter covers six primitives:

- `ServicedObservableCollection<T>` — hub-aware observable collection
- `KeyedServicedObservableCollection<TKey, TItem>` — ordered, hub-aware
  collection with a captured-key index
- `ObservableList<T>` — granular per-mutation events
- `ObservableDictionary` — multi-key observable dictionary
- `PagedComposition<TVM>` — finite, index-based paged composition helper
- `TokenPagedComposition<TVM, TToken>` — accumulated, forward-only token paging

Paging and filtering capabilities (`IPageable` / `IFilterable<TItem>`) are defined
in `14-capabilities.md`. `PagedComposition<TVM>` implements `IPageable` as
described here.

## 1. Overview

### 1.1 Relationship to capabilities

`IFilterable<TItem>` (ADR-0022, `CAP-021`) and `IPageable` (ADR-0023, `CAP-022`)
are **interface contracts**. This chapter defines **helper classes** that
implement those contracts and provide the underlying mechanics. Consumers who
only need the interface contract (e.g., to write capability-based dispatch code)
use `14-capabilities.md`. Consumers who want a ready-made implementation use the
primitives here.

### 1.2 Relationship to `CompositeVM.BatchUpdate()`

`CompositeVM.BatchUpdate()` (per `spec/06-composite-vm.md`) suppresses
intermediate `CollectionChanged` notifications and emits a single `Reset` when
the batch completes. `ObservableList<T>` (§3) exposes an analogous —
**independent** — batch scope of its own (§3.5); entering one scope has no
effect on the other, and `ServicedObservableCollection<T>` (§2) has no batch
mechanism. (Corrected in v2.5.0 via ADR-0038: an earlier revision claimed
these collections "participate" in a VM-initiated batch, which no flavor
implements.)

### 1.3 Opt-in scope

None of the primitives in this chapter are instantiated automatically by any
core VM type. Every use is explicit. There are no breaking changes to existing
types.

## 2. Serviced observable collections

Per ADR-0024, ADR-0096, and ADR-0097.

### 2.1 Unkeyed shape

The collection accepts an optional `IMessageHub`, exposes the established
per-flavor local collection-change event/Observable, supports indexed and
iterable reads, and provides this idiomatic conceptual mutation surface:

| Concept      | C#                  | Python        | TypeScript                   | Swift                                  | Rust          |
| ------------ | ------------------- | ------------- | ---------------------------- | -------------------------------------- | ------------- |
| Add          | `Add`               | `append`      | `push`                       | `append`                               | `push`        |
| Remove value | `Remove`            | `remove`      | `remove`                     | `remove`                               | `remove`      |
| Remove index | `RemoveAt`          | `remove_at`   | `removeAt`                   | `removeAt`                             | `remove_at`   |
| Replace      | indexer / `Replace` | `replace`     | `replace` (`setAt` retained) | `replace(at:with:)` (`setAt` retained) | `replace`     |
| Replace all  | `ReplaceAll`        | `replace_all` | `replaceAll`                 | `replaceAll`                           | `replace_all` |
| Move         | `Move`              | `move`        | `move`                       | `move(from:to:)`                       | `move_item`   |
| Clear        | `Clear`             | `clear`       | `clear`                      | `clear`                                | `clear`       |

Size and iteration follow the host collection idiom (`Count`, `len`/`count`,
`length`, and native iteration or established indexed access). Existing
indexers, `setAt`, `splice`, `pop`, `at`, and `toArray` affordances remain
source-compatible; see ADR-0009. Rust provides a distinct real
`ServicedObservableCollection<T>`, not an alias for `ObservableList<T>`.

### 2.2 Hub injection

The `IMessageHub` is injected at construction time. If no hub is provided (or
if `null` / `None` is explicitly passed), the collection behaves exactly like a
plain platform `ObservableCollection<T>`:

- Local `CollectionChanged` events fire normally on every mutation.
- No message is published to any hub.
- No error is raised.

This is the **null-hub fallback**. It preserves backward compatibility and
removes the need for a null-hub guard at every call site.

### 2.3 Mutation semantics

#### 2.3.1 Value and indexed removal

Value removal targets the first equal occurrence only. A missing value changes
nothing and returns false except in Python: Python preserves the standard
`MutableSequence.remove` behavior, returning `None` on success and raising
`ValueError` when the value is absent.

Indexed removal emits exactly one Remove. In C#, Python, TypeScript, and Swift,
the message contains the removed item and its pre-removal position. Rust emits
Remove with `old_index == Some(pre-removal)` and `new_index == None`, without an
item payload.

C#, TypeScript, and Swift accept only indices in `[0, Count)` and reject an
invalid index before mutation. Rust's index type is `usize`, so a negative value
is unrepresentable; a value at or above `Count` is rejected before mutation.
Python preserves normal negative-index resolution for named indexed removal:
the message reports the resolved nonnegative position, while an excessively
negative or positive index raises `IndexError` atomically. Swift's established
nonthrowing indexed mutators preserve their array-precondition failure behavior.
Newly named Python and Rust indexed operations return the removed item;
established flavor returns remain unchanged.

#### 2.3.2 Replacement

Named replacement emits exactly one Replace. In C#, Python, TypeScript, and
Swift, its message contains the old item, new item, and replaced position. Rust
emits Replace with equal present optional old/new positions and no item payload.
Replacing an item with the identical or equal item still emits Replace; this
unconstrained generic does not compare items to suppress an explicit
replacement. Indexed bounds and per-flavor divergence behavior match §2.3.1.
Newly named Python and Rust operations return the old item; established flavor
returns remain unchanged.

#### 2.3.3 Whole-list replacement and clear

Whole-list replacement fully materializes its input before changing the backing
store. Passing the collection itself or a live view is safe. In flavors where
input iteration can fail, materialization failure leaves contents and both
notification channels unchanged.

Empty-to-empty is the only replacement no-op. Every other call, including
element-for-element identical non-empty contents, emits exactly one Reset and no
granular messages. A serviced collection has no `Count` property-change
channel; Reset is its sole bulk notification.

Clearing an empty collection is a true no-op. Clearing a non-empty collection
emits exactly one Reset. Serviced collections have no batch mechanism: every
effective mutation delivers immediately.

#### 2.3.4 Move

Move reuses the portable ADR-0085 index contract. Both indices address the
pre-move collection and MUST lie in `[0, Count)`. Invalid indices raise a
flavor-idiomatic catchable bounds error before mutation. C#, Python, TypeScript,
and Swift reject negative Move indices; Rust's `usize` indices make negative
values unrepresentable. Python's strict Move behavior differs from its indexed
remove and replace operations. Swift Move failures use the existing catchable
`VMCollectionIndexError` rather than its nonthrowing indexed-mutator precondition
path.

Equal Move indices are a true no-op. A successful move preserves item identity,
places that item at the destination, and emits exactly one Move containing the
same item as old and new payload in C#, Python, TypeScript, and Swift. Rust's
non-generic message identifies the move through its action and positions only.
Move does not construct, dispose, reparent, detach, or otherwise manage the
item.

### 2.4 `CollectionChangedMessage`

A `CollectionChangedMessage` is emitted for each mutation. C#, Python,
TypeScript, and Swift use the typed item-payload shape:

```
CollectionChangedMessage:
    Action  : <flavor action type>   # Add | Remove | Replace | Move | Reset
    NewItems : T[]               # items after the change (empty for Remove/Reset)
    OldItems : T[]               # items before the change (empty for Add/Reset)
    Index   : int                # -1 for Reset
    OldIndex : int               # -1 when there is no old position
    NewIndex : int               # -1 when there is no new position
```

Their action member's type is per-flavor idiom (ADR-0006): C# reuses the BCL
`NotifyCollectionChangedAction`, Python uses action string literals, TypeScript
uses a `CollectionMutationAction` union, and Swift uses
`CollectionChangedAction`. Member casing follows ADR-0006 (`OldIndex` /
`old_index` / `oldIndex`). The existing `Index` / `index` member and
constructor/factory defaults remain compatible in these four flavors.

| Action  |     `index` |  `oldIndex` |  `newIndex` | Item payload                        |
| ------- | ----------: | ----------: | ----------: | ----------------------------------- |
| Add     |   insertion |          -1 |   insertion | new item                            |
| Remove  | pre-removal | pre-removal |          -1 | old item                            |
| Replace |    replaced |    replaced |    replaced | old and new item                    |
| Move    | destination |      source | destination | identical moved item as old and new |
| Reset   |          -1 |          -1 |          -1 | none                                |

Rust preserves its established non-generic, hub-oriented message shape:

```
CollectionChangedMessage:
    sender_id    : usize
    property_name: String
    action       : CollectionChangeAction
    old_index    : Option<usize>
    new_index    : Option<usize>
```

| Action  | `old_index`         | `new_index`         |
| ------- | ------------------- | ------------------- |
| Add     | `None`              | `Some(insertion)`   |
| Remove  | `Some(pre-removal)` | `None`              |
| Replace | `Some(replaced)`    | `Some(replaced)`    |
| Move    | `Some(source)`      | `Some(destination)` |
| Reset   | `None`              | `None`              |

Rust has no legacy `index` member and carries no typed old/new item payloads.
Its optional positions encode absence with `None`, not an integer sentinel.

### 2.5 Mutation ordering and threading

Every effective mutation follows this order:

1. Change the backing state.
1. Deliver the local collection-change notification.
1. Publish the equivalent `CollectionChangedMessage` to the optional hub.

Local delivery always precedes hub delivery, and subscribers to both channels
can read the complete final state. Subscriber failures follow the flavor's
established local-reactive and message-hub delivery rules; this primitive adds
no new failure policy.

Publication happens **on the same thread as the mutation**. The collection does
not marshal to any scheduler and does not observe any `IDispatcher`. Consumers
wanting foreground delivery subscribe via `ObserveOn(dispatcher.Foreground)`
after the fact, as they would for any other hub message
(see [chapter 11 — threading](11-threading.md)).

### 2.6 Ownership

`ServicedObservableCollection<T>` does **not** own, construct, destruct, or
dispose the items it contains. "Serviced" means "optionally publishes
collection-change messages to a service" (`IMessageHub`), not "service-managed
lifecycle."

Removing, replacing, resetting, moving, clearing, or popping an item only
mutates the collection and emits collection-change notifications. If the items
are disposable VMs, the caller remains responsible for their lifecycle.
Consumers that need lifecycle-cascading VM ownership should use `CompositeVM` /
`GroupVM` or an explicit owner wrapper.

### 2.7 Conformance

`COL-001` through `COL-004` and `COL-048` through `COL-055` in
`12-conformance.md`.

### 2.8 `KeyedServicedObservableCollection<TKey, TItem>` shape

Per ADR-0097, every flavor exposes a distinct, additive keyed serviced type.
It is not a mode or constructor overload on the unkeyed type: choosing the
keyed type makes the stable-key requirement explicit and leaves all existing
unkeyed construction and generic signatures source-compatible.

The keyed type preserves the complete ordered-list contract in §§2.1–2.6:
add, value removal, indexed removal, replacement, whole-list replacement,
move, clear, count, indexed reads, snapshots, insertion-order iteration, local
change delivery, optional hub publication, and caller-owned items. It adds a
projector, key lookup and membership, upsert, and keyed deletion:

| Flavor     | Construction / projector                                                                                               | Lookup / membership                                        | Upsert                                         | Keyed deletion                |
| ---------- | ---------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ---------------------------------------------- | ----------------------------- |
| C#         | `(Func<TItem, TKey> keySelector, IMessageHub? hub = null, IEqualityComparer<TKey>? comparer = null)`, `TKey : notnull` | `TryGetValue(TKey, out TItem?)`, `ContainsKey(TKey)`       | `bool Upsert(TItem)` (`true` means Add)        | `bool RemoveKey(TKey)`        |
| Python     | `(key_of: Callable[[T], TKey], hub = None)`; keys are hashable                                                         | `get(key) -> Optional[T]`, `contains_key(key) -> bool`     | `upsert(item) -> bool` (`True` means Add)      | `delete(key) -> bool`         |
| TypeScript | options with `keyOf: (item: T) => TKey` and optional nullable `hub`                                                    | `get(key)` returns `T` or `undefined`; `has(key): boolean` | `upsert(item): boolean` (`true` means Add)     | `delete(key): boolean`        |
| Swift      | `(keyOf: @escaping (T) throws -> Key, hub: MessageHubProtocol? = nil)`, `Key: Hashable`                                | `get(_:) -> T?`, `containsKey(_:) -> Bool`                 | `upsert(_:) throws -> Bool` (`true` means Add) | `delete(_:) -> Bool`          |
| Rust       | `(owner_id, key_of: Fn(&T) -> VmxResult<K>)` / `with_hub`, `K: Eq + Hash`                                              | `get(&K) -> Option<T>`, `contains_key(&K) -> bool`         | `upsert(T) -> VmxResult<bool>` (`true` = Add)  | `remove_key(&K) -> Option<T>` |

The exact Python miss annotation is `get(key) -> T | None`. The exact
TypeScript options shape is
`{ keyOf: (item: T) => TKey; hub?: IMessageHub | null }`, and its lookup is
`get(key): T | undefined`.

A missing keyed deletion is a false / `None` no-op. Rust returns the removed
value because ownership-returning removal is its established idiom. An upsert
of a missing key returns the Add outcome; an upsert of a present key returns
the replacement outcome.

Every list convenience exposed by the corresponding unkeyed serviced type is
preserved and keeps the key index synchronized:

- C#: inherited Add, Insert, value Remove, RemoveAt, indexer replacement, Move,
  and Clear, plus Replace and ReplaceAll;
- Python: the full `MutableSequence` integer/slice surface, insert, append,
  clear, value/index removal, replacement, replace-all, and move;
- TypeScript: push, pop, value/index removal, splice, replace/setAt,
  replaceAll, move, and clear;
- Swift: append, removeLast, Equatable value removal, indexed removal,
  replace/setAt, replaceAll, move, and clear; and
- Rust: push, PartialEq value removal, indexed removal, replace, replace-all,
  move, and clear. The unkeyed Rust type has no positional-insert convenience,
  so the keyed type does not invent one.

Host-language naming, bounds, equality, return values, and typed versus
non-generic message payloads remain those in §§2.1–2.4 and ADR-0009.

### 2.9 Captured-key contract

The projector runs before a candidate item is committed. Its result is stored
as that membership's captured key and is not recomputed by lookup, membership,
move, or removal. Mutating a key-like property on a stored item therefore does
not silently reindex it: lookup by the captured key continues to return the
item, while lookup by the newly projectable key misses.

Callers explicitly rekey a membership through indexed replacement,
whole-list replacement, or delete followed by add/upsert. Indexed replacement
removes the old captured key and installs the newly projected key at the same
position atomically, provided another position does not already own that key.
Whole-list replacement captures a fresh key for every replacement membership.

Passing the same stored item instance to upsert after mutating its key-like
property projects the new key. If that key is absent, upsert appends a second
membership for the same instance and emits Add; generic value types do not
permit a portable identity-uniqueness rule. If the projected key is already
present, upsert replaces that membership at its existing position and emits
Replace, even when the old and new item are the identical instance.

Captured keys MUST retain stable equality and hashing while stored. The key
universe and optional/null-like key behavior are the host hash map's concern,
not a portable absence sentinel. Unsupported or unhashable keys fail before
mutation where the host can report such failure.

### 2.10 Uniqueness, preflight, and atomicity

Add and, where exposed, insert reject a key already captured by another
membership. Indexed replacement may change a key only when no other position
owns the new key. Upsert is the deliberate exception: a present projected key
selects replacement at that key's existing position rather than reporting a
duplicate.

Whole-list replacement first materializes all input, projects every key, and
validates uniqueness before commit. Passing the collection itself is safe.
Empty-to-empty is its only no-op; every other valid invocation emits exactly
one Reset, including identical non-empty contents. A duplicate, input
iteration failure, or projection failure emits nothing and preserves the old
ordered items, captured-key sequence, key-to-index map, and both notification
channels.

C#, Python, and TypeScript propagate exceptions from user projectors. Swift's
projector is explicitly throwing, so operations that project new items are
throwing. Rust projectors return `VmxResult<K>`, and operations that project
new items return `VmxResult`. All projection, unsupported-key, and duplicate
failures complete preflight before collection-owned state changes.

This atomicity promise does not roll back arbitrary side effects inside user
projector/equality/hash code, allocation failure, process abort, or a subscriber
failure after state has committed.

### 2.11 Ordered mutations and messages

Every effective mutation synchronizes the ordered item store, captured-key
sequence, and key-to-index map before observers run. It then uses exactly the
unkeyed action, item, and old/new position semantics from §§2.3–2.4:

- add, insert, and missing-key upsert emit Add at the insertion position;
- value, index, and key removal emit Remove for the stored item at its
  pre-removal position;
- indexed replacement and present-key upsert emit Replace at the stable
  position;
- move emits Move with the source and destination positions; and
- clear and whole-list replacement emit Reset.

Value removal follows the base flavor's first-equal-occurrence and
missing-value idiom, and uses that membership's captured key rather than
reprojecting the item. Equal-index move, empty clear, missing keyed deletion,
and empty-to-empty replacement are true no-ops. Invalid positions and duplicate
keys fail before mutation or notification.

### 2.12 Complexity boundary

Key lookup and membership are expected O(1), as is target discovery for keyed
delete and upsert, subject to the host hash map's equality and hashing behavior.
This does not make every complete mutation O(1). Contiguous indexing,
insertion-order iteration, precise pre-removal positions, and ordinary
array/list snapshots require O(n) shifting and key-to-index repair after a
middle insertion, deletion, or move. The keyed type eliminates a consumer's
extra snapshot allocation and linear target scan; it does not promise an
impossible constant-time ordered-list deletion.

Expected O(1) lookup is a design and source-review requirement. Conformance MAY
use countable equality/hash probes where a host makes that reliable, but MUST
NOT use wall-clock timing as a portable assertion.

### 2.13 Delivery, reentrancy, and hub transactions

The complete backing state and key index change first, then the local channel
fires, then the optional external hub receives the equivalent message.
Reentrant observers see a consistent item/key/index state. Subscriber failures
retain the unkeyed serviced collection's committed-state policy.

The keyed collection has no collection batch scope. If the injected hub is
already inside its own transaction/batch, local notifications remain immediate
and granular while hub delivery is deferred in original hub order. Hub batching
does not collapse keyed changes into Reset and does not weaken key-index
atomicity. For reentrant mutations, each individual operation preserves its
local-before-hub partial order; no one portable global ordering of nested local
and external events is required.

### 2.14 Ownership

The keyed collection never constructs, disposes, destructs, reparents, or
otherwise owns an item. Key projection and index maintenance do not change the
caller-owned lifecycle rule in §2.6.

### 2.15 Keyed conformance

`COL-056` through `COL-064` in `12-conformance.md` cover captured lookup,
uniqueness and failure atomicity, upsert, keyed deletion, synchronization and
explicit rekeying, whole-list replacement, move/clear/ownership, delivery and
hub transactions, and reentrant consistency.

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

Bulk clears follow the same rule (clarified in v2.5.0 via ADR-0037): a
`Clear()` on a non-empty list emits `PropertyChanged("Count")` **after** the
`Reset` event, mirroring the batch-exit rule in §3.5. Clearing an empty list
changes nothing and emits nothing — neither the `Reset` event nor the `Count`
notification (ADR-0037 §2.2, matching the empty-batch case).

### 3.4 Platform compatibility

Where the host platform defines `INotifyCollectionChanged` (C# / WPF / .NET),
`ObservableList<T>` also raises the standard `CollectionChanged` event. Platform
binding frameworks (e.g., WPF `ItemsControl`) continue to work without
modification.

Python and TypeScript have no platform standard for collection-changed
notification; they omit the compatibility event. This is a flavor-idiomatic
deviation per ADR-0006 and is catalogued in ADR-0009.

### 3.5 Batch interaction

`ObservableList<T>` owns its batch scope directly — `BatchUpdate()` (C#),
`batch_update()` (Python), `withBatch()` (TypeScript). While a scope is
active on the list:

- Granular events (`ItemAdded`, `ItemRemoved`, `ItemReplaced`) are suppressed
  during the batch.
- A single `Reset` is emitted when the batch completes **and at least one
  mutation occurred** during the batch. A batch in which no mutation occurred
  emits **no** `Reset` (and no `Count` notification), mirroring the
  empty-batch-no-event rule for `CompositeVM.BatchUpdate()` (06 §4.1) and
  `GroupVM.BatchUpdate()` (07 §5).
- Nested batch scopes are **ref-counted**: opening a second scope while one is
  already live does not start a new batch, and only the completion of the
  **outermost** scope emits the single `Reset`. Inner-scope completions emit
  nothing. This matches the ref-counted nesting `CompositeVM` / `GroupVM` use
  for their own `BatchUpdate()` (06 §4.1 / 07 §5).
- In C#, the platform `CollectionChanged` event follows the same suppression
  rule.
- When a batch completes, if `Count` changed during the batch, the
  implementation MUST emit a `PropertyChanged("Count")` notification after
  firing `Reset`. When the batch is empty or count-preserving (e.g., only
  replace operations), no `Count` notification is emitted.

Consumers who need per-item granularity inside a batch must collect mutations
themselves.

If a batch body exits exceptionally, every entered scope MUST still close. If
the body mutated the list, the outermost exit MUST publish the same Reset and
optional `Count` sequence before the original failure propagates, and later
mutations MUST behave outside that completed scope.

### 3.6 Whole-list replacement

`ObservableList<T>` exposes flavor-idiomatic `ReplaceAll(items)` /
`replace_all(items)` / `replaceAll(items)`. It MUST fully materialize the input
before mutating the backing list. Passing the list itself or a view over it is
therefore safe. In flavors where input iteration can fail, materialization
failure MUST propagate without changing contents or emitting an event.

Empty-to-empty replacement is a no-op and emits nothing. Every other invocation
is an effective bulk mutation, including an equal-count replacement and an
element-for-element identical non-empty replacement. Implementations MUST NOT
require or invoke element equality to decide whether to publish.

An effective replacement emits no granular item events and exactly one Reset.
If `Count` changed, `PropertyChanged("Count")` MUST follow Reset; otherwise no
`Count` notification is emitted. Both notifications observe the complete final
snapshot.

Inside an existing list batch, replacement only marks that batch dirty. It
emits nothing immediately, and only the outermost batch exit emits the single
Reset and cardinality-dependent `Count` notification defined in §3.5.

### 3.7 Conformance

`COL-005` through `COL-009`, `COL-023`, and `COL-040` through `COL-047` in
`12-conformance.md`.

## 4. `ObservableDictionary`

Per ADR-0025.

### 4.1 Shape

The documented common case is `ObservableDictionary<TKey1, TKey2, TValue>` (the
two-key form). Each flavor implements it as a standalone class over a
compound-key backing store — `ValueTuple` keys in C#, `tuple` keys in Python,
and a serialized-string key map in TypeScript (the entry type exposed to
consumers remains `DictionaryEntry`). There is no single-key base type.
(Corrected in v2.5.0 via ADR-0038.)

```
ObservableDictionary<TKey1, TKey2, TValue>:
    constructor(hub?: IMessageHub)              # hub is optional; absence is a safe no-op
    this[key1: TKey1, key2: TKey2] : TValue    # per-flavor indexer
    TryGetValue(key1, key2) : (found, value)   # per-flavor shape (C# out-param, Python tuple, TS object)
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
    CurrentPageIndex : int     # mutable; clamped to [0, max(0, PageCount-1)] (§5.4)
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
`CurrentPageIndex` is clamped to `[0, max(0, PageCount-1)]` if the prior index is
now out of range. The `max(0, …)` term covers the empty-source case
(`PageCount == 0`), where the index clamps to `0` rather than to `-1` (§5.4).

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

### 5.5 Source observation

`PagedComposition<TVM>` observes source mutation streams when the source exposes
them. Observable-list split streams (`ItemAdded` / `ItemRemoved` /
`ItemReplaced` / `Reset`, with per-flavor casing) and composite-style
`CollectionChanged` streams are both valid source shapes.

### 5.6 Conformance

`COL-016` through `COL-021` and `COL-031` in `12-conformance.md`.

## 6. Token paging: `TokenPagedComposition<TVM, TToken>`

Per ADR-0069 and ADR-0078.

### 6.1 Shape

```
TokenPagedComposition<TVM, TToken>:
    constructor(fetch_next)                 # async function: token? -> (items, nextToken?)

    Items        : IReadOnlyList<TVM>       # accumulated loaded items
    CurrentToken : TToken?                  # token for the next load; null/nil/None after terminal page
    HasMore      : bool                     # true before first fetch, then CurrentToken != null/nil/None

    LoadMoreCommand : AsyncRelayCommand     # fetches CurrentToken, appends returned items
    RefreshCommand  : AsyncRelayCommand     # fetches from initial token and replaces/dedups accumulator

    CollectionChanged                       # reset event after effective accumulator mutations
    PropertyChanged                         # Items / CurrentToken / HasMore changes
```

The token is opaque to VMx. `null` / `None` / `nil` is the initial token and the
terminal "no more pages" token.

### 6.2 Load and refresh semantics

`LoadMoreCommand` calls `fetch_next(CurrentToken)`, appends returned items to the
accumulator, stores the returned next token, and emits a coarse `Reset`
collection event. When the returned token is terminal, `HasMore` becomes false
and `LoadMoreCommand.CanExecute` returns false.

`RefreshCommand` calls `fetch_next(null)` and treats the result as a new first
page. If the new first page matches the current accumulator head according to
the flavor's equality/comparer hook, the accumulator is not mutated and no
collection event is emitted; token and property state are still refreshed. If it
differs, the accumulator is replaced with the first page and a coarse `Reset`
event is emitted.

When `auto_construct_on_add` / `autoConstructOnAdd` / `AutoConstructOnAdd` is
enabled and returned items are VMx component VMs, they are constructed before
the reset event is emitted.

Disposal is terminal for suspended load/refresh completions. If `dispose()` wins
the race while a fetch is in flight, the resumed operation MUST return without
mutating `Items`, advancing `CurrentToken`, changing `HasMore`, or publishing
collection/property notifications.

### 6.3 Conformance

`COL-024` through `COL-030` in `12-conformance.md`.

## 7. Composition with other helpers

### 7.1 Filter-then-page ordering

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

### 7.2 Batch interaction

When a `BatchUpdate()` scope is active, `ObservableList<T>` suppresses granular
events and emits a single `Reset` on completion (per §3.5). A
`PagedComposition<TVM>` wrapping that list observes the `Reset` and recomputes
its page slice. The recomputation happens once after the batch, not once per
item.

### 7.3 `ServicedObservableCollection<T>` with composition helpers

`ServicedObservableCollection<T>` publishes `CollectionChangedMessage` to the
hub on every mutation, even when wrapped by `SearchableState` or
`PagedComposition`. The hub publication is triggered by the mutation, not by
the downstream view's state. Consumers observing the hub receive the raw change
regardless of what filtering or paging is applied on top.

## 8. Conformance

`COL-001` through `COL-064` in `12-conformance.md`. Applicable ADRs:
ADR-0024, ADR-0096, and ADR-0097 (§2), ADR-0026 and ADR-0089 (§3),
ADR-0025 (§4), ADR-0023 (§5), ADR-0069 (§6), and ADR-0085 (shared Move
semantics).

`DISP-006` provides cross-cutting repeated-dispose coverage for the public
collection, paging, batch, and projection helpers that expose disposal. It
retains the in-flight token-page rule in §6 and the non-ownership rule in §2.6.
