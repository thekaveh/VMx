# npm Release Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish `@thekaveh/vmx` 3.21.0 from a verified main tag with checked
contents, provenance, clean ESM/CommonJS/declaration consumers, a GitHub
Release, and accurate three-surface documentation.

**Architecture:** Python release tools validate the npm tarball and generate
disposable local/public consumers. TypeScript CI exercises the tarball on Node
20/22; the release workflow uses Node 24 + npm 11.5.1, supports a one-time token
bootstrap followed by OIDC, polls npm, and gates release notes on public smoke.

**Tech Stack:** npm/Node.js, TypeScript/tsup/Vitest, Python/pytest, GitHub
Actions OIDC, npm provenance, canonical Markdown/MkDocs/GitHub wiki.

## Global Constraints

- First release is exactly `@thekaveh/vmx@3.21.0`; never reuse a published
  version or move an existing tag.
- Public entries are `.`, `./notifications`, and `./conformance` in ESM,
  CommonJS, and declarations.
- Release uses a GitHub-hosted runner, Node 24, npm 11.5.1, and
  `id-token: write`.
- The bootstrap token is optional job input, exposed only to its publish step,
  and removed after npm trusted publishing is configured.
- Public status docs change only after npm, provenance, exact installs, and the
  GitHub Release are independently verified.
- No VMx behavior, spec, ADR, dependency contract, or conformance ID changes.

______________________________________________________________________

### Task 1: Checked npm package-content allowlist

**Files:**

- Create: `tools/check-typescript-package.py`
- Create: `tools/tests/test_check_typescript_package.py`
- Modify: `tools/tests/conftest.py`

**Interfaces:**

- `validate_paths(paths: set[str]) -> list[str]` returns actionable errors.

- CLI accepts `--package-dir`, runs `npm pack --dry-run --json`, and fails on
  missing or unexpected files.

- [ ] **Step 1: Write failing tests** for the exact metadata, three entry-point
  families, four fixtures, allowed hashed chunks, a missing declaration, and
  an unexpected secret/source file. Preload the hyphenated tool in conftest.

- [ ] **Step 2: Run RED:**

  ```bash
  uv --project langs/python run pytest tools/tests/test_check_typescript_package.py -q
  ```

  Expect import failure because the tool does not exist.

- [ ] **Step 3: Implement the minimal validator.** Require `README.md`,
  `package.json`, all fixture paths, and `.js/.cjs/.d.ts/.d.cts` plus maps for
  `index`, `notifications`, and `conformance`. Permit only narrow
  `dist/chunk-*` and `dist/relayCommand-*` generated patterns.

- [ ] **Step 4: Run GREEN**, Ruff, and the real CLI against
  `langs/typescript`; require the current 34-file package to pass.

- [ ] **Step 5: Commit:**

  ```bash
  git commit -m "test(typescript): enforce npm package contents (#57)"
  ```

### Task 2: Disposable packed/public consumer smoke

**Files:**

- Create: `tools/smoke-npm-consumer.py`
- Create: `tools/tests/test_smoke_npm_consumer.py`
- Modify: `tools/tests/conftest.py`

**Interfaces:**

- Render ESM, CJS, and `.mts` declaration probes for all three entries.

- `wait_for_version(package, version, timeout_seconds) -> None` polls exact npm
  availability.

- CLI accepts `--package-dir` for a local tarball or `--package-name` plus
  `--version` for public mode, and optional `--keep-directory`.

- [ ] **Step 1: Write failing renderer, input-validation, polling, and cleanup
  tests.** Require `__version__`, root/notifications/conformance imports,
  CommonJS requires, and NodeNext declaration compilation.

- [ ] **Step 2: Run RED** and confirm the missing-tool failure.

- [ ] **Step 3: Implement local mode.** Pack to a temp directory, generate a
  consumer with exact tarball + `rxjs` + `typescript`, install without scripts,
  run ESM/CJS probes, compile declarations, and clean up.

- [ ] **Step 4: Implement public mode.** Poll `npm view` for the exact version,
  install `@thekaveh/vmx@X.Y.Z`, and reuse the same probes.

- [ ] **Step 5: Run GREEN**, Ruff, and a real local packed-consumer smoke.

- [ ] **Step 6: Commit:**

  ```bash
  git commit -m "test(typescript): add npm consumer smoke (#57)"
  ```

### Task 3: CI and workflow contracts

**Files:**

- Create: `tools/tests/test_typescript_release_workflow.py`
- Modify: `.github/workflows/typescript.yml`
- Modify: `.github/workflows/conformance.yml`

**Interfaces:** TypeScript CI has a Node 20/22 Ubuntu package job running the
allowlist and local smoke; workflow changes trigger the contract suite.

- [ ] **Step 1: Write RED workflow tests** requiring tool path triggers,
  Node 20/22 package matrix, both tool invocations, and release-workflow trigger
  reachability.

- [ ] **Step 2: Add the minimal TypeScript CI package job** after the existing
  cross-platform library matrix; use `npm ci`, allowlist, and local smoke.

- [ ] **Step 3: Ensure conformance triggers** on both TypeScript and release
  workflow changes so contract tests cannot be skipped.

- [ ] **Step 4: Run GREEN** and pre-commit YAML checks.

- [ ] **Step 5: Commit:**

  ```bash
  git commit -m "ci(typescript): verify packed npm consumers (#57)"
  ```

### Task 4: Bootstrap-to-OIDC release pipeline

**Files:**

- Modify: `.github/workflows/release.yml`
- Modify: `tools/tests/test_typescript_release_workflow.py`

**Interfaces:**

- Publish job performs all gates before authentication.

- Verify matrix polls/installs public 3.21.0 on Node 20/22.

- Release-notes job runs only after both public consumers pass.

- [ ] **Step 1: Extend RED contract tests** for Node 24, npm 11.5.1, no
  release cache, fixture sync, both typechecks, lint, build/test/audit,
  allowlist/smoke, tag/main/version gates, mutually exclusive bootstrap/OIDC
  publish steps, public verify matrix, and changelog-backed GitHub Release.

- [ ] **Step 2: Harden the publish job.** Keep the protected
  `npm-typescript` environment and `id-token: write`; expose `NPM_TOKEN` but map
  it to `NODE_AUTH_TOKEN` only in the bootstrap step.

- [ ] **Step 3: Add public verification.** Poll and install the exact version on
  Node 20 and 22 using `tools/smoke-npm-consumer.py`.

- [ ] **Step 4: Add release notes.** Extract `## [3.21.0]` portably and create
  `typescript-v3.21.0` only after public verification.

- [ ] **Step 5: Run GREEN**, full tools tests, and YAML validation.

- [ ] **Step 6: Commit:**

  ```bash
  git commit -m "ci(typescript): operationalize npm publishing (#57)"
  ```

### Task 5: Pre-release runbook and preparation verification

**Files:**

- Modify: `langs/typescript/RELEASING.md`

- Modify: `langs/typescript/CHANGELOG.md`

- [ ] **Step 1: Rewrite the runbook** with the 3.21.0 bootstrap token,
  `release.yml` trusted-publisher identity, Node/npm floors, protected
  environment, token removal, provenance, allowlist, exact public polling,
  deprecation/recovery, and post-verification docs phases. Remove tag-deletion
  guidance for immutable tags.

- [ ] **Step 2: Add a 3.21.0 changelog bullet** for the verified release
  pipeline without claiming the package is public.

- [ ] **Step 3: Run preparation gates:** all TypeScript gates, real allowlist
  and packed smoke, all tools tests/Ruff, version/fixture/conformance checks,
  docs checks, pre-commit, diff/secret hygiene.

- [ ] **Step 4: Commit:**

  ```bash
  git commit -m "docs(typescript): document npm release procedure (#57)"
  ```

### Task 6: Preparation PRs, environment, and first publication

- [ ] Push a ready PR to `develop` with `Relates to #57`; require green CI and
  squash-merge.
- [ ] Promote only #57 preparation to `main` with a green merge-commit PR.
- [ ] Create protected environment `npm-typescript`, restricted to
  `typescript-v*`, with maintainer approval. Never transmit the npm token in
  chat or logs.
- [ ] Confirm `typescript-v3.21.0` and npm version are absent. After an
  authenticated owner places the scoped token in the environment, create the
  immutable tag at verified main and watch the full workflow.
- [ ] Require npm 3.21.0, provenance, both public consumer cells, and GitHub
  Release. Independently run a second exact public consumer.
- [ ] Configure npm trusted publisher for `thekaveh/VMx`, `release.yml`,
  environment `npm-typescript`, publish permission; remove/revoke the bootstrap
  token and document evidence.

### Task 7: Post-publication documentation and completion

**Files:**

- Modify: `README.md`

- Modify: `compatibility-matrix.md`

- Modify: `langs/typescript/README.md`

- Modify: `langs/typescript/RELEASING.md`

- Modify: `docs/content/installation.md`

- Modify: `docs/content/flavors/typescript.md`

- Modify: `docs/getting-started/typescript.md`

- [ ] Create `codex/issue-57-npm-release-docs` from current `origin/develop`.

- [ ] Replace source-only claims with verified npm 3.21.0 install, provenance,
  three exports, Node support, and trusted-publishing/recovery guidance.

- [ ] Run deterministic repo/site/wiki generation, strict MkDocs, wiki dry run,
  links, version checks, pre-commit, and diff hygiene.

- [ ] Complete docs PR to develop, then final develop-to-main PR with
  `Closes #57` and merge commit.

- [ ] Verify live npm, GitHub Release, Pages, and wiki. Comment with all PRs,
  commits, workflows, provenance, consumers, and docs evidence; set
  Done/Completed, clear ordering fields, close, and remove worktrees/branches.
