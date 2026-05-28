# ADR 0022 — `IFilterable<T>` capability

**Status:** Accepted (2026-05-27)
**Spec version:** introduced in 2.1.0

## 1. Context

`SearchableState<TItem>` (per ADR-0014) gives consumers a debounced search-string
filter with a consumer-supplied predicate builder. The underlying capability —
"this collection/composition can be filtered by an arbitrary predicate" — is
implicit, not surfaced. The VMx.old predecessor invented its own predicate-based
filter contract (`IFilterable<T>` in `Contract/Receivers.cs`) and used it in
places that were not search-string-shaped.

## 2. Options considered

1. **Skip — keep `SearchableState` as the only filter primitive.** Consumers
   who want a predicate-only filter wrap a no-op search term. Awkward.
1. **Add `IFilterable<T>` as a 21st capability.** Surface the predicate
   directly. `SearchableState<TItem>` is reframed as a predicate-builder over the
   capability — no breaking change to its surface.
1. **Add a standalone `IPredicateFilter<T>` distinct from capabilities.**
   Avoids growing the capability set. Inconsistent with ADR-0010.

## 3. Decision

Option 2. `IFilterable<T>` joins the capability set as the 21st member with
two members: `Filter: Predicate<T>?` (null means no filter) and
`CanFilter() : bool`.

## 4. Consequences

- `spec/14-capabilities.md` adds a new 2.x subsection for `IFilterable<T>`.
- One new conformance ID `CAP-021` covers the capability's contract surface.
- Each flavor's `capabilities/` directory adds an `IFilterable<T>` interface
  declaration (no implementation; capabilities are opt-in per ADR-0010).
- `SearchableState<TItem>`'s public surface does not change; an internal cycle may
  refactor it to implement `IFilterable<T>` in a future minor version.
