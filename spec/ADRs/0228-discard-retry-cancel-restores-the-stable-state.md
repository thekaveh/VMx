# ADR 0228 — A cancelled discard retry restores the stable state it started from

- **Status:** Accepted
- **Date:** 2026-11-12
- **Spec version:** 3.30.0 (chapter 23 §7 and §8, `ARES-013`)
- **Amends:** [ADR-0100](0100-async-resource-vm.md) §8, the cancellation baseline
  of `DiscardPrevious`. Related:
  [ADR-0199](0199-async-resource-loader-cancellation-restores-the-stable-state.md),
  and ledger item §1.1 in
  `docs/maintenance/2026-10-18-open-cross-flavor-decisions.md`.

## 1. Context

Chapter 23 gives two rules for a cancelled reload. §5 and §7 say that
cancellation restores the saved stable state. §8 says that `DiscardPrevious`
uses `Idle` as the cancellation baseline.

The rules differ when a discard reload starts from a value-less `Error`. C#,
Python, TypeScript and Rust keep that `Error` as the baseline, so a cancel
returns to `Error`. Swift resets the baseline to `Idle`, so a cancel returns to
`Idle`. Heimdall's poll had to accept both outcomes. No ARES ID covered the
case. ARES-007 covers a discard reload from `Ready`, where both rules give
`Idle`.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: pick the rule that is uniform
across the flavors and simplest to state.

1. A discard reload relinquishes an accepted value and installs value-less
   `Loading`, as before.
1. The cancellation baseline is `Idle` when the reload relinquished a value.
   Otherwise it is the saved stable state. A reload that starts from a
   value-less `Error` therefore returns to that `Error`.

Four of the five flavors already behave this way, and §5 and §7 already state
the general rule. Only Swift changes. The alternative, always `Idle`, would
change four flavors and the §5 and §7 text.

## 3. Consequences

- Swift resets the stable state to `Idle` only when a value is relinquished. A
  cancelled discard retry from `Error` now restores `Error`. The Swift
  CHANGELOG records this under Fixed.
- Heimdall's poll rule (load in `Idle`, skip `Loading`, reload otherwise)
  stays correct, because a value-less `Error` reloads.
- `ARES-013` covers the case with tests in all five flavors.
- This ADR does not bump the spec version. The release version is the owner's
  decision, as it was for ADR-0226.

## 4. Owner review

This decision was made under the delegation. Owner review of this ADR and the
chapter 23 diff remains open on issue #671.
