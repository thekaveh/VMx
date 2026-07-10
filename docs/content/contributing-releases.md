# 11. Contributing & Releases

This page is the short routing layer for contributors. The operational source of
truth remains the repository docs.

## Start With

- Contributing guide:
  [CONTRIBUTING.md](../../CONTRIBUTING.md)
- Spec index:
  [spec/README.md](../../spec/README.md)
- Compatibility matrix:
  [compatibility-matrix.md](../../compatibility-matrix.md)

## Contribution Flow

- Open an issue for non-trivial work.
- Branch from `main` and run the relevant flavor checks locally.
- For behavior changes, start in `spec/` and follow the ADR discipline.
- Keep all supported flavors visible when a change affects shared behavior.

## Validation Entry Points

The main local check families are:

- C#: restore, build, test, and `dotnet format`
- Python: `uv run pytest`, `ruff`, and `mypy --strict`
- TypeScript: `npm ci`, fixture sync, typecheck, lint, build, and test
- Swift: `swift build` and `swift test`
- Rust: `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, and
  `cargo test`
- Repo-wide coverage and example-contract tools from `CONTRIBUTING.md`

Use the canonical command list in
[CONTRIBUTING.md](../../CONTRIBUTING.md)
instead of copying commands from this page into long-lived process docs.

## Spec Discipline

Two repo rules matter most:

- semantic changes under `spec/` require a matching ADR unless the change is in
  an exempt path
- new conformance IDs require matching stubs in every full-parity flavor

Those rules are enforced in CI and described in the contributing guide and
repository automation.

## Release Shape

Releases are coordinated through three tag families on the same commit:

- repo-wide: `vX.Y.Z`
- per-language: `<lang>-vX.Y.Z`
- spec: `spec-vX.Y.Z`

Companion packages version independently and are tracked in the compatibility
matrix rather than through their own tag family.

For the exact release and tagging procedure, use
[CONTRIBUTING.md#4-releases-and-tagging](../../CONTRIBUTING.md#4-releases-and-tagging).
