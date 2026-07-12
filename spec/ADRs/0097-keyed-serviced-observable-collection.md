# ADR 0097 — Add an ordered keyed serviced collection

**Status:** Accepted (2026-07-12)
**Spec version:** introduced in 3.17.0
**Related:** ADR-0006, ADR-0009, ADR-0024, ADR-0085, ADR-0089, ADR-0096,
issue #140

## 1. Context

`ServicedObservableCollection<T>` now provides the same complete ordered-list
mutation and notification contract in all five full-parity flavors. It
deliberately has no identity index. A consumer with a stable domain key must
therefore allocate or enumerate a snapshot and scan it before an upsert, keyed
removal, or keyed repaint.

Replacing the serviced collection with `ObservableDictionary` is not
equivalent: it changes the renderer-facing item from the stored value to a
dictionary entry, changes the public access shape, and does not preserve the
same list-compatible mutation messages and indexed iteration contract.

The original request described keyed deletion as expected O(1). Hash lookup and
target discovery can meet that bound, but a complete middle deletion cannot do
so while also preserving contiguous indices, insertion-order iteration,
precise pre-removal message positions, and ordinary array/list snapshots. The
ordered store shifts and later key-to-index entries require repair.

## 2. Decision

### 2.1 Add a distinct keyed type

Every flavor adds an additive
`KeyedServicedObservableCollection<TKey, TItem>` (with idiomatic generic
spelling and method casing). It is not a mode on
`ServicedObservableCollection<T>`. Existing unkeyed constructors, generic
signatures, behavior, and imports remain unchanged.

The keyed type preserves its flavor's full unkeyed serviced surface, ordered
reads, insertion-order iteration, snapshots, local change channel, optional
external hub, message shape, and caller-owned item lifecycle. It adds:

- C#: a `Func<TItem, TKey>` projector, optional hub and optional
  `IEqualityComparer<TKey>` (`TKey : notnull`); `TryGetValue`, `ContainsKey`,
  `Upsert`, and `RemoveKey`;
- Python: a hashable-key `key_of` callable and optional hub; `get`,
  `contains_key`, `upsert`, and `delete`;
- TypeScript: `{ keyOf, hub? }` options using native `Map` key semantics;
  `get`, `has`, `upsert`, and `delete`;
- Swift: a throwing `keyOf` closure, optional hub, and `Key: Hashable`; `get`,
  `containsKey`, `upsert`, and `delete`; and
- Rust: `owner_id` plus a `Fn(&T) -> VmxResult<K>` projector, with a
  `with_hub` variant and `K: Eq + Hash`; `get`, `contains_key`, `upsert`, and
  `remove_key`.

C# lookup is exactly
`bool TryGetValue(TKey key, [MaybeNullWhen(false)] out TItem item)`, matching
the repository's nullable-flow dictionary contract. Rust construction is
exactly `new(owner_id, key_of)` and `with_hub(owner_id, hub, key_of)`, retaining
the unkeyed type's leading `owner_id, hub` order.

Upsert returns `true` for Add and `false` for Replace. A missing keyed deletion
is a false / `None` no-op. Rust's `remove_key` returns `Option<T>` because
ownership-returning removal is its established idiom.

Every convenience mutator exposed by the corresponding unkeyed serviced type
is either preserved or deliberately inapplicable. C# keeps inherited Insert;
Python keeps its `MutableSequence` integer and slice surface, including atomic
reverse; TypeScript keeps pop and splice; Swift keeps removeLast and its
Equatable value-removal extension; Rust keeps the unkeyed type's surface
without inventing positional insert. Every preserved path maintains the keyed
index.

Swift's newly projecting append, replace/setAt, replaceAll, and upsert methods
are throwing. Rust's exact newly fallible methods are
`push(T) -> VmxResult<()>`, `replace(usize, T) -> VmxResult<T>`,
`replace_all(I) -> VmxResult<()>`, and `upsert(T) -> VmxResult<bool>`; its
projector generic is `Fn(&T) -> VmxResult<K> + Send + Sync + 'static`.

### 2.2 Capture one key per membership

The projector runs before a candidate item is committed. Its result is captured
for that membership and is not recomputed during lookup, membership, move, or
removal. Mutating a key-like property on a stored item does not silently
reindex it: the old captured key still resolves and the newly projectable key
does not.

Indexed replacement is the explicit atomic rekey operation: it removes the old
captured key and installs the new projection at the same position when that key
is otherwise unused. Whole-list replacement reprojects every replacement
membership. Delete followed by add/upsert is the other explicit rekey path.

Passing the same stored instance to upsert after mutating its key-like property
projects the new key. If that key is absent, it appends a second membership for
the same instance. Portable generic value types do not support an identity
uniqueness requirement. If the projected key is already present, upsert emits
Replace at that key's stable position, even for the identical instance.

Captured key equality and hashing must remain stable while stored. Each flavor
accepts the key universe supported by its native hash map and type constraints;
optional/null-like key behavior is not a portable absence sentinel.

### 2.3 Enforce uniqueness and failure atomicity

Add and, where available, insert reject a key already captured by another
membership. Indexed replacement rejects a key owned by another position.
Upsert intentionally treats a present key as its replacement target.

`ReplaceAll` first materializes all items, projects all keys, and validates
uniqueness before commit. Self input is safe. Empty-to-empty is its only no-op;
every other valid call emits one Reset. Duplicate, input-iteration, unsupported
key, or projector failure preserves ordered items, captured keys, the
key-to-index map, and both notification channels.

C#, Python, and TypeScript propagate projector exceptions. Swift projectors are
throwing, and operations that project new items become throwing. Rust
projectors and projecting operations return `VmxResult`. This promise excludes
arbitrary side effects inside consumer projector/equality/hash code, allocation
failure, process abort, and subscriber failure after commit.

Duplicate candidates fail as `ArgumentException` in C#, `ValueError` in
Python, `Error` in TypeScript,
`KeyedServicedCollectionError.duplicateKey` in Swift, and
`VmxError::InvalidArgument` in Rust. Projector failures propagate unchanged.

Python slice assignment/deletion and TypeScript splice build and validate the
complete candidate result before commit. Inserted input is materialized and
projected; retained memberships keep captured keys; keys removed by the same
operation are available to its inserted items. Native slice/splice index and
shape rules apply to the candidate. Any duplicate, projection, iteration, or
shape failure preserves state and emits nothing. A successful Python slice
mutation emits Reset. TypeScript preserves its existing splice result and
message rules: return removed items, use Remove for one removal and no inserts,
Reset for any other effective splice, and no event for no mutation.

### 2.4 Preserve ordered mutation and message semantics

An effective operation synchronizes the ordered item store, captured-key
sequence, and key-to-index map before any observer runs. Add, insert, and a
missing-key upsert emit Add. Value/index/key removal emits Remove with the
pre-removal position. Indexed replacement and present-key upsert emit Replace
at the stable position. Move emits one Move. Clear and whole-list replacement
emit Reset.

Python reverse retains captured keys without reprojection. Lengths zero and
one are no-ops; reversing two or more memberships emits exactly one Reset.

Value removal uses the base flavor's first-equal-occurrence and missing-value
idiom. Equal-index move, empty clear, missing keyed deletion, and empty-to-empty
replacement are true no-ops. Bounds, typed/non-generic payloads, old/new
positions, and subscriber-failure policy remain those of ADR-0096.

### 2.5 State the achievable complexity bound

Lookup and membership are expected O(1), as is target discovery for keyed
delete and upsert, subject to the native hash map. Ordered-list shifts and
key-to-index repair remain O(n) for middle insertion, deletion, and move. This
eliminates the consumer's extra snapshot allocation and linear target scan
without promising constant-time physical mutation.

After projection and hash lookup, Python append and present-key upsert do not
scan or rebuild existing memberships; their collection-owned work is expected
amortized O(1).

Expected O(1) lookup is reviewed structurally. Countable equality/hash probes
may support host-specific tests, but wall-clock benchmarks are not portable
conformance cases.

### 2.6 Preserve delivery, transactions, reentrancy, and ownership

Each effective mutation commits all item/key/index state, delivers the local
channel, then publishes the equivalent message to the optional hub. Reentrant
observers always see a consistent index. Each nested operation preserves its
own local-before-hub partial order; no one global nested-event sequence is
portable.

The keyed collection has no collection batch scope. If the injected hub is
already in a transaction/batch, local changes remain immediate and granular;
hub messages are deferred in original hub order and are not collapsed to Reset.

The collection never constructs, disposes, destructs, reparents, or otherwise
owns contained items. Projection and indexing do not alter caller lifecycle
responsibility.

The keyed type supplies the same ordered read and collection-change surface to
`SearchableState` and `PagedComposition`; its index requires no adapter or
dictionary-entry wrapper.

### 2.7 Conformance

`COL-056..064` cover captured lookup and ordering, uniqueness/failure
atomicity, upsert, keyed deletion, index synchronization and explicit rekey,
whole-list replacement, move/clear/ownership, local/hub transaction delivery,
and reentrant consistency in all five full-parity flavors.

## 3. Consequences

- Consumers with stable keys can keep list-compatible rendering and message
  payloads while removing repeated snapshot scans.
- The feature is additive; unkeyed serviced collections, observable lists,
  observable dictionaries, and existing messages retain their contracts.
- Implementations carry an ordered item store, a parallel captured-key
  sequence, and a key-to-index map that must commit atomically.
- The specification and four stable flavors advance to 3.17.0; pre-1.0 Rust
  advances to 0.17.0. Nine new library IDs raise coverage from 354 to 363 and
  the full catalog from 359 to 368 scenarios.

## 4. Rejected alternatives

### 4.1 Add a keyed mode to the unkeyed type

Rejected. Optional key configuration would obscure which operations and
invariants are available and would complicate existing generic constructors.

### 4.2 Replace the ordered collection with `ObservableDictionary`

Rejected. It changes iteration/access and message element shape rather than
adding an index to the existing ordered serviced contract.

### 4.3 Reproject keys on every lookup

Rejected. It restores O(n) scans, lets mutable item properties silently change
membership, and makes lookup capable of unexpected projector failure.

### 4.4 Promise O(1) complete keyed deletion

Rejected. That conflicts with contiguous indexing, insertion order, precise
list positions, and ordinary snapshots. Target discovery is O(1)-expected;
physical ordered-list repair is not.

### 4.5 Impose item identity uniqueness

Rejected. It is not portable across generic value/reference type systems and is
unnecessary once membership identity is the captured key.
