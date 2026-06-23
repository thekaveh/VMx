# ADR 0024 — `ServicedObservableCollection<T>` (hub-aware observable collection)

**Status:** Accepted (2026-05-27)
**Spec version:** introduced in 2.1.0

## 1. Context

The 2012 VMx predecessor contained a `ServicedObservableCollection<T>` in
`Collections/ServicedObservableCollection.cs` that extended the platform's
`ObservableCollection<T>` with the ability to publish collection-change
notifications to the `IMessageHub`. Consumers subscribed to the hub to observe
mutations across any collection in the VM tree without holding direct references
to individual collections.

The current VMx has no equivalent. Consumers who want hub-level visibility into
collection mutations must wire up `CollectionChanged` handlers manually and call
`hub.Send(…)` themselves. This is error-prone and creates boilerplate duplicated
across every collection a consumer wants to observe.

ADR-0010 established that VMx collections should be opt-in primitives, not part
of the base VM hierarchy. The `IMessageHub` contract is core, defined in
`spec/03-messages.md` (ch. 03).

## 2. Options considered

1. **Skip — remain consumer-owned.** Each team re-implements the hub-publication
   pattern. No shared abstraction.
1. **Extend `CompositeVM` to publish its own `CollectionChanged` to the hub.**
   Couples hub publication to the VM hierarchy. Consumers using non-VM
   `ObservableCollection` instances gain nothing.
1. **Reintroduce `ServicedObservableCollection<T>` as a standalone opt-in
   primitive.** Matches the 2012 name (recognizable to readers of legacy code);
   injectable hub is optional (null-hub is a safe no-op); no coupling to the VM
   hierarchy.

## 3. Decision

Option 3. `ServicedObservableCollection<T>` is a standalone opt-in primitive
defined in `spec/21-collections.md` §2. Key rules:

1. The constructor accepts an optional `IMessageHub`. If no hub is injected the
   collection behaves exactly like a plain `ObservableCollection<T>` (standard
   local `CollectionChanged` events fire; nothing is published to any hub; no
   error is raised).
1. When a hub is injected, every mutation (add, remove, replace, reset) raises
   the local `CollectionChanged` event **first**, then publishes a
   `CollectionChangedMessage` to the hub. The two notifications always occur in
   this order.
1. Hub publication happens on the same thread as the mutation. The collection
   does not marshal to any scheduler.
1. The local `CollectionChanged` event is always raised, regardless of hub
   presence, so that platform bindings (e.g., WPF `ItemsControl`) continue to
   work without modification.

## 4. Consequences

- `spec/21-collections.md` §2 defines `ServicedObservableCollection<T>` and
  its `CollectionChangedMessage` shape.
- Conformance IDs `COL-001..COL-004` cover: publish ordering (local before hub),
  null-hub fallback, threading non-marshal, and each mutation kind
  (add/remove/replace/reset).
- Per-flavor placement: C# `VMx.Collections/`, Python `vmx.collections`,
  TypeScript `vmx/collections`.
- Consumers who want cross-collection hub visibility pass their hub at
  construction time; consumers who do not care pass nothing. No new required
  service contract; no breaking change to existing VM types.
- `IMessageHub` is defined in `spec/03-messages.md` and referenced here.
  `CollectionChangedMessage` is defined in `spec/21-collections.md` §2.4 as a
  v2.1 domain-specific message (per chapter 03 §2). Flavors add the type to
  their existing typed-message catalog.

## 5. Amendments

- **Correction (2026-06, spec v2.6.x maintenance):** §1 originally read
  "ADR-0013 introduced the `IMessageHub` contract." That attribution is
  incorrect — ADR-0013 introduced `INotificationHub`; `IMessageHub` is a core
  contract defined in `spec/03-messages.md` (ch. 03) and predates ADR-0013.
  The §1 sentence has been corrected accordingly.
