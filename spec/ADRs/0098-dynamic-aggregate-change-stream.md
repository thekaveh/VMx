# ADR 0098 — Add a dynamic aggregate change stream

**Status:** Accepted (2026-07-12)
**Spec version:** introduced in 3.18.0

## 1. Context

Consumers need one observable that follows a live collection and reports both
structural changes and changes from every current member. Reimplementing this
fan-in in applications has produced duplicate sender bookkeeping, broad hub
filters, revision counters, and incompatible batching rules.

ADR-0095's selected-state subscription observes one fixed source. It cannot
represent dynamic membership. The existing collection interfaces also expose
more mutation, ownership, or selection surface than this read-only operation
requires.

## 2. Decision

### 2.1 Sources and read-only capability

VMx adds an independent `ObservableMembershipSource<T>` capability with two
operations: an ordered current snapshot and a disposable structural-change
subscription. The callback has no event payload; the aggregate always
resnapshots committed membership.

The capability is additive. Existing VM collection interfaces, protocols, and
traits gain no requirement. The first release supports four source families:

1. `CompositeVM`;
1. `GroupVM`;
1. `ServicedObservableCollection`; and
1. `KeyedServicedObservableCollection`.

Rust's exact additive source contract is:

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

`Clone` denotes a shared source handle, not a copied collection. `VmNode`,
`VmCollection`, and all other existing Rust collection traits remain unchanged;
external implementations gain no requirement.

Normal VM collections map Add, Remove, Replace, Move, and Reset to a structural
pulse. The serviced sources map their existing local collection notification.
No adapter changes the source's item ownership.

### 2.2 Selector, convenience, and provenance

`AggregateChangeStream<T>` requires a selector that supplies each member's
local change stream. This permits nested state such as `item.model.state`, not
only changes on the member itself. Each flavor also exposes an idiomatic
`forComponents` / `ForComponents` convenience for the standard component
property-change stream.

Rust's `for_components` convenience uses a second independent additive trait:

```rust
pub trait ObservablePropertySource: VmNode {
    fn property_changed(&self) -> PropertyChangedStream;
}
```

The general selector overload requires no `ObservablePropertySource` bound.
Adding the convenience does not extend `VmNode` or change existing external
`VmNode` implementations.

The hot output carries an `AggregateChange<T>` envelope with one reason:

- `Initial`, with no item: an optional subscriber-local readiness seed;
- `Membership`, with no item: committed ordered membership changed;
- `Item`, with the current item: that member's selected stream emitted; or
- `Batch`, with no item: an explicit aggregate batch coalesced changes.

The envelope is provenance, not a snapshot, revision, or application value.
Initial delivery is selected per subscription. Registration and its one seed
are serialized atomically, so the seed precedes later changes for that
subscriber without replaying history or publishing a global initial event.

### 2.3 Identity, refcounts, and membership epochs

The aggregate tracks reference identity in C#, Python, TypeScript, and Swift,
and `VmNode::id()` in Rust. Null members are invalid. Equal-but-distinct objects
remain distinct; Rust's existing VM ID contract defines logical identity.

Duplicate occurrences share one selected-stream subscription and increment a
refcount. Removing the final occurrence detaches before the corresponding
membership event. A retained identity across Replace, Reset, Move, or duplicate
add keeps its subscription and monotonically assigned membership epoch. Only
final removal followed by re-add creates a new epoch. Queued item events carry
the epoch and are discarded after final removal or selected-stream termination,
so stale work cannot be attributed to a later membership.

### 2.4 Setup, resynchronization, and failure

The structural subscription attaches before the first snapshot. If a
structural callback races setup, snapshots repeat until one commits without an
intervening callback. Construction commits only the latest membership and emits
no replayable `Membership`; the optional subscriber-local `Initial` represents
readiness. Every structural pulse admitted after construction likewise
resnapshots before the aggregate publishes exactly one `Membership`.

New selected subscriptions are staged transactionally. Synchronous selected
emissions during initial construction are discarded as pre-existing state;
those during later reconciliation are buffered behind the membership event.
Null or selector/subscription failure is terminal for the aggregate. Before
throwing or notifying the output error, it detaches the structural subscription
and every staged and admitted item subscription. Construction failure then
throws before returning an aggregate; later failure terminates the existing
output with that error according to the host reactive convention. No live but
unobserved current member survives.

Selected-stream completion, and unexpected selected-stream error in Rx
flavors, terminates only that item's current positive-refcount epoch and emits
no aggregate event. Other members and the aggregate remain active. The item is
not resubscribed until final removal and re-add.

Notifications drain through one serialized FIFO. Reentrant events append
behind the current envelope. Subscriber failure follows the host reactive
primitive and must not corrupt membership bookkeeping or detach unrelated item
subscriptions.

### 2.5 Explicit batching

The aggregate owns a synchronous, nested, ref-counted batch scope. Outside a
batch, every admitted structural or item change emits immediately. Inside a
batch, changes mark it dirty; the outermost exit emits exactly one `Batch` when
dirty. Empty batches emit nothing. If a body changes state and then fails, the
final batch event is emitted and the original failure is rethrown.

If synchronous subscriber delivery of that final `Batch` also throws while the
body failure is active, cleanup suppresses the delivery exception so the
original body failure wins. When the body succeeds, a synchronous subscriber
failure follows the host reactive convention. This precedence rule is batch
cleanup behavior, not general subscriber-failure isolation.

Hub batching has no portable end-of-batch or idle callback, so it is not
detected automatically. A consumer needing one combined pulse explicitly nests
the aggregate and hub scopes.

### 2.6 Completion, disposal, and ownership

Explicit disposal is idempotent. It detaches the structural subscription and
all item subscriptions, completes output where supported, and makes later
source activity inert. The aggregate owns only those subscriptions; it never
constructs, disposes, reparents, removes, or otherwise owns source items. A
source lifetime has no portable completion signal and does not replace explicit
aggregate disposal.

### 2.7 Excluded source families

`ObservableDictionary`, paging projections, and filtered projections are
excluded from this release. Their public element identity or visible-membership
meaning requires a separate projection decision.

## 3. Consequences

- Consumers gain one portable dynamic fan-in with item provenance and no
  synthetic revision state.
- Existing collection implementers remain source and binary compatible because
  the membership capability is independent.
- Reference/VM identity and transactional reconciliation add bookkeeping, but
  make duplicates, Reset, reentrancy, and removal deterministic.
- Coalescing across a hub transaction requires explicit nested scopes.
- Ten `AGCH-001..010` cases raise the library catalog from 363 to 373 IDs and
  the total catalog, including five scenarios, from 368 to 378 IDs.

## 4. Rejected alternatives

- Per-collection `onAnyChange` methods duplicate difficult fan-in behavior.
- A payload-free pulse cannot identify DayDreams' changed current member.
- Automatic hub-boundary coalescing requires a new public hub lifecycle
  contract beyond this decision.
- Dictionary and projection support without an explicit element projection
  would make membership ambiguous.
