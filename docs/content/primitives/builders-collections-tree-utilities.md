# 6.7. Builders, Collections & Tree Utilities

## When To Use It

Use this area when the question is how to construct primitives, how to expose
observable collections, or how to traverse an existing VM tree.

## Shape And Ownership

Three groups live here:

- immutable fluent builders and additive `create` helpers
- opt-in collection primitives such as `ServicedObservableCollection`,
  `KeyedServicedObservableCollection`, `ObservableList`,
  `ObservableDictionary`, `PagedComposition`, and
  `TokenPagedComposition`
- traversal helpers such as `walk`, `find`, and `walk_expanded`

These pieces are deliberately separate from the core hierarchy so you can opt
into them only where they help.

The core `CompositeVM` / `GroupVM` child surface is a different concern. Both
implement the [VM Collection Contract](vm-collection-contract.md), including
atomic identity-preserving move; selection is a composite-only extension.

## Lifecycle And Messaging

The main operational rules:

- builders are immutable and reusable
- required fields validate on `Build()`
- `ObservableList` and VM container batching are independent scopes
- `ObservableList.replaceAll` / `replace_all` / `ReplaceAll` snapshots input
  before mutation and emits one Reset instead of clear-plus-N-add churn
- `ServicedObservableCollection` publishes local collection events before hub
  messages
- `KeyedServicedObservableCollection` adds a captured-key index without
  changing the ordered serviced message contract
- tree utilities are pure reads; they do not trigger lifecycle transitions

Batch handles, paging helpers, disposable collections, and frozen projections
have type-specific terminal behavior cataloged in the
[Disposal Contract](disposal-contract.md). Serviced collections remain
non-owning and never dispose their items.

## Dynamic Aggregate Change Stream

Use `AggregateChangeStream<T>` when one host adapter must invalidate for both a
live collection's membership and a selected local stream from every current
distinct member. It is a standalone, read-only fan-in helper: it does not add
mutation methods to a collection, create synthetic revision state, or route
member changes through the message hub.

VMx supplies the additive `ObservableMembershipSource<T>` capability on four
source families:

| Supported source                    | Membership meaning                         |
| ----------------------------------- | ------------------------------------------ |
| `CompositeVM`                       | Ordered selectable child membership        |
| `GroupVM`                           | Ordered non-selectable child membership    |
| `ServicedObservableCollection`      | Ordered caller-owned item membership       |
| `KeyedServicedObservableCollection` | Ordered caller-owned keyed item membership |

The capability exposes only an ordered snapshot and a disposable structural
subscription. Every structural pulse causes a committed resnapshot. Add,
remove, replace, move, and reset therefore share one portable path, including
duplicate-reference refcounts and final-removal detachment.

Each output is an `AggregateChange<T>` provenance envelope:

| Reason       | Item    | Meaning                                                            |
| ------------ | ------- | ------------------------------------------------------------------ |
| `Initial`    | absent  | Optional subscriber-local seed after current observation is ready  |
| `Membership` | absent  | One committed structural resynchronization                         |
| `Item`       | present | The identified current member's selected stream emitted            |
| `Batch`      | absent  | One or more changes coalesced by an explicit outer aggregate batch |

The envelope is not a membership snapshot or domain value. An invalidation-only
consumer can ignore its fields; a renderer that needs the changed member can
use `Item` provenance directly.

Construction accepts a selector, so the observed stream may belong to nested
state rather than to the member itself. For example, TypeScript can follow a
cell's nested model state:

```typescript
import {
  AggregateChangeReason,
  AggregateChangeStream,
} from "@thekaveh/vmx";

const aggregate = new AggregateChangeStream(
  cells,
  (cell) => cell.model.state.propertyChanged,
);

const subscription = aggregate
  .observe({ emitInitial: true })
  .subscribe((change) => {
    if (change.reason === AggregateChangeReason.Item) {
      invalidateCell(change.item);
    } else {
      invalidateCanvas();
    }
  });
```

When the member itself is a component, use the standard convenience instead of
repeating that selector:

| Flavor     | Component convenience                           |
| ---------- | ----------------------------------------------- |
| C#         | `AggregateChangeStream.ForComponents(source)`   |
| Python     | `AggregateChangeStream.for_components(source)`  |
| TypeScript | `AggregateChangeStream.forComponents(source)`   |
| Swift      | `AggregateChangeStream.forComponents(source)`   |
| Rust       | `AggregateChangeStream::for_components(source)` |

Selector or selected-subscription setup failure has aggregate-wide terminal
semantics. During construction it throws before an aggregate is returned.
During a later membership reconciliation, VMx transactionally detaches the
structural, staged, and already admitted subscriptions before terminating the
aggregate output with that failure; no partially observed membership remains.

That setup path is different from an event after a selected subscription was
admitted. Selected streams are expected to be non-failing, and Swift and Rust
encode that in their stream types. In the Rx flavors, an unexpected
selected-stream error (or normal completion) ends only that member's current
membership epoch; it does not fail the aggregate or affect other members.
Final removal followed by re-add is what establishes a fresh epoch and
subscription.

Aggregate coalescing is explicit and nested. Hub batching has no portable
completion callback, so combine the scopes at the mutation boundary when one
aggregate pulse and ordered hub delivery must cover the same operation:

```typescript
aggregate.withBatch(() =>
  hub.batch(() => {
    cells.replaceAll(nextCells);
    selected.model.state.refresh();
  }),
);
```

Equivalent APIs are `Batch` in C#, the `batch()` context manager in Python,
`withBatch` in Swift, and `batch` in Rust. Empty scopes emit nothing; a dirty
outermost scope emits one `Batch` even when its body exits with an error.
That envelope goes only to subscriptions active when at least one coalesced
change was admitted. A subscriber joining after all dirtying changes receives
no batch history; it becomes eligible only if a later change occurs before the
outer scope exits.

The host owns the aggregate and its output subscription. Call `dispose` when
the adapter stops: disposal is idempotent and detaches the structural and
selected subscriptions owned by the aggregate. It never disposes, reparents,
removes, or otherwise owns source items.

`ObservableDictionary`, paging projections, and filtered projections are
excluded because their public element identity or visible-membership meaning
needs a separate projection contract. This dynamic fan-in is the decision in
[ADR-0098](../../../spec/ADRs/0098-dynamic-aggregate-change-stream.md). It is
different from [ADR-0095](../../../spec/ADRs/0095-cross-flavor-subscribe-value.md)
`subscribeValue`, which reevaluates selected state for one fixed sender and
does not track changing collection membership.

## Choosing A Collection

| Need                                                                       | Choose                                           |
| -------------------------------------------------------------------------- | ------------------------------------------------ |
| Local granular item streams, a `Count` channel, and nested batch scopes    | `ObservableList<T>`                              |
| Ordered caller-owned items with local changes and optional hub publication | `ServicedObservableCollection<T>`                |
| The same ordered contract plus stable-key lookup, upsert, and deletion     | `KeyedServicedObservableCollection<TKey, TItem>` |
| Two independent keys, dictionary-entry iteration, and live key views       | `ObservableDictionary<TKey1, TKey2, TValue>`     |
| Child construction/destruction, parent membership, or composite selection  | `GroupVM` / `CompositeVM` child collections      |

These contracts are deliberately separate. Choose the unkeyed serviced type
when positional access and ordered iteration are sufficient. Choose the keyed
serviced type when callers would otherwise snapshot and scan that same ordered
list by one stable domain key. Choose `ObservableDictionary` when the public
shape really is a two-key dictionary: it iterates entries rather than bare
stored values and does not substitute for list-compatible positions and
messages.

Neither serviced type batches, publishes a `Count` channel, implements the VM
child-collection lifecycle interfaces, or owns its items. A `GroupVM` or
`CompositeVM` child collection does own membership and lifecycle; use it when
contained values are children rather than caller-owned data.

## Cross-Language Surface

| Primitive                                                      | Purpose                                          |
| -------------------------------------------------------------- | ------------------------------------------------ |
| Builders                                                       | immutable fluent construction with validation    |
| `ServicedObservableCollection<T>`                              | local changes plus optional hub publication      |
| `KeyedServicedObservableCollection<TKey, TItem>`               | ordered serviced changes plus captured-key index |
| `ObservableList<T>`                                            | granular events plus atomic whole-list replace   |
| `ObservableDictionary<K1, K2, V>`                              | dual-key observable lookup plus live key views   |
| `PagedComposition<TVM>` / `TokenPagedComposition<TVM, TToken>` | paging helpers                                   |
| `walk`, `find`, `walk_expanded`                                | tree traversal helpers                           |

## Example

Representative traversal contract:

- `walk(root)` yields root first, then descendants in depth-first pre-order
- `find(root, predicate)` returns the first match in walk order
- `walk_expanded(root)` respects `IExpandable` boundaries

On the collection side, the Notes Workspace note lists and notifications layers
are practical references for observable-list and paging composition.

### Serviced mutation contract

The complete mutation surface is add, remove by value, remove by index,
replace, replace all, move, and clear. See
[Cross-Language Naming](../flavors/cross-language-naming.md) for exact names.

- Value removal targets the first equal match. A missing value returns `false`
  in C#, TypeScript, Swift, and Rust. Python keeps list behavior: successful
  removal returns `None`, while a missing value raises `ValueError`.
- Indexed remove and replace reject invalid bounds before mutation. Python also
  accepts normal negative list indices and reports the resolved nonnegative
  position. Swift's nonthrowing indexed mutators use array preconditions. Rust
  uses `usize`, so negative indices are not representable. Python and Rust
  return the removed or old item from their newly named indexed methods;
  established returns in the other flavors are unchanged.
- `ReplaceAll` first snapshots its input. Iteration failure therefore leaves
  state and streams unchanged. Empty-to-empty is its only no-op; even identical
  non-empty contents produce one Reset.
- `Move` treats both arguments as strict pre-move positions in
  `[0, count)`. Equal positions do nothing; a real move preserves identity and
  emits one Move. Python does not accept negative move indices, and Swift move
  bounds failures throw `VMCollectionIndexError`.
- `Clear` does nothing when already empty and otherwise emits one Reset.

For C#, Python, TypeScript, and Swift, collection messages retain `index` and
add explicit old/new positions:

| Action  | `index`     | old position | new position | Typed items               |
| ------- | ----------- | ------------ | ------------ | ------------------------- |
| Add     | insertion   | `-1`         | insertion    | new                       |
| Remove  | old index   | old index    | `-1`         | old                       |
| Replace | same index  | same index   | same index   | old and new               |
| Move    | destination | source       | destination  | moved item as old and new |
| Reset   | `-1`        | `-1`         | `-1`         | none                      |

The member names follow each language's casing idiom (`OldIndex`,
`old_index`, or `oldIndex`). Rust intentionally keeps its existing non-generic
hub payload: `action`, `old_index: Option<usize>`, and
`new_index: Option<usize>` plus sender/property identity. It has no legacy
`index` field and no item payload.

Every effective mutation changes state first, notifies the local stream second,
and publishes to the optional external hub third. Both observer classes can
read the final state. Delivery is immediate and non-batched. Removing,
replacing, resetting, moving, or clearing never disposes or reparents an item;
the caller keeps lifecycle ownership.

### Keyed serviced mutation contract

`KeyedServicedObservableCollection` preserves the complete ordered mutation
surface above and adds one projected, unique key per membership. Construction
and the four keyed operations use the host-language idiom:

| Flavor     | Construction                                                       | Lookup / membership           | Upsert   | Delete       |
| ---------- | ------------------------------------------------------------------ | ----------------------------- | -------- | ------------ |
| C#         | `new KeyedServicedObservableCollection<TKey,T>(keySelector, hub?)` | `TryGetValue` / `ContainsKey` | `Upsert` | `RemoveKey`  |
| Python     | `KeyedServicedObservableCollection(key_of, hub=None)`              | `get` / `contains_key`        | `upsert` | `delete`     |
| TypeScript | `new KeyedServicedObservableCollection({ keyOf, hub? })`           | `get` / `has`                 | `upsert` | `delete`     |
| Swift      | `KeyedServicedObservableCollection(keyOf:hub:)`                    | `get` / `containsKey`         | `upsert` | `delete`     |
| Rust       | `new(owner_id, key_of)` / `with_hub(owner_id, hub, key_of)`        | `get_by_key` / `contains_key` | `upsert` | `remove_key` |

Rust retains `get(usize)` for positional reads and uses `get_by_key(&K)` for
keyed lookup because Rust cannot overload the two meanings of `get`. Its
captured keys require `Eq + Hash + Send`, not `Clone`; VMx stores them behind
shared ownership internally. The other flavors retain their usual indexed
read spellings alongside the keyed operations.

The projector runs before an add or explicit replacement and its result is
captured for that membership. Lookup, movement, and removal do not run it
again. Mutating a key-like property on an item therefore does not silently
rekey the collection: the old captured key continues to resolve. Indexed
replacement is the explicit atomic rekey operation and keeps the same ordered
position. Delete followed by add/upsert is the other explicit rekey path.
Passing the same mutated instance to upsert can append a second membership
under its newly projected key while the old-key membership remains; VMx does
not impose portable object-identity uniqueness.

All add/insert/replace/whole-list paths reject duplicate captured keys before
commit. Projector, iteration, shape, and duplicate-key failures preserve the
items, keys, index, local stream, and hub stream. `replaceAll` materializes and
validates the entire candidate first, including self input. Python integer and
slice mutation keeps the full `MutableSequence` surface; slice assignment,
slice deletion, and `reverse` are atomic. TypeScript keeps `pop` and native
`splice` normalization while validating the final candidate atomically.

Upsert returns `true` when it appends a missing key with Add and `false` when it
replaces a present key at its stable position. Missing keyed deletion is a
no-op (`false`, or `None` in Rust); Rust returns the removed item in `Option<T>`.
The remaining messages are identical to the unkeyed serviced contract: Remove
uses the pre-removal position, indexed replacement emits Replace at one stable
position, Move emits one Move, and effective clear/whole-list replacement emit
Reset. Same-index move, empty clear, missing keyed deletion, and
empty-to-empty replacement emit nothing.

State settles before observers run. Each effective operation delivers its
local message immediately and then the equivalent message to the optional
external hub. If that hub is already inside a transaction, only the external
message is deferred in hub order; the local stream remains immediate and
granular. The collection has no batch scope of its own and never constructs,
disposes, reparents, or otherwise manages stored-item lifecycle.

Key lookup, membership checks, keyed-delete target discovery, and present-key
upsert target discovery are expected O(1) under the host hash map. Append is
expected amortized O(1) after projection and lookup. Preserving contiguous
ordered positions still makes middle insertion, deletion, movement, and the
associated index repair O(n); keyed deletion removes the caller's extra scan,
not the ordered-store shift.

### ObservableList whole-list refresh

Use the flavor-idiomatic `replaceAll` / `replace_all` / `ReplaceAll` when one
semantic refresh supplies a complete snapshot. VMx materializes the input
before changing the backing list, so passing the list or a live view is safe.
Empty-to-empty does nothing; every other call emits exactly one Reset, including
identical non-empty contents. `Count` follows Reset only when cardinality
changes, and both observers see the final snapshot.

Inside an existing list batch, replacement emits nothing immediately and folds
into the outermost Reset. If the batch body fails after replacement, the scope
still closes, publishes that completed mutation once, and rethrows the original
failure. This is list-local batching; it does not suppress VM container events.

### NNx Studio pilot result

A temporary pilot against NNx Studio commit
`d304336799d4f377c9dd34a465072dd697a8fd7b` replaced the run-history refresh's
four-line clear-plus-push loop with `items.replaceAll(runs)`. The package
typecheck and all 322 viewmodel tests passed. A focused 13-to-13 refresh test
observed one Reset instead of the former Reset plus 13 add events: 14
adapter-visible collection notifications became one. The pilot was validation
only and was not pushed to NNx Studio.

## Common Pitfalls

- Mutating a builder and expecting in-place changes. Builder setters return new
  instances.
- Assuming `ObservableList` batch scopes also suppress `CompositeVM` or
  `GroupVM` collection events. They do not.
- Expecting a serviced collection to batch, emit a `Count` channel, implement
  VM child-collection lifecycle interfaces, or manage item lifecycle. Those
  are intentionally outside its contract.
- Mutating an item's key-like property and expecting lookup to follow it.
  Membership keys are captured; replace the indexed membership or delete and
  add it explicitly.
- Treating expected O(1) keyed target discovery as an O(1) middle deletion.
  Ordered positions still require O(n) shifting and index repair.
- Rebuilding a complete list with `clear` plus repeated adds. That produces
  O(n) adapter notifications; use whole-list replacement for one Reset.
- Rewriting custom tree walkers when the built-in helpers already express the
  intended traversal semantics.

## Related Primitives

- [Composite Family](viewmodel-families/composite-family.md)
- [Hierarchical Family](viewmodel-families/hierarchical-family.md)
- [State & Reactive Helpers](state-reactive-helpers.md)
- [VM Collection Contract](vm-collection-contract.md)
