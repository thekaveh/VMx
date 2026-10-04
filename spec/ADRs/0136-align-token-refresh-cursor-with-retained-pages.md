# ADR 0136 — Keep the token-paging refresh cursor aligned with retained pages

- **Status:** Accepted
- **Date:** 2026-10-04
- **Spec version:** 3.25.0
- **Amends:** [ADR-0069](0069-token-paged-composition.md)

## 1. Context

ADR-0069 lets `RefreshCommand` skip mutating the accumulator when the
refreshed first page matches the accumulator head, and chapter 21 then said
that "token and property state are still refreshed". Every flavor therefore
adopted the refreshed page's next token even when the accumulator kept pages
two and later. That token addresses page two, so the next `LoadMoreCommand`
appended page two again: `Items` and `CurrentToken` no longer described the
same loaded prefix (#326).

The same head comparison treated an empty refreshed page as a match for any
accumulator, and treated a terminal first page as a match for a longer
accumulator. Both kept items that the refreshed result no longer contains while
adopting a terminal token.

Rust also lacked the stale-result guard that the other flavors use. A load
that started before a refresh could commit after it and append a page from the
old cursor to the refreshed first page.

## 2. Decision

`Items` and `CurrentToken` always describe one contiguous prefix loaded from
the initial token: after any commit, `CurrentToken` is the continuation that
follows the last accumulated item. For a refreshed page *P* with next token *T*
and an accumulator *A*, where *P* matches when it is no longer than *A* and the
equality hook accepts it against the first `len(P)` items of *A*:

1. *P* matches and is as long as *A*: keep *A* and adopt *T*. *T* is the
   refreshed continuation for exactly the retained items, so a changed opaque
   token or a newly terminal token is adopted.
1. *P* matches, is shorter than *A*, is non-empty, and *T* is not terminal: keep
   *A* and keep the prior `CurrentToken`, including a prior terminal value.
1. Anything else, including an empty or terminal page shorter than *A*:
   replace *A* with *P*, adopt *T*, and emit one `Reset`.

Chapter 21 now states the notification order for both branches and for
failures. A non-mutating refresh publishes no `CollectionChanged`, then the
`Items`, `CurrentToken`, and `HasMore` property notifications, then a
command-eligibility re-signal. A replacing refresh publishes one `Reset` before
that same sequence. A failed fetch or equality hook changes nothing and
publishes nothing. These orders are what every flavor already emitted.

Each load or refresh supersedes every operation started before it. A stale
operation commits nothing and publishes nothing. Rust gains the operation
generation that C#, Python, TypeScript, and Swift already had, in both of its
constructor paths and in its direct `load_more` method.

`COL-065` covers the rule, and `COL-027`'s token clause now applies to the
replacement branch.

## 3. Consequences

- An unchanged-head refresh after several loads never makes the next load
  refetch or duplicate a retained page.
- Head equality establishes only that the first page is unchanged. VMx still
  neither refetches nor reconciles later pages, and it never compares or
  interprets token values, so a backend that invalidates a retained
  continuation is not detected. A refresh after reaching the end keeps the
  terminal cursor while the head matches, so rows appended after the end are
  not discovered by that refresh.
- A consumer that needs every refresh to resynchronize from the first page
  supplies an equality hook that rejects every match (Rust: the item type's
  `PartialEq`). Swift's default hook already rejects every match.
- The visible window is unchanged for a matching head and collapses to the
  refreshed first page otherwise, as before.
- This is a backward-compatible minor change: spec 3.25.0, with a minor bump in
  every flavor.

## 4. Rejected alternatives

Always replacing the accumulator with the refreshed first page and adopting its
token whenever *A* is longer than *P* keeps the cursor fresh, but it collapses
the visible window and emits a `Reset` on every refresh after a second load,
which removes the redundant-mutation suppression ADR-0069 provides.

Keeping the prior cursor in every matching case, including an empty or terminal
page, would keep items that the refreshed result shows no longer exist.

Comparing or reinterpreting token values to detect a changed cursor was
rejected because tokens are opaque to VMx.

Keyed reconciliation of refreshed and overlapping pages is a separate extension
(#390) and builds on this baseline.
