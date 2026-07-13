# crates.io Release Channel Design

## 1. Objective

Publish `vmx-rs` 0.20.0 as the first public Rust release from a verified
`main` commit while preserving `vmx` as the library import name. The channel
must prove the crate contents, Rust 1.88 MSRV, stable Rust, lifecycle and
command behavior, five-flavor conformance, crates.io availability, docs.rs,
and an exact clean consumer before creating a GitHub Release or changing
public-status documentation.

This is distribution-only work. It does not change VMx behavior, the
language-neutral specification, dependencies, or conformance IDs.

## 2. Current Evidence

- `langs/rust/Cargo.toml` declares package `vmx-rs` 0.20.0, library `vmx`,
  and minimum spec 3.20.0. Revalidation found that its former Rust 1.82 floor
  cannot parse required dependency `rxrust` 1.0.0-rc.5's edition-2024
  manifest; Rust 1.85 parses it but cannot compile its let chains, which were
  stabilized in Rust 1.88. The first truthful consumer floor is therefore
  Rust 1.88.
- The crate has 391/391 behavioral conformance coverage and its ordinary Rust
  CI runs on Linux, macOS, and Windows.
- The crates.io API reports that `vmx-rs` does not exist; docs.rs 0.20.0 and
  `rust-v0.20.0` are also absent.
- `cargo package` succeeds, but currently includes the complete conformance
  test tree because no explicit publish allowlist exists.
- No Rust release job, release runbook, protected `crates-rust` environment,
  local Cargo credential, registry token environment variable, or repository
  publishing secret exists.
- crates.io requires the crate to exist before an owner can configure trusted
  publishing. Its official action exchanges GitHub OIDC for a short-lived
  token after that configuration exists.

## 3. First-Publish Authentication

Use one tag-driven workflow with two mutually exclusive authentication paths.
The first `rust-v0.20.0` run consumes a narrowly scoped crates.io token stored
only in the protected `crates-rust` environment. After 0.20.0 is public, the
owner configures the trusted publisher for `thekaveh/VMx`, `release.yml`, and
`crates-rust`, removes/revokes the bootstrap token, and future runs use the
official `rust-lang/crates-io-auth-action` pinned to an immutable commit.

The token is never accepted through chat, committed, printed, or copied into
a general repository secret. A local manual publish is not used because it
would bypass the checked tag path. A permanent API token is not retained once
OIDC can identify the exact repository, workflow, and environment.

## 4. Package and Consumer Contracts

`Cargo.toml` explicitly includes `src/**`, the behavioral `tests/**`,
`README.md`, and `CHANGELOG.md`. Cargo-generated manifest, lock, and VCS
metadata remain expected. A Python checker runs Cargo's real package listing
and rejects any missing or unexpected path, including local configuration,
build output, credentials, or test/source files outside the reviewed list.

The disposable consumer tool has two modes:

1. local mode packages the checkout, extracts the exact `.crate`, adds it as a
   path dependency, and runs against only those packaged files;
1. public mode polls the exact crates.io version and docs.rs URL, then runs
   `cargo add vmx-rs@=X.Y.Z` in a fresh project.

Both modes require `vmx::VERSION` to match, complete a construct/destruct/
dispose lifecycle, and execute a `RelayCommand` exactly once. Temporary files
are removed unless explicitly retained.

## 5. CI and Release Ordering

Ordinary Rust CI adds a Linux package-consumer matrix for Rust 1.88 and stable.
The tag workflow uses the same toolchain matrix for format, Clippy with denied
warnings, all-feature tests, docs, package allowlist, and local consumer. A
separate gate runs full five-flavor conformance coverage before the protected
publish job can start.

The publish job rechecks main ancestry, exact tag/manifest version, package
contents, and the packaged consumer before authentication. Bootstrap-token
and OIDC steps are mutually exclusive, and neither hides duplicate-version or
registry failures. After publication, Rust 1.88 and stable jobs poll crates.io
and docs.rs and run the exact public consumer. Only both green consumers allow
the matching changelog section to become a GitHub Release.

## 6. Documentation and Recovery

The preparation PR adds the release runbook and a release-engineering
changelog note but keeps all public status truthful. After registry, docs.rs,
consumer, and GitHub Release verification, a second PR pair updates README,
compatibility matrix, Rust README, installation and flavor docs, regenerates
the MkDocs site and GitHub wiki, and verifies their live deployments.

Published versions and tags are immutable. A pre-publish failure is fixed on
a new `main` commit and receives a new patch version if its tag already exists.
A bad public version is yanked, never overwritten or deleted; locked consumers
remain reproducible. Corrective code ships as a new SemVer version and public
status stays unchanged until its own verification completes.

## 7. External Gate

Repository preparation and the protected GitHub environment can be completed
without crates.io credentials. The first tag cannot be created until an
authenticated crates.io account owns a narrowly scoped publish token. If that
authorization remains unavailable, #67 stays Todo/Ready with exact evidence;
no tag, release, public claim, or completion state is fabricated.
