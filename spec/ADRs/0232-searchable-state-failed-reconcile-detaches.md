# ADR 0232 — A failed post-subscribe reconcile releases the source-change signal

- **Status:** Accepted
- **Date:** 2026-11-15
- **Spec version:** 3.30.0 (chapter 06 §8.2, `SRCH-010`)
- **Amends:** [ADR-0191](0191-subscriber-failures-do-not-stop-delivery-or-detach.md)
  Decision rules 2 and 6 (§2.3).
- **Extends:** [ADR-0224](0224-failed-population-disposes-unowned-candidates.md)
  Decision rule 5. Related: [ADR-0014](0014-search-and-filter.md),
  [ADR-0099](0099-searchable-source-reactivity.md), #1881, #1324.

## 1. Context

`SearchableState` takes an optional source-change signal (`sourceChanged`,
`source_changes` or `sourceChanges`, ADR-0099). Its constructor filters once
for the seed snapshot. It then installs the merged subscription, which includes
the signal. It filters a second time to close the gap between the first read
and the attach (chapter 06 §8.2).

C#, Python and TypeScript run that second filter after the subscription exists
and outside any guard. If the item supplier or the predicate throws there, the
constructor throws, but the subscription to the signal stays attached. The
caller never receives the object, so it cannot dispose it. The signal then keeps
running consumer code on every later value, for the life of the signal (#1881).
Python reproduces this on develop: after the constructor raises, the signal
subject keeps one observer, and a later signal calls the supplier again.

The rules that govern this case did not cover it. ADR-0191 rule 6 says that a
failure in the constructor's first filter reaches the caller. It does not say
what a failure in the second filter does. ADR-0191 rule 2 says that no failure
detaches the library's own source subscription. ADR-0224 rule 5 detaches a
filtered view whose first recompute throws, and it names no `SearchableState`.
No test fails the second pass.

Swift and Rust differ in shape, and the evidence is in the Decision.

## 2. Decision

The owner delegated open design decisions on 2026-11-07. The orchestrator chose
the options below, and each choice has its reason here. The rule is the same
in all five flavors wherever a flavor can fail.

1. **The reconcile is part of construction.** If the second filter pass fails,
   the helper releases its subscription to the signal before the failure
   reaches the caller. The caller receives the original failure. The caller
   never gets the helper, so the helper must release itself. The reason is that
   the detach is the only way to stop the signal from running consumer code.
1. **The first filter pass is unchanged.** It runs before any subscription
   exists, so nothing needs releasing. A failure there still reaches the caller
   (ADR-0191 rule 6).
1. **A disposal failure does not replace the original failure.** This is
   ADR-0224 rule 3. C# catches and discards a failure of `Dispose()`. Python
   wraps `dispose()` in `suppress(Exception)`. TypeScript wraps `dispose()` in a
   `try` and discards its failure. Each flavor then rethrows the original
   failure.
1. **A later signal runs neither the supplier nor the predicate.** Once the
   subscription is released, the signal has no path to the helper's code.
1. **The amendments.** ADR-0191 rule 6 now reads: a failure in the constructor's
   first filter, or in its post-subscribe reconcile, reaches the constructor's
   caller. ADR-0191 rule 2 now has one exception: the constructor's own
   post-subscribe reconcile releases the helper's signal subscription before its
   failure propagates. These amendments name rules 2 and 6 only. The other
   rules are unchanged.
1. **The extension.** ADR-0224 rule 5 detaches a filtered view whose first
   recompute throws. This ADR extends the same detach to a `SearchableState`
   whose post-subscribe reconcile throws. ADR-0224 rules 3 and 4 apply to it.
1. **A new conformance ID, `SRCH-010`.** The ID covers the detach rule in all
   five flavors. `SRCH-009` is not extended, for three reasons. `SRCH-009` says
   that the helper stays live after a failure, and this rule says the opposite
   after a constructor failure, so one ID cannot state both outcomes. The ID
   names one construction-time behavior, so a regression fails under one
   marker. The catalog rule requires a test in every catalog-complete flavor
   (ADR-0224 rule 7 and ADR-0226 precedent). Every flavor can pass its test, so
   the ID is required. The ID is the next free `SRCH` number.
1. **Swift: no library change.** The second pass exists at
   `langs/swift/Sources/VMx/Capabilities/Search.swift` L84-L87, after the
   subscription at L76. It cannot throw. The item supplier and the predicate are
   the non-throwing types `() -> [T]` and `(T, String) -> Bool` (L35-L36), and
   `init` is not `throws` (L51). No caught failure can reach the caller, so no
   guard can be written. A Swift trap ends the process. The `sink` captures
   `self` weakly (L77), so a released helper is freed and its `AnyCancellable`
   cancels the signal subscription. The Swift `SRCH-010` test checks that
   release.
1. **Rust: no library change.** The second pass exists at
   `langs/rust/src/searchable_state.rs` L121 (`let _ = state.filtered();`),
   outside any guard. The subscription is stored at L117 in
   `source_changes_subscription` (field at L40), and no other owner holds that
   `Arc`. A panic in the pull unwinds through `build`, which drops `state`, so
   the `Option<Subscription>` drops. `Drop for Subscription` calls `dispose`
   (`langs/rust/src/runtime.rs` L1793-L1797, and `dispose` at L1776), which
   removes the subscriber. The Rust defect therefore does not exist, and the
   behavior already matches the rule. This evidence is traced from the code,
   not run. The Rust `SRCH-010` test checks that the panic reaches the caller
   and that a later source message does not read the supplier. The test cannot
   detect a leaked subscription through the public API, because `MessageHub`
   has no subscriber count and the signal handler never reads the supplier.
   It does detect a swallowed panic.
1. **No divergence entry in ADR-0009.** After items 8 and 9, all five flavors
   show the same behavior: a failed construction holds no signal subscription,
   and a later signal runs no consumer code. No divergence is recorded.
1. **No package version change.** The fix changes no public API. Each changed
   package records a `Fixed` entry under its unreleased source-version section.
   `spec/VERSION` stays at 3.30.0, because no `spec-v3.30.0` tag exists
   (`CONTRIBUTING.md` §2.8 and §4.3).

## 3. Consequences

- In C#, Python and TypeScript, a `SearchableState` whose constructor fails
  holds no subscription on its signal. A later signal runs no consumer code.
- Swift and Rust need no code change. Their behavior is pinned by `SRCH-010`.
- Chapter 06 §8.2 states the rule. Chapter 12 §20 defines `SRCH-010`, and
  chapter 06 §10 lists it.
- ADR-0191 and ADR-0224 carry the back-links in their `Status` lines and
  registry cells.
- The public API does not change.

## 4. Rejected alternatives

- **Extend `SRCH-009`.** Rejected, as item 7 gives. `SRCH-009` requires that
  the helper stays live, which is the opposite outcome.
- **No ID, as ADR-0224 did.** Rejected. ADR-0224 added no ID while Rust could
  not pass a test. Here every flavor can pass its test, so the catalog rule
  requires the ID.
- **An explicit guard in Rust.** Rejected. `Drop` already releases the
  subscription on unwinding, so a guard would change no observable behavior.
  The added code would be a second release path that tests cannot tell apart.
- **Making the Swift closures throwing.** Rejected. That changes a public
  signature to guard a failure that no caller can produce today.
