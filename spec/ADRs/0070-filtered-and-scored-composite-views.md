# ADR 0070 — Add filtered and scored composite views

**Status:** Accepted (2026-07-01)
**Spec version:** introduced in 3.1.0

## 1. Context

`SearchableState<T>` can recompute a filtered list, but it does not own a
visible-domain current item or subscribe to a composite as a derived view. A
consumer that renders a filtered list over a `CompositeVM<VM>` often needs the
cursor to live in visible-row space, not source-index space.

The aws-tui adoption feedback identified this as repeated wrapper code for file
panes, command palettes, and score-ranked search results.

## 2. Decision

Add `FilteredCompositeVM<VM>` as an additive companion to `CompositeVM<VM>`.
The source composite remains the owner of membership and lifecycle; the filtered
view owns a visible projection, visible count, visible-domain current, change
notification, predicate replacement, visible navigation, and disposal of its
source subscription.

Add `ScoredFilteredCompositeVM<VM>` for score-ranked projections. Null/absent
scores exclude an item. Non-null scores sort descending with source-order stable
ties. A `RefreshScores()` method recomputes ordering when external score state
changes.

## 3. Consequences

Consumers can keep collection ownership in `CompositeVM<VM>` while reusing a
standard derived-view primitive for filtered rendering and cursor behavior.

This does not replace `SearchableState<T>`: `SearchableState<T>` remains the
small capability helper for search-term and debounce behavior; filtered
composites are the cursor-owning projection layer.

## 4. Rejected alternatives

Adding filtering directly to `CompositeVM<VM>` was rejected because it would mix
source ownership with view-specific projection state.

Using only `SearchableState<T>` was rejected because it has no current/cursor
contract and no translated collection-view semantics.
