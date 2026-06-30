# ADR-0065 — Swift conformance cutover to full-catalog enforcement (subset manifest retired)

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** the subset-manifest enforcement mechanism introduced for the Swift flavor (referenced by ADR-0053 and ADR-0059 through ADR-0064)

## Context

The Swift flavor entered Phase 3 as a documented 42-ID subset (9 of 19 areas). Across Increments 0–6 (ADRs 0059–0064) it was grown to cover **all 237 library conformance IDs** — full library parity with C#, Python, and TypeScript.

Throughout that effort Swift was special-cased in `tools/check-conformance-coverage.py`: it alone carried a `manifest_rel` entry (`langs/swift/conformance-subset.txt`) and was graded by a **two-way subset match** — every manifest ID must have a `/// XXX-NNN —` doc-comment marker, every tested catalog ID must be listed in the manifest, and no marker may reference a non-catalog ID. The other three flavors are graded against the **full catalog** (`catalog - found`). The subset manifest was the ratchet that let parity grow one area per increment without CI demanding the whole catalog up front.

Now that the manifest lists exactly the 237 catalog IDs, the two-way match is operationally identical to full-catalog enforcement, and the 237-line file is pure maintenance burden — it must be kept byte-for-byte in sync with both the catalog and the test markers forever.

## Decision

Retire the subset manifest and make Swift a first-class full-parity flavor in the coverage tooling:

1. In `tools/check-conformance-coverage.py`, set the `_SCRAPERS["swift"]` registry entry's `manifest_rel` to `None`. This routes Swift through the same `catalog - found` MISSING gate as csharp/python/typescript: `--require swift` now fails unless **every** one of the 237 library catalog IDs has a Swift `/// XXX-NNN —` marker. (Markers for IDs not in the catalog become informational `ORPHAN`s, not hard failures — matching the other flavors.)
1. Delete `langs/swift/conformance-subset.txt`.
1. Update the tool's unit tests: the subset-specific cases (manifest-id-without-test, test-id-not-in-manifest "unlisted", bogus-as-hard-failure) are replaced by full-catalog cases (full coverage passes, a missing catalog ID fails, an orphan marker is informational). The `VMX-NNN` finding-reference exclusion test is retained.
1. Update the `conformance.yml` enforcement-step comment (the `--require swift` flag was already present; only its semantics change).

The Swift scraper itself is unchanged: it still reads only `*.swift` doc-comment markers, so no Swift toolchain is needed in the coverage CI job (`swift test` remains a separate CI-only job on macOS, per ADR-0037).

## Consequences

- **Full Swift library parity is now CI-mandatory.** Any newly added catalog ID must ship a Swift marker in the same PR (the existing spec-discipline rule already required this for the other three; Swift now joins it for real, against the full catalog).
- **The divergence escape hatch is gone.** Under the subset, an ID Swift genuinely could not cover could simply be omitted from the manifest. That is no longer possible — every library catalog ID is required. This is safe today (the catalog excludes the 5 `THEME-00x` scenario IDs, which live in example apps; the subset already equalled 237). A future Swift-impossible primitive would have to be handled by a catalog/spec change, not a silent manifest omission — a stricter, more honest bar.
- **`THEME-00x` remains the only gap before *total* parity.** The five scenario IDs are exercised by flagship example apps; Swift does not yet ship a flagship app, so they stay pending. They are not part of the library catalog the coverage tool enforces, so this cutover is independent of them.
- **Historical references.** Several earlier Swift ADRs — 0050, 0053, and 0059–0064 — reference `langs/swift/conformance-subset.txt` by name (and earlier subset counts like "41 IDs"); those references are accurate as of when each was written and are left intact as point-in-time records. This ADR is the breadcrumb for the file's retirement.
- The subset plumbing in the tool (`load_subset_manifest`, the `subsets` dict, the `compute_gaps` subset branch, the `manifest_rel` registry column) is retained as a dormant, documented extension point for any future flavor that needs a growth ratchet — it is simply unused now that no flavor sets a manifest.

## Alternatives considered

- **Keep the manifest, rely on the two-way match for "full" enforcement.** Rejected: leaves a 237-line file that must be kept in lockstep with the catalog and markers indefinitely, with no behavioral benefit now that subset == catalog.
- **Delete the subset plumbing entirely (not just the swift entry).** Deferred: the `manifest_rel`/`load_subset_manifest`/subset-branch machinery is harmless dormant code and documents how a future flavor could be onboarded with a growth ratchet. Removing it is a separate, optional refactor with no functional effect.
