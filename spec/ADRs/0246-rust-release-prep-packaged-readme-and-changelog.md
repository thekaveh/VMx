# ADR 0246 — Rust release-prep corrects the packaged README and CHANGELOG before the tag

- **Status:** Accepted
- **Date:** 2026-11-22
- **Spec version:** 3.30.0 (no normative change; the `vmx-rs` release process in `langs/rust/RELEASING.md` §2 steps 3 and 4)
- **Related:** [ADR-0080](0080-rust-flavor-feasibility.md) (the planned `rust-v<X.Y.Z>` tags and crates.io publication), issue #1443 (this change), issue #67 (the tag and publication), [CONTRIBUTING §4.3](../../CONTRIBUTING.md#43-release-invariants) (release invariants), #1560 (restored the source-only README).

## 1. Context

`langs/rust/README.md` and `langs/rust/CHANGELOG.md` ship inside the `vmx-rs`
package: `Cargo.toml` sets `readme = "README.md"` and its `include` list selects
both files. crates.io keeps the README and CHANGELOG of each version and cannot
replace them, so the source-only text must be corrected before the
`rust-v0.37.0` tag.

Before this change, the README said that the crate was not yet published
(§1), gave only the git and path dependency forms (§2), and the CHANGELOG
release heading read `## [0.37.0] — unreleased source version`. The release
section also cited repository paths and a repository file that do not resolve
inside the crate.

Owner decision B: the release-prep PR is prepared now and is not merged. On
publish day the owner merges it to `develop`, promotes `develop` to `main`, and
tags `rust-v0.37.0` in the same sitting.

## 2. Decision

1. **Timing (owner decision B).** The release-prep PR stays open until publish
   day. The owner merges it, promotes it and tags it in one sitting. The date
   on the CHANGELOG heading is set in that sitting, so it equals the tag date.
   Reason: the owner chose this sequence, and it keeps the packaged text, the
   heading date and the tag in agreement.

1. **README status (§1).** The sentence "The crate is not yet published to
   crates.io. Use a git or path dependency, as §2 shows." is replaced by
   "Install the crate from crates.io, as §2 shows." Reason: issue #1443
   criterion 1 and `RELEASING.md` §2 step 3 remove the "not yet published"
   status.

1. **README install (§2).** `vmx-rs = "0.37.0"` is the first install form and
   the only live `vmx-rs` line. The git and path forms stay as commented
   alternatives. Reason: issue #1443 criterion 2 and `RELEASING.md` §2 step 3
   make the crates.io form first. A second live `vmx-rs` key would duplicate
   the key in one `[dependencies]` table, which TOML rejects.

1. **README spec and coverage wording.** The status line already names spec
   3.30.0 with no tag reference, and the README already states that the tests
   cover every library conformance ID with no count (`CONTRIBUTING.md` §3.2).
   Both stay unchanged. Reason: `RELEASING.md` §2 step 3 asks for these two
   properties, and the README already has them.

1. **CHANGELOG heading.** The heading stays `## [0.37.0] — unreleased source version` in this PR. On publish day the owner replaces `unreleased source version` with the release date, so that the heading reads
   `## [0.37.0] — YYYY-MM-DD` and the date equals the tag date. Reason:
   `RELEASING.md` §2 step 4 and `CONTRIBUTING.md` §4.3 date the heading
   immediately before the tag, and the date is not known before publish day.
   `tools/check-version-consistency.py` accepts the heading in both states,
   because `[Unreleased]` stays empty.

1. **CHANGELOG release section body.** Two references are corrected so they
   resolve inside the published crate: "the 0.1.0 to 0.36.0 sections of
   `langs/rust/CHANGELOG.md`" becomes "the 0.1.0 to 0.36.0 sections below", and
   "(CONTRIBUTING §2.8)" becomes a link to the §2.8 anchor on `main`. Reason:
   `RELEASING.md` §2 step 3 asks that the release section describe the
   published package. The bullets that cite ADRs and issues stay unchanged.

1. **No library behavior change, so no CHANGELOG Fixed or Changed entry.**
   `[Unreleased]` stays empty.

1. **No new test or guard.** The issue asks for checks, not a new test. Its
   criteria 3 to 5 can run only at tag time, and the rest run now (see the PR
   body). A CI guard that the README's first install form matches the
   `Cargo.toml` version is a possible follow-up; it is not added here. Because
   no test is added, no mutation evidence applies.

1. **Record.** This ADR is the durable record of the release-prep decisions. It
   changes no spec chapter, conformance ID or fixture. Its number is 0246, the
   next free number on `origin/develop` when it was written.

## 3. Consequences

- On publish day, the owner sets the CHANGELOG heading date (decision 5) before
  the tag, and checks that it equals the tag date.
- The release-prep PR must merge in the same sitting as the tag. If the tag
  slips after the merge, `develop` advertises `vmx-rs = "0.37.0"` before the
  crate exists on crates.io.
- The root README, `compatibility-matrix.md`, the installation guide and the
  Rust flavor page keep their source-status text until after publication
  (`RELEASING.md` §4). This PR does not change them.

## 4. Rejected alternatives

- **Merge now and set the date now.** Rejected: owner decision B. A date set
  now is wrong if publication slips, and `develop` would advertise an install
  form that crates.io does not yet serve.
- **Keep the git form as the first live line.** Rejected: issue #1443
  criterion 2 and `RELEASING.md` §2 step 3 make the crates.io form first, and
  two live `vmx-rs` keys cannot share one `[dependencies]` table.
- **Add a guard test in this PR.** Rejected: the issue asks for checks, and a
  guard is a new CI rule outside its scope. It is a possible follow-up.
