# ADR 0254 — A disposed Rust `PagedComposition` changes no state

- **Status:** Accepted
- **Date:** 2026-11-24
- **Spec version:** 3.30.0 (chapter 21 §5.5, a new §5.6, and the §8 `DISP-006` row; chapter 12 is unchanged, see §2.6)
- **Related:** [ADR-0214](0214-collection-paging-keyed-add-and-aggregate-gate-rules.md) (rule 1 is corrected here for Rust), [ADR-0208](0208-rust-collection-local-events-and-paging-notifications.md) (gives the Rust pager `dispose()`), [ADR-0168](0168-swift-and-rust-paged-composition-page-a-stored-copy.md), [ADR-0023](0023-paging-capability-and-paged-composition.md), issue #1783. Also #1299 (the C#, TypeScript and Swift rule) and #1782 (the §5 notification section).

## 1. Context

ADR-0214 rule 1 made `PagedComposition` paging calls inert after `dispose()` in C#, Python, TypeScript and Swift. It exempted Rust with the reason that Rust "has no public disposal member and is unchanged". That premise is false. ADR-0208 §2.5 gives the Rust pager a `dispose()` member, on the same date as ADR-0214, and `langs/rust/src/paged_composition.rs` has had one since then.

The Rust `dispose()` set the disposed flag without the state lock. `PagerCore::publish` read the flag, so no change after disposal was announced. The mutators did not read it. After `dispose()`, these calls changed the page size, the page index, the page count and the items, with no notification:

- `set_page_size`, through the state directly;
- `set_current_page_index`, `next_page`, `previous_page` and the four `move_to_…_page` calls, through `PagerCore::navigate`;
- `set_source`, through `PagerCore::replace_source`;
- `push` and `remove_at`.

The COL-031 test `pager_follows_a_composite_source_until_disposed` pinned this change: after `dispose()`, `set_page_size(1)` and `push(c)` left `page_count() == 4`.

Chapter 21 §5 had no disposal rule. Its §5.5 said only that `dispose` stops the source observation and the publication, and the disposal contract's Rust section (§6.8.5.5) recorded the state change as a flavor exception, not as a defect.

## 2. Decision

Decided under the owner's 2026-11-07 delegation. Each rule takes the cross-flavor-uniform and simplest option.

1. **Rust applies ADR-0214 rule 1.** After `dispose()`, `set_page_size`, every page-index write and move call, `set_source`, `push` and `remove_at` change no state and publish nothing. A `remove_at` after disposal removes nothing and returns `None`. Reads keep the last page size, page index, page count and items. This matches the other four flavors and the disposal contract's inventory row, which already states the rule for every flavor.
1. **The flag is set and read under the state lock.** `dispose()` stores the flag while it holds `core.state`. Each mutator reads the flag under the same lock before it changes anything. A mutator that held the lock before `dispose()` returned finished its change first, and one that takes the lock later sees the flag. A check made before the lock could let a call that passed it change state after `dispose()` had returned. The source subscription is still released after the lock. No subscriber runs under the state lock, so the lock taken in `dispose()` cannot re-enter.
1. **The rule is stated in chapter 21.** Chapter 21 §5.6 states the rule for all five flavors, and the §8 `DISP-006` row cites it. `DISP-006` requires each helper to follow its documented post-dispose behavior, so the rule belongs in the chapter, not only in ADR-0214. The §5.5 sentence about `dispose` now points to §5.6.
1. **No new conformance ID.** The rule is the documented post-dispose behavior that `DISP-006` already requires. The Rust test is `disposed_pager_paging_calls_change_no_state_and_publish_nothing` in `langs/rust/tests/post_dispose_inertness.rs`, which carries no ID, as the other tests in that file do. `pager_follows_a_composite_source_until_disposed` (COL-031) now asserts the frozen state, and its other two markers are unchanged. A new ID would need a marker in all five flavors, and this change does not need one.
1. **ADR-0214 records the correction.** Its Status gains "rule 1 corrected by ADR-0254", and its registry cell repeats that. The body of ADR-0214 is not edited. Its rule 1 text stays true for the four flavors it names, and the Rust sentence stays as the historical record.
1. **Versions and records.** `spec/VERSION` stays at 3.30.0, as ADR-0251 did, because no `spec-v3.30.0` tag exists. The change adds no public member, so `compatibility-matrix.md` does not change. `spec/HISTORY.md` §39 names ADR-0254, because rule B of the release-record test requires each ADR labelled with the target release to be named there. The Rust CHANGELOG records a `Fixed` entry under `[0.37.0] — unreleased source version`. No package version changes.
1. **The disposal contract drops the Rust exception.** `docs/content/primitives/disposal-contract.md` §6.8.5.5 no longer says that later paging calls still change the pager's state.

## 3. Consequences

- A disposed Rust pager keeps the page size, page index and items it had at `dispose()`. A caller that changed a Rust pager after disposal sees no effect, as in the other flavors.
- COL-031's `pager_follows_a_composite_source_until_disposed` is the only in-repo test that pinned the old state. It now asserts the frozen state.
- The Rust `dispose()` takes the state lock. The `navigate` target closure runs under that lock, and each closure is a plain index computation.

## 4. Rejected alternatives

- **Check the flag before the lock.** A check outside the lock is racy for the reason in §2.2. Rejected.
- **Keep the Rust exception and document it.** The inventory row already states the rule for all flavors, so the exception would leave the code, the chapter and the disposal contract in disagreement. Rejected.
- **Guard publication only.** Publication is already suppressed. The state change is the defect. Rejected.
- **Add a new conformance ID.** It would need five stubs in one change, and `DISP-006` already requires the behavior. Rejected for this change.

## Evidence

- The premise was checked at `origin/develop` `983e11b7`. The Rust `set_page_size`, `navigate`, `replace_source`, `push` and `remove_at` had no disposed check, and `publish` read the flag.
- Before the fix, the new test `disposed_pager_paging_calls_change_no_state_and_publish_nothing` failed at its first assertion. `set_page_size(3)` after `dispose()` left `(3, 1, 2, [4, 5])` where `(2, 1, 3, [3, 4])` was expected.
- Mutation check: with only the disposed check removed from `set_page_size`, the new test fails at its first assertion (`set_page_size`, `(3, 1, 2, [4, 5])` against `(2, 1, 3, [3, 4])`, exit 101). The check was then restored, and the library diff matched its pre-mutation copy byte for byte.
- After the fix, the Rust conformance and post-dispose suites pass, including COL-031 with its frozen-state assertion.
