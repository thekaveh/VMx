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

For the exact release and tagging procedure, use
[CONTRIBUTING.md#4-releases-and-tagging](../../CONTRIBUTING.md#4-releases-and-tagging).
