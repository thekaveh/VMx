# Contributing to VMx

Thanks for your interest in contributing!

## Workflow

1. Open an issue describing the change before opening a PR for anything non-trivial.
2. Branch from `main`. Use a descriptive branch name (`feat/...`, `fix/...`, `docs/...`).
3. Run the relevant test suite locally before pushing.
4. Open a PR. CI must be green and at least one approval is required.

## Per-language setup

### C#

```bash
cd langs/csharp
dotnet restore
dotnet build
dotnet test
dotnet format --verify-no-changes
```

### Python

```bash
cd langs/python
uv sync --all-extras
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/vmx
```

## Spec-driven changes

Behavior changes start in `spec/`. The rules are:

- A spec change requires a matching ADR in `spec/ADRs/`. This is enforced by the
  `spec-discipline` CI check.
- Files exempt from the ADR requirement: `spec/README.md`, `spec/VERSION`,
  `spec/ADRs/**`, `spec/fixtures/**`, and `spec/12-conformance.md` (adding catalog
  IDs is governed by the conformance-stub rule below, not by ADRs).
- A new conformance test ID in `spec/12-conformance.md` requires a matching test stub
  in **every** active language flavor in the same PR. The CI check looks for
  `@pytest.mark.conformance("XXX-NNN")` (Python) and `[Trait("Conformance", "XXX-NNN")]`
  (C#) — comment stubs do not satisfy the check.

### Bypass

If a spec change genuinely does not warrant an ADR (e.g., a typo fix or pure
formatting change), a maintainer may add the `no-adr-needed` PR label to bypass the
ADR check. Use sparingly; the label is intended for changes with zero semantic effect.

See `docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md` §5 and §6 for
the full process.

## Code of conduct

This project follows the Contributor Covenant v2.1 — see [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
