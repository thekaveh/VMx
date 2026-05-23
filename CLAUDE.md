# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture

VMx is **one language-neutral specification with three idiomatic flavors**. The shape is identical across flavors; only the surface idiom changes (PascalCase C#, snake_case Python, camelCase TypeScript — codified in `spec/ADRs/0006-idiomatic-api-per-language.md`).

- **`spec/` is the source of truth.** 13 numbered markdown chapters (`00-overview.md` … `13-tree-utilities.md`), 8 ADRs, three JSON fixtures, current version in `spec/VERSION`. Behavior changes start here.
- **`spec/fixtures/*.json` are consumed at runtime by all three flavors** for lifecycle, message-ordering, and command-truthtable validation. Python wires them via hatchling `force-include` in `langs/python/pyproject.toml`; TypeScript copies them via `npm run sync-fixtures` (auto-run by `prebuild` / `prepack`); C# embeds them as resources. When editing a fixture, ensure all three flavors still load it.
- **`spec/12-conformance.md` enumerates 75 normative test IDs** (`LIFE-001`, `HUB-007`, `COMP-013`, `UTIL-002`, …). Every active flavor re-implements the catalog under `langs/<flavor>/tests/conformance/`. `tools/check-conformance-coverage.py` enforces 100% coverage in CI.
- **Each flavor versions independently** but a spec major bump triggers a major bump in every active flavor. Each package declares the spec version it implements: `MinSpecVersion` (C#), `__min_spec_version__` (Python), `__minSpecVersion__` (TypeScript). Compatibility is tracked by hand in `compatibility-matrix.md`.
- **Per-flavor source layout mirrors the spec chapters** — `aggregates/`, `builders/`, `commands/`, `components/`, `composites/`, `forwarding/`, `groups/`, `lifecycle/`, `messages/`, `services/`, `tree/`, `collections/`. When adding a primitive, add it to the same-named directory in all three flavors.
- **Reactive primitive per flavor**: C# uses `System.Reactive`, Python uses `reactivex`, TypeScript uses `rxjs` (ADR-0002). Don't introduce additional reactive libraries.

## Spec discipline (enforced by CI)

Two rules in `.github/workflows/spec-discipline.yml` block PRs:

1. **Any change under `spec/` requires a new ADR in `spec/ADRs/`** in the same PR. Exempt files: `spec/README.md`, `spec/VERSION`, `spec/ADRs/**`, `spec/fixtures/**`, `spec/12-conformance.md`. A maintainer can apply the `no-adr-needed` label to bypass for typos/formatting.
2. **A new conformance ID in `spec/12-conformance.md` requires a matching test stub in every active flavor**, in the same PR. Stub patterns the check recognizes (comments don't count):
   - Python: `@pytest.mark.conformance("XXX-NNN")`
   - C#: `[Trait("Conformance", "XXX-NNN")]`
   - TypeScript: `describe("XXX-NNN", ...)`

## Build / test / lint commands

### Python (`langs/python`)
```bash
cd langs/python
uv sync --all-extras
uv run pytest                              # full suite (385 tests)
uv run pytest tests/conformance            # conformance only
uv run pytest -k LIFE_005                  # a single conformance ID
uv run pytest tests/unit/test_xxx.py::test_name
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/vmx               # must be strict-clean
```

### C# (`langs/csharp`)
```bash
cd langs/csharp
dotnet restore
dotnet build
dotnet test                                # both VMx.Tests + VMx.Conformance.Tests
dotnet test --filter "Conformance=LIFE-005"
dotnet format --verify-no-changes
```
Central package versions live in `Directory.Packages.props`; common project settings in `Directory.Build.props` (`TreatWarningsAsErrors=true`, `Nullable=enable`).

### TypeScript (`langs/typescript`)
```bash
cd langs/typescript
npm ci
npm run sync-fixtures   # copies spec/fixtures/*.json → src/fixtures/ (required after spec fixture edits)
npm run typecheck
npm run lint
npm run build           # tsup, dual ESM + CJS
npm test                # vitest run
npm run test:watch
npx vitest run -t "LIFE-005"   # single conformance ID
```

### Conformance coverage tool
```bash
# Report-only across all flavors
python3 tools/check-conformance-coverage.py

# CI mode (matches the conformance workflow)
uv --project langs/python run python tools/check-conformance-coverage.py \
    --require csharp --require python --require typescript

# The tool's own unit tests
uv --project langs/python run pytest tools/tests/
```

### Pre-commit
`pre-commit install` once. Hooks: ruff (Python only), mdformat (spec/ and docs/), `dotnet format --verify-no-changes` (C# only), whitespace/EOL hygiene. mdformat is pinned to 0.7.x (1.0 is incompatible with `mdformat-gfm`).

## When changing behavior

1. Update the relevant `spec/NN-*.md` chapter.
2. Add an ADR in `spec/ADRs/` describing the decision (numbered NNNN-kebab-title.md).
3. If the change is normative, add an ID to `spec/12-conformance.md` and a stub in **all three** `langs/*/tests/conformance/` trees.
4. Implement in all three flavors. Keep the public surface idiomatic per ADR-0006 (Pascal/snake/camel); keep the conceptual shape identical.
5. If touching `spec/fixtures/`, re-run TS `npm run sync-fixtures` and verify Python/C# still load the file (the Python hatchling mapping and C# embedded-resource paths are configured for these exact filenames).
6. Bump `spec/VERSION` and each flavor's package version per the SemVer policy in README §6.1. Update `compatibility-matrix.md`.
