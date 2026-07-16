# Releasing the `vmx-rs` Rust crate

This runbook documents VMx's tag-driven crates.io channel. A
`rust-v<X.Y.Z>` tag on `main` starts `.github/workflows/release.yml`. The Cargo
package name is `vmx-rs`; consumers import its `[lib]` target as `vmx`.

The declared minimum supported Rust version (MSRV) is 1.88. Every package and
release consumer runs on Rust 1.88 and stable. Change `rust-version` only with
an explicit compatibility decision, changelog entry, and matching CI update.

## 1. One-time owner setup

### 1.1 Protected GitHub environment

Create the `crates-rust` environment in `thekaveh/VMx`:

- restrict deployment refs to `rust-v*` tags;
- require maintainer approval; and
- disable administrator bypass.

The publish job has `id-token: write`. Store the one-time bootstrap credential
only on this environment, never as a repository-wide secret.

### 1.2 First publication bootstrap

crates.io trusted publishing requires an existing crate, so the first release
needs a one-time owner-authorized API token:

1. Sign in to crates.io with the intended owner and verify the email address.
1. Reconfirm that `vmx-rs` does not exist and the intended `rust-v<X.Y.Z>` tag
   is absent.
1. Create a short-lived token whose endpoint scope is only `publish-new`, with
   crate pattern `vmx-rs` and the earliest practical expiry.
1. Add it through the GitHub UI as the `CRATES_IO_TOKEN` secret on
   `crates-rust`. Never paste it into chat, a shell transcript, an issue, or a
   repository file.
1. Create and approve the first immutable tag only after all preparation is on
   `main`. The workflow maps the secret to `CARGO_REGISTRY_TOKEN` only for the
   bootstrap `cargo publish` step.

Do not use a local manual publish: the first release must traverse the same
main-ancestry, package, MSRV, conformance, and consumer gates as later releases.

### 1.3 Switch to trusted publishing

After the first release is visible, open the crate's **Settings → Trusted Publishing** and
add a GitHub configuration with these exact values:

- repository owner: `thekaveh`;
- repository: `VMx`;
- workflow filename: `release.yml`; and
- environment: `crates-rust`.

Delete `CRATES_IO_TOKEN` from the GitHub environment and revoke the bootstrap
token on crates.io. With the secret absent, the workflow invokes the official
`rust-lang/crates-io-auth-action`, pinned to an immutable commit, and passes
its short-lived token only to `cargo publish`. Do not retain an API token as a
fallback after this migration.

## 2. Cutting a stable release

1. Land all release changes on `main` through feature-to-develop and
   develop-to-main PRs.

1. Update `version` and, when required, `rust-version` in `Cargo.toml`,
   `MIN_SPEC_VERSION` in `src/lib.rs`, and the compatibility matrix.

1. Add a matching `## [X.Y.Z] — YYYY-MM-DD` changelog section.

1. From a clean checkout of current `origin/main`, run the release gates and
   prove the version and tag are unused:

   ```bash
   version=$(sed -nE 's/^version = "([^"]+)"/\1/p' langs/rust/Cargo.toml)
   git ls-remote --exit-code --tags origin "refs/tags/rust-v${version}" || true
   curl --fail --user-agent \
     'VMx-release-verifier/1.0 (https://github.com/thekaveh/VMx)' \
     "https://crates.io/api/v1/crates/vmx-rs/${version}" || true
   ```

1. Tag the exact verified main commit and push once:

   ```bash
   git tag "rust-v${version}" origin/main
   git push origin "rust-v${version}"
   ```

1. Approve the `crates-rust` deployment and monitor every Release workflow
   job. Never move, delete, or recreate a tag after crates.io accepts its
   version or a GitHub Release exists.

The workflow is stable-version-only. Add and test explicit prerelease handling
before using an alpha, beta, or release-candidate version.

## 3. Release gates

Before publication, Rust 1.88 and stable jobs independently verify:

- the tag commit is reachable from `origin/main` and tag/Cargo versions match;
- `cargo fmt --check` and all-target/all-feature Clippy with warnings denied;
- all-feature tests and warning-free documentation;
- the exact package-content allowlist and Cargo's clean package build; and
- an extracted `.crate` consumer using the `vmx` namespace, exact version,
  lifecycle transitions, and command execution.

A separate gate enforces 100% five-flavor conformance coverage and Rust fixture
sync. The protected publish job repeats ancestry, version, package, and local
consumer checks before either bootstrap or OIDC authentication.

After crates.io accepts the version, Rust 1.88 and stable consumers poll both
crates.io and docs.rs, execute `cargo add vmx-rs@=X.Y.Z` in fresh projects, and
repeat the behavior smoke. Only both passing jobs allow creation of the GitHub
Release from the matching Rust changelog section.

## 4. Independent verification and documentation

Repeat the public consumer outside the release run:

```bash
python3 tools/smoke-rust-consumer.py --version X.Y.Z --poll-timeout 1800
gh release view rust-vX.Y.Z --repo thekaveh/VMx
```

Inspect the crates.io version, docs.rs API page, owner list, workflow run, and
GitHub Release through fresh requests. Only then update README, compatibility
matrix, Rust README, installation guide, and Rust flavor page. Regenerate and
verify the in-repository docs, MkDocs `.io` site, and GitHub wiki through the
normal develop/main PR flow before marking the issue complete.

## 5. Immutability, yank, and recovery

### 5.1 Failure before publication

Fix the failure through the normal PR flow. If crates.io has not accepted the
version and no GitHub Release exists, remove the unused failed tag, land the
fix on `main`, and tag the new commit. Once either public artifact exists, do
not move or reuse the tag/version.

### 5.2 Authentication failure

Confirm environment approval and the exact trusted-publisher repository,
workflow, and environment. During the first release only, replace an expired
`publish-new` token with another equally narrow, short-lived token. Never add a
permanent token or bypass environment protection.

### 5.3 Publication succeeded but verification failed

crates.io versions are permanent and cannot be overwritten or deleted. Fix
forward with a new patch version. If the published version is unsafe or
unusable, an authenticated owner may yank it:

```bash
cargo yank --version X.Y.Z vmx-rs
```

Yanking prevents new resolution but preserves existing lockfiles. It is not a
secret-removal mechanism; revoke exposed credentials immediately and follow
the repository security process. Document the failure, replacement version,
and any yank. Never silently replace an accepted package or tag.
