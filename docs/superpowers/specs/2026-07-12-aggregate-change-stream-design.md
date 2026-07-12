# Aggregate Change Stream Design

**Issue:** #136\
**Status:** Approved for implementation by the continuous roadmap directive\
**Target line:** spec/C#/Python/TypeScript/Swift 3.18.0; Rust 0.18.0

## 1. Problem and scope

Consumers repeatedly need one subscription that tracks both membership in a
live collection and changes from every current member. Tableau currently owns a
revision counter, a `BehaviorSubject<number>`, nested-state sender bookkeeping,
and a defer-depth guard. DayDreams listens to collection membership separately
and casts every hub `PropertyChanged(model)` before a renderer map rejects
nonmembers.

VMx will add a standalone `AggregateChangeStream<TItem>`. It is not a new
collection, does not change collection ownership, and is distinct from the
fixed-source selector in ADR-0095. The first release supports:

- `CompositeVM` and `GroupVM` through the normal VM-collection contract;
- `ServicedObservableCollection`; and
- `KeyedServicedObservableCollection`.

`ObservableDictionary`, paging projections, and filtered projections are out of
scope because their public element/visible-membership meanings require a
separate value projection decision.

## 2. Chosen architecture

### 2.1 Read-only membership capability

Add a small read-only observable-membership capability. It exposes only:

1. an ordered current snapshot/iteration; and
1. a structural-change subscription.

It contains no mutators, selection, batching, lifecycle, or ownership. Normal
VM collections and both serviced collection types implement it without making
caller-owned serviced values into VM children.

It is additive and separate from every existing public collection interface,
protocol, and trait. `IVmCollection`, `VmCollectionProto`, TypeScript
`IVmCollection`, Swift `VMCollection`, and Rust `VmCollection` do not inherit or
gain requirements. VMx's concrete composite/group and serviced
sources conform directly; external collection implementations remain source
and binary compatible and may opt into the new capability independently.

The public capability and built-in adapters are explicit:

| Flavor     | Capability                                       | Snapshot                      | Structural subscription                         |
| ---------- | ------------------------------------------------ | ----------------------------- | ----------------------------------------------- |
| C#         | `IObservableMembershipSource<T>`                 | `IReadOnlyList<T> Snapshot()` | `IDisposable SubscribeMembership(Action)`       |
| Python     | `ObservableMembershipSource[T]` protocol         | `snapshot() -> tuple[T, ...]` | `subscribe_membership(callback) -> Disposable`  |
| TypeScript | `ObservableMembershipSource<T>`                  | `snapshot(): readonly T[]`    | `subscribeMembership(callback): Subscription`   |
| Swift      | `ObservableMembershipSource` (`Item: AnyObject`) | `snapshot() -> [Item]`        | `subscribeMembership(_:) -> AnyCancellable`     |
| Rust       | `ObservableMembershipSource<T: VmNode>`          | `snapshot() -> Vec<T>`        | `subscribe_membership(handler) -> Subscription` |

For normal VM collections, every add/remove/replace/move/reset notification is
structural. The serviced and keyed-serviced adapters map their existing
collection-change notification to the same structural pulse. The capability
never exposes the collection event payload.

The aggregate stream resnapshots on every structural event before notifying its
subscribers. This is intentionally more general than interpreting event
payloads: Reset is correct, Rust's item-less collection messages are sufficient,
and reentrant observers see the committed membership.

### 2.2 Item-change selector

Construction requires an item-change selector. Given a member, it returns or
installs that member's change subscription. Rx/Combine flavors accept a local
observable/publisher selector. Rust accepts a selector returning the existing
`PropertyChangedStream`.

This selector is required because Tableau observes `node.model.state`, not the
`HexNode` itself. The own-property conveniences are `ForComponents` (C#),
`for_components` (Python and Rust), and `forComponents` (TypeScript and Swift).
They are available only for the standard component/property-stream constraint;
all other item types use the selector overload.

Their signatures return the same aggregate type and merely supply the selector:

| Flavor     | Convenience signature                                                                                                                                                                 |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C#         | `AggregateChangeStream.ForComponents<T>(IObservableMembershipSource<T> source) -> AggregateChangeStream<T> where T : class, IComponentVM`                                             |
| Python     | `AggregateChangeStream.for_components(source: ObservableMembershipSource[TComponent]) -> AggregateChangeStream[TComponent]`, with `TComponent` bound to the component protocol        |
| TypeScript | `static forComponents<T extends ComponentVMBase>(source: ObservableMembershipSource<T>): AggregateChangeStream<T>`                                                                    |
| Swift      | constrained extension on `AggregateChangeStream where Item: ComponentVMBase`: `static func forComponents<S>(_ source: S) -> Self where S: ObservableMembershipSource, S.Item == Item` |
| Rust       | `AggregateChangeStream::for_components(source)` where the source implements `ObservableMembershipSource<T>` and `T` implements the additive `ObservablePropertySource: VmNode` trait  |

Selected item streams are required to be non-failing. Swift uses `Failure == Never`, and Rust's local stream has no error channel. In the Rx flavors, an
unexpected selected-stream error terminates only that item's current membership
epoch and emits no aggregate event; it does not fail the aggregate or detach
other members.

### 2.3 One provenance stream, not application state

The underlying hot `changes` stream emits `AggregateChange<TItem>` envelopes:

| Reason       | `item`  | Meaning                                                                |
| ------------ | ------- | ---------------------------------------------------------------------- |
| `initial`    | absent  | Optional per-subscriber seed; current state is ready.                  |
| `membership` | absent  | The committed ordered membership changed.                              |
| `item`       | present | This current distinct item emitted through its selected change stream. |
| `batch`      | absent  | One or more changes were coalesced by the aggregate's explicit batch.  |

The envelope is provenance, not a revision, snapshot, or domain value. A
consumer needing only a pulse ignores it. Tableau can feed it to derived
composition without maintaining an integer. DayDreams can use the `item`
identity for member-property events while retaining its existing detailed
collection event handling for add/remove item payloads.

Initial delivery is an option on `observe`/subscription, not construction. The
aggregate registers the subscriber under the same serialized gate used for
normal delivery, privately queues exactly one `initial` envelope ahead of later
changes for that subscriber, and then admits it to the shared hot stream. This
closes the seed/attach race without replaying past changes or publishing a
global initial event. A subscriber that does not request it receives no seed.

A pure `Void`/`Unit` stream was rejected because it cannot remove DayDreams'
broad hub cast without rescanning or repainting every member.

### 2.4 Identity multiset

Membership is tracked by stable object identity:

- reference identity in C#, Python, TypeScript, and Swift;
- `VmNode::id()` in Rust.

The membership capability itself remains unconstrained in C# and TypeScript so
existing generic serviced collections keep value-type/primitive compatibility;
only `AggregateChangeStream<T>` applies the reference/object bound. Swift uses
conditional conformance for reference-item serviced collections. Rust treats
`VmNode::id()` uniqueness as the existing VM identity contract; two
simultaneously present objects with the same ID are the same logical member and
therefore share one refcounted subscription. The aggregate does not add
equality or hashing fallbacks.

C# supplies explicit capability methods on composite/group bases and both
serviced types; `IVmCollection` remains unchanged. Its aggregate uses a private comparer
implemented with `ReferenceEquals` and `RuntimeHelpers.GetHashCode`, not the
newer BCL `ReferenceEqualityComparer`.

Null members are invalid. Swift and Rust cannot express them and strict
TypeScript excludes them statically; all flavors still validate snapshots at
runtime where applicable. C# and Python reject a snapshot containing null at
construction or reconciliation using their idiomatic argument/value error. The
same transactional-failure rule as a throwing selector applies, so no partially
observed aggregate survives.

Duplicate memberships increment a refcount and share one item subscription. A
single item notification produces one `item` event. Removing one occurrence
keeps the item observed; removing the final occurrence detaches it before the
corresponding `membership` event. An item removed or replaced during a
reentrant callback cannot produce a later admitted event when that identity's
refcount reaches zero; an identity-retaining Replace remains observed.

## 3. API sketches

Names remain idiomatic; exact generic spellings may differ where the host
language requires type erasure.

```csharp
var aggregate = new AggregateChangeStream<Node>(
    source,
    node => Observable
        .FromEventPattern<PropertyChangedEventHandler, PropertyChangedEventArgs>(
            handler => node.Model.State.PropertyChanged += handler,
            handler => node.Model.State.PropertyChanged -= handler)
        .Select(_ => Unit.Default));
IObservable<AggregateChange<Node>> changes = aggregate.Observe(emitInitial: true);
aggregate.Batch(() => Mutate());
aggregate.Dispose();

var componentAggregate = AggregateChangeStream.ForComponents(componentSource);
```

```python
aggregate = AggregateChangeStream(
    source,
    observe_item=lambda node: node.model.state.property_changed,
)
changes = aggregate.observe(emit_initial=True)
with aggregate.batch():
    mutate()
aggregate.dispose()
```

```typescript
const aggregate = new AggregateChangeStream(
  source,
  node => node.model.state.propertyChanged,
);
const changes = aggregate.observe({ emitInitial: true });
aggregate.withBatch(() => mutate());
aggregate.dispose();
```

```swift
let aggregate = AggregateChangeStream(
    source: source,
    observeItem: { $0.model.state.propertyChanged.eraseToAnyPublisher() })
let changes = aggregate.observe(emitInitial: true)
try aggregate.withBatch { try mutate() }
aggregate.dispose()
```

```rust
let aggregate = AggregateChangeStream::new(
    source,
    |node| node.model().state.property_changed(),
);
let changes = aggregate.observe(AggregateObserveOptions::default().emit_initial(true));
aggregate.batch(|| mutate());
aggregate.dispose();
```

Rust's additive contract is concrete:

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

The own-property convenience uses one additional additive trait:

```rust
pub trait ObservablePropertySource: VmNode {
    fn property_changed(&self) -> PropertyChangedStream;
}
```

`T: VmNode` supplies stable logical identity; the source's `Clone` is a shared
handle, not a copied collection. Built-in normal, serviced, and keyed-serviced
collections implement the trait directly. This does not extend `VmNode`, so
external `VmNode` implementations remain source compatible.

The first release requires identity-bearing VM/reference items: `class` /
object references in C#, Python, TypeScript, and Swift (`AnyObject`), and
`VmNode` in Rust. It does not attempt value-identity semantics for primitive or
copy-only serviced items.

## 4. Batching and hub composition

The aggregate owns a synchronous, ref-counted batch/defer scope:

- outside a batch, each admitted structural or item change emits immediately;
- inside nested batches, changes mark the aggregate dirty;
- the outermost exit emits exactly one `batch` event when dirty;
- an empty batch emits nothing; and
- the final event targets the union of subscribers active at each dirtying
  change, excluding later cancellations, so late subscribers receive no
  history unless another change occurs after they join; and
- if the body fails after a change, the final batch event is emitted and the
  original error is rethrown. If synchronous final-event delivery itself throws,
  that cleanup exception is suppressed so it cannot replace the body error.
  With no body error active, subscriber failure follows the host reactive
  contract as usual.

Native collection batches already publish one Reset, so they naturally cause
one `membership` event. Current `hub.batch()` implementations expose neither an
outer-batch boundary nor a drain-idle callback; automatic coalescing across a
hub transaction is therefore impossible without expanding the message-hub
contract. #136 will not do that. Consumers that require one pulse nest scopes
explicitly:

```typescript
aggregate.withBatch(() => hub.batch(() => mutate()));
```

This is deterministic, synchronous, and portable. Hub batching still preserves
its own lossless message order; aggregate batching controls only aggregate
notifications.

## 5. Delivery, reentrancy, and failure

Aggregate notifications use a serialized FIFO drain. State and membership
subscriptions settle before an envelope is queued. Reentrant membership or item
changes append behind the current envelope rather than recursively corrupting
the identity table. Cross-thread mutations use each flavor's existing locking
or serialization conventions.

Construction attaches the structural subscription under the serialized gate
before taking the first snapshot. Structural callbacks during setup mark the
snapshot stale; reconciliation repeats until it commits a snapshot with no
intervening structural callback. Selected streams are staged before commit.
This setup race publishes no `membership` history because the output is hot and
not yet externally subscribable; a later subscriber may request its private
`initial` readiness seed. Only structural pulses after construction publish a
`membership` envelope.
Synchronous item emissions during staging are buffered: after later structural
reconciliation they queue behind its `membership` envelope, while during initial
construction they are discarded as pre-existing state and the optional
subscriber-local `initial` envelope represents readiness.

Every distinct admitted item receives a monotonically increasing membership
epoch token. Queued item callbacks carry that token and are discarded during
the FIFO drain only if the identity's refcount reached zero or its selected
stream terminated. An identity-retaining Replace, Reset, Move, or duplicate add
preserves the epoch and subscription. Re-adding after final removal creates a
new epoch, so a stale callback can never be attributed to the new membership.

Subscriber failures follow the established local reactive primitive contract.
HUB-007 isolation is not claimed for an ordinary Rx/Combine/local pulse stream.
One observer failure must not change membership bookkeeping or detach other
subscriptions beyond what the host reactive library already specifies.

The item-change selector is a total, nonthrowing precondition (Swift and Rust
make that explicit in the type). C#, Python, and TypeScript build all newly
required selected subscriptions into a temporary set before committing a
membership resynchronization. If selection or subscription fails, temporary
subscriptions are disposed and the aggregate atomically terminates with that
error on its existing output error channel. Terminal failure detaches the
structural subscription plus every staged and already admitted item
subscription. Construction-time failure throws synchronously because no
aggregate is returned. A later callback may also surface the exception to the
mutator only where the host reactive primitive does so; RxJS reports observer
exceptions through its own host mechanism, so portable callers rely on the
terminal output error. No live but unobserved current member or subscription
behind a dead output survives, and no secondary error stream is introduced.

## 6. Completion, disposal, and ownership

The aggregate owns only its structural and item subscriptions.

- Explicit disposal is idempotent, detaches every subscription, completes the
  output where the host convention supports completion, and makes later source
  activity inert.
- It never disposes, constructs, destructs, reparents, or removes source items.
- Item-stream completion or unexpected Rx error terminates that item's current
  positive-refcount membership epoch and detaches its selected subscription
  without changing source membership. Move, Reset with the identity retained,
  and adding a duplicate do not resubscribe. Only final removal followed by a
  later re-add establishes a fresh epoch and selected subscription.
- There is no portable source-disposal signal across the supported families;
  source lifetime does not replace explicit aggregate disposal.

## 7. Conformance plan

Add `AGCH-001..010` as one ten-ID catalog family:

1. atomic per-subscriber optional initial event, no replay, and no synthetic
   revision state;
1. setup races commit without replay while post-construction membership events
   resynchronize before delivery;
1. current selected item stream emits an item-identity event;
1. members removed/replaced to a zero identity refcount become silent, while a
   same-identity Replace remains observed; selected-stream completion/error
   terminates only the current positive-refcount epoch;
1. Reset rebuilds membership without leaks or missed members;
1. duplicate identity refcounting subscribes once and detaches last;
1. nested explicit batch emits one final batch event, including body-failure
   exit with original-error precedence;
1. empty batch and Move subscription stability;
1. reentrant membership mutation preserves FIFO consistency;
1. null/selector transactional failure with full subscription cleanup, terminal
   output error, idempotent disposal, ownership, and subscriber-failure
   isolation rules.

Coverage must exercise normal VM collections, unkeyed serviced collections,
and keyed serviced collections across all five flavors. Tests use counted
selectors/subscriptions rather than timing-based leak assertions.

## 8. Consumer pilots and documentation

Disposable Tableau validation must aggregate the supported internal
`cellComposite` source (not its `ObservableList` mirror) and prove initial
derived computation, one post-tree-attachment pulse, nested state updates,
removed/reset silence, duplicate refcounting, and one final explicit-batch
pulse. It should remove the revision counter, sender set, broad hub filter, and
manual defer depth while preserving post-tree-attachment timing explicitly.

Disposable DayDreams validation keeps precise collection add/remove handling
but replaces broad property-message casting with aggregate `item` events. It
must prove unrelated hub messages and removed/replaced cells are silent and
preserve current renderer event order and unsubscribe behavior in both Three
and Babylon where applicable.

Canonical docs will distinguish dynamic aggregate membership from ADR-0095's
fixed source, document the provenance envelope and explicit batch composition,
and regenerate the in-repo, `.io`, and native wiki surfaces.

Release metadata is part of the same change: bump `spec/VERSION`, every flavor's
package and minimum-spec declarations, lockfiles/manifests, compatibility
matrix, all flavor changelogs, and version/count claims in the root/spec/flavor
READMEs and `AGENTS.md`. "Every minimum-spec" means the five core flavors;
independently versioned C# companion packages keep their existing floors unless
their own code changes. The normative library catalog rises from 363 to 373 IDs
and the total including scenarios from 368 to 378. Generated `.io` and
native-wiki outputs must be regenerated from the canonical documentation source
and pass drift/link checks.

## 9. Rejected alternatives

- **Per-collection `onAnyChange` implementations:** duplicates difficult
  resubscription, identity, batching, and disposal logic.
- **Automatic hub-boundary coalescing:** requires a new public hub idle/batch
  lifecycle capability and expands custom-hub obligations beyond #136.
- **Pure payload-free `Void` only:** cannot identify DayDreams' changed current
  member and would force rescans or broad repainting. The provenance envelope
  remains optional to inspect and never requires consumers to maintain
  synthetic revision or other application state.
- **ObservableDictionary/paging in the first release:** element identity and
  visible membership need separate projection decisions.

## 10. Self-review

The design contains no placeholders. It chooses one source abstraction, one
event model, one identity rule, one batching rule, and explicit disposal. The
two known consumer differences are addressed without changing collection or
hub ownership contracts.
