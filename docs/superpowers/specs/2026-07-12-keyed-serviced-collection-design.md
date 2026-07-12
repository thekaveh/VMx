# Keyed Serviced Collection Design

Issue: #140\
Target spec: 3.17.0\
Rust source line: 0.17.0

## 1. Problem

`ServicedObservableCollection<T>` now has a complete seven-operation mutation
contract, insertion-order reads, and list-compatible `CollectionChangedMessage<T>`
delivery. It deliberately has no identity index. Consumers that already have a
stable domain key must therefore copy and scan the collection before an upsert,
keyed removal, or keyed repaint.

DayDreams demonstrates the cost on a streamed renderer path. `WorldVM` performs
three `toArray().find/findIndex` operations over `CellVM.coordKey`. Replacing the
collection with `ObservableDictionary` would remove the scans but would also
change ordered item iteration and the renderer-facing message item from
`CellVM` to a dictionary entry.

## 2. Feasibility correction

The issue's original O(1)-expected wording is feasible for key lookup and
target discovery, but not for the complete delete operation while all of these
requirements remain:

- contiguous list indexing;
- stable insertion-order iteration;
- precise pre-removal indices in collection messages; and
- ordinary array/list snapshots.

After a middle deletion, the ordered store shifts and all later key-to-index
entries must be updated. That physical work is O(n). The contract therefore
promises expected O(1) `get`/`has`, expected O(1) target discovery for keyed
delete and upsert, and the existing O(n) ordered-list mutation cost. This still
eliminates the consumer's extra O(n) snapshot allocation and scan.

## 3. Decision

Add a distinct, additive `KeyedServicedObservableCollection<TKey, TItem>` in
every flavor. It is not a mode on the existing class: a distinct type keeps the
unkeyed generic surface and constructor source-compatible and makes the stable
key requirement visible in type choice.

The keyed type preserves the serviced collection's complete list contract:
add, value removal, indexed removal, replacement, whole-list replacement,
move, clear, count, indexed reads, snapshots, insertion-order iteration, local
change delivery, optional hub publication, and caller-owned items. It adds:

| Flavor     | Construction/projector                                                                                                | Lookup/membership                                    | Upsert                                        | Keyed delete                          |
| ---------- | --------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | --------------------------------------------- | ------------------------------------- |
| C#         | `(Func<TItem,TKey> keySelector, IMessageHub? hub = null, IEqualityComparer<TKey>? comparer = null)`, `TKey : notnull` | `TryGetValue(TKey, out TItem?)`, `ContainsKey(TKey)` | `bool Upsert(TItem)` (`true` = Add)           | `bool RemoveKey(TKey)`                |
| Python     | `(key_of: Callable[[T], TKey], hub = None)`, keys must be hashable                                                    | \`get(key) -> T                                      | None`, `contains_key(key) -> bool\`           | `upsert(item) -> bool` (`True` = Add) |
| TypeScript | \`({ keyOf: (item: T) => TKey, hub?: IMessageHub                                                                      | null })`, native `Map\` keys                         | \`get(key): T                                 | undefined`, `has(key): boolean\`      |
| Swift      | `(keyOf: @escaping (T) throws -> Key, hub: MessageHubProtocol? = nil)`, `Key: Hashable`                               | `get(_:) -> T?`, `containsKey(_:) -> Bool`           | `upsert(_:) throws -> Bool` (`true` = Add)    | `delete(_:) -> Bool`                  |
| Rust       | `(owner_id, key_of: Fn(&T) -> VmxResult<K>)` / `with_hub`, `K: Eq + Hash`                                             | `get(&K) -> Option<T>`, `contains_key(&K) -> bool`   | `upsert(T) -> VmxResult<bool>` (`true` = Add) | `remove_key(&K) -> Option<T>`         |

A missing keyed delete is a false/`None` no-op. Upsert of a present key returns
the replacement outcome and emits Replace; Rust's keyed delete returns the
removed value because ownership-returning removal is its established idiom.

Every convenience mutator exposed by the corresponding unkeyed serviced type
is either preserved or deliberately inapplicable, and every preserved mutator
updates the index atomically:

- C#: inherited Add/Insert/value Remove/RemoveAt/indexer/Move/Clear plus
  `Replace` and `ReplaceAll`;
- Python: the full `MutableSequence` integer/slice surface, insert, append,
  clear, value/index removal, replace, replace-all, and move;
- TypeScript: push, pop, value/index removal, splice, replace/setAt,
  replaceAll, move, and clear;
- Swift: append, removeLast, Equatable value removal, indexed remove,
  replace/setAt, replaceAll, move, and clear;
- Rust: push, PartialEq value removal, indexed remove, replace, replace-all,
  move, and clear (the unkeyed Rust type has no positional insert convenience).

## 4. Key contract

The key projection runs before a candidate item is committed. Its result is
captured as the membership key and is not recomputed during lookup. Mutating a
key-like property on an already stored item does not silently reindex it. A
caller that wants a new key uses indexed replacement, whole-list replacement,
or delete plus add/upsert.

After such a property mutation, lookup by the old captured key still returns
the item and lookup by the newly projected key misses. Passing that same item
instance to `upsert` projects the new key and appends a second membership when
that key is absent. Generic value types do not provide a portable identity
constraint, so identity uniqueness is deliberately not imposed. Indexed
same-instance replacement is the explicit rekey operation: it removes the old
captured key and installs the new one at the same position atomically.

Key equality and hashing must remain stable while the captured key is stored.
Each flavor accepts the key universe supported by its native hash map and type
constraints; optional/null-like key behavior is therefore a host-type concern,
not a portable absence sentinel. Unsupported/unhashable keys fail before
mutation where the host can report that failure.

C#, Python, and TypeScript propagate exceptions thrown by user projectors.
Swift projectors are explicitly `throws`, and only operations that project new
items (`append`, insert-equivalent operations, replacement, replace-all, and
upsert) become throwing. Rust projectors return `VmxResult<K>` and the same
operations return `VmxResult`. Projector errors, unsupported keys, or duplicates
discovered during preflight leave collection-owned items, captured keys, index,
and both notification channels unchanged. Atomicity does not roll back arbitrary
side effects performed inside user projector/equality/hash code, allocation
failure, process abort, or subscriber failure after commit.

Append/insert rejects an already captured key. Upsert of a missing key appends
and emits Add. Upsert of an existing key replaces at the same position and
emits Replace, even for the same item instance. Indexed replacement may change
the captured key when the new key is otherwise unused; replacing it with a key
owned by another position is rejected atomically.

`replaceAll` materializes all items, projects every key, and validates uniqueness
before commit. Empty-to-empty is its only no-op; every other valid call emits
one Reset. Duplicate or projection failure emits nothing and preserves the old
state. Passing the collection itself is safe.

## 5. Ordered mutations and messages

Every effective mutation keeps the ordered item store, captured-key sequence,
and key-to-index map synchronized before observers run. Message item/action and
old/new index semantics are exactly those of `ServicedObservableCollection`:

- add and missing-key upsert: Add at the append/insertion position;
- value/index/key removal: Remove with the stored item and pre-removal index;
- indexed replacement and existing-key upsert: Replace at the stable position;
- move: Move with source and destination positions;
- clear and whole-list replacement: Reset.

Equal-index move, empty clear, missing keyed delete, and empty-to-empty
replacement are true no-ops. Value removal follows the base flavor's equality
and missing-value idiom. Invalid positional operations and duplicate-key
operations fail before mutation. Items are never constructed, disposed,
destructed, reparented, or otherwise owned by the collection.

## 6. Delivery, reentrancy, and transactions

The backing state and key index change first, then the local channel fires,
then the optional external hub receives the equivalent message. Reentrant
observers see a consistent final lookup/index state. Subscriber failures retain
the base collection's committed-state policy.

Like the unkeyed serviced collection, the keyed collection has no collection
batch scope. When the injected hub is already inside its transaction/batch,
local notifications remain immediate and granular while hub delivery is
deferred by the hub in original order. Hub batching does not collapse changes
into Reset and does not affect key-index atomicity.

## 7. Conformance

Add `COL-056..064`:

- `COL-056`: captured-key lookup/membership, no post-insertion reprojection,
  and insertion-order snapshots;
- `COL-057`: append/insert uniqueness and atomic duplicate/projection failure;
- `COL-058`: keyed upsert Add/Replace action, stable position, and same-item replacement;
- `COL-059`: keyed delete success/missing behavior and pre-removal index;
- `COL-060`: value/index removal, explicit rekey, and same-instance second
  membership keep the captured index synchronized;
- `COL-061`: atomic whole-list replacement, duplicate rejection, captured keys, and self input;
- `COL-062`: move, clear/no-op behavior, and caller ownership;
- `COL-063`: local-before-hub state visibility and transactional-hub delivery;
- `COL-064`: reentrant mutation preserves state/index consistency and each
  operation's local-before-hub partial order without requiring one portable
  global nested-event order.

All five full-parity flavors implement concrete Given/When/Then assertions for
each catalog entry. An instrumented key projection proves lookup does not
reproject items, while expected O(1) map lookup remains a design/source-review
requirement (and may use countable equality/hash probes in host languages where
that is reliable); wall-clock benchmarks are not conformance tests.

## 8. Documentation and consumer pilot

Document the keyed/unkeyed/dictionary choice, common naming, complexity bounds,
captured-key rule, messages, transactions, and ownership from canonical docs,
then regenerate in-repo, MkDocs `.io`, and native wiki outputs.

In a disposable DayDreams clone pinned to the final VMx branch commit, change
`WorldVM.cells` to the keyed type and replace all three snapshot scans with
`get`/`has`/`upsert`/keyed deletion as appropriate. Preserve explicit `CellVM`
disposal and verify identical renderer Add/Replace/Remove item/index traces.
Never modify or push the real DayDreams checkout.

## 9. Compatibility

The feature is additive. Existing serviced collections, observable lists,
observable dictionaries, messages, and imports retain behavior. Spec and the
four stable flavors advance to 3.17.0; pre-1.0 Rust advances to 0.17.0. Nine
new library IDs raise coverage from 354 to 363 and the full catalog from 359 to
368 scenarios.
