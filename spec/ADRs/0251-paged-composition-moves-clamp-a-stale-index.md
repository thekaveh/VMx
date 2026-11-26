# ADR 0251 — A page move clamps a stale index before it picks its target

- **Status:** Accepted (amends the stale-index rule of [ADR-0168](0168-swift-and-rust-paged-composition-page-a-stored-copy.md) §2 and chapter 21 §5.2)
- **Date:** 2026-11-24
- **Spec version:** 3.30.0 (chapter 21 §5.1 comments, §5.2 and the §8 table; chapter 12 adds `COL-074`; no version bump in this change, see §2.5)
- **Related:** [ADR-0168](0168-swift-and-rust-paged-composition-page-a-stored-copy.md), [ADR-0023](0023-paging-capability-and-paged-composition.md), [ADR-0214](0214-collection-paging-keyed-add-and-aggregate-gate-rules.md) (inert after dispose), issue #1917. Also #1380 (closed; it defined the stale-index rule), #1782 (whether a clamping move publishes `PageCount`) and #1628 (pager commands).

## 1. Context

### 1.1 The stale-index rule

In C#, Python and TypeScript, `PagedComposition` reads a live source on each access and holds no copy (chapter 21 §5.2). A change to a source that the pager does not observe shows on the next read. The pager does not clamp `CurrentPageIndex` until one of three things happens: a delivered change, the next `CurrentPageIndex` assignment, or a `PageSize` assignment that changes the page size.

The four page moves are not on that list. Each move compares the raw stored index with its bound. A stale index that is larger than `PageCount - 1` therefore defeats both bound checks.

### 1.2 The reproduction

Issue #1917 gives this scenario. A plain 7-item list with `page_size=3` is on its last page (index 2). The list then shrinks to 2 items without the pager seeing it. The pager has `PageCount == 1`, and the stored index is still 2. The outcomes below follow from the code on `origin/develop` at `7d445367`.

- `move_to_last_page()` is a no-op, because `2 >= 0`.
- `move_to_next_page()` is a no-op, for the same reason.
- `move_to_previous_page()` moves to index 1, which is also an empty page.
- Only `move_to_first_page()` recovers.

A pager UI bound to the moves stays on an empty page until the user selects "First". The same guards exist in C# (`MoveToLastPage`, `MoveToNextPage`) and TypeScript (`moveToLastPage`, `moveToNextPage`).

### 1.3 Contract and the other flavors

Chapter 14 §3 (the `can_*` rule) says that the `IPageable` `move_to_*` methods clamp at the page bounds by contract, so every call is legal. Chapter 21 §5.1 calls `move_to_last_page()` a no-op only "when at last page", which a stale index does not satisfy.

Swift and Rust page a stored copy, and their index cannot go stale this way. Every write to the stored copy clamps the index in the same step:

- Swift `setSource(_:)` clamps. `init(sourceComposite:)` builds the copy from `snapshot()`, with the index at `0`, and the composite's change stream reaches the copy through `setSource(_:)`. The Swift moves still compare the raw index, but that index is always in range.
- Rust `set_source`, `push` and `remove_at` clamp. Rust's moves clamp the target in `move_to`, which `navigate` calls.

## 2. Decision

### 2.1 Previous and next moves clamp a stale index before they pick their target

In C#, Python and TypeScript, `move_to_previous_page` and `move_to_next_page` do the following:

1. Read `PageCount` once and compute `last = max(0, PageCount - 1)`.
1. Clamp the stored index to `[0, last]`, which gives `current`.
1. Choose the target from `current`.
1. Store and publish the move only when the target differs from the **stored** index, which is the value observers last saw.

The four targets are:

| Move                    | Target                   | Reads the stored index? |
| ----------------------- | ------------------------ | ----------------------- |
| `move_to_first_page`    | `0`                      | no                      |
| `move_to_previous_page` | `max(0, current - 1)`    | yes, through the clamp  |
| `move_to_next_page`     | `min(current + 1, last)` | yes, through the clamp  |
| `move_to_last_page`     | `last`                   | no                      |

The clamp changes a target only for `move_to_previous_page`. For `move_to_next_page`, `min(current + 1, last)` already bounds a stale index to `last`, so the clamp leaves that target unchanged. The clamp stays there so that the two relative moves share one rule. `move_to_first_page` and `move_to_last_page` do not read the stored index. `move_to_first_page` targets `0`, and `move_to_last_page` targets `last`, computed from `PageCount` as in step 1. All four moves publish under the rule in step 4, so a stale index still publishes once.

A stale index is compared with the target, not with the clamped value. The stored index changes from the stale value to the target, so observers receive the change. A move that only clamped the stored value and did not publish would change state silently, and that is rejected.

Each flavor has a small private helper (`MoveTo` in C#, `_move_to` in Python, `#moveTo` in TypeScript) that stores the target and publishes `CurrentPageIndex` and then `Items`, only when the stored index changes.

### 2.2 Amendment to ADR-0168 and chapter 21 §5.2

ADR-0168 §2 and chapter 21 §5.2 list the events that clamp a stale index. The list gains a fourth: **a page move call**. Every move call resolves a stale index, because each one stores an in-range target. A previous or next move clamps the index before it picks its target. A first or last move sets the index to its own target without reading the stored index. The index stays stale in the other cases until the events the chapter already names.

Chapter 21 §5.1 changes the move comments. The previous and next comments say that each clamps a stale index first. The first and last comments say that they target `0` and `max(0, PageCount-1)`. Chapter 21 §5.2 names the moves in the sentence that lists the triggers.

### 2.3 What does not change

- **In-range moves.** When the stored index is in `[0, last]`, the clamp is the identity. The targets and the no-op cases match the old guards, so `COL-016` to `COL-021` and `COL-031` keep their results. `COL-018` is unchanged.
- **Notification shape.** A move that changes the index publishes `CurrentPageIndex` then `Items`, once each. A move that changes nothing publishes nothing.
- **`PageCount`.** A move does not publish `PageCount`. Whether it should belongs to #1782.
- **Disposal.** After `dispose()`, the moves change nothing and emit nothing (ADR-0214).
- **Swift and Rust.** No code changes. Their stored index cannot be out of range, as §1.3 shows. Their tests are added so that all five flavors cover the rule.

### 2.4 Conformance

`COL-074` is a new normative ID. It states the stale-index rule: after an unobserved shrink, each move lands on a page in `[0, max(0, PageCount - 1)]`, and it publishes `CurrentPageIndex` and `Items` once. Chapter 12 §24 holds its entry, after `COL-073`. Chapter 21 §8 maps it to §5. `COL-018` stays as it was, because it tests only in-range no-ops.

The markers are:

- C#: `[Trait("Conformance", "COL-074")]` on `COL_074_PageMoves_ClampStaleIndex_AfterUnobservedShrink`.
- Python: `@pytest.mark.conformance("COL-074")` on `test_COL_074_page_move_clamps_stale_index_after_unobserved_shrink`, parametrized over the four moves.
- TypeScript: `describe("COL-074", ...)`.
- Swift: `/// COL-074 — ...` on `testCOL074PageMovesStayInRangeAfterSourceShrink`.
- Rust: `/// COL-074 — ...` on `paged_composition_moves_stay_in_range_after_source_shrink`.

### 2.5 Versions

No `spec-v3.30.0` tag exists on origin at this change. `git ls-remote --tags origin spec-v3.30.0` returns nothing. Following the precedent of ADR-0214 to ADR-0227, `spec/VERSION` stays at `3.30.0`. The change adds no public member, so `compatibility-matrix.md` does not change. Each package records the fix under its unreleased source version in its CHANGELOG. The C#, Python and TypeScript flavors each get a `### Fixed` entry. Swift and Rust change no library code. Each adds its tests and a `COL-074` entry under `### Added`.

## 3. Consequences

- A pager over an unobserved live source recovers on any page move. A pager UI bound to the moves no longer stays on an empty page after a shrink.
- From a stale index, `move_to_previous_page()` now lands on the last page in range, not on the page one below the stale index. This is the intended fix. The stale index was already out of range, so no in-range result changes.
- `move_to_previous_page()` now reads `PageCount` before it moves. For a non-sized live source (a C# `IEnumerable` or a Python generator-backed factory), that is one enumeration per previous move. The next and last moves already paid it, and this change makes the previous move consistent with them.
- Chapter 21 §5.2 gains a trigger that the other flavors' tests must cover. `COL-074` is that coverage.

## 4. Rejected alternatives

- **Clamp on read.** The `CurrentPageIndex` and `Items` getters could clamp. #1380 left that as a separate decision, and it would change every read path. Out of scope.
- **Clamp the stored index without publishing when the target equals the clamped value.** This changes state silently, and observers would keep the stale value. Rejected in §2.1.
- **Publish `PageCount` from the move.** That is the subject of #1782. Out of scope here.
- **Reuse `COL-018`.** `COL-018` pins the in-range no-ops, and the stale-index rule is a different behavior. A new ID states it.
- **Add the clamp to Swift and Rust moves.** Their stored index cannot be out of range, so the clamp would be dead code there. Rust's moves already clamp their target.

## Evidence

- The premise was checked by reading the move methods of all five flavors at `7d445367`. The C#, Python and TypeScript moves compare the raw stored index, and the Swift and Rust stored indexes clamp on every write (§1.3).
- Before the change, the new `COL-074` tests failed in each of the three changed flavors. C# failed at `MoveToPreviousPage` (index 2, expected 0). Python failed on three of the four moves (index 3, expected 1 on the next move). TypeScript failed at `moveToPreviousPage` (index 2, expected 0). The tests use a larger shrink than the issue's script (10 items to 5, from index 3), so the previous and next moves land on a non-empty page after the fix.
- Mutation check: with the clamp removed from Python `move_to_previous_page` only, the `COL-074` run failed for that move (exit 1, the other three passed). The clamp is removed only in that test run and is restored from the commit afterwards. Removing it from `move_to_next_page` would change no target (§2.1), and that removal was not run.
