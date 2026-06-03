# Contributing to VMx

Thanks for your interest in contributing!

## 1. Workflow

1. Open an issue describing the change before opening a PR for anything non-trivial.
2. Branch from `main`. Use a descriptive branch name (`feat/...`, `fix/...`, `docs/...`).
3. Run the relevant test suite locally before pushing.
4. Open a PR. CI must be green and at least one approval is required.

## 2. Per-language setup

### 2.1 C#

```bash
cd langs/csharp
dotnet restore
dotnet build
dotnet test
dotnet format --verify-no-changes
```

### 2.2 Python

```bash
cd langs/python
uv sync --all-extras
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/vmx
```

### 2.3 TypeScript

```bash
cd langs/typescript
npm ci
npm run sync-fixtures   # copy spec/fixtures/*.json → src/fixtures/
npm run typecheck
npm run lint
npm run build
npm test
```

## 3. Spec-driven changes

Behavior changes start in `spec/`. The rules are:

- A spec change requires a matching ADR in `spec/ADRs/`. This is enforced by the
  `spec-discipline` CI check.
- Files exempt from the ADR requirement: `spec/README.md`, `spec/VERSION`,
  `spec/ADRs/**`, `spec/fixtures/**`, `spec/12-conformance.md` (adding catalog
  IDs is governed by the conformance-stub rule below, not by ADRs), and
  `spec/proposals/**` (historical planning artifacts; landed proposals are
  already covered by the ADR they introduced).
- A new conformance test ID in `spec/12-conformance.md` requires a matching test stub
  in **every** active language flavor in the same PR. The CI check looks for
  `@pytest.mark.conformance("XXX-NNN")` (Python), `[Trait("Conformance", "XXX-NNN")]`
  (C#), and `describe("XXX-NNN", ...)` (TypeScript) — comment stubs do not satisfy
  the check.

### 3.1 Bypass

If a spec change genuinely does not warrant an ADR (e.g., a typo fix or pure
formatting change), a maintainer may add the `no-adr-needed` PR label to bypass the
ADR check. Use sparingly; the label is intended for changes with zero semantic effect.

See the ADRs in `spec/ADRs/` for the rationale behind each architectural rule.

## 4. Releases and tagging

VMx uses **three coordinated tag families** at every release, all pointing to the
same commit:

| Tag family            | Format                  | What it pins                                       |
| --------------------- | ----------------------- | -------------------------------------------------- |
| Repo-wide             | `vX.Y.Z`                | The whole repository at this version.              |
| Per-language          | `<lang>-vX.Y.Z`         | A specific language flavor at this version.        |
| Spec                  | `spec-vX.Y.Z`           | The language-neutral specification at this version. |

`<lang>` is one of: `csharp`, `python`, `typescript`, `swift`. The Swift family
was added in v2.4.0; releases prior to v2.4.0 only have the first three.

### 4.1 Why all three families

- **Submodule consumers** (e.g., projects vendoring VMx as `vendor/vmx/`) expect a
  plain `vX.Y.Z` tag to pin against. Without it `git checkout v2.1.0` fails.
- **Per-language consumers** pinning to a specific flavor (e.g., a Python project
  that wants `python-v2.1.0` without caring about the C# release cadence) get a
  canonical tag for their flavor.
- **Spec consumers** (e.g., third-party language implementations) can pin to a
  `spec-vX.Y.Z` independent of any flavor's implementation pace.

### 4.2 Cutting a release

At every release, the maintainer creates **all** of:

```bash
# Example for v2.4.0 (six tags from this release onward; v2.3.0 and earlier
# only had five — no swift-v* tag).
git tag spec-v2.4.0       <sha>   # spec/VERSION matches X.Y.Z
git tag csharp-v2.4.0     <sha>
git tag python-v2.4.0     <sha>
git tag typescript-v2.4.0 <sha>
git tag swift-v2.4.0      <sha>   # added in v2.4.0 — Swift's first release
git tag v2.4.0            <sha>   # repo-wide

git push origin spec-v2.4.0 csharp-v2.4.0 python-v2.4.0 typescript-v2.4.0 \
    swift-v2.4.0 v2.4.0
```

All six tags must point to the same SHA — the commit where every flavor's
manifest declares X.Y.Z and `spec/VERSION` reads X.Y.Z.

A companion package (e.g., `VMx.Notifications`) versions independently per
ADR-0009 / ADR-0013 and does not get its own family tag — its version lives in
its package manifest and in [`compatibility-matrix.md`](compatibility-matrix.md).

### 4.3 Source-version invariant

The source on `main` MUST always declare the version that the next release will
ship. Do not let source claim `X.Y.Z` if no `vX.Y.Z` tag exists at the
corresponding SHA — that confuses downstream consumers who try to `git checkout
vX.Y.Z`. Either tag immediately or revert the source manifests to the previous
released version.

## 5. Code of conduct

This project follows the Contributor Covenant v2.1 — see [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
