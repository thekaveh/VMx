# ADR 0193 — Read-only dictionary key views, dictionary Remove and Replace positions, and one Reset for Python `reverse()`

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 21 §2.3.6, §4.1, §4.2, §4.7, §4.8,
  `COL-068` and `COL-070`)
- **Related:** [ADR-0009](0009-cross-flavor-divergence-catalogue.md) §2.21 and
  §2.15, [ADR-0025](0025-multi-key-observable-dictionary.md),
  [ADR-0097](0097-keyed-serviced-observable-collection.md),
  [ADR-0177](0177-dictionary-key-views-update-before-dictionary-events.md),
  #1316.

## 1. Context

Issue #1316 names three open collection contracts.

**Key views.** Chapter 21 §4.1 gave `Keys1` and `Keys2` the type
`ObservableList`. C#, TypeScript and Swift return the backing list, so a caller
can add, remove or clear keys. Python returns a `ReadOnlyObservableList` facade
with no mutators (VMX-014). ADR-0009 §2.21 recorded the split and left the
decision to the maintainer. The dictionary never repairs a caller edit. At
commit `349ca12`, a TypeScript caller pushed `"ghost"` into `keys2`, then added
an entry with key2 `"ghost"`. `keys2` became `["x", "ghost", "ghost"]`. Rust
`keys1()` and `keys2()` return `Vec` snapshots, so a caller edit cannot reach
the dictionary.

**Remove and Replace positions.** The §2.4 table gives Remove its pre-removal
position and Replace its replaced position. Chapter 21 §4.7 did not say whether
the dictionary follows the table. Dictionary Add sends the insertion position.
If a local subscriber moves or removes the entry before the hub message, Add
sends the entry's position at send time, or `-1` when it is gone (#733).
Remove and Replace send `-1` in C#, Python, TypeScript and Swift, and `None` in
Rust. The Rust single-key `ObservableDictionary<K, V>` does the same.

**Python `reverse()`.** The unkeyed Python `ServicedObservableCollection`
inherits `MutableSequence.reverse`, which swaps items through `__setitem__`.
Each assignment sends one Replace. Reversing `[1, 2, 3, 4]` sends four Replace
messages, at positions 0, 3, 1 and 2. Observers see interim states such as
`[4, 2, 3, 4]`. The keyed collection sends one Reset (§2.11). No other flavor
has an unkeyed `reverse`.

## 2. Decision

Decided under the owner's 2026-11-07 delegation. Each rule is the simplest
common-sense rule that all flavors can follow.

### 2.1 Key views are read-only

1. `Keys1` and `Keys2` return a `ReadOnlyObservableList<TKey>`. It is a facade
   over the live backing list. It has every read and subscribe member of
   `ObservableList<T>`, and no mutator and no batch member. The name is
   `ReadOnlyObservableList` in C#, Python, TypeScript and Swift, with
   idiomatic member casing (ADR-0006).
1. The facade does not expose the backing list. In C#, its
   `CollectionChanged` and `PropertyChanged` events carry the facade as
   sender, as the BCL `ReadOnlyObservableCollection<T>` does. A cast to
   `ObservableList<T>` fails.
1. Rust keeps its `Vec` snapshots (chapter 21 §4.2). An edit to a snapshot does
   not change the dictionary.
1. `COL-070` is normative. C#, TypeScript and Swift show that the key-view
   type is `ReadOnlyObservableList<T>`, with no add, remove or clear member:
   C# by reflection and TypeScript with `@ts-expect-error` lines. Swift binds
   the views to the declared `ReadOnlyObservableList<T>` type. Swift has no
   runtime check for an absent member, so the declaration is the evidence.
   Python shows that the view has no mutator attribute. Rust
   shows that a snapshot edit leaves `keys1()`, `keys2()` and `entries()`
   unchanged.

The change breaks source in C#, TypeScript and Swift. Only code that edits a
view, or that names the view's type as `ObservableList`, fails to compile. An
edit corrupted the dictionary, so no correct program depended on it. Code that
reads or subscribes to a view compiles without a change. Thus the change ships
in each flavor's current source version as a narrow 3.x exception to the
major-version rule, recorded in ADR-0009 §2.21. If the Swift source version is
already a major (4.0.0), the change rides in it. Each CHANGELOG lists the
change as source-breaking, with a migration line.

### 2.2 Dictionary Remove and Replace carry positions

The dictionary follows the §2.4 table. A position is the entry's index in
enumeration (insertion) order.

| Action  |     `index` |  `oldIndex` | `newIndex` | Rust `old_index`    | Rust `new_index` |
| ------- | ----------: | ----------: | ---------: | ------------------- | ---------------- |
| Remove  | pre-removal | pre-removal |         -1 | `Some(pre-removal)` | `None`           |
| Replace |    replaced |    replaced |   replaced | `Some(replaced)`    | `Some(replaced)` |

- Remove reports the position that the entry had just before the removal. A
  local subscriber that changes the dictionary before the hub message does not
  change it.
- Replace reports the entry's position when the hub message is sent, as Add
  already does (#733). If a local subscriber moved the entry, Replace reports
  the new position. If it removed the entry, Replace reports `-1`. One rule
  thus covers both actions whose entry stays in the dictionary.
- A replacement does not move the entry, so its old and new positions are
  equal.
- Add keeps its established rule: the insertion position, read when the hub
  message is sent (§2.4, #733).
- Rust has no local dictionary event. Nothing can change the dictionary
  between the commit and the hub message, so its positions are the commit
  positions.
- Reset keeps `-1` (`None` in Rust).
- The Rust single-key `ObservableDictionary<K, V>` follows the same rule.
- `COL-068` is normative in all five flavors.
- The local dictionary events keep their payloads. The C#
  `NotifyCollectionChangedEventArgs` of the dictionary keep their shape, which
  has no position.

### 2.3 Python unkeyed `reverse()` sends one Reset

The unkeyed Python `ServicedObservableCollection.reverse()` reverses the items
atomically. Lengths zero and one are no-ops. Reversing two or more items sends
exactly one Reset and no granular message, as the keyed collection does
(§2.11). No other flavor has an unkeyed `reverse`, so the rule needs no
conformance ID. A Python unit test covers it.

## 3. Consequences

- ADR-0009 §2.21 is resolved. Python's facade becomes the rule in every flavor
  with live views.
- A consumer that binds to `Keys1` or `Keys2` keeps working. A WPF binding
  receives `CollectionChanged` from the C# facade.
- A hub subscriber can locate a removed or replaced dictionary entry by
  position, as it can for a serviced collection.
- A Replace position computes the entry's index only when a hub is present.
  A dictionary without a hub keeps an O(1) value replacement.
- A Python `reverse()` observer sees only the final order.
- The library conformance catalog grows by two IDs, `COL-068` and `COL-070`.

## 4. Rejected alternatives

- **Mutable key views with a stated outcome.** The spec would have to define
  the result of a caller edit, for example "the view is undefined until the
  next `Clear()`". Every flavor would keep a footgun that Python already
  removed.
- **A read-only interface that the backing list implements.** A cast would
  reach the mutators, and Python already uses a facade.
- **A major bump for C# and TypeScript.** Only incorrect programs and explicit
  type annotations break. A major bump for this alone would force a release
  decision on a defect repair. ADR-0009 already records narrow 3.x exceptions
  of this kind.
- **Commit-time positions for Remove and Replace.** Add already reads the
  position when the hub message is sent (#733). A commit-time Replace would
  give one dictionary two rules after a local re-entry, and a stale Replace
  position could name another entry.
- **Send-time positions for Remove.** A removed entry has no current position.
  The pre-removal position is the only one that names the entry.
- **Python `reverse()` as granular Move messages.** Several Move messages would
  still expose interim orders. One Reset matches the keyed collection.
