# ADR 0096 — Complete serviced collection parity

**Status:** Accepted (2026-07-11)
**Spec version:** introduced in 3.16.0
**Related:** ADR-0006, ADR-0009, ADR-0024, ADR-0085, ADR-0089, issue #90

## 1. Context

Chapter 21 already declares `ServicedObservableCollection<T>` as a standalone,
hub-aware collection with add, remove, replace, whole-list replacement, clear,
and deterministic local-before-hub delivery. The shipped flavors expose uneven
subsets of that contract. C# inherits most single-item operations but does not
forward its inherited Move to the hub and has no atomic `ReplaceAll`; Python,
TypeScript, and Swift each omit parts of the declared named surface; Rust has
no distinct serviced collection and has used `ObservableList<T>` for the
serviced conformance cases.

`ObservableList<T>` and the shared VM collection contract now have precise
whole-list replacement and move semantics through ADR-0089 and ADR-0085. The
serviced collection needs the same operations without acquiring list batching,
VM ownership, selection, or keyed-lookup responsibilities.

## 2. Decision

### 2.1 Common surface

Every flavor provides a real `ServicedObservableCollection<T>` with this
idiomatic conceptual surface:

| Concept      | C#                  | Python        | TypeScript                   | Swift                                  | Rust          |
| ------------ | ------------------- | ------------- | ---------------------------- | -------------------------------------- | ------------- |
| Add          | `Add`               | `append`      | `push`                       | `append`                               | `push`        |
| Remove value | `Remove`            | `remove`      | `remove`                     | `remove`                               | `remove`      |
| Remove index | `RemoveAt`          | `remove_at`   | `removeAt`                   | `removeAt`                             | `remove_at`   |
| Replace      | indexer / `Replace` | `replace`     | `replace` (`setAt` retained) | `replace(at:with:)` (`setAt` retained) | `replace`     |
| Replace all  | `ReplaceAll`        | `replace_all` | `replaceAll`                 | `replaceAll`                           | `replace_all` |
| Move         | `Move`              | `move`        | `move`                       | `move(from:to:)`                       | `move_item`   |
| Clear        | `Clear`             | `clear`       | `clear`                      | `clear`                                | `clear`       |

Existing indexers and array-ergonomic aliases remain source-compatible. Rust's
type is a distinct public primitive with its own local hub-backed change stream
and optional external hub; it is neither an alias nor a replacement for
`ObservableList<T>`.

### 2.2 Single-item operations

Value removal removes the first equal occurrence only. A missing value is a
no-op returning false except in Python, which preserves the standard
`MutableSequence.remove` contract: return `None` on success and raise
`ValueError` when absent.

C#, TypeScript, and Swift indexed removal and replacement reject indices outside
`[0, Count)` atomically. Rust uses `usize`, making negative indices
unrepresentable, and rejects values at or above `Count`. Python preserves normal
negative-index resolution for these operations and reports the resolved
nonnegative position; an excessively negative or positive index raises
`IndexError`. Swift preserves its established array-precondition behavior for
its nonthrowing indexed mutators. Newly named Python and Rust operations return
the removed or old value where idiomatic; established void returns remain
unchanged.

Replacement always emits one Replace, even when the old and new items are
identical or equal. The unconstrained generic does not compare items to
suppress the mutation.

### 2.3 Whole-list operations

`ReplaceAll` fully materializes its input before changing the backing store, so
self or live-view input is safe and iteration failure is atomic. Empty-to-empty
is its only no-op. Every other call, including identical non-empty contents,
emits one Reset and no granular messages. Serviced collections have no `Count`
property-change channel.

Clearing an empty collection is a true no-op. Clearing a non-empty collection
emits exactly one Reset. Serviced collections do not batch; every effective
operation delivers immediately.

### 2.4 Move

Move is part of the common serviced contract and reuses ADR-0085. Both indices
address the pre-move collection and must be in `[0, Count)`. C#, Python,
TypeScript, and Swift reject negative Move indices; Rust's `usize` indices make
negative values unrepresentable. Other invalid indices raise a
flavor-idiomatic catchable bounds error before mutation, including Swift's
existing `VMCollectionIndexError`. Equal indices are a true no-op.

A successful move preserves item identity. C#, Python, TypeScript, and Swift
emit exactly one Move naming the identical item, source index, and destination
index. Rust preserves the identical item in the final collection contents but
its non-generic message emits only Move plus the present optional source and
destination positions.

Move changes ordering only. It does not construct, dispose, reparent, detach,
or otherwise manage the item.

### 2.5 Message compatibility and delivery

In C#, Python, TypeScript, and Swift, `CollectionChangedMessage` adds explicit
old and new integer positions while retaining the existing `index` member and
constructor/factory defaults:

| Action  |     `index` |  `oldIndex` |  `newIndex` |
| ------- | ----------: | ----------: | ----------: |
| Add     |   insertion |          -1 |   insertion |
| Remove  | pre-removal | pre-removal |          -1 |
| Replace |    replaced |    replaced |    replaced |
| Move    | destination |      source | destination |
| Reset   |          -1 |          -1 |          -1 |

These four flavors use `-1` for an absent position. Add carries the new item,
Remove the old item, Replace both old and new items, and Move the identical
moved item as old and new; Reset carries neither. Existing consumers that read
only `index` retain its historical meaning.

Rust preserves the non-generic hub message established by ADR-0085. It carries
`action`, `old_index: Option<usize>`, and `new_index: Option<usize>` plus sender
and property identity. It has no legacy `index` member and no typed old/new item
payloads. Add is `(None, Some(insertion))`, Remove is
`(Some(pre-removal), None)`, Replace and Move carry two present positions, and
Reset is `(None, None)`.

Every effective mutation changes backing state, delivers the local collection
change, then publishes the equivalent message to the optional external hub.
Both observer classes can read the complete final state. Subscriber failures
follow the established local-reactive and message-hub delivery rules; this
decision adds no new failure policy. The collection does not marshal or batch
delivery.

### 2.6 Ownership and conformance

The collection never owns, constructs, disposes, reparents, or otherwise
manages contained items. Callers retain lifecycle responsibility across every
removal, replacement, reset, and move.

`COL-048..055` cover value removal, indexed removal, replacement, whole-list
replacement, move, delivery ordering, clear behavior, and non-ownership in all
five full-parity flavors. Rust's `COL-001..004` cases move from
`ObservableList<T>` to its real serviced type.

## 3. Consequences

- Consumers can express serviced removal, replacement, and reordering without
  hand-written index/splice or clear/add notification rituals.
- C# Move becomes visible on the hub and empty Clear stops producing a Reset;
  those are deliberate behavior corrections to the common contract.
- The specification and stable flavors advance to 3.16.0; pre-1.0 Rust advances
  to 0.16.0. Eight new library IDs raise the catalog from 346 to 354 library
  IDs and from 351 to 359 total IDs.
- Keyed lookup and indexed collection derivatives remain issue #140.

## 4. Rejected alternatives

### 4.1 Keep Move as a C#-only unforwarded affordance

Rejected. It preserves accidental drift after Move already gained a precise
portable contract in ADR-0085 and leaves hub consumers unable to distinguish a
reorder.

### 4.2 Alias Rust's `ObservableList<T>`

Rejected. A serviced collection has an optional external hub and
local-before-external delivery semantics, while `ObservableList<T>` has split
granular streams, a `Count` channel, and batching. An alias would conceal a real
contract difference.

### 4.3 Encode Move as remove plus add

Rejected. Two messages expose a transient absence, lose one-mutation intent,
and can invite lifecycle side effects in consumers.

### 4.4 Suppress equal replacement or identical non-empty `ReplaceAll`

Rejected. That would impose equality on an unconstrained generic and diverge
from ADR-0089's deterministic call-means-notification contract.

### 4.5 Add batching or collection ownership

Rejected. Neither is required for parity, and both would change the primitive's
scope and lifetime model.
