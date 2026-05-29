# ADR 0023 — Paging (`IPageable` capability + `PagedComposition` helper)

**Status:** Accepted (2026-05-27)
**Spec version:** introduced in 2.1.0

## 1. Context

GuideArch and its predecessor both wrap `PagedCollectionView`-style paging
around compositions. The 2012 VMx predecessor added an `IPageable` interface
to `Contract/Receivers.cs` that described page-size, a current-page index,
a derived page count, navigation verbs, and a paging-enabled flag. The current
VMx has no paging primitive; `SearchableState<TItem>` (per ADR-0014) filters
but does not page.

## 2. Options considered

1. **Skip paging — consumer-owned.** Each consumer re-implements page
   arithmetic and navigation. No shared abstraction.
1. **Capability-only — add `IPageable` to capabilities, no helper.** Surfaces
   the navigation contract. Leaves composition mechanics to consumers.
1. **Capability + helper — add `IPageable` AND a `PagedComposition<TVM>`
   decorator** (analogous to `SearchableState`/`ExpandableState`) that wraps
   any composition and exposes a paged slice. Consumers who only need the
   capability can still implement it directly.

## 3. Decision

Option 3. `IPageable` joins the capability set (ADR-0010) as the 22nd member;
`PagedComposition<TVM>` lands in `spec/21-collections.md` §"Paging" with its
own conformance IDs in the `COL-` block.

## 4. Consequences

- `spec/14-capabilities.md` adds `IPageable` as the 22nd capability (§2.X).
- One conformance ID `CAP-022` covers the capability's contract surface.
- `spec/21-collections.md` defines `PagedComposition<TVM>` and contributes
  `COL-NNN` IDs in the paging range.
- Per-flavor implementation: `IPageable` interface in `capabilities/`;
  `PagedComposition<TVM>` in `collections/` (or per-flavor equivalent).
- Composition with `SearchableState<TItem>` is well-defined: filter first,
  then page. The chapter §"Composition with other helpers" pins ordering.
  See also ADR-0014 for `SearchableState` context.
