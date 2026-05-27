# ADR 0014 — Search / filter on container VMs

**Status:** Accepted (2026-05-25)
**Spec version:** introduced in 2.0.0

## 1. Context

The 2012 VMx predecessor put `SearchTerm`, `SearchPredicate`,
`FilteredInnerCollection`, and `SearchCommand` directly on the composite
base class, with a 1-second Rx throttle on `SearchTerm` change events. The
current VMx has no equivalent — consumers wanting a filtered tree-view
build their own throttle, predicate, and filter pipeline.

## 2. Options considered

1. **Skip — leave search to consumers.** Smallest spec surface; loses the
   legacy parity goal.
1. **Restore search directly on `CompositeVM` / `GroupVM` base classes.**
   Symmetric with the legacy predecessor but grows the default container
   surface for every consumer (including those who never search).
1. **Provide a `SearchableState<TItem>` helper that implements `ISearchable`
   (from chapter 14) and composes with any iterable container.**

## 3. Decision

Option 3. The cycle ships a `SearchableState<TItem>` helper per flavor that:

- Implements `ISearchable` (from cycle 1).
- Holds the current `SearchTerm` and an Rx-style debounce.
- Holds the user-supplied `Predicate(TItem, string) -> bool`.
- Holds the current `Items` source (an iterable, typically the container).
- Exposes `Filtered` as an observable of the current matches.
- Exposes `search()` for force-immediate recompute (no debounce).

The base `CompositeVM` and `GroupVM` types are unchanged. Consumers opt in
by composing `SearchableState` with the container as the items source.

The debounce default is **1 second** (matching the legacy predecessor) and
is configurable via constructor/builder.

## 4. Consequences

- Five conformance IDs `COMP-014..COMP-018` cover search/filter behavior in
  composite context.
- Four conformance IDs `GRP-007..GRP-010` cover the same behavior in group
  context.
- Each flavor exposes `SearchableState<TItem>` in its `capabilities/`
  directory (it is itself capability-related — implementing `ISearchable`).
- The 1-second debounce default is normative; the helper accepts an
  override (per-flavor: TimeSpan / float seconds / number milliseconds).
- `search()` is the canonical "search now" method (typed already by
  `ISearchable`).
- The spec mentions but does NOT mandate a default predicate;
  case-insensitive substring is the recommended convenience but not
  required.
