# VMx Phase 0 — Repo Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the existing near-empty repo to a state where the new multi-language layout is in place, the legacy Python stubs have moved to their new home, both `langs/csharp/` and `langs/python/` build & test successfully as empty skeletons, GitHub Actions runs green for each, and the standard OSS hygiene files are in place. After Phase 0, the repo is ready to receive spec content (Phase 1) and real implementation code (Phases 2 & 3).

**Architecture:** Top-level `langs/<lang>/` folders host each language flavor as a self-contained project. Shared concerns (`spec/`, `docs/`, `examples/`, `tools/`, `.github/`) live at the repo root. Phase 0 only creates the scaffolding — no spec text, no library code. Smoke tests (a single trivial passing test per language) prove the build pipelines work.

**Tech Stack:**

- **C#:** .NET SDK 8.x, multi-target `netstandard2.0;net8.0`, xUnit, `dotnet format`
- **Python:** 3.10–3.13, `hatchling` build backend, `uv` as dev/CI runner, `pytest`, `ruff`, `mypy --strict`
- **CI:** GitHub Actions (ubuntu-latest + macos-latest + windows-latest matrix)
- **Hygiene:** `.editorconfig`, `.gitattributes`, pre-commit (ruff + dotnet format + markdown lint)

**Spec reference:** `/Users/kaveh/repos/VMx/docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md`, primarily sections §4 (layout), §10 (tooling/CI), §11 (migration).

**Open question resolutions baked into this plan:**

- Python build backend: **hatchling** (mature, well-supported by `uv`).
- Python dev/CI runner: **uv** (faster than pip, supports lockfiles).
- Symbol packages (`.snupkg`): on from day one.
- `vmx` PyPI / NuGet / npm name availability: verified during Task 4/5 (fall back to `vmx-mvvm` if `vmx` is taken on PyPI).

**Scope explicitly NOT in this plan:** spec content (Phase 1), library implementation (Phases 2/3), examples (Phases 2k, 3j), docs site content (Phases 2k, 3j), release workflows (Phases 2m, 3l). Each gets its own plan.

**Working directory for all relative paths:** `/Users/kaveh/repos/VMx`

______________________________________________________________________

## Pre-flight

Run from `/Users/kaveh/repos/VMx`:

```bash
git status
git log --oneline -5
```

Expected state at start: branch `main`, untracked `messages/` and `services/` directories from the very early Python stub, plus `docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md` (created during brainstorming, uncommitted — leave it alone; it will be committed as part of Task 1).

**Tools required on the developer machine** (verify each before starting):

```bash
git --version          # any 2.30+
dotnet --version       # 8.x
python3 --version      # 3.10+
uv --version           # latest; install via: brew install uv
pre-commit --version   # install via: brew install pre-commit  (or: pipx install pre-commit)
```

If any are missing, install them before proceeding. Tasks below assume all are present and on `PATH`.

______________________________________________________________________

## File structure produced by Phase 0

```
VMx/
├── .editorconfig                       NEW
├── .gitattributes                      NEW
├── .gitignore                          REWRITTEN (was Python-only)
├── .pre-commit-config.yaml             NEW
├── CODE_OF_CONDUCT.md                  NEW
├── CONTRIBUTING.md                     NEW
├── LICENSE                             KEPT (existing MIT)
├── README.md                           REWRITTEN (was 2-line)
├── SECURITY.md                         NEW
├── compatibility-matrix.md             NEW (empty placeholder)
├── docs/
│   └── superpowers/
│       ├── specs/2026-05-16-vmx-multilang-revival-design.md   KEPT
│       └── plans/2026-05-16-vmx-phase-0-scaffolding.md        KEPT (this file)
├── examples/                           NEW (empty dir w/ .gitkeep)
│   └── .gitkeep
├── langs/
│   ├── csharp/
│   │   ├── .editorconfig               NEW (C#-specific overrides)
│   │   ├── CHANGELOG.md                NEW (empty)
│   │   ├── Directory.Build.props       NEW
│   │   ├── Directory.Packages.props    NEW
│   │   ├── README.md                   NEW
│   │   ├── VMx.sln                     NEW
│   │   ├── src/
│   │   │   └── VMx/
│   │   │       ├── VMx.csproj          NEW (empty library)
│   │   │       └── Class1.cs           NEW (placeholder, deleted in Phase 2a)
│   │   └── tests/
│   │       └── VMx.Tests/
│   │           ├── VMx.Tests.csproj    NEW
│   │           └── SmokeTests.cs       NEW
│   └── python/
│       ├── CHANGELOG.md                NEW (empty)
│       ├── README.md                   NEW
│       ├── pyproject.toml              NEW
│       ├── tox.ini                     NEW
│       ├── src/
│       │   └── vmx/
│       │       ├── __init__.py         NEW (re-exports stubs)
│       │       ├── __about__.py        NEW (__version__, min_spec_version)
│       │       ├── py.typed            NEW (empty marker)
│       │       ├── messages/
│       │       │   ├── __init__.py     NEW
│       │       │   └── protocols.py    MOVED from messages/contracts/message.py
│       │       └── services/
│       │           ├── __init__.py     NEW
│       │           └── message_hub.py  MOVED+UPDATED from services/contracts/message_hub.py
│       └── tests/
│           ├── conftest.py             NEW
│           ├── unit/
│           │   ├── __init__.py         NEW
│           │   └── test_smoke.py       NEW
│           └── conformance/
│               ├── __init__.py         NEW
│               └── README.md           NEW (placeholder)
├── spec/                               NEW
│   ├── README.md                       NEW (explains the folder; content arrives in Phase 1)
│   ├── ADRs/.gitkeep                   NEW
│   └── fixtures/.gitkeep               NEW
├── tools/                              NEW
│   ├── README.md                       NEW (explains the folder)
│   └── .gitkeep                        NEW (until Phase 1 adds the real scripts)
├── messages/                           DELETED
└── services/                           DELETED
└── .github/
    ├── CODEOWNERS                      NEW
    ├── ISSUE_TEMPLATE/
    │   ├── bug-csharp.yml              NEW
    │   ├── bug-python.yml              NEW
    │   ├── spec-feature-request.yml    NEW
    │   └── adr-proposal.yml            NEW
    ├── PULL_REQUEST_TEMPLATE.md        NEW
    └── workflows/
        ├── csharp.yml                  NEW
        ├── python.yml                  NEW
        ├── docs.yml                    NEW (skeleton only — succeeds with a no-op step)
        ├── conformance.yml             NEW (skeleton only — succeeds with a no-op step)
        └── spec-discipline.yml         NEW (skeleton only — succeeds with a no-op step)
```

______________________________________________________________________

## Task 1 — Top-level scaffolding (directories + hygiene files)

**Files:**

- Create: `/Users/kaveh/repos/VMx/.gitignore` (rewrite)

- Create: `/Users/kaveh/repos/VMx/.editorconfig`

- Create: `/Users/kaveh/repos/VMx/.gitattributes`

- Create directories: `spec/`, `spec/ADRs/`, `spec/fixtures/`, `examples/`, `tools/`, `langs/csharp/src/VMx/`, `langs/csharp/tests/VMx.Tests/`, `langs/python/src/vmx/messages/`, `langs/python/src/vmx/services/`, `langs/python/tests/unit/`, `langs/python/tests/conformance/`, `.github/ISSUE_TEMPLATE/`, `.github/workflows/`

- [ ] **Step 1: Create the directory layout**

```bash
cd /Users/kaveh/repos/VMx
mkdir -p spec/ADRs spec/fixtures examples tools \
  langs/csharp/src/VMx langs/csharp/tests/VMx.Tests \
  langs/python/src/vmx/messages langs/python/src/vmx/services \
  langs/python/tests/unit langs/python/tests/conformance \
  .github/ISSUE_TEMPLATE .github/workflows
```

- [ ] **Step 2: Add `.gitkeep` placeholders so empty dirs are tracked**

```bash
cd /Users/kaveh/repos/VMx
touch spec/ADRs/.gitkeep spec/fixtures/.gitkeep examples/.gitkeep tools/.gitkeep
```

- [ ] **Step 3: Write the multi-language `.gitignore`**

Replace `/Users/kaveh/repos/VMx/.gitignore` entirely with:

```gitignore
# ─── macOS ────────────────────────────────────────────────────────────
.DS_Store

# ─── IDE / editor ─────────────────────────────────────────────────────
.idea/
.vscode/
*.swp
*.swo
*~

# ─── Python ───────────────────────────────────────────────────────────
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
sdist/
wheels/
share/python-wheels/
*.egg-info/
*.egg
MANIFEST
pip-log.txt
pip-delete-this-directory.txt
htmlcov/
.tox/
.nox/
.coverage
.coverage.*
.cache
coverage.xml
*.cover
.pytest_cache/
.mypy_cache/
.dmypy.json
.ruff_cache/
.env
.venv
env/
venv/
ENV/

# uv
uv.lock.bak

# ─── .NET / C# ────────────────────────────────────────────────────────
bin/
obj/
*.user
*.suo
*.userosscache
*.sln.docstates
TestResults/
[Bb]uild[Ll]og.*
*.[Cc]ache
project.lock.json
project.fragment.lock.json
artifacts/
.vs/
.idea/

# NuGet
*.nupkg
*.snupkg
.nuget/

# ─── Node (future TS flavor) ──────────────────────────────────────────
node_modules/
*.log
npm-debug.log*
yarn-debug.log*
yarn-error.log*
.npm/
.pnpm-store/

# ─── Build / coverage artifacts ───────────────────────────────────────
coverage/
*.coverage
*.lcov

# ─── Docs builds ──────────────────────────────────────────────────────
docs/_build/
docs/site/
site/
```

- [ ] **Step 4: Write `.editorconfig`**

Create `/Users/kaveh/repos/VMx/.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
indent_style = space
indent_size = 4
insert_final_newline = true
trim_trailing_whitespace = true

[*.{md,markdown}]
trim_trailing_whitespace = false

[*.{yml,yaml,json,toml}]
indent_size = 2

[*.{cs,csproj,props,targets,sln}]
indent_size = 4

[*.py]
indent_size = 4

[Makefile]
indent_style = tab
```

- [ ] **Step 5: Write `.gitattributes`**

Create `/Users/kaveh/repos/VMx/.gitattributes`:

```gitattributes
* text=auto eol=lf

*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.ico binary
*.snupkg binary
*.nupkg binary

# linguist hints — keep docs from dominating language stats
docs/**       linguist-documentation
spec/**       linguist-documentation
examples/**   linguist-vendored=false
langs/csharp/**  linguist-detectable=true
langs/python/**  linguist-detectable=true
```

- [ ] **Step 6: Verify directory layout**

```bash
cd /Users/kaveh/repos/VMx
find . -maxdepth 4 -type d -not -path './.git*' -not -path './.mypy_cache*' | sort
```

Expected: every directory listed in the Step 1 `mkdir` command is present.

- [ ] **Step 7: Commit**

```bash
cd /Users/kaveh/repos/VMx
git add .gitignore .editorconfig .gitattributes spec/ examples/ tools/ langs/csharp/ langs/python/ .github/
git commit -m "chore: scaffold multi-language repo layout

- adds top-level langs/, spec/, docs/, examples/, tools/, .github/
- replaces single-language .gitignore with multi-lang one
- adds .editorconfig and .gitattributes
- empty dirs preserved via .gitkeep

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §4, §11"
```

______________________________________________________________________

## Task 2 — Repo metadata (README, CONTRIBUTING, etc.)

**Files:**

- Create: `README.md` (rewrite of the 2-line existing one)

- Create: `CONTRIBUTING.md`

- Create: `CODE_OF_CONDUCT.md`

- Create: `SECURITY.md`

- Create: `compatibility-matrix.md` (empty placeholder)

- Create: `.github/CODEOWNERS`

- Create: `.github/PULL_REQUEST_TEMPLATE.md`

- Create: `.github/ISSUE_TEMPLATE/bug-csharp.yml`, `bug-python.yml`, `spec-feature-request.yml`, `adr-proposal.yml`

- Create: `langs/csharp/README.md`, `langs/csharp/CHANGELOG.md`, `langs/python/README.md`, `langs/python/CHANGELOG.md`

- [ ] **Step 1: Rewrite top-level `README.md`**

Replace `/Users/kaveh/repos/VMx/README.md` entirely with:

```markdown
# VMx

A hierarchical, lifecycle-aware MVVM viewmodel framework, available in multiple language flavors.

| Flavor | Package | Status |
| --- | --- | --- |
| C# | [`VMx`](https://www.nuget.org/packages/VMx/) on NuGet | scaffolding — not yet released |
| Python | [`vmx`](https://pypi.org/project/vmx/) on PyPI | scaffolding — not yet released |
| TypeScript | `vmx` on npm | planned (post-1.0) |

## Repository layout

- `spec/` — the language-neutral specification (source of truth for every flavor).
- `docs/` — user-facing documentation site sources.
- `examples/` — runnable example projects per language.
- `langs/<lang>/` — one self-contained project per language flavor.
- `tools/` — cross-cutting scripts (conformance coverage, compatibility-matrix generator).
- `.github/` — issue/PR templates and CI workflows.

## Getting started

See the language-specific quickstart pages:
- `docs/getting-started/csharp.md` (arrives in Phase 2 of the roadmap)
- `docs/getting-started/python.md` (arrives in Phase 3 of the roadmap)

## Versioning

Each language flavor versions independently in SemVer; the spec versions independently in SemVer too.
Every published package declares the spec version it implements. See [`compatibility-matrix.md`](compatibility-matrix.md).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and the design spec at
[`docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md`](docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md).

## License

MIT — see [`LICENSE`](LICENSE).
```

- [ ] **Step 2: Write `CONTRIBUTING.md`**

Create `/Users/kaveh/repos/VMx/CONTRIBUTING.md`:

````markdown
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
````

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

- A spec change requires a matching ADR in `spec/ADRs/` (the `spec-discipline` CI check enforces this).
- A new conformance test ID in `spec/12-conformance.md` requires a stub test in **every** active language flavor in the same PR.

See `docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md` §5 and §6 for the full process.

## Code of conduct

This project follows the Contributor Covenant v2.1 — see [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

````

- [ ] **Step 3: Write `CODE_OF_CONDUCT.md`**

Create `/Users/kaveh/repos/VMx/CODE_OF_CONDUCT.md` containing the Contributor Covenant v2.1 text. Use the official text at https://www.contributor-covenant.org/version/2/1/code_of_conduct/. To save the exact text now, download it:

```bash
cd /Users/kaveh/repos/VMx
curl -sSL https://www.contributor-covenant.org/version/2/1/code_of_conduct/code_of_conduct.md \
  -o CODE_OF_CONDUCT.md
````

Then replace the placeholder enforcement email (`[INSERT CONTACT METHOD]`) with your contact email manually (e.g., `kaveh.razavi@gmail.com`).

- [ ] **Step 4: Write `SECURITY.md`**

Create `/Users/kaveh/repos/VMx/SECURITY.md`:

```markdown
# Security policy

## Supported versions

Until VMx reaches 1.0 in any flavor, only the most recent published release is supported.

## Reporting a vulnerability

Please report security issues privately, not in public issues. Two options:

1. Use GitHub's **Report a vulnerability** feature on the repository's Security tab.
2. Email `kaveh.razavi@gmail.com` with subject `[VMx security]`.

You will receive an acknowledgement within 72 hours. Coordinated disclosure timelines are negotiated case-by-case.
```

- [ ] **Step 5: Write `compatibility-matrix.md` placeholder**

Create `/Users/kaveh/repos/VMx/compatibility-matrix.md`:

```markdown
# Spec ↔ language compatibility matrix

This file is regenerated by `tools/build-compatibility-matrix.py` (planned for Phase 1).
Until then, it is empty.

| spec | csharp | python | typescript |
| --- | --- | --- | --- |
| (none) | — | — | — |
```

- [ ] **Step 6: Write `.github/CODEOWNERS`**

Create `/Users/kaveh/repos/VMx/.github/CODEOWNERS`:

```
# Repository owners — required reviewers for all changes
*               @kavehr
spec/**         @kavehr
langs/csharp/** @kavehr
langs/python/** @kavehr
.github/**      @kavehr
```

(Replace `@kavehr` with your actual GitHub handle if different — confirm before committing.)

- [ ] **Step 7: Write `.github/PULL_REQUEST_TEMPLATE.md`**

Create `/Users/kaveh/repos/VMx/.github/PULL_REQUEST_TEMPLATE.md`:

```markdown
## Summary

<!-- 1-3 bullets. What changed and why. -->

## Affected flavor(s)

- [ ] spec
- [ ] csharp
- [ ] python
- [ ] docs / infra

## Checklist

- [ ] Tests added / updated
- [ ] Spec updated (if behavior changed)
- [ ] Conformance catalog entries added (if new behavior or new spec ID)
- [ ] ADR added (if architectural / cross-language decision)
- [ ] CHANGELOG entry under the relevant `langs/<lang>/CHANGELOG.md`

## How to test

<!-- Exact commands the reviewer can run -->
```

- [ ] **Step 8: Write issue templates**

Create `/Users/kaveh/repos/VMx/.github/ISSUE_TEMPLATE/bug-csharp.yml`:

```yaml
name: Bug report — C# (VMx NuGet package)
description: Something is broken in the C# flavor.
labels: [bug, csharp]
body:
  - type: input
    id: version
    attributes:
      label: VMx (C#) version
      placeholder: e.g., 0.1.0
    validations:
      required: true
  - type: input
    id: tfm
    attributes:
      label: Target framework
      placeholder: e.g., net8.0, netstandard2.0
    validations:
      required: true
  - type: textarea
    id: repro
    attributes:
      label: Minimal reproduction
      description: Smallest code snippet that reproduces the issue.
      render: csharp
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: Expected behavior
    validations:
      required: true
  - type: textarea
    id: actual
    attributes:
      label: Actual behavior
    validations:
      required: true
```

Create `/Users/kaveh/repos/VMx/.github/ISSUE_TEMPLATE/bug-python.yml`:

```yaml
name: Bug report — Python (vmx PyPI package)
description: Something is broken in the Python flavor.
labels: [bug, python]
body:
  - type: input
    id: version
    attributes:
      label: vmx version
      placeholder: e.g., 0.1.0
    validations:
      required: true
  - type: input
    id: python
    attributes:
      label: Python version
      placeholder: e.g., 3.12.1
    validations:
      required: true
  - type: textarea
    id: repro
    attributes:
      label: Minimal reproduction
      description: Smallest code snippet that reproduces the issue.
      render: python
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: Expected behavior
    validations:
      required: true
  - type: textarea
    id: actual
    attributes:
      label: Actual behavior
    validations:
      required: true
```

Create `/Users/kaveh/repos/VMx/.github/ISSUE_TEMPLATE/spec-feature-request.yml`:

```yaml
name: Spec — feature request
description: Propose a behavior change that affects all language flavors.
labels: [spec, enhancement]
body:
  - type: textarea
    id: motivation
    attributes:
      label: Motivation
      description: Why is this needed? What's the user-facing problem?
    validations:
      required: true
  - type: textarea
    id: proposal
    attributes:
      label: Proposed change
      description: What should the spec say? What new conformance IDs are needed?
    validations:
      required: true
  - type: textarea
    id: cross-language
    attributes:
      label: Cross-language considerations
      description: Any language-specific constraints worth flagging upfront.
```

Create `/Users/kaveh/repos/VMx/.github/ISSUE_TEMPLATE/adr-proposal.yml`:

```yaml
name: ADR proposal
description: Propose an Architecture Decision Record.
labels: [adr]
body:
  - type: input
    id: title
    attributes:
      label: Proposed ADR title
      placeholder: e.g., 0008 — Use source-generated AggregateVM for arities 3–5
    validations:
      required: true
  - type: textarea
    id: context
    attributes:
      label: Context
      description: What's the situation that demands a decision?
    validations:
      required: true
  - type: textarea
    id: options
    attributes:
      label: Options considered
    validations:
      required: true
  - type: textarea
    id: decision
    attributes:
      label: Proposed decision + consequences
    validations:
      required: true
```

- [ ] **Step 9: Write per-language READMEs and CHANGELOGs**

Create `/Users/kaveh/repos/VMx/langs/csharp/README.md`:

````markdown
# VMx — C# flavor

The C# implementation of the VMx hierarchical MVVM framework, published as the `VMx` NuGet package.

- Target frameworks: `netstandard2.0`, `net8.0`
- See the language-neutral spec at [`/spec/`](../../spec) and the design doc at
  [`/docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md`](../../docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md).

## Build and test

```bash
dotnet restore
dotnet build
dotnet test
dotnet format --verify-no-changes
````

````

Create `/Users/kaveh/repos/VMx/langs/csharp/CHANGELOG.md`:

```markdown
# Changelog

All notable changes to the C# flavor are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial repo scaffolding.
````

Create `/Users/kaveh/repos/VMx/langs/python/README.md`:

````markdown
# VMx — Python flavor

The Python implementation of the VMx hierarchical MVVM framework, published as the `vmx` PyPI package.

- Supported Python versions: 3.10, 3.11, 3.12, 3.13
- See the language-neutral spec at [`/spec/`](../../spec) and the design doc at
  [`/docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md`](../../docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md).

## Build and test

```bash
uv sync --all-extras
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/vmx
````

````

Create `/Users/kaveh/repos/VMx/langs/python/CHANGELOG.md`:

```markdown
# Changelog

All notable changes to the Python flavor are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial repo scaffolding.
````

- [ ] **Step 10: Commit**

```bash
cd /Users/kaveh/repos/VMx
git add README.md CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md compatibility-matrix.md \
        .github/CODEOWNERS .github/PULL_REQUEST_TEMPLATE.md .github/ISSUE_TEMPLATE/ \
        langs/csharp/README.md langs/csharp/CHANGELOG.md \
        langs/python/README.md langs/python/CHANGELOG.md
git commit -m "docs: add repo metadata, code of conduct, issue/PR templates

- README rewritten with flavor matrix and layout overview
- CONTRIBUTING.md with per-language setup instructions
- Contributor Covenant 2.1 + SECURITY.md
- CODEOWNERS, PR template, four issue templates (csharp bug, python bug, spec request, ADR)
- per-language READMEs and CHANGELOGs (empty unreleased section)
- empty compatibility-matrix.md placeholder

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §10.7"
```

______________________________________________________________________

## Task 3 — Migrate legacy Python stubs

**Files:**

- Move: `messages/contracts/message.py` → `langs/python/src/vmx/messages/protocols.py`
- Move + edit: `services/contracts/message_hub.py` → `langs/python/src/vmx/services/message_hub.py`
- Delete: `messages/` and `services/` top-level directories

The existing stubs are:

**`messages/contracts/message.py`** (current content — keep verbatim):

```python
from typing import Protocol, runtime_checkable, TypeVar, Generic

Sender = TypeVar("Sender", covariant=True)


@runtime_checkable
class Message(Protocol):
    @property
    def sender_name(self) -> str:
        """Should return the sender's name as a string."""
        pass

    @property
    def sender_object(self) -> object:
        """Should return the sender object."""
        pass


@runtime_checkable
class TypedMessage(Message, Protocol, Generic[Sender]):
    @property
    def sender(self) -> Sender:
        """Should return the sender, typed according to the Sender type variable."""
        pass
```

**`services/contracts/message_hub.py`** (current content):

```python
from typing import TypeVar, Protocol, runtime_checkable
from rx.core.observable.observable import Observable

from messages.contracts.message import Message

TMessage = TypeVar("TMessage", contravariant=True)


@runtime_checkable
class MessageHub(Protocol[TMessage]):
    @property
    def messages(self) -> Observable:
        """Provides an Observable stream of messages."""
        pass

    def send(self, message: TMessage) -> None:
        """Sends a message of type TMessage."""
        pass
```

- [ ] **Step 1: Move the messages protocol file**

```bash
cd /Users/kaveh/repos/VMx
git mv messages/contracts/message.py langs/python/src/vmx/messages/protocols.py
```

- [ ] **Step 2: Move the message hub stub**

```bash
cd /Users/kaveh/repos/VMx
git mv services/contracts/message_hub.py langs/python/src/vmx/services/message_hub.py
```

- [ ] **Step 3: Update imports in `message_hub.py`**

Open `/Users/kaveh/repos/VMx/langs/python/src/vmx/services/message_hub.py` and replace its content entirely with:

```python
"""Message hub protocol.

The concrete `MessageHub` implementation arrives in Phase 3 (see the design spec).
This file currently only declares the Protocol that consumers code against.
"""

from typing import Protocol, TypeVar, runtime_checkable

from reactivex import Observable

from vmx.messages.protocols import Message

TMessage = TypeVar("TMessage", contravariant=True)


@runtime_checkable
class MessageHub(Protocol[TMessage]):
    @property
    def messages(self) -> Observable[Message]:
        """Provides an Observable stream of messages."""
        ...

    def send(self, message: TMessage) -> None:
        """Sends a message of type TMessage."""
        ...
```

Changes vs. the original:

- Import switched from `rx.core.observable.observable.Observable` to `reactivex.Observable` (rx 3 → reactivex 4).

- Import path for `Message` switched to the new package root (`vmx.messages.protocols`).

- Function bodies use `...` instead of `pass` (the standard for Protocol method stubs).

- Docstring at module top noting that the concrete implementation is deferred.

- [ ] **Step 4: Delete the legacy top-level folders**

```bash
cd /Users/kaveh/repos/VMx
rm -rf messages services
```

`git mv` in steps 1–2 already removed the old paths from git's index; this `rm -rf` cleans up the now-empty parent directories (`messages/contracts/`, `services/contracts/`) on disk so they don't show up in `git status` as untracked.

- [ ] **Step 5: Verify the moves**

```bash
cd /Users/kaveh/repos/VMx
ls langs/python/src/vmx/messages/
ls langs/python/src/vmx/services/
test ! -d messages && test ! -d services && echo "OK: legacy dirs are gone"
git status
```

Expected:

- `langs/python/src/vmx/messages/` contains `protocols.py`.

- `langs/python/src/vmx/services/` contains `message_hub.py`.

- `messages/` and `services/` no longer exist.

- `git status` shows the renames (`R  messages/... -> langs/python/...`) plus the modification to `message_hub.py`.

- [ ] **Step 6: Commit**

```bash
cd /Users/kaveh/repos/VMx
git add langs/python/src/vmx/messages/protocols.py \
        langs/python/src/vmx/services/message_hub.py
git commit -m "refactor: relocate legacy Python stubs into langs/python/src/vmx

- messages/contracts/message.py -> langs/python/src/vmx/messages/protocols.py
- services/contracts/message_hub.py -> langs/python/src/vmx/services/message_hub.py
- imports updated: rx 3 -> reactivex 4 (Observable); Message import path
- legacy top-level messages/ and services/ folders deleted

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §9.8, §11"
```

______________________________________________________________________

## Task 4 — Python skeleton (pyproject.toml, package layout, smoke test)

**Files:**

- Create: `langs/python/pyproject.toml`
- Create: `langs/python/tox.ini`
- Create: `langs/python/src/vmx/__init__.py`
- Create: `langs/python/src/vmx/__about__.py`
- Create: `langs/python/src/vmx/py.typed` (empty marker)
- Create: `langs/python/src/vmx/messages/__init__.py`
- Create: `langs/python/src/vmx/services/__init__.py`
- Create: `langs/python/tests/conftest.py`
- Create: `langs/python/tests/unit/__init__.py`
- Create: `langs/python/tests/unit/test_smoke.py`
- Create: `langs/python/tests/conformance/__init__.py`
- Create: `langs/python/tests/conformance/README.md`

This task is TDD-style: write a smoke test that imports the package, watch it fail, then make the package importable, then watch it pass.

- [ ] **Step 1: Verify `vmx` is available on PyPI**

```bash
curl -sf "https://pypi.org/pypi/vmx/json" -o /dev/null && echo "TAKEN" || echo "AVAILABLE"
```

If output is `TAKEN`, change the project name to `vmx-mvvm` in the `pyproject.toml` and `__about__.py` below (and update Step 6's import path in tests). Otherwise proceed with `vmx`.

- [ ] **Step 2: Write the failing smoke test first**

Create `/Users/kaveh/repos/VMx/langs/python/tests/conftest.py`:

```python
"""Top-level pytest configuration for the vmx test suite."""
```

Create `/Users/kaveh/repos/VMx/langs/python/tests/unit/__init__.py` (empty):

```python
```

Create `/Users/kaveh/repos/VMx/langs/python/tests/unit/test_smoke.py`:

```python
"""Smoke tests — verify the package imports cleanly and exposes expected metadata."""

import vmx


def test_vmx_has_version() -> None:
    assert isinstance(vmx.__version__, str)
    assert len(vmx.__version__) > 0


def test_vmx_has_min_spec_version() -> None:
    assert isinstance(vmx.__min_spec_version__, str)
    assert len(vmx.__min_spec_version__) > 0


def test_message_protocol_importable() -> None:
    from vmx.messages.protocols import Message, TypedMessage

    assert Message is not None
    assert TypedMessage is not None


def test_message_hub_protocol_importable() -> None:
    from vmx.services.message_hub import MessageHub

    assert MessageHub is not None
```

Create `/Users/kaveh/repos/VMx/langs/python/tests/conformance/__init__.py` (empty):

```python
```

Create `/Users/kaveh/repos/VMx/langs/python/tests/conformance/README.md`:

```markdown
# Conformance tests (Python flavor)

This directory will contain the Python implementation of the cross-language conformance
catalog defined in `spec/12-conformance.md` (Phase 1). Until Phase 1 is complete, this
directory is intentionally empty.

See the design spec, §6, for the catalog format and enforcement rules.
```

- [ ] **Step 3: Run the test, confirm it fails**

```bash
cd /Users/kaveh/repos/VMx/langs/python
uv run pytest tests/unit/test_smoke.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'vmx'` (because there's no `pyproject.toml` and no installed package yet). This is the failing state we want.

If `uv run` fails because there's no project initialized, that's also the expected failing state — move on to Step 4.

- [ ] **Step 4: Write `pyproject.toml`**

Create `/Users/kaveh/repos/VMx/langs/python/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.21"]
build-backend = "hatchling.build"

[project]
name = "vmx"
description = "Hierarchical, lifecycle-aware MVVM viewmodel framework."
readme = "README.md"
license = { text = "MIT" }
authors = [{ name = "Kaveh Razavi", email = "kaveh.razavi@gmail.com" }]
requires-python = ">=3.10"
dependencies = [
  "reactivex>=4.0.4",
]
classifiers = [
  "Development Status :: 3 - Alpha",
  "Intended Audience :: Developers",
  "License :: OSI Approved :: MIT License",
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Topic :: Software Development :: Libraries",
  "Typing :: Typed",
]
dynamic = ["version"]

[project.urls]
Repository = "https://github.com/kavehr/VMx"
Documentation = "https://kavehr.github.io/VMx/"
Issues = "https://github.com/kavehr/VMx/issues"
Changelog = "https://github.com/kavehr/VMx/blob/main/langs/python/CHANGELOG.md"

[project.optional-dependencies]
test = ["pytest>=7", "pytest-asyncio>=0.23", "pytest-cov>=4"]
typing = ["mypy>=1.8"]
lint = ["ruff>=0.4"]
dev = ["pytest>=7", "pytest-asyncio>=0.23", "pytest-cov>=4", "mypy>=1.8", "ruff>=0.4"]

[tool.hatch.version]
path = "src/vmx/__about__.py"

[tool.hatch.build.targets.wheel]
packages = ["src/vmx"]

[tool.ruff]
line-length = 100
target-version = "py310"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "RUF"]

[tool.mypy]
strict = true
python_version = "3.10"
files = ["src/vmx"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
  "conformance: cross-language conformance test (Phase 1 catalog ID)",
]

[tool.coverage.run]
branch = true
source = ["vmx"]

[tool.coverage.report]
show_missing = true
fail_under = 0   # raised once real code lands in Phase 3
```

- [ ] **Step 5: Write `__about__.py`**

Create `/Users/kaveh/repos/VMx/langs/python/src/vmx/__about__.py`:

```python
"""Package metadata for vmx.

`__version__` is read by hatchling at build time (see pyproject.toml).
`__min_spec_version__` is the minimum spec version this release implements.
"""

__version__ = "0.0.1.dev0"
__min_spec_version__ = "0.0.0"  # bumped to "1.0.0" once Phase 1 ships
```

- [ ] **Step 6: Write `__init__.py`**

Create `/Users/kaveh/repos/VMx/langs/python/src/vmx/__init__.py`:

```python
"""VMx — hierarchical, lifecycle-aware MVVM viewmodel framework (Python flavor).

This package is currently in scaffolding state. The public API arrives in Phase 3 of
the roadmap. See the design spec at
docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md.
"""

from vmx.__about__ import __min_spec_version__, __version__

__all__ = ["__version__", "__min_spec_version__"]
```

- [ ] **Step 7: Write empty `py.typed` marker and sub-package init files**

```bash
cd /Users/kaveh/repos/VMx/langs/python
touch src/vmx/py.typed
```

Create `/Users/kaveh/repos/VMx/langs/python/src/vmx/messages/__init__.py`:

```python
"""Message protocols and concrete messages.

Concrete message types arrive in Phase 3; this module currently only re-exports the
Protocols moved over from the legacy stub.
"""

from vmx.messages.protocols import Message, TypedMessage

__all__ = ["Message", "TypedMessage"]
```

Create `/Users/kaveh/repos/VMx/langs/python/src/vmx/services/__init__.py`:

```python
"""Service protocols (message hub, dispatcher).

Concrete implementations arrive in Phase 3. Currently only the MessageHub Protocol
is exposed, moved from the legacy stub.
"""

from vmx.services.message_hub import MessageHub

__all__ = ["MessageHub"]
```

- [ ] **Step 8: Write `tox.ini`**

Create `/Users/kaveh/repos/VMx/langs/python/tox.ini`:

```ini
[tox]
envlist = py310, py311, py312, py313, lint, type
isolated_build = true

[testenv]
deps =
    pytest>=7
    pytest-asyncio>=0.23
    pytest-cov>=4
commands =
    pytest --cov=vmx --cov-report=term {posargs}

[testenv:lint]
deps = ruff>=0.4
commands =
    ruff check src tests
    ruff format --check src tests

[testenv:type]
deps =
    mypy>=1.8
commands =
    mypy --strict src/vmx
```

- [ ] **Step 9: Install the package and run the smoke test**

```bash
cd /Users/kaveh/repos/VMx/langs/python
uv sync --all-extras
uv run pytest tests/unit/test_smoke.py -v
```

Expected: all 4 tests pass.

If a test fails, do not move on — fix the cause first. Likely culprits if it fails:

- Forgot the `__init__.py` in `messages/` or `services/` (Step 7).

- Typo in the `from vmx... import ...` paths in `test_smoke.py`.

- `reactivex` failed to install (rare; check `uv sync` output).

- [ ] **Step 10: Run lint and type-check, confirm clean**

```bash
cd /Users/kaveh/repos/VMx/langs/python
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src/vmx
```

Expected: all three commands exit 0 with no errors. If `ruff format --check` reports diffs, run `uv run ruff format src tests` and re-verify.

- [ ] **Step 11: Commit**

```bash
cd /Users/kaveh/repos/VMx
git add langs/python/pyproject.toml langs/python/tox.ini \
        langs/python/src/vmx/__init__.py langs/python/src/vmx/__about__.py \
        langs/python/src/vmx/py.typed \
        langs/python/src/vmx/messages/__init__.py \
        langs/python/src/vmx/services/__init__.py \
        langs/python/tests/conftest.py \
        langs/python/tests/unit/__init__.py langs/python/tests/unit/test_smoke.py \
        langs/python/tests/conformance/__init__.py \
        langs/python/tests/conformance/README.md
git commit -m "feat(python): scaffold vmx package with smoke tests

- pyproject.toml (hatchling, reactivex>=4, py3.10-3.13)
- src/vmx layout: __init__, __about__, py.typed, messages/, services/
- tests/unit/test_smoke.py covers version metadata and protocol importability
- tests/conformance/ directory in place (catalog content lands in Phase 1)
- tox.ini for the multi-Python-version matrix
- ruff, mypy --strict, pytest with asyncio + conformance marker all configured

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §9.1-9.7"
```

______________________________________________________________________

## Task 5 — C# skeleton (solution, projects, smoke test)

**Files:**

- Create: `langs/csharp/Directory.Build.props`
- Create: `langs/csharp/Directory.Packages.props`
- Create: `langs/csharp/VMx.sln`
- Create: `langs/csharp/src/VMx/VMx.csproj`
- Create: `langs/csharp/src/VMx/Class1.cs` (trivial placeholder, deleted in Phase 2a)
- Create: `langs/csharp/tests/VMx.Tests/VMx.Tests.csproj`
- Create: `langs/csharp/tests/VMx.Tests/SmokeTests.cs`
- Create: `langs/csharp/.editorconfig`
- Create: `langs/csharp/.config/dotnet-tools.json`

This task is also TDD-style: write a failing smoke test, see it fail (project doesn't exist), create the projects, see it pass.

- [ ] **Step 1: Verify `VMx` is available on NuGet**

```bash
curl -sf "https://api.nuget.org/v3-flatcontainer/vmx/index.json" -o /dev/null \
  && echo "TAKEN" || echo "AVAILABLE"
```

If `TAKEN`, choose an alternative (e.g., `Vmx`, `VMx.Core`) and substitute in the files below before creating them. Otherwise proceed.

- [ ] **Step 2: Write `langs/csharp/.editorconfig` (C# overrides)**

Create `/Users/kaveh/repos/VMx/langs/csharp/.editorconfig`:

```ini
# C# specific overrides on top of /Users/kaveh/repos/VMx/.editorconfig
[*.cs]
# Roslyn analyzer rules — keep minimal in Phase 0, tighten later
dotnet_diagnostic.IDE0005.severity = warning   # unused usings
csharp_using_directive_placement = outside_namespace:warning
csharp_style_namespace_declarations = file_scoped:warning
csharp_new_line_before_open_brace = all
csharp_indent_case_contents = true
csharp_indent_switch_labels = true
```

- [ ] **Step 3: Write `Directory.Build.props`**

Create `/Users/kaveh/repos/VMx/langs/csharp/Directory.Build.props`:

```xml
<Project>
  <PropertyGroup>
    <LangVersion>latest</LangVersion>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
    <EnforceCodeStyleInBuild>true</EnforceCodeStyleInBuild>
    <AnalysisLevel>latest-recommended</AnalysisLevel>
    <GenerateDocumentationFile>true</GenerateDocumentationFile>
    <Deterministic>true</Deterministic>

    <!-- Package authoring defaults -->
    <Authors>Kaveh Razavi</Authors>
    <Company>Kaveh Razavi</Company>
    <Copyright>Copyright (c) Kaveh Razavi</Copyright>
    <PackageLicenseExpression>MIT</PackageLicenseExpression>
    <PackageProjectUrl>https://github.com/kavehr/VMx</PackageProjectUrl>
    <RepositoryUrl>https://github.com/kavehr/VMx</RepositoryUrl>
    <RepositoryType>git</RepositoryType>
    <PublishRepositoryUrl>true</PublishRepositoryUrl>
    <EmbedUntrackedSources>true</EmbedUntrackedSources>
    <IncludeSymbols>true</IncludeSymbols>
    <SymbolPackageFormat>snupkg</SymbolPackageFormat>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Microsoft.SourceLink.GitHub" Version="$(MicrosoftSourceLinkGitHubVersion)" PrivateAssets="all" />
  </ItemGroup>
</Project>
```

Replace `kavehr` with the actual GitHub org/handle hosting this repo if different — the URL has to resolve for SourceLink to embed it correctly.

- [ ] **Step 4: Write `Directory.Packages.props`**

Create `/Users/kaveh/repos/VMx/langs/csharp/Directory.Packages.props`:

```xml
<Project>
  <PropertyGroup>
    <ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally>
    <CentralPackageTransitivePinningEnabled>true</CentralPackageTransitivePinningEnabled>

    <!-- Versions referenced in Directory.Build.props or csproj files -->
    <MicrosoftSourceLinkGitHubVersion>8.0.0</MicrosoftSourceLinkGitHubVersion>
  </PropertyGroup>

  <ItemGroup>
    <PackageVersion Include="System.Reactive" Version="6.0.1" />
    <PackageVersion Include="Microsoft.Bcl.AsyncInterfaces" Version="8.0.0" />

    <!-- Test stack -->
    <PackageVersion Include="Microsoft.NET.Test.Sdk" Version="17.10.0" />
    <PackageVersion Include="xunit" Version="2.9.0" />
    <PackageVersion Include="xunit.runner.visualstudio" Version="2.8.2" />
    <PackageVersion Include="FluentAssertions" Version="6.12.0" />
    <PackageVersion Include="Microsoft.Reactive.Testing" Version="6.0.1" />
    <PackageVersion Include="coverlet.collector" Version="6.0.2" />
  </ItemGroup>
</Project>
```

- [ ] **Step 5: Write `src/VMx/VMx.csproj`**

Create `/Users/kaveh/repos/VMx/langs/csharp/src/VMx/VMx.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFrameworks>netstandard2.0;net8.0</TargetFrameworks>
    <RootNamespace>VMx</RootNamespace>
    <AssemblyName>VMx</AssemblyName>
    <PackageId>VMx</PackageId>
    <Version>0.0.1-dev</Version>
    <Description>Hierarchical, lifecycle-aware MVVM viewmodel framework.</Description>
    <PackageTags>mvvm;viewmodel;reactive;wpf;avalonia;maui;xamarin</PackageTags>

    <!-- Minimum spec version this assembly implements -->
    <MinSpecVersion>0.0.0</MinSpecVersion>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="System.Reactive" />
    <PackageReference Include="Microsoft.Bcl.AsyncInterfaces" Condition="'$(TargetFramework)' == 'netstandard2.0'" />
  </ItemGroup>

  <ItemGroup>
    <AssemblyAttribute Include="System.Reflection.AssemblyMetadataAttribute">
      <_Parameter1>MinSpecVersion</_Parameter1>
      <_Parameter2>$(MinSpecVersion)</_Parameter2>
    </AssemblyAttribute>
  </ItemGroup>
</Project>
```

- [ ] **Step 6: Write the placeholder type so the assembly is non-empty**

Create `/Users/kaveh/repos/VMx/langs/csharp/src/VMx/Class1.cs`:

```csharp
namespace VMx;

/// <summary>
/// Placeholder marker type. Replaced with the real Lifecycle types in Phase 2a.
/// Exists so the assembly is non-empty and the smoke test has something to assert against.
/// </summary>
public static class Placeholder
{
    /// <summary>
    /// The minimum spec version this assembly implements. Mirrors the
    /// <c>MinSpecVersion</c> MSBuild property and is asserted by the smoke test.
    /// </summary>
    public const string MinSpecVersion = "0.0.0";
}
```

- [ ] **Step 7: Write the failing smoke test**

Create `/Users/kaveh/repos/VMx/langs/csharp/tests/VMx.Tests/VMx.Tests.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <IsPackable>false</IsPackable>
    <IsTestProject>true</IsTestProject>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" />
    <PackageReference Include="xunit" />
    <PackageReference Include="xunit.runner.visualstudio" />
    <PackageReference Include="FluentAssertions" />
    <PackageReference Include="coverlet.collector" />
  </ItemGroup>

  <ItemGroup>
    <ProjectReference Include="..\..\src\VMx\VMx.csproj" />
  </ItemGroup>
</Project>
```

Create `/Users/kaveh/repos/VMx/langs/csharp/tests/VMx.Tests/SmokeTests.cs`:

```csharp
using System.Linq;
using System.Reflection;
using FluentAssertions;
using Xunit;

namespace VMx.Tests;

public class SmokeTests
{
    [Fact]
    public void Placeholder_Has_MinSpecVersion()
    {
        Placeholder.MinSpecVersion.Should().NotBeNullOrEmpty();
    }

    [Fact]
    public void Assembly_Has_MinSpecVersion_Metadata()
    {
        // The test project runs on net8.0 only, but the referenced VMx assembly
        // is multi-targeted (netstandard2.0 + net8.0). We verify the AssemblyMetadata
        // attribute injected by the csproj is present and non-empty.
        var assembly = typeof(Placeholder).Assembly;
        var minSpec = assembly
            .GetCustomAttributes<AssemblyMetadataAttribute>()
            .FirstOrDefault(a => a.Key == "MinSpecVersion");

        minSpec.Should().NotBeNull();
        minSpec!.Value.Should().NotBeNullOrEmpty();
    }
}
```

- [ ] **Step 8: Write `VMx.sln`**

Create `/Users/kaveh/repos/VMx/langs/csharp/VMx.sln`. Easiest way: generate it via the dotnet CLI, then verify.

```bash
cd /Users/kaveh/repos/VMx/langs/csharp
dotnet new sln -n VMx
dotnet sln VMx.sln add src/VMx/VMx.csproj
dotnet sln VMx.sln add tests/VMx.Tests/VMx.Tests.csproj
```

Verify with:

```bash
dotnet sln VMx.sln list
```

Expected output lists `src/VMx/VMx.csproj` and `tests/VMx.Tests/VMx.Tests.csproj`.

- [ ] **Step 9: Write `.config/dotnet-tools.json`**

```bash
cd /Users/kaveh/repos/VMx/langs/csharp
dotnet new tool-manifest --force
```

This creates `.config/dotnet-tools.json` with an empty `tools` map. The file should look like:

```json
{
  "version": 1,
  "isRoot": true,
  "tools": {}
}
```

(`dotnet format` ships with the SDK starting in 6.x, so no tool is needed for the formatter itself.)

- [ ] **Step 10: Build and run the tests**

```bash
cd /Users/kaveh/repos/VMx/langs/csharp
dotnet restore
dotnet build -c Release
dotnet test --no-build -c Release
```

Expected: both smoke tests pass. If they fail, do not move on — check that `Directory.Build.props` had the `<PackageProjectUrl>` closing tag fixed (Step 3 sentinel), and that the namespaces line up.

- [ ] **Step 11: Run `dotnet format` and verify clean**

```bash
cd /Users/kaveh/repos/VMx/langs/csharp
dotnet format VMx.sln --verify-no-changes
```

Expected: exit code 0. If it reports diffs, run `dotnet format VMx.sln` once, then re-verify.

- [ ] **Step 12: Commit**

```bash
cd /Users/kaveh/repos/VMx
git add langs/csharp/.editorconfig langs/csharp/.config/dotnet-tools.json \
        langs/csharp/Directory.Build.props langs/csharp/Directory.Packages.props \
        langs/csharp/VMx.sln \
        langs/csharp/src/VMx/VMx.csproj langs/csharp/src/VMx/Class1.cs \
        langs/csharp/tests/VMx.Tests/VMx.Tests.csproj \
        langs/csharp/tests/VMx.Tests/SmokeTests.cs
git commit -m "feat(csharp): scaffold VMx solution with smoke tests

- VMx.sln, Directory.Build.props (LangVersion=latest, Nullable=enable, SourceLink,
  symbol packages), Directory.Packages.props (central versioning)
- src/VMx/VMx.csproj multi-targets netstandard2.0;net8.0
- Placeholder type carries MinSpecVersion metadata via AssemblyMetadataAttribute
- tests/VMx.Tests/ smoke tests cover the placeholder and the metadata attribute
- .config/dotnet-tools.json scaffolded (empty tools map)
- C#-specific .editorconfig overrides (file-scoped namespaces, etc.)

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §8.1, §8.2"
```

______________________________________________________________________

## Task 6 — Pre-commit hooks

**Files:**

- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Write `.pre-commit-config.yaml`**

Create `/Users/kaveh/repos/VMx/.pre-commit-config.yaml`:

```yaml
# pre-commit configuration. Run `pre-commit install` once locally to wire the hooks.
# See https://pre-commit.com/ for details.

repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
        exclude: \.md$   # markdown trailing whitespace can be meaningful (line breaks)
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-json
      - id: check-added-large-files
      - id: check-merge-conflict
      - id: mixed-line-ending
        args: ["--fix=lf"]

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.10
    hooks:
      - id: ruff
        args: ["--fix"]
        files: ^langs/python/.*\.py$
      - id: ruff-format
        files: ^langs/python/.*\.py$

  - repo: https://github.com/executablebooks/mdformat
    rev: 0.7.17
    hooks:
      - id: mdformat
        files: ^(spec|docs)/.*\.md$
        additional_dependencies:
          - mdformat-gfm
          - mdformat-tables

  - repo: local
    hooks:
      - id: dotnet-format
        name: dotnet format (C# only)
        entry: bash -c 'cd langs/csharp && dotnet format VMx.sln --verify-no-changes --include $(echo "$@" | tr " " "\n" | sed "s|^langs/csharp/||" | paste -sd " " -)' --
        language: system
        files: ^langs/csharp/.*\.(cs|csproj|props)$
        pass_filenames: true
```

- [ ] **Step 2: Install and verify the hooks**

```bash
cd /Users/kaveh/repos/VMx
pre-commit install
pre-commit run --all-files
```

Expected: all hooks pass on the files committed so far. The first `pre-commit run` is slow because hook environments are installed from scratch — that's normal. If `dotnet-format` fails because of nothing-to-format on a fresh tree (it shouldn't), inspect the diff and either fix or temporarily remove that hook to revisit later.

- [ ] **Step 3: Commit**

```bash
cd /Users/kaveh/repos/VMx
git add .pre-commit-config.yaml
git commit -m "chore: add pre-commit hooks (ruff, mdformat, dotnet format, hygiene)

- general hygiene: trailing whitespace, EOL, large files, merge conflict markers
- ruff (lint + format) for Python paths
- mdformat for spec/ and docs/ markdown
- local dotnet format hook scoped to langs/csharp/ paths

Run \`pre-commit install\` once after cloning."
```

______________________________________________________________________

## Task 7 — GitHub Actions: Python workflow

**Files:**

- Create: `.github/workflows/python.yml`

- [ ] **Step 1: Write `python.yml`**

Create `/Users/kaveh/repos/VMx/.github/workflows/python.yml`:

```yaml
name: python

on:
  push:
    branches: [main]
    paths:
      - "langs/python/**"
      - "spec/**"
      - ".github/workflows/python.yml"
  pull_request:
    paths:
      - "langs/python/**"
      - "spec/**"
      - ".github/workflows/python.yml"

defaults:
  run:
    working-directory: langs/python

jobs:
  build:
    name: build & test (${{ matrix.os }} / py${{ matrix.python-version }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python-version: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          version: latest

      - name: Set up Python
        run: uv python install ${{ matrix.python-version }}

      - name: Sync dependencies
        run: uv sync --all-extras

      - name: Ruff lint
        run: uv run ruff check src tests

      - name: Ruff format check
        run: uv run ruff format --check src tests

      - name: Mypy
        run: uv run mypy --strict src/vmx

      - name: Pytest
        run: uv run pytest --cov=vmx --cov-report=xml -v

      - name: Upload coverage to Codecov
        if: matrix.os == 'ubuntu-latest' && matrix.python-version == '3.12'
        uses: codecov/codecov-action@v4
        with:
          files: langs/python/coverage.xml
          flags: python
          fail_ci_if_error: false
```

- [ ] **Step 2: Commit**

```bash
cd /Users/kaveh/repos/VMx
git add .github/workflows/python.yml
git commit -m "ci(python): add build/test/lint/type-check workflow

matrix: ubuntu, macos, windows × py3.10-3.13; uv as the runner; uploads coverage
to Codecov from the linux/3.12 cell only.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §10.2"
```

After the next push, verify the workflow ran green in the GitHub Actions UI before moving on. If it failed, inspect logs and fix locally before pushing again.

______________________________________________________________________

## Task 8 — GitHub Actions: C# workflow

**Files:**

- Create: `.github/workflows/csharp.yml`

- [ ] **Step 1: Write `csharp.yml`**

Create `/Users/kaveh/repos/VMx/.github/workflows/csharp.yml`:

```yaml
name: csharp

on:
  push:
    branches: [main]
    paths:
      - "langs/csharp/**"
      - "spec/**"
      - ".github/workflows/csharp.yml"
  pull_request:
    paths:
      - "langs/csharp/**"
      - "spec/**"
      - ".github/workflows/csharp.yml"

defaults:
  run:
    working-directory: langs/csharp

jobs:
  build:
    name: build & test (${{ matrix.os }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    steps:
      - uses: actions/checkout@v4

      - name: Setup .NET
        uses: actions/setup-dotnet@v4
        with:
          dotnet-version: 8.0.x

      - name: Restore
        run: dotnet restore VMx.sln

      - name: Format check
        run: dotnet format VMx.sln --verify-no-changes

      - name: Build
        run: dotnet build VMx.sln -c Release --no-restore

      - name: Test
        run: dotnet test VMx.sln -c Release --no-build --collect:"XPlat Code Coverage" --results-directory ./TestResults --logger "trx"

      - name: Upload coverage to Codecov
        if: matrix.os == 'ubuntu-latest'
        uses: codecov/codecov-action@v4
        with:
          files: langs/csharp/TestResults/**/coverage.cobertura.xml
          flags: csharp
          fail_ci_if_error: false
```

- [ ] **Step 2: Commit**

```bash
cd /Users/kaveh/repos/VMx
git add .github/workflows/csharp.yml
git commit -m "ci(csharp): add build/test/format-check workflow

matrix: ubuntu, macos, windows × net8.0 SDK; dotnet format --verify-no-changes
gates merges. Coverage uploaded to Codecov from linux only.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §10.2"
```

After the next push, verify the workflow ran green in the GitHub Actions UI.

______________________________________________________________________

## Task 9 — GitHub Actions: skeleton cross-cutting workflows

**Files:**

- Create: `.github/workflows/docs.yml`
- Create: `.github/workflows/conformance.yml`
- Create: `.github/workflows/spec-discipline.yml`

These are skeletons that **succeed trivially** in Phase 0. They're filled in during Phase 1 once the spec content, ADR layout, and conformance tooling exist.

- [ ] **Step 1: Write skeleton `docs.yml`**

Create `/Users/kaveh/repos/VMx/.github/workflows/docs.yml`:

```yaml
name: docs

on:
  push:
    branches: [main]
    paths:
      - "docs/**"
      - "spec/**"
      - ".github/workflows/docs.yml"
  pull_request:
    paths:
      - "docs/**"
      - "spec/**"
      - ".github/workflows/docs.yml"

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Placeholder — real docs build wired up in Phase 2k/3j
        run: |
          echo "docs build will be wired up once mkdocs config lands"
          test -d docs/superpowers || (echo "docs dir missing" && exit 1)
```

- [ ] **Step 2: Write skeleton `conformance.yml`**

Create `/Users/kaveh/repos/VMx/.github/workflows/conformance.yml`:

```yaml
name: conformance

on:
  push:
    branches: [main]
    paths:
      - "spec/**"
      - "langs/**/tests/conformance/**"
      - "tools/check-conformance-coverage.py"
      - ".github/workflows/conformance.yml"
  pull_request:
    paths:
      - "spec/**"
      - "langs/**/tests/conformance/**"
      - "tools/check-conformance-coverage.py"
      - ".github/workflows/conformance.yml"

jobs:
  coverage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Placeholder — real conformance check wired up in Phase 1
        run: |
          if [ -f tools/check-conformance-coverage.py ]; then
            python3 tools/check-conformance-coverage.py
          else
            echo "conformance tool not present yet (lands in Phase 1) — skipping"
          fi
```

- [ ] **Step 3: Write skeleton `spec-discipline.yml`**

Create `/Users/kaveh/repos/VMx/.github/workflows/spec-discipline.yml`:

```yaml
name: spec-discipline

on:
  pull_request:
    paths:
      - "spec/**"

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Check ADR accompanies non-trivial spec change
        run: |
          # PRs touching spec/ should also touch spec/ADRs/ (the spec/README.md and
          # spec/VERSION are allowed exceptions). This check is permissive in Phase 0
          # — it warns but does not fail until spec content lands in Phase 1.
          base_sha="${{ github.event.pull_request.base.sha }}"
          head_sha="${{ github.event.pull_request.head.sha }}"
          changed=$(git diff --name-only "$base_sha" "$head_sha" -- spec/ | grep -v '^spec/README.md$' | grep -v '^spec/VERSION$' || true)
          adr_changed=$(git diff --name-only "$base_sha" "$head_sha" -- spec/ADRs/ || true)

          if [ -n "$changed" ] && [ -z "$adr_changed" ]; then
            echo "::warning::Spec changed without a matching ADR. (Soft-fail until Phase 1 lands.)"
          else
            echo "OK"
          fi
```

- [ ] **Step 4: Commit**

```bash
cd /Users/kaveh/repos/VMx
git add .github/workflows/docs.yml .github/workflows/conformance.yml .github/workflows/spec-discipline.yml
git commit -m "ci: add skeleton docs, conformance, spec-discipline workflows

These succeed trivially in Phase 0; real logic is wired in during Phase 1
once spec content, ADR layout, and tools/check-conformance-coverage.py exist.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §10.3"
```

______________________________________________________________________

## Task 10 — Final verification & spec placeholder

**Files:**

- Create: `spec/README.md`

- Create: `tools/README.md`

- Update: `compatibility-matrix.md` (no-op for Phase 0 — already a placeholder)

- Update: top-level `README.md` (add CI status badges)

- [ ] **Step 1: Write `spec/README.md` placeholder**

Create `/Users/kaveh/repos/VMx/spec/README.md`:

```markdown
# spec/

The language-neutral specification of VMx. Source of truth for every language flavor.

Contents are authored during Phase 1 of the roadmap (see
`/docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md` §12).

Until Phase 1 lands, this directory only contains:
- `ADRs/` (empty — will be populated with ADRs 0001–0007 in Phase 1)
- `fixtures/` (empty — will hold cross-language test fixtures in Phase 1)
- `VERSION` (will be written in Phase 1 with the initial `1.0.0`)

See the design spec at `/docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md` §5 for the planned spec file inventory.
```

- [ ] **Step 2: Write `tools/README.md` placeholder**

Create `/Users/kaveh/repos/VMx/tools/README.md`:

```markdown
# tools/

Cross-cutting scripts that operate across `spec/` and `langs/`.

Planned (Phase 1):
- `check-conformance-coverage.py` — enumerates `XXX-NNN` IDs in `spec/12-conformance.md`
  and verifies every active language flavor has a matching test. Used by
  `.github/workflows/conformance.yml`.
- `build-compatibility-matrix.py` — regenerates `compatibility-matrix.md`
  from spec/version files in each `langs/<lang>/`.
- `spec-to-docs.py` — renders `spec/` into `docs/concepts/` for the docs site.

This directory is intentionally empty in Phase 0.
```

- [ ] **Step 3: Add CI status badges to the top-level README**

Edit `/Users/kaveh/repos/VMx/README.md` to add a badges block immediately under the `# VMx` title (line 1). Insert these lines after the title and before the description:

```markdown
[![csharp](https://github.com/kavehr/VMx/actions/workflows/csharp.yml/badge.svg)](https://github.com/kavehr/VMx/actions/workflows/csharp.yml)
[![python](https://github.com/kavehr/VMx/actions/workflows/python.yml/badge.svg)](https://github.com/kavehr/VMx/actions/workflows/python.yml)
[![docs](https://github.com/kavehr/VMx/actions/workflows/docs.yml/badge.svg)](https://github.com/kavehr/VMx/actions/workflows/docs.yml)
[![conformance](https://github.com/kavehr/VMx/actions/workflows/conformance.yml/badge.svg)](https://github.com/kavehr/VMx/actions/workflows/conformance.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

```

(Replace `kavehr` with the actual GitHub org/handle hosting this repo if different.)

- [ ] **Step 4: Verify everything builds and tests pass locally one more time**

Run all of the following from `/Users/kaveh/repos/VMx`. Each should succeed:

```bash
# Python
cd langs/python
uv sync --all-extras
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src/vmx
uv run pytest -v
cd ../..

# C#
cd langs/csharp
dotnet restore VMx.sln
dotnet format VMx.sln --verify-no-changes
dotnet build VMx.sln -c Release --no-restore
dotnet test VMx.sln -c Release --no-build
cd ../..

# Pre-commit (all files)
pre-commit run --all-files
```

Expected: every command exits 0.

- [ ] **Step 5: Commit and push**

```bash
cd /Users/kaveh/repos/VMx
git add spec/README.md tools/README.md README.md
git commit -m "docs: add spec/ and tools/ placeholders, README badges

- spec/README.md documents that contents arrive in Phase 1
- tools/README.md lists the planned cross-cutting scripts
- top-level README gains CI status badges (csharp/python/docs/conformance)

Phase 0 complete: empty multi-language repo with green CI."

git push origin main
```

- [ ] **Step 6: Verify all five workflows ran and succeeded on GitHub**

Open `https://github.com/kavehr/VMx/actions` (substitute the actual org/repo). You should see five workflow runs from the push above:

- `csharp` (matrix: 3 OSes, all green)
- `python` (matrix: 3 OSes × 4 Python versions = 12 cells, all green)
- `docs` (single job, green)
- `conformance` (single job, green — emits a "tool not present yet" message)
- `spec-discipline` (does not run on push; will run on the first PR that touches spec/)

If any cell is red, **do not declare Phase 0 done**. Inspect the logs, fix the issue locally, push the fix as an additional commit, and re-verify.

______________________________________________________________________

## Phase 0 — completion criteria

Phase 0 is done when **all** of these are true:

1. The repo has the layout shown in §4 of the design spec.
1. `/Users/kaveh/repos/VMx/messages/` and `/Users/kaveh/repos/VMx/services/` no longer exist.
1. `langs/python/src/vmx/messages/protocols.py` and `langs/python/src/vmx/services/message_hub.py` exist with the updated `reactivex` import.
1. `dotnet test langs/csharp/VMx.sln` passes locally (2 smoke tests green).
1. `uv run pytest` in `langs/python` passes locally (4 smoke tests green).
1. `dotnet format langs/csharp/VMx.sln --verify-no-changes` exits 0.
1. `uv run ruff check`, `ruff format --check`, and `mypy --strict src/vmx` exit 0 in `langs/python`.
1. `pre-commit run --all-files` exits 0.
1. All five GitHub Actions workflows ran on the latest push to `main` and succeeded.
1. The top-level README shows badges for all four CI workflows.
1. Repo metadata files exist: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CODEOWNERS`, PR template, 4 issue templates, per-language READMEs and CHANGELOGs, `compatibility-matrix.md` placeholder.

Once those are all true, the repo is ready for **Phase 1: Spec v1.0.0 authoring**. A separate plan should be written for Phase 1 at that point.

______________________________________________________________________

## Plan self-review notes

- **Spec coverage:** This plan covers §4 (layout), §10 (tooling/CI), §11 (migration), parts of §8.1–8.2 (C# skeleton), parts of §9.1–9.2 (Python skeleton). It explicitly defers §5 (spec content — Phase 1), §6 (conformance enforcement — Phase 1), §7 (versioning rules in practice — Phases 2/3 release), §8.3–8.6, §9.3–9.8 (library implementations — Phases 2/3), §13 (future languages — post-1.0).
- **Placeholder scan:** Every code block is intentional and complete. No TBDs, TODOs, or "implement later" patterns. The only deferred work is the explicit "lands in Phase 1/2/3" notes inside the skeleton workflows, which themselves succeed trivially in Phase 0.
- **Type consistency:** `MinSpecVersion` (C#) and `__min_spec_version__` (Python) both stored as strings, both set to `"0.0.0"` in Phase 0 and earmarked to flip to `"1.0.0"` when Phase 1 ships. `Placeholder.MinSpecVersion` (C# const) and `vmx.__min_spec_version__` (Python module attr) intentionally diverge in casing (idiomatic per language, per §9 of design spec) but match in semantics.
- **GitHub handle:** `kavehr` is used throughout as the GitHub org/user placeholder (in URLs, CODEOWNERS, badges). If the actual handle differs, update it consistently in Tasks 2, 5, and 10 before pushing.
