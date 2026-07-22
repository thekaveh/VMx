# 11. Contributing & Releases

This page is the short routing layer for contributors. The operational source of
truth remains the repository docs.

## 11.1. Start With

- Contributing guide:
  [CONTRIBUTING.md](../../CONTRIBUTING.md)
- Spec index:
  [spec/README.md](../../spec/README.md)
- Compatibility matrix:
  [compatibility-matrix.md](../../compatibility-matrix.md)

## 11.2. Contribution Flow

- Open an issue for non-trivial work.
- Branch from `develop`, open the feature PR to `develop`, and run the relevant
  flavor checks locally.
- Promote `develop` to protected `main` only through a separate maintainer PR.
- Direct pushes to `develop` and `main` are blocked. Both PR stages require the
  always-present conformance, C#, Python, TypeScript, Swift, Rust, docs,
  examples, security, and spec-discipline aggregate checks against the latest
  target branch. Maintainer review is expected when another reviewer is
  available; the single-collaborator repository does not require self-approval.
- For behavior changes, start in `spec/` and follow the ADR discipline.
- Keep all supported flavors visible when a change affects shared behavior.

## 11.3. Validation Entry Points

The main local check families are:

- C#: restore, build, test, and `dotnet format`
- Python: `uv run pytest`, `ruff`, and `mypy --strict`
- TypeScript: `npm ci`, fixture sync, typecheck, lint, build, and test
- Swift: `swift build` and `swift test`
- Rust: `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, and
  `cargo test --locked`
- Repo-wide coverage and example-contract tools from `CONTRIBUTING.md`

Use the canonical command list in
[CONTRIBUTING.md](../../CONTRIBUTING.md)
instead of copying commands from this page into long-lived process docs.

## 11.4. Spec Discipline

Two repo rules matter most:

- semantic changes under `spec/` require a matching ADR unless the change is in
  an exempt path
- new conformance IDs require matching stubs in every catalog-complete flavor

Those rules are enforced in CI and described in the contributing guide and
repository automation.

## 11.5. Release Shape

Flavor packages version independently and release from verified `main` commits
through `<lang>-vX.Y.Z` operational tags. C# uses that form for core and
package-specific `csharp-notifications-vX.Y.Z` and
`csharp-dependency-injection-vX.Y.Z` tags for its companions, so independent
versions cannot collide. The spec uses `spec-vX.Y.Z`; Swift also pairs its
operational tag with the semantic `vX.Y.Z` tag required by SwiftPM.
Registry-backed channels are protected by environment approval, OIDC,
pre-publish checks of the exact locally built artifact, public-artifact checks,
and fresh-consumer verification. The Python channel pins its isolated PEP 517
backend and installs/smokes the wheel from `dist/` before the irreversible PyPI
action, then repeats the consumer check from the public registry.

### 11.5.1. Release Checklist

Use this sequence for every flavor so the repository, site, and wiki carry the
same actionable procedure:

1. Start from a clean, freshly fetched `origin/main`; never release from
   `develop` or an unmerged feature branch.
1. Confirm the source/package version and minimum-spec declaration agree, and
   prove both the intended operational tag and public registry version are
   unused.
1. Run the flavor's complete release gate and build the exact package locally.
   Inspect that artifact, install it into a clean consumer, and retain the check
   evidence before creating a tag.
1. Create the immutable `<lang>-vX.Y.Z` tag from the verified `main` commit. For
   Swift, create the paired semantic `vX.Y.Z` tag from the same commit. For C#
   companion packages, use their package-specific tag prefixes.
1. Monitor the matching release workflow, approve its protected environment
   only after the pre-publish jobs identify the expected artifact, and do not
   bypass a failed gate.
1. Verify the exact version on the public registry and install it into a second
   fresh consumer. Confirm the GitHub release points to the tagged commit and
   contains the expected artifacts and notes.
1. If publication fails after tag creation, keep the tag immutable. Correct the
   source or workflow on `main`, bump the affected package to a new patch
   version, and publish through a new tag.
