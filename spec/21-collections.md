# 21 — Collection primitives

Collection primitives are **opt-in, standalone helpers** that complement the
core VM hierarchy (`ComponentVM`, `CompositeVM`, `GroupVM`, `AggregateVM`) with
richer observable-collection behaviour. They are not part of the base VM types;
a consumer chooses which primitives to compose into a given VM.

The shared `CompositeVM` / `GroupVM` child-collection capability and its atomic
identity-preserving `Move` operation are core hierarchy contracts, not
standalone helpers; see chapter 01 §1.4, chapters 06–07, and ADR-0085.

This chapter covers seven primitives:

- `ServicedObservableCollection<T>` — hub-aware observable collection
- `KeyedServicedObservableCollection<TKey, TItem>` — ordered, hub-aware
  collection with a captured-key index
- `ObservableList<T>` — granular per-mutation events
- `ObservableDictionary` — multi-key observable dictionary
- `PagedComposition<TVM>` — finite, index-based paged composition helper
- `TokenPagedComposition<TVM, TToken>` — accumulated, forward-only token paging
- `AggregateChangeStream<T>` — dynamic membership and current-member change
  fan-in

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
| C#         | `(Func<TItem, TKey> keySelector, IMessageHub? hub = null, IEqualityComparer<TKey>? comparer = null)`, `TKey : notnull` | `TryGetValue`, `ContainsKey(TKey)`                         | `bool Upsert(TItem)` (`true` means Add)        | `bool RemoveKey(TKey)`        |
| Python     | `(key_of: Callable[[T], TKey], hub = None)`; keys are hashable                                                         | `get(key) -> Optional[T]`, `contains_key(key) -> bool`     | `upsert(item) -> bool` (`True` means Add)      | `delete(key) -> bool`         |
| TypeScript | options with `keyOf: (item: T) => TKey` and optional nullable `hub`                                                    | `get(key)` returns `T` or `undefined`; `has(key): boolean` | `upsert(item): boolean` (`true` means Add)     | `delete(key): boolean`        |
| Swift      | `(keyOf: @escaping (T) throws -> Key, hub: MessageHubProtocol? = nil)`, `Key: Hashable`                                | `get(_:) -> T?`, `containsKey(_:) -> Bool`                 | `upsert(_:) throws -> Bool` (`true` means Add) | `delete(_:) -> Bool`          |
| Rust       | `new(owner_id, key_of)` / `with_hub(owner_id, hub, key_of)`, `K: Eq + Hash`                                            | `get_by_key(&K) -> Option<T>`, `contains_key(&K) -> bool`  | `upsert(T) -> VmxResult<bool>` (`true` = Add)  | `remove_key(&K) -> Option<T>` |

The exact Python miss annotation is `get(key) -> T | None`. The exact
TypeScript options shape is
`{ keyOf: (item: T) => TKey; hub?: IMessageHub | null }`, and its lookup is
`get(key): T | undefined`.

C# lookup has the exact nullable-flow contract
`bool TryGetValue(TKey key, [MaybeNullWhen(false)] out TItem item)`: `true`
means `item` is the stored value, while `false` permits the out value to be
null/default. The attribute is
`System.Diagnostics.CodeAnalysis.MaybeNullWhenAttribute` (or the repository's
target-framework polyfill).

Rust's exact constructor and newly fallible projecting signatures are:

```rust
pub fn new<F>(owner_id: usize, key_of: F) -> Self
where F: Fn(&T) -> VmxResult<K> + Send + Sync + 'static;

pub fn with_hub<F>(owner_id: usize, hub: MessageHub, key_of: F) -> Self
where F: Fn(&T) -> VmxResult<K> + Send + Sync + 'static;

pub fn push(&self, item: T) -> VmxResult<()>;
pub fn replace(&self, index: usize, item: T) -> VmxResult<T>;
pub fn replace_all<I>(&self, items: I) -> VmxResult<()>
where I: IntoIterator<Item = T>;
pub fn upsert(&self, item: T) -> VmxResult<bool>;
```

Its existing `remove_at` and `move_item` bounds failures remain `VmxResult`;
nonprojecting `remove`, `remove_key`, and `clear` retain their non-fallible
signatures.

Swift's projector can fail, so its exact newly throwing mutator surface is:

```swift
func append(_ item: T) throws
func replace(at index: Int, with newItem: T) throws
func setAt(_ index: Int, _ newItem: T) throws
func replaceAll<S: Sequence>(_ newItems: S) throws where S.Element == T
func upsert(_ item: T) throws -> Bool
```

Removal, move, and clear retain the unkeyed signatures because they use
captured keys and do not invoke the projector.

A missing keyed deletion is a false / `None` no-op. Rust returns the removed
value because ownership-returning removal is its established idiom. An upsert
of a missing key returns the Add outcome; an upsert of a present key returns
the replacement outcome.

Every list convenience exposed by the corresponding unkeyed serviced type is
preserved and keeps the key index synchronized:

- C#: inherited Add, Insert, value Remove, RemoveAt, indexer replacement, Move,
  and Clear, plus Replace and ReplaceAll;
- Python: the full `MutableSequence` integer/slice surface, insert, append,
  clear, value/index removal, replacement, replace-all, move, and reverse;
- TypeScript: push, pop, value/index removal, splice, replace/setAt,
  replaceAll, move, and clear;
- Swift: append, removeLast, Equatable value removal, indexed removal,
  replace/setAt, replaceAll, move, and clear; and
- Rust: push, PartialEq value removal, indexed removal, replace, replace-all,
  move, and clear. The unkeyed Rust type has no positional-insert convenience,
  so the keyed type does not invent one.

Rust retains the unkeyed `get(usize) -> Option<T>` indexed read and names the
additional keyed lookup `get_by_key(&K) -> Option<T>`. Rust has no method
overloading, and keeping both concepts as `get` would be ambiguous when the key
type is `usize`. This is an idiomatic naming adaptation under ADR-0006, not a
semantic divergence.

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

Duplicate-key failure types are exact: C# throws `ArgumentException`, Python
raises `ValueError`, TypeScript throws `Error`, Swift throws
`KeyedServicedCollectionError.duplicateKey`, and Rust returns
`Err(VmxError::InvalidArgument(_))`. Projector errors propagate unchanged
instead of being rewritten as duplicate errors.

Python slice assignment and deletion, and TypeScript `splice`, preflight the
operation's complete final result. They first materialize inserted input,
project every inserted item, apply native index/slice normalization to a
candidate ordered item/captured-key sequence, and validate uniqueness across
that candidate. Retained memberships keep their captured keys; removed keys
are absent from final-result validation and MAY be reused by an item inserted
by the same operation. Python's extended-slice cardinality rules and
TypeScript's normalized `start` / `deleteCount` behavior remain native.

Only after successful final-result validation does the operation atomically
commit items, captured keys, and the index. Duplicate, projection, input
iteration, or native slice-shape failure changes nothing and emits nothing.
On success, Python slice mutation emits its established Reset. TypeScript
`splice` returns the removed items and preserves the unkeyed notification
rule: a removal of exactly one item with no inserts emits Remove, any other
effective splice emits Reset, and removal/insertion of nothing emits nothing.

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

Python reverse atomically reverses the ordered items and their captured keys
without reprojecting them. Lengths zero and one are no-ops; reversing two or
more memberships emits exactly one Reset.

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

After projection and hash lookup, Python append and present-key upsert do not
scan or rebuild existing memberships; their collection-owned work is expected
amortized O(1).

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
an internal `CompositeKey` value in Swift, and nested native `Map` instances in
TypeScript (the entry type exposed to consumers remains `DictionaryEntry`). Each
axis uses the host language's standard dictionary-key equality; in TypeScript
that is `Map`'s SameValueZero primitive equality and reference identity for
objects. There is no single-key base type. (Corrected in v2.5.0 via ADR-0038
and in v3.22.0 via ADR-0111.)

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

### 7.3 Serviced collections with composition helpers

`ServicedObservableCollection<T>` publishes `CollectionChangedMessage` to the
hub on every mutation, even when wrapped by `SearchableState` or
`PagedComposition`. The hub publication is triggered by the mutation, not by
the downstream view's state. Consumers observing the hub receive the raw change
regardless of what filtering or paging is applied on top.

`KeyedServicedObservableCollection<TKey, TItem>` composes with the same helpers
through its ordinary ordered read and collection-change surface. Filtering and
paging operate on stored items in insertion order; the captured-key index is an
additional lookup facility and requires no adapter, special-case projection,
or dictionary-entry wrapper. Hub observers likewise receive the raw
list-compatible keyed-collection mutation before any downstream view logic.

## 8. Conformance

`COL-001` through `COL-064` and `AGCH-001` through `AGCH-010` in
`12-conformance.md`. Applicable ADRs:
ADR-0024, ADR-0096, and ADR-0097 (§2), ADR-0026 and ADR-0089 (§3),
ADR-0025 (§4), ADR-0023 (§5), ADR-0069 (§6), and ADR-0085 (shared Move
semantics), and ADR-0098 (§9).

`DISP-006` provides cross-cutting repeated-dispose coverage for the public
collection, paging, batch, aggregate, and projection helpers that expose
disposal. It retains the in-flight token-page rule in §6 and the non-ownership
rule in §2.6.

## 9. Dynamic aggregate change stream

Per ADR-0098, `AggregateChangeStream<T>` observes one live membership source
and the selected local change stream of every current distinct member. It is a
standalone helper, not a collection, a hub extension, or application revision
state.

### 9.1 Read-only membership source

VMx defines an additive read-only capability with this portable shape:

```text
ObservableMembershipSource<T>:
    snapshot() -> ordered snapshot<T>
    subscribe_membership(callback) -> disposable subscription

AggregateChange<T>:
    Reason : Initial | Membership | Item | Batch
    Item   : T?  # present only for Item

AggregateChangeStream<T>:
    constructor(source, observe_item)
    observe(emit_initial = false) -> hot observable/publisher
    batch()/withBatch(callback) -> explicit ref-counted coalescing scope
    dispose()
```

The exact idiomatic capability surface is:

| Flavor     | Capability                                       | Snapshot                      | Structural subscription                         |
| ---------- | ------------------------------------------------ | ----------------------------- | ----------------------------------------------- |
| C#         | `IObservableMembershipSource<T>`                 | `IReadOnlyList<T> Snapshot()` | `IDisposable SubscribeMembership(Action)`       |
| Python     | `ObservableMembershipSource[T]` protocol         | `snapshot() -> tuple[T, ...]` | `subscribe_membership(callback) -> Disposable`  |
| TypeScript | `ObservableMembershipSource<T>`                  | `snapshot(): readonly T[]`    | `subscribeMembership(callback): Subscription`   |
| Swift      | `ObservableMembershipSource` (`Item: AnyObject`) | `snapshot() -> [Item]`        | `subscribeMembership(_:) -> AnyCancellable`     |
| Rust       | `ObservableMembershipSource<T: VmNode>`          | `snapshot() -> Vec<T>`        | `subscribe_membership(handler) -> Subscription` |

Rust's exact additive contract, including its handler bounds, is:

```rust
pub trait ObservableMembershipSource<T>: Clone + Send + Sync + 'static
where
    T: VmNode,
{
    fn snapshot(&self) -> Vec<T>;
    fn subscribe_membership<F>(&self, handler: F) -> Subscription
    where
        F: Fn() + Send + Sync + 'static;
}
```

The source's `Clone` is a shared handle, not a copied collection. `VmNode`,
`VmCollection`, and all other existing Rust collection traits remain unchanged;
external implementations gain no requirement.

The capability is independent of every existing collection interface,
protocol, and trait. Existing external implementations gain no requirement.
VMx supplies it directly on these source families:

1. `CompositeVM`;
1. `GroupVM`;
1. `ServicedObservableCollection`; and
1. `KeyedServicedObservableCollection`.

Its snapshot is ordered. Its subscription emits a payload-free structural
pulse for Add, Remove, Replace, Move, or Reset on normal VM collections and for
the corresponding existing local notification on serviced sources. The
aggregate resnapshots committed membership on every pulse; it does not
interpret an event payload. The capability has no mutation, selection,
lifecycle, batching, or ownership surface.

`ObservableDictionary`, paging projections, and filtered projections do not
participate. Their element or visible-membership projection requires a separate
decision.

### 9.2 Selected change streams and envelope

Construction requires `observe_item`, a selector for each member's local
change stream. It MAY select nested state rather than the member's own property
stream. Every flavor also provides an idiomatically named `ForComponents` /
`for_components` / `forComponents` convenience that selects the standard
component property-change stream.

Rust's `for_components` convenience is constrained by this separate additive
trait:

```rust
pub trait ObservablePropertySource: VmNode {
    fn property_changed(&self) -> PropertyChangedStream;
}
```

The general selector overload does not require `ObservablePropertySource`.
This trait does not extend or modify `VmNode`, so existing external `VmNode`
implementations remain source compatible.

The aggregate output is hot. Each envelope has exactly one reason:

| Reason       | Item    | Meaning                                                                |
| ------------ | ------- | ---------------------------------------------------------------------- |
| `Initial`    | absent  | Optional subscriber-local seed after current state is ready            |
| `Membership` | absent  | Ordered membership has committed a structural resynchronization        |
| `Item`       | present | The named current distinct member's selected change stream emitted     |
| `Batch`      | absent  | One or more admitted changes were coalesced by an explicit outer batch |

The envelope reports provenance only. It is not a membership snapshot,
revision counter, or domain value. Consumers needing only invalidation MAY
ignore its fields.

Initial delivery is selected per output subscription, not at aggregate
construction. Registration and the one private `Initial` envelope occur under
the same serialized gate as normal delivery. The seed therefore precedes every
later admitted change for that subscriber. It does not enter the shared hot
stream, replay history, or reach subscribers that did not request it.

### 9.3 Identity multiset and epochs

Membership uses reference identity in C#, Python, TypeScript, and Swift, and
`VmNode::id()` in Rust. Equal-but-distinct reference objects remain distinct.
Rust treats equal IDs as one logical member under its existing VM identity
contract. The aggregate supports identity-bearing reference/VM items; it does
not define value identity for primitive or copy-only serviced items.

Null members are invalid. C# and Python reject them with an idiomatic
argument/value error, strict TypeScript excludes them statically and validates
runtime input, and Swift and Rust make null unrepresentable.

Repeated occurrences of one identity increment a refcount and share exactly
one selected-stream subscription. One selected notification emits one `Item`,
not one per occurrence. Removing one duplicate preserves observation. Removing
the final occurrence detaches it before delivering the corresponding
`Membership` event.

Every admitted identity has a monotonically increasing membership epoch.
Identity-retaining Replace, Reset, Move, and duplicate add preserve that epoch
and subscription. Selected-stream completion or unexpected selected-stream
error terminates the current positive-refcount epoch without changing source
membership or emitting an aggregate event. It does not resubscribe on Move,
Reset with identity retained, or duplicate add. Only final removal followed by
re-add creates a new epoch and selected subscription.

Queued item work carries its epoch. The serialized drain discards it when the
identity reached zero refcount or that epoch's selected stream terminated. A
stale callback can therefore never become an `Item` event for a later re-add.

### 9.4 Setup and structural reconciliation

Construction subscribes to structural changes under the serialized gate before
taking its first snapshot. If a structural callback occurs during setup, the
snapshot is stale and reconciliation repeats until it commits a snapshot with
no intervening structural callback. This construction-time reconciliation
commits only the latest membership. It queues no `Membership` event for replay;
the optional subscriber-local `Initial` envelope represents readiness. A
structural pulse admitted after construction queues exactly one `Membership`
after its successful resynchronization.

For every structural pulse, the aggregate snapshots and stages all newly
required selected subscriptions before changing its admitted table. Retained
identities keep their epoch and subscription. Only after complete staging
succeeds does it commit the new identity multiset, detach zero-refcount entries,
and settle the reconciliation. That commit queues `Membership` only when the
structural pulse was admitted after construction; setup-race reconciliation
remains silent.

Selected streams MAY emit synchronously while their subscriptions are staged.
During initial construction, those values are pre-existing state and are
discarded; the optional `Initial` seed represents readiness. During a later
structural resynchronization, staged values are buffered and queued behind that
resynchronization's `Membership` envelope after commit.

### 9.5 Ordering, reentrancy, and failure

All aggregate envelopes use one serialized FIFO drain. State and subscription
changes settle before an envelope is queued. Reentrant structural or item
activity appends behind the envelope currently being delivered rather than
recursively mutating the membership table.

The selector is a total, nonthrowing precondition. C#, Python, and TypeScript
nevertheless handle a selector or selected-subscription failure
transactionally. Null, selector, or selected-subscription failure is terminal:
before throwing or delivering the output error, the aggregate detaches its
structural subscription and every staged and admitted item subscription. It
admits no partial membership and becomes inert. A construction failure throws
synchronously before an aggregate is returned. Later failure terminates the
existing output with the same error; mutator propagation follows the host
reactive convention, so portable callers rely on the terminal output error.

Selected streams are non-failing in Swift and Rust. In Rx flavors, unexpected
selected-stream error has the same item-epoch-only effect as completion: no
aggregate event, no failure of the aggregate, and no effect on other members.

Subscriber failures follow the established host reactive primitive. They MUST
NOT corrupt membership bookkeeping or detach unrelated item subscriptions
beyond host-library behavior; message-hub subscriber isolation is not promised
for this local stream.

### 9.6 Explicit batching and hub composition

The aggregate owns a synchronous, nested, ref-counted batch/defer scope.
Outside a batch, every admitted structural or item change emits immediately.
Inside any batch depth, changes only mark the aggregate dirty. The outermost
exit emits exactly one `Batch` if dirty. An empty batch emits nothing.

Batch delivery preserves the hot/no-history rule. At each coalesced change,
the aggregate unions the output subscriptions that are active at that change's
admission. Outermost exit offers the final `Batch` only to that union, after
discarding subscriptions cancelled before delivery. A subscriber joining after
all dirtying changes receives no historical `Batch`; if another change is
admitted after it joins but before exit, it becomes eligible for that final
envelope.

If a body admits a change and then fails, outermost cleanup emits the one
`Batch` and rethrows the original failure. Cleanup MUST NOT replace the body
failure. A native collection batch that publishes one Reset naturally causes
one `Membership` event.

If delivery of the final `Batch` synchronously throws from a subscriber while
the body failure is already active, cleanup MUST suppress that delivery
exception and rethrow the original body failure. If the body succeeded, a
synchronous subscriber failure follows the host reactive convention. This is
only an exception-precedence rule for batch cleanup; it does not promise general
subscriber isolation.

Hub batching has no portable end-boundary or idle callback and is not detected
automatically. A consumer that requires one pulse nests scopes explicitly:

```text
aggregate.withBatch(() => hub.batch(() => mutate()))
```

Hub batching retains its own lossless message ordering; the aggregate batch
controls only aggregate output.

### 9.7 Completion, disposal, and ownership

The aggregate owns only its structural and selected-item subscriptions.
Explicit disposal is idempotent, detaches all of them, completes aggregate
output where the host convention supports completion, and makes later source
activity inert. It never constructs, destructs, disposes, reparents, removes,
or otherwise manages a source item.

The supported source families expose no common source-completion signal.
Source lifetime therefore does not replace explicit aggregate disposal.

### 9.8 Conformance

`AGCH-001` through `AGCH-010` in `12-conformance.md` cover atomic
subscriber-local initial delivery, committed membership resynchronization,
item provenance, zero-refcount and terminal-epoch silence, Reset, duplicate
refcounts, nested exceptional batching, empty batches and Move stability,
reentrant FIFO and stale epochs, transactional failure, disposal, ownership,
and subscriber isolation.
