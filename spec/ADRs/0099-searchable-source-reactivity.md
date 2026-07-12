# ADR 0099 — Add source reactivity to SearchableState

**Status:** Accepted (2026-07-12)
**Spec version:** introduced in 3.19.0

## 1. Context

`SearchableState<T>` accepts a lazy item supplier but historically re-read it
only for a term change or explicit `search()`. Mutation with an unchanged term
could leave the published filtered snapshot stale. TypeScript documented this
as VMX-093, while the language-neutral shape already said `Filtered` recomputes
when items change. C#, Python, TypeScript, Swift, and Rust all retain the same
pull-source limitation.

Renaming the stable helper to advertise snapshot semantics would break callers
and contradict the intended reactive composition. Hard-coding every observable
collection family would couple a capability helper to container internals and
would not work for arbitrary suppliers.

ADR-0098 now provides a setup-safe `AggregateChangeStream` for consumers that
need membership plus current-member invalidation. Search should compose with
that seam rather than reimplementing its identity registry.

## 2. Decision

### 2.1 Add an optional invalidation signal

Keep the lazy supplier and all existing construction paths. Add one trailing,
optional source-change input. Its values carry no search data; each value means
"re-read the supplier with the current term now."

| Flavor     | Surface                                                                        |
| ---------- | ------------------------------------------------------------------------------ |
| C#         | `IObservable<Unit>? sourceChanged = null`                                      |
| Python     | \`Observable[object]                                                           |
| TypeScript | `sourceChanges?: Observable<unknown>`                                          |
| Swift      | `sourceChanges: AnyPublisher<Void, Never>? = nil`                              |
| Rust       | additive `new_with_changes` / `from_items_with_changes` accepting `MessageHub` |

The parameter remains last in default-argument languages. Rust keeps `new` and
`from_items` unchanged because it has no optional/default parameters.

### 2.2 Keep term and source timing independent

A source signal recomputes immediately with the current term. It neither enters
the term debounce nor cancels/restarts pending term work. Every pulse produces
one notification even if the filtered sequence is value-equal.

The helper performs no extra coalescing. Upstream batching is authoritative: a
coalesced source pulse causes one recompute, while N admitted pulses cause N.
This preserves collection/hub/aggregate transaction boundaries without adding
a competing clock.

### 2.3 Reconcile after attachment

With a signal, the helper reads the initial supplier, attaches the signal, and
then reads the supplier again before construction returns. Anything that changed
before attachment is represented by the final reconciliation; later committed
changes are represented by the signal. This does not override the source's own
thread-safety rules.

### 2.4 Isolate signal termination

Signal completion ends automatic refresh only. In C#, Python, and TypeScript,
signal errors are caught and treated the same way. They do not fail `Filtered`;
explicit search and later term changes still work. Swift's `Never` failure and
Rust's message hub encode a non-failing signal and exercise completion/disposal.

### 2.5 Own only the subscription

`SearchableState` owns the subscription it creates, cancels it exactly once on
idempotent disposal, and never disposes the signal, collection, items,
predicate, or aggregate. The signal is fixed for the helper lifetime. A supplier
may return a replacement collection, which is read on the next pulse or
explicit search.

### 2.6 Compose member-property changes through ADR-0098

Membership-only sources may map their structural event directly. A consumer
that also needs current-member properties maps `AggregateChangeStream` envelopes
to the source pulse. The consumer owns that aggregate; search owns only its pulse
subscription. No member registry is added to `SearchableState`.

### 2.7 Preserve Rust's established reactive facade

Rust's current `SearchableState` exposes `filtered()` as the pull projection and
`filtered_changed()` as the hot invalidation hub. A source hub pulse sends one
`Custom("filtered")` notification and the next pull sees the current supplier.
Rust's existing term notification is synchronous rather than scheduler-backed;
the source pulse remains an independent immediate trigger. This records the
pre-existing facade mapping rather than changing the public output shape in this
focused issue.

## 3. Consequences

- Existing supplier-only callers compile and behave unchanged.
- Source mutations can refresh without changing the term or calling `search()`.
- Aggregate membership/item tracking remains centralized in ADR-0098.
- Error-capable invalidation streams cannot terminate the filtered result.
- A replaying source signal intentionally causes a refresh when subscribed;
  non-replaying pulse streams are recommended when no seed is desired.
- Seven `SRCH` conformance IDs raise library coverage from 373 to 380 and total
  catalog coverage from 378 to 385 including five `THEME` scenarios.
- The additive feature releases as spec/C#/Python/TypeScript/Swift 3.19.0 and
  Rust 0.19.0.

## 4. Rejected alternatives

### 4.1 Rename the helper as snapshot-only

Rejected. It would break the stable surface and preserve a correctness trap
despite a compatible reactive extension being available.

### 4.2 Detect concrete collection families internally

Rejected. The supplier can represent arbitrary state, and search must not own
or downcast container implementations.

### 4.3 Embed AggregateChangeStream

Rejected. Membership-only callers do not need item subscriptions, and consumers
may already own an aggregate with application-specific item selectors.

### 4.4 Debounce or deep-compare source refreshes

Rejected. Source mutation is already committed, equality is not portable, and
upstream sources own their batch boundaries.

### 4.5 Forward source errors to Filtered

Rejected. The invalidation transport is not the data source, explicit refresh
remains valid, and Swift/Rust source signals are non-failing.
