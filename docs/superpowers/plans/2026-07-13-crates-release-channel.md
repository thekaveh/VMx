# crates.io Release Channel Implementation Plan

## 1. Package contract

- Add failing tests for exact Cargo package paths and actionable drift errors.
- Add an explicit Cargo include list and `tools/check-rust-package.py`.
- Run the checker against the real 0.20.0 package.

## 2. Disposable consumer

- Add failing tests for SemVer validation, manifests, lifecycle/command smoke,
  public polling, and exact dependency selection.
- Implement local `.crate` extraction and public `cargo add` modes.
- Prove the packaged crate using the installed stable toolchain.

## 3. CI and workflow contracts

- Add RED contract tests for ordinary Rust package CI and the tag workflow.
- Exercise package/consumer gates on Rust 1.88 and stable in ordinary CI.
- Add `rust-v*` release test, conformance, protected publish, public verify,
  and changelog-backed GitHub Release jobs.

## 4. Runbook and release truth

- Document MSRV, package/library names, first-token bootstrap, protected
  environment, official OIDC identity, immutable versions, yank/recovery,
  docs.rs lag, and post-verification three-surface docs.
- Add a 0.20.0 release-engineering changelog note without claiming publication.

## 5. Verification and Git flow

- Run Rust fmt, Clippy, all-feature tests, docs, package, and local consumer.
- Run full tools tests/current Ruff, versions, fixtures, five-flavor coverage,
  docs/site/wiki checks, pre-commit, diff, and credential hygiene.
- Merge a ticket-only PR to develop, then a ticket-only develop-to-main PR.

## 6. First release and completion

- Create protected `crates-rust` with reviewer approval, no admin bypass, and
  `rust-v*` tag-only deployments.
- Require an authenticated owner to place the narrow bootstrap token, then tag
  the verified main commit and monitor all release jobs.
- Verify crates.io, docs.rs, Rust 1.88/stable consumers, and GitHub Release;
  configure trusted publishing and remove/revoke the bootstrap token.
- Merge verified publication docs through develop/main, verify live site/wiki,
  close #67, and finalize the board item.
