# ADR 0073 — Add explicit hierarchical child-cache invalidation

**Status:** Accepted (2026-07-01)
**Spec version:** introduced in 3.1.0

## 1. Context

`HierarchicalVM` caches lazy children after first materialization. That is useful
for stable tree identity, but consumers with externally mutable hierarchies need
a documented way to drop a stale child cache and reload on the next access.

The aws-tui adoption feedback called out this missing contract for file/S3-like
trees, where listings can change outside the process.

## 2. Decision

Add explicit invalidation methods in every flavor:

- `InvalidateChildren` / `invalidate_children` / `invalidateChildren` drops this
  node's materialized child cache;
- calling it before materialization is a no-op;
- the next children access re-invokes the child factory;
- `InvalidateSubtree` recursively invalidates this node and all materialized
  descendants;
- invalidation publishes a property-changed message for the children property,
  not a structural add/remove/reparent message.

## 3. Consequences

Consumers can keep lazy caching as the default while explicitly refreshing stale
nodes. The operation is modeled as cache invalidation rather than structural
mutation, so existing tree-structure message semantics remain precise.

Time-to-live invalidation is deferred. A cross-flavor TTL contract needs an
injectable clock/test scheduler to avoid non-deterministic tests and host-specific
timing behavior.

## 4. Rejected alternatives

Automatically refreshing on every access was rejected because it would remove the
current stable-cache behavior and surprise consumers that rely on child identity.

Publishing `TreeStructureChangedMessage` for invalidation was rejected because
cache refresh is not an add/remove/reparent operation.
