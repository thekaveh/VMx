# Release Please Unreleased-Section Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the canonical empty Python `[Unreleased]` changelog section on every Release Please PR so required CI passes without manual edits.

**Architecture:** An idempotent Python normalizer owns the repository-specific changelog transformation. The Release Please workflow keeps the trusted `main` checkout at the root, checks out the reported mutable PR branch under `release-pr/` using the fine-grained PAT, executes only the trusted root normalizer, and pushes a scoped repair commit only when necessary.

**Tech Stack:** Python 3 standard library, pytest, GitHub Actions YAML, Release Please v5 outputs, git.

## Global Constraints

- The release PR must continue to modify only the four metadata files allowed by `spec-discipline.yml` relative to `main`.
- `RELEASE_PLEASE_TOKEN` must remain masked and restricted to repository Contents and Pull requests permissions.
- The tool must require an empty canonical Unreleased section and a numbered first release, fail closed on ambiguous changelog structure, and be idempotent on canonical input.
- Mutable release-branch code must never execute in the PAT-bearing workflow job.
- Normal pushes continue through `develop` and then `main`; the generated release PR remains the documented direct-to-main exception.

______________________________________________________________________

### Task 1: Changelog normalizer

**Files:**

- Create: `tools/ensure-release-changelog-unreleased.py`
- Create: `tools/tests/test_ensure_release_changelog_unreleased.py`

**Interfaces:**

- Consumes: one changelog filesystem path from the CLI.

- Produces: `ensure_unreleased(path: Path) -> bool`, returning whether it rewrote the file; CLI exit 0 for canonical/repaired input and nonzero for ambiguity.

- [ ] **Step 1: Write failing tests** for insertion before the first numbered heading, idempotence, safe movement of an empty section below a linked Release Please heading, rejection of a misplaced section with notes, duplicate rejection, and missing-release rejection.

- [ ] **Step 2: Verify RED** with `uv --project langs/python run --locked --extra tools pytest tools/tests/test_ensure_release_changelog_unreleased.py -q`; expect import/collection failure because the tool does not exist.

- [ ] **Step 3: Implement the minimal normalizer** using anchored multiline heading matches and atomic same-file text replacement only after validation.

- [ ] **Step 4: Verify GREEN** with the same pytest command; expect all normalizer cases to pass.

### Task 2: Release Please workflow integration

**Files:**

- Modify: `.github/workflows/release-please.yml`
- Modify: `tools/tests/test_ci_workflow_contracts.py`

**Interfaces:**

- Consumes: `steps.release.outputs.prs_created` and `fromJSON(steps.release.outputs.pr).headBranchName` from the pinned Release Please action.

- Produces: an authenticated checkout of the generated branch followed by an idempotent repair commit and push.

- [ ] **Step 1: Add failing workflow-contract assertions** for the action step ID, PR-created condition, generated head checkout, PAT input, tool invocation, diff guard, commit, and push.

- [ ] **Step 2: Verify RED** with `uv --project langs/python run --locked --extra tools pytest tools/tests/test_ci_workflow_contracts.py -q`; expect the new assertions to fail against the current workflow.

- [ ] **Step 3: Add the minimal workflow steps**: identify the Release Please action as `release`, check out the generated head only when a PR changed, invoke the normalizer, and commit/push only when the file differs.

- [ ] **Step 4: Verify GREEN** with the focused workflow-contract test.

### Task 3: Verification and Git flow

**Files:**

- Verify all files changed by Tasks 1 and 2 plus this design and plan.

**Interfaces:**

- Consumes: the completed repair branch.

- Produces: green feature-to-develop and develop-to-main PRs, followed by a refreshed green release PR.

- [ ] **Step 1: Run local gates:** focused tests; `uv --project langs/python run --locked --extra tools pytest tools/tests -q`; `uv --project langs/python run --locked --extra tools python tools/check-version-consistency.py`; workflow-pin checks; Ruff on the new Python files; pre-commit; and `git diff --check`.

- [ ] **Step 2: Commit and push** `codex/fix-release-please-unreleased`, open a PR to `develop`, wait for required CI, and merge it.

- [ ] **Step 3: Open a `develop` to `main` promotion PR**, wait for required CI, and merge it with a merge commit.

- [ ] **Step 4: Verify Release Please refreshes PR #298**, wait for all required checks, review its exact four-file diff, and merge it.

- [ ] **Step 5: Stop at the protected `pypi-python` environment approval**, report the exact approval link to the maintainer, and do not approve the irreversible upload on their behalf.
