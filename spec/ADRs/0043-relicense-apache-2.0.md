# ADR 0043 — Relicense from MIT to Apache-2.0

**Status:** Accepted (2026-06-19)
**Spec version:** — (no spec change; project-governance decision)
**Related:** [`LICENSE`](../../LICENSE), [`NOTICE`](../../NOTICE), README §6.1 (versioning policy)

## 1. Context

VMx shipped under the MIT license from inception through the currently-published
releases (Python `2.6.1`, C# `2.6.0`, TypeScript `2.6.0`, Swift `2.6.0` subset).
MIT is permissive and short, but it grants **no explicit patent license** and
provides no defensive-termination or attribution (`NOTICE`) mechanism. As VMx
matures toward broader and enterprise adoption across four language ecosystems,
the absence of an explicit patent grant is a recurring concern for downstream
consumers performing license review.

The repository is **single-copyright-holder** (Kaveh Razavi); there are no
external contributors retaining copyright, so a forward relicense is
unrestricted.

## 2. Decision

Relicense VMx from **MIT** to **Apache License 2.0**, effective this commit,
uniformly across all four flavors and the shared specification/tooling.

Concretely:

- [`LICENSE`](../../LICENSE) is replaced with the **verbatim** Apache License 2.0
  text (so GitHub and SPDX tooling detect `Apache-2.0` reliably).
- A [`NOTICE`](../../NOTICE) file is added (Apache convention) asserting the
  copyright and the Apache-2.0 grant.
- SPDX license metadata is updated in every package manifest:
  `langs/python/pyproject.toml` (`license` + the `License ::` classifier),
  `langs/csharp/Directory.Build.props` (`PackageLicenseExpression`),
  `langs/typescript/package.json` (`license`). Swift has no manifest license
  field and relies on the `LICENSE` file.
- Documentation license badges and the per-flavor README "License" sections are
  updated to Apache-2.0.
- **No per-file SPDX headers are added.** The repository has never used per-file
  headers; `LICENSE` + `NOTICE` fully establish the grant, and adding headers to
  every source file across four languages is churn without commensurate benefit.

## 3. Rationale

- **Explicit patent grant.** Apache-2.0 §3 grants users a patent license from
  contributors — protection MIT does not provide.
- **Defensive termination.** Apache-2.0 §3 terminates the patent grant for a
  party that initiates patent litigation over the work, discouraging patent
  aggression.
- **Attribution via `NOTICE`.** Apache-2.0 §4 standardizes downstream
  attribution without the MIT requirement to reproduce the full license text in
  every copy.
- **Enterprise familiarity.** Apache-2.0 is among the most widely-reviewed and
  pre-approved permissive licenses in corporate open-source policies.
- **Still permissive.** Apache-2.0 remains a permissive, non-copyleft license —
  the change does not restrict how consumers use, modify, or redistribute VMx.

## 4. Consequences

- **Forward-effective only.** Already-published artifacts (PyPI `vmx 2.6.1`, the
  npm/NuGet `2.6.0` packages) remain MIT-licensed for those exact versions; the
  copyright holder cannot retroactively alter a published release's terms.
  Apache-2.0 applies to the source from this commit forward and to all **future**
  releases.
- **Registry propagation requires a release.** The new SPDX metadata reaches
  PyPI / npm / NuGet only when each flavor next publishes. This relicense lands
  in the repository now; the publish is **deferred** to the next release (no
  version bump in this change).
- **No code, runtime, API, or behavioral change.** No conformance ID is affected;
  `spec/VERSION` is unchanged (this is not a spec change). No SemVer bump is
  mandated by the license change itself, though each flavor's eventual release
  will record the relicense in its `CHANGELOG.md`.
- **CI is unaffected.** `PackageLicenseExpression=Apache-2.0` and the npm/PyPI
  SPDX strings are valid; builds and the conformance gate are independent of the
  license field.
