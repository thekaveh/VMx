# SearchableState Source Reactivity Design

**Issue:** #98\
**Status:** Approved for implementation by the continuous roadmap directive\
**Target line:** spec/C#/Python/TypeScript/Swift 3.19.0; Rust 0.19.0

## 1. Problem and scope

`SearchableState<T>` receives a lazy items supplier, but today it re-reads that
supplier only after a debounced term change or explicit `search()`. A caller can
add, remove, replace, reset, or reorder items while the term stays unchanged and
leave the published filtered view stale. The existing name and specification
already say the filtered view recomputes on item changes, so renaming the stable
surface would preserve the bug rather than repair the contract.

VMx will preserve every existing constructor and the lazy supplier, then add an
optional source-change signal. Each signal is a payload-free invalidation: the
helper re-reads the supplier, applies the current term, and emits/notifies the
new snapshot immediately.

This ticket does not add collection mutators, take ownership of a collection or
its items, replace `AggregateChangeStream`, or infer item-property changes.
Consumers that need membership plus current-member changes compose the #136
aggregate output into this signal.

## 2. Portable contract

```text
SearchableState<T>(
    items: () -> Iterable<T>,
    predicate: (T, string) -> bool,
    debounce = 1 second,
    scheduler = default,
    source_changed = absent
)

source_changed event:
    recompute Filtered from items() and the current SearchTerm immediately
```

The additive idiomatic surfaces are:

| Flavor     | Optional input                                                                         |
| ---------- | -------------------------------------------------------------------------------------- |
| C#         | `IObservable<Unit>? sourceChanged = null`                                              |
| Python     | \`Observable[object]                                                                   |
| TypeScript | `sourceChanges?: Observable<unknown>`                                                  |
| Swift      | `sourceChanges: AnyPublisher<Void, Never>? = nil`                                      |
| Rust       | `from_items_with_changes(..., source_changes: MessageHub)` and `new_with_changes(...)` |

The new parameter is last in every default-argument flavor, preserving source
compatibility for positional calls. Rust retains `new` and `from_items` and
adds named constructors because Rust has no default arguments.

## 3. Trigger and debounce semantics

Term and source invalidations are independent inputs:

- a new term retains the existing trailing debounce;
- `search()` remains an immediate explicit recompute;
- a source signal is immediate and uses the current term, even if that term has
  a pending debounced delivery;
- a source signal neither cancels nor restarts the pending term debounce, so
  the later debounced term delivery still occurs;
- every admitted source signal emits/notifies once, even when the resulting
  sequence is value-equal to the previous snapshot.

`SearchableState` does not invent a second batch window. It is transparent to
the supplied signal: N input pulses produce N recomputes. If an observable
collection, hub batch, or `AggregateChangeStream` batch coalesces a mutation
storm into one pulse, `SearchableState` recomputes once. This keeps batch
boundaries owned by the source that knows them.

The supplier may start returning a different collection instance. That is not
a separately owned replaceable source: the next source signal or explicit
`search()` reads the replacement. Replacing the signal subscription itself is
out of scope.

## 4. Construction, ordering, and ownership

When a signal is supplied, construction performs an initial supplier read,
installs the signal subscription, and then reconciles from the supplier again
before returning. The second read closes the ordinary snapshot/attach gap:
anything that changed before attachment is represented by the reconciliation,
and anything after attachment is represented by the signal. Intermediate
constructor-only values are not externally observable.

Signal callbacks use the host reactive library's normal serialized delivery
rules. This feature does not make a non-thread-safe supplier safe for concurrent
mutation; callers must follow the source collection's threading contract.

The helper owns exactly its signal subscription and its existing internal term
subscription. It never disposes the signal object, collection, items, predicate,
or aggregate stream. `dispose()` cancels owned subscriptions once, completes the
helper-owned output as before, and makes later source pulses inert.

## 5. Completion and failure

Source completion stops automatic source-triggered recomputation only. Term
changes and explicit `search()` remain usable until the helper is disposed.

The source signal is an invalidation channel, not the data channel. In C#,
Python, and TypeScript, an upstream error is isolated exactly like completion:
the automatic trigger detaches, the last filtered value is retained, and term
or explicit search can still re-read the supplier. The error is not forwarded
to `Filtered`, whose portable contract is non-failing. Swift encodes this with
`Failure == Never`; Rust's `MessageHub` likewise has no error channel, so their
conformance case exercises completion/disposal of the signal.

Synchronous constructor subscription failures that escape the host library
still fail construction; no partially returned helper exists.

## 6. Rust mapping

Rust keeps its existing idiom: `filtered()` is the current pull projection and
`filtered_changed()` is the hot invalidation hub. A source hub pulse sends one
`Custom { name: "filtered" }` notification; the next `filtered()` read sees the
latest supplier snapshot. The state stores and owns the returned `Subscription`
and gains idempotent `dispose()` for that ownership.

Rust's existing term notification is synchronous rather than scheduler-backed.
The new source trigger remains independent of that term notification. The ADR
records this pre-existing reactive-facade mapping; this ticket does not redesign
the established Rust `SearchableState` output shape.

## 7. AggregateChangeStream composition

Membership-only consumers can map their collection change stream directly to
the optional signal. Consumers that also depend on current-member properties
use `AggregateChangeStream` and erase/map each provenance envelope to a pulse.
The aggregate remains owned and disposed by the consumer; `SearchableState`
owns only its subscription to the exposed pulse stream. No dynamic member
registry is duplicated inside search.

## 8. Conformance and release

Add `SRCH-001..007`:

1. unchanged-term add triggers an immediate refreshed snapshot;
1. remove, replace, reset/reorder always read the latest supplier snapshot;
1. each pulse emits once even for a value-equal result, while upstream
   coalescing remains one pulse/one recompute;
1. a source pulse uses the current term without canceling pending term work;
1. source completion/error is isolated and manual search remains operational;
1. disposal cancels the owned source subscription once and later pulses are
   inert; and
1. omitting the signal preserves explicit-refresh compatibility and ownership.

The catalog moves from 373 to 380 library IDs and from 378 to 385 total IDs
including the five `THEME` scenarios. This additive behavior/API release is
3.19.0 for the spec and stable flavors, and 0.19.0 for Rust.

## 9. Rejected alternatives

- **Rename to snapshot-only.** Rejected because the normative shape already
  promises item-change recomputation and a compatible additive fix is possible.
- **Observe every known collection type internally.** Rejected because it
  couples a capability helper to container families and cannot represent
  arbitrary suppliers.
- **Embed AggregateChangeStream.** Rejected because membership-only signals do
  not need an item registry and callers may already own an aggregate.
- **Debounce source changes with the term.** Rejected because it delays committed
  membership changes and makes a source pulse reset unrelated term timing.
- **Deep-equality suppression.** Rejected because equality is not portable and
  a pulse can represent meaningful external state even when item values compare
  equal.
- **Forward source errors to Filtered.** Rejected because Swift/Rust signals are
  non-failing and a failed invalidation transport must not destroy explicit
  search.
