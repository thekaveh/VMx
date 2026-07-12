# Serviced Collection Parity Design

Issue: #90\
Target spec: 3.16.0\
Rust source line: 0.16.0

## 1. Problem

Chapter 21 has always described `ServicedObservableCollection<T>` as a
language-neutral, hub-aware observable collection with add, remove, replace,
whole-list replacement, clear, and deterministic local-before-hub delivery.
The shipped flavors do not provide that shape consistently:

- C# inherits value removal, indexed removal, replacement, clear, and move from
  `ObservableCollection<T>`, but move is deliberately not forwarded to the hub
  and there is no atomic `ReplaceAll`.
- Python implements the mutable-sequence core and value removal, but lacks named
  `remove_at`, `replace`, `replace_all`, and `move` parity.
- TypeScript exposes array conveniences (`push`, `pop`, `splice`, `setAt`,
  `clear`) but not the declared higher-level surface.
- Swift has append, pop, set-at, clear, and Equatable value removal, but no
  indexed remove, named replace, whole-list replacement, or move.
- Rust has no distinct serviced collection. `COL-001..004` currently exercise
  `ObservableList`, so local-before-hub delivery and null-hub behavior are not
  represented by a dedicated public primitive.

DayDreams consequently performs a find-index plus splice ritual for cell
eviction. Keyed lookup remains #140 and is not part of this work.

## 2. Decision

Define a complete serviced mutation concept in every flavor:

| Concept      | C#                  | Python        | TypeScript                   | Swift                                  | Rust          |
| ------------ | ------------------- | ------------- | ---------------------------- | -------------------------------------- | ------------- |
| Add          | `Add`               | `append`      | `push`                       | `append`                               | `push`        |
| Remove value | `Remove`            | `remove`      | `remove`                     | `remove`                               | `remove`      |
| Remove index | `RemoveAt`          | `remove_at`   | `removeAt`                   | `removeAt`                             | `remove_at`   |
| Replace      | indexer / `Replace` | `replace`     | `replace` (`setAt` retained) | `replace(at:with:)` (`setAt` retained) | `replace`     |
| Replace all  | `ReplaceAll`        | `replace_all` | `replaceAll`                 | `replaceAll`                           | `replace_all` |
| Move         | `Move`              | `move`        | `move`                       | `move(from:to:)`                       | `move_item`   |
| Clear        | `Clear`             | `clear`       | `clear`                      | `clear`                                | `clear`       |

Existing idiomatic aliases remain source-compatible. Python retains its
documented list-style `remove(value) -> None` / `ValueError` behavior; all other
flavors return a boolean for value removal. Indexed-removal and replacement
returns remain flavor-idiomatic (void where established, removed/old value in
Python and Rust where newly named).

Rust gains a real `ServicedObservableCollection<T>` with a local hub-backed
change stream and an optional external hub. It does not replace or alias
`ObservableList<T>`.

## 3. Mutation Semantics

### 3.1 Value and indexed removal

- Value removal targets the first equal occurrence only.
- A missing value is a no-op returning false, except Python's preserved
  list-style `ValueError` divergence.
- Indexed removal emits one Remove containing the removed value and its
  pre-removal index.
- C#, TypeScript, Swift, and Rust reject indices outside `[0, Count)` before
  mutation. Python's named/indexed operations preserve normal negative-index
  behavior and report the resolved nonnegative index; excessively negative or
  positive indices raise `IndexError` atomically.

### 3.2 Replacement

- Named replacement emits exactly one Replace with old/new values and index.
- Replacing an item with the identical/equal item still emits Replace; the
  unconstrained generic does not compare values to suppress it.
- Invalid-index behavior matches indexed removal and is atomic.

### 3.3 Whole-list replacement

- Materialize the input before changing the backing store; self/live-view input
  is safe and iteration failure leaves contents and streams unchanged.
- Empty-to-empty is the only no-op.
- Every other call, including identical non-empty contents, emits one Reset and
  no granular events.
- A serviced collection has no `Count` property-change channel; Reset is its
  sole bulk notification.

### 3.4 Clear

- Clearing an empty collection is a true no-op.
- Clearing a non-empty collection emits one Reset.

### 3.5 Move

Reuse ADR-0085 index semantics: both indices address the pre-move collection and
must lie in `[0, Count)`. Equal indices are a true no-op. A successful move
preserves item identity and emits exactly one Move with old/new indices and the
same item in old/new payloads where the flavor carries item payloads. Move never
disposes, constructs, reparents, or otherwise manages the item.

Python does not accept negative indices for `move`, matching the portable
ADR-0085 rule even though its indexed remove/replace operations remain
Python-idiomatic. Swift move failures are catchable via the existing
`VMCollectionIndexError`; its established nonthrowing indexed mutators retain
array-precondition behavior.

## 4. Message Shape And Ordering

`CollectionChangedMessage` gains Move and explicit old/new positions while
preserving the existing `index` field:

| Action  |     `index` |  `oldIndex` |  `newIndex` |
| ------- | ----------: | ----------: | ----------: |
| Add     |   insertion |          -1 |   insertion |
| Remove  | pre-removal | pre-removal |          -1 |
| Replace |    replaced |    replaced |    replaced |
| Move    | destination |      source | destination |
| Reset   |          -1 |          -1 |          -1 |

Adding old/new fields is source-compatible: constructors/factories retain
defaults and existing fields. Rust already carries optional old/new indices and
keeps its documented hub-oriented payload shape.

Every effective mutation follows one order:

1. backing state changes;
1. local collection observers receive the change and can read final state;
1. the optional external hub receives the equivalent message.

Subscriber failures remain isolated by the existing reactive/message-hub
delivery rules. No operation changes caller-owned item lifecycle.

## 5. Conformance

Add `COL-048..055`:

- `COL-048`: first-duplicate value removal and missing-value behavior;
- `COL-049`: indexed removal and invalid/negative index behavior;
- `COL-050`: replacement, same-item notification, and invalid-index atomicity;
- `COL-051`: whole-list snapshot, identical/non-empty, and empty cases;
- `COL-052`: forward/backward move payload and final order;
- `COL-053`: same-index no-op and invalid move atomicity;
- `COL-054`: local-before-hub ordering and final-state visibility;
- `COL-055`: clear no-op plus non-owning removal/replacement/reset/move.

All five full-parity flavors carry behavioral tests. Existing `COL-001..004`
Rust tests move to the new serviced type instead of borrowing ObservableList.

## 6. Documentation And Pilot

Extend the cross-language naming table with the serviced surface and document
when to choose serviced collections versus `ObservableList`. Update all three
documentation surfaces from canonical `docs/content` sources.

In a disposable DayDreams clone, replace the renderer/world cell eviction's
index/splice ceremony with value removal after locating the cell by `coordKey`.
The pilot must preserve explicit caller disposal and identical hub behavior.
No consumer push is allowed; keyed search remains #140.

## 7. Compatibility

This is additive except for correcting empty-clear notification drift and C#'s
unforwarded inherited Move. Existing method names remain. The spec and stable
flavors advance to 3.16.0; pre-1.0 Rust advances to 0.16.0. Eight new library
IDs raise the catalog from 346 to 354 library IDs and from 351 to 359 total IDs.
