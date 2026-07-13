# SwiftPM Release Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make VMx Swift 3.20.0 installable from the public repository through
SwiftPM, with synchronized root/nested manifests, immutable dual tags, a
verified GitHub Release, a clean remote-consumer smoke test, and accurate docs.

**Architecture:** A root facade manifest points at the existing Swift sources,
tests, and resources. A dump-based checker enforces manifest parity. The
`swift-v3.20.0` workflow validates its sibling `v3.20.0` tag, builds/tests both
package roots, runs a public remote-consumer smoke test, and only then creates
the GitHub Release. Publication evidence is documented in a second PR pair.

**Tech Stack:** Swift 5.9+/SwiftPM, macOS/Xcode CI, Python 3.12 tooling/pytest,
GitHub Actions, canonical Markdown + MkDocs + GitHub wiki.

## Global Constraints

- Release version is exactly `3.20.0`; do not move or reuse any existing tag.
- `v3.20.0` and `swift-v3.20.0` must reference one verified `main` commit.
- Root and nested packages expose the same `VMx` product and target structure.
- Platform floors remain iOS 16, macOS 13, tvOS 16, and watchOS 9.
- The root facade reuses `langs/swift` sources/resources; no copied Swift code.
- No VMx behavior, spec chapter, ADR, dependency, or conformance ID changes.
- Public status docs change only after the tag, release, and remote smoke pass.
- Consumer verification uses a disposable directory and never pushes a consumer.

______________________________________________________________________

### Task 1: Manifest parity checker and root facade

**Files:**

- Create: `tools/check-swift-package-sync.py`
- Create: `tools/tests/test_check_swift_package_sync.py`
- Modify: `tools/tests/conftest.py`
- Create: `Package.swift`

**Interfaces:**

- Produces `normalize_dump(payload, root_prefix) -> dict[str, object]`.

- Produces `manifest_diff(root_payload, nested_payload) -> str` (empty when equal).

- CLI runs both `swift package dump-package` commands and exits nonzero on drift.

- [ ] **Step 1: Write failing normalization and drift tests**

  Cover equal payloads after stripping only `langs/swift/` target paths, a
  platform-floor mismatch, a resource-rule mismatch, and an actionable unified
  diff. Preload the hyphenated script in `tools/tests/conftest.py`.

- [ ] **Step 2: Run RED**

  Run:

  ```bash
  uv --project langs/python run pytest tools/tests/test_check_swift_package_sync.py -q
  ```

  Expected: FAIL because `check-swift-package-sync.py` does not exist.

- [ ] **Step 3: Implement the minimal checker**

  Use `subprocess.run(..., check=True, capture_output=True, text=True)` for
  `swift package dump-package --package-path <path>`, `json.loads`, recursive
  target-path prefix normalization, and `difflib.unified_diff` diagnostics.

- [ ] **Step 4: Run GREEN**

  Run the focused tests; expect all pass. Run Ruff check/format on the new tool.

- [ ] **Step 5: Demonstrate the missing-root failure**

  Run `python3 tools/check-swift-package-sync.py`; expect failure identifying
  the absent root manifest.

- [ ] **Step 6: Add the minimal root manifest**

  Mirror tools version, name, platform floors, product, targets, and resources.
  Prefix only target paths with `langs/swift/`.

- [ ] **Step 7: Verify both manifests**

  Run:

  ```bash
  python3 tools/check-swift-package-sync.py
  swift package dump-package >/dev/null
  swift package dump-package --package-path langs/swift >/dev/null
  swift build -c release
  swift build -c release --package-path langs/swift
  ```

  Expect parity and both release builds to pass.

- [ ] **Step 8: Commit**

  ```bash
  git add Package.swift tools/check-swift-package-sync.py \
    tools/tests/test_check_swift_package_sync.py tools/tests/conftest.py
  git commit -m "feat(swift): add synchronized root SwiftPM facade (#58)"
  ```

### Task 2: Fresh public-consumer smoke tool

**Files:**

- Create: `tools/smoke-swiftpm-consumer.py`
- Create: `tools/tests/test_smoke_swiftpm_consumer.py`
- Modify: `tools/tests/conftest.py`

**Interfaces:**

- `render_manifest(url: str, version: str) -> str` uses the documented remote range.

- `render_main(version: str) -> str` imports VMx and performs a lifecycle round trip.

- `validate_resources(build_root: Path) -> None` requires all four fixture names.

- CLI accepts `--url`, `--version`, and optional `--keep-directory`.

- [ ] **Step 1: Write failing renderer/resource tests**

  Assert the manifest contains `.package(url: ..., from: "3.20.0")` and a
  `VMx` product dependency. Assert the Swift source checks `VMxVersion.current`,
  constructs/destructs/disposes a `ComponentVM`, and that missing resource
  names produce a precise error.

- [ ] **Step 2: Run RED**

  ```bash
  uv --project langs/python run pytest tools/tests/test_smoke_swiftpm_consumer.py -q
  ```

  Expected: FAIL because the tool does not exist.

- [ ] **Step 3: Implement minimal generation and execution**

  Generate a temporary executable package, run `swift build`, recursively
  verify `lifecycle-transitions.json`, `derived-properties.json`,
  `command-truthtable.json`, and `message-ordering.json` below `.build`, then run
  `swift run VMxSmoke 3.20.0`. Remove the directory unless explicitly retained.

- [ ] **Step 4: Run GREEN and lint**

  Run the focused tests plus Ruff check/format. Do not run the remote CLI before
  the semantic tag exists.

- [ ] **Step 5: Commit**

  ```bash
  git add tools/smoke-swiftpm-consumer.py \
    tools/tests/test_smoke_swiftpm_consumer.py tools/tests/conftest.py
  git commit -m "test(swift): add remote SwiftPM consumer smoke (#58)"
  ```

### Task 3: CI and immutable dual-tag release contract

**Files:**

- Create: `tools/tests/test_swift_release_workflow.py`
- Modify: `.github/workflows/swift.yml`
- Modify: `.github/workflows/release.yml`

**Interfaces:**

- Swift CI checks manifest parity and builds/tests root and nested packages.

- Swift release job verifies main ancestry, tag equality, declared version,
  package parity, both builds/tests, public smoke, and changelog release notes.

- [ ] **Step 1: Write a failing workflow contract test**

  Read the workflow files as text and require: root `Package.swift` path trigger;
  parity checker; root and nested release build/test commands; exact sibling
  semantic-tag verification; smoke-tool invocation; and `--notes-file` release.

- [ ] **Step 2: Run RED**

  ```bash
  uv --project langs/python run pytest tools/tests/test_swift_release_workflow.py -q
  ```

  Expected: FAIL on the missing dual-tag/parity/smoke gates.

- [ ] **Step 3: Update Swift CI**

  Add root/tool path triggers, run the parity checker, and run release builds and
  parallel tests from both `.` and `langs/swift` on `macos-latest`.

- [ ] **Step 4: Update the release job**

  Fetch `refs/tags/v${tag_version}`, compare its commit to `GITHUB_SHA`, verify
  `VMxVersion.current`, run the parity checker and both build/test gates, execute
  the remote smoke tool, extract the matching changelog section, and create the
  `swift-v*` release with `--notes-file` only after all earlier steps pass.

- [ ] **Step 5: Run GREEN and validate YAML**

  Run the focused test and `pre-commit run check-yaml --files` for both workflows.

- [ ] **Step 6: Commit**

  ```bash
  git add .github/workflows/swift.yml .github/workflows/release.yml \
    tools/tests/test_swift_release_workflow.py
  git commit -m "ci(swift): verify dual-tag SwiftPM releases (#58)"
  ```

### Task 4: Pre-release runbook and preparation verification

**Files:**

- Modify: `langs/swift/RELEASING.md`

- Modify: `langs/swift/CHANGELOG.md`

- Existing: `docs/superpowers/specs/2026-07-12-swiftpm-release-channel-design.md`

- Existing: `docs/superpowers/plans/2026-07-12-swiftpm-release-channel.md`

- [ ] **Step 1: Update the runbook**

  Document the root facade, exact public URL, platform floors, atomic dual-tag
  push, immutable-tag recovery, parity gate, public smoke, resource validation,
  GitHub Release, and post-verification docs phase.

- [ ] **Step 2: Update the 3.20.0 changelog entry**

  Record the root SwiftPM distribution facade and verified release pipeline
  without claiming the public release already exists.

- [ ] **Step 3: Run all preparation gates**

  Run tool tests/Ruff, manifest parity, root+nested release builds, version and
  fixture checks, docs checks, five-flavor coverage, pre-commit, and
  `git diff --check`. Record local `swift test` as unavailable only if the fresh
  failure is specifically missing XCTest under Command Line Tools; require CI.

- [ ] **Step 4: Commit**

  ```bash
  git add langs/swift/RELEASING.md langs/swift/CHANGELOG.md
  git commit -m "docs(swift): document SwiftPM release procedure (#58)"
  ```

### Task 5: Preparation PRs, tags, release, and public proof

- [ ] **Step 1: Push the ticket branch and open a ready PR to `develop`**

  Use `Relates to #58`; include the design, tests, local XCTest limitation, tag
  plan, and the fact that publication docs remain unchanged until verification.

- [ ] **Step 2: Wait for green CI and squash-merge to `develop`**

  Resolve every review/check on the branch and delete the remote feature branch.

- [ ] **Step 3: Promote `develop` to `main`**

  Open a ticket-only PR with `Relates to #58` (not `Closes` yet), require green
  CI, and merge with a merge commit.

- [ ] **Step 4: Create and push immutable tags together**

  From the verified main merge commit:

  ```bash
  git tag v3.20.0 <main-sha>
  git tag swift-v3.20.0 <main-sha>
  git push origin v3.20.0 swift-v3.20.0
  ```

- [ ] **Step 5: Verify release automation**

  Wait for the release workflow. Require both tags at the same SHA, public smoke
  success, all resources, and GitHub Release `swift-v3.20.0` with changelog notes.

- [ ] **Step 6: Independently verify a second clean consumer**

  Run the smoke tool against the public URL in a new temporary directory and
  remove it after recording output.

### Task 6: Post-publication docs and completion flow

**Files:**

- Modify: `README.md`

- Modify: `compatibility-matrix.md`

- Modify: `langs/swift/README.md`

- Modify: `langs/swift/RELEASING.md`

- Modify: `docs/content/installation.md`

- Modify: `docs/content/flavors/swift.md`

- Modify: `docs/getting-started/swift.md`

- [ ] **Step 1: Create a second issue-scoped branch from `origin/develop`**

  Use `codex/issue-58-swiftpm-release-docs` in a fresh isolated worktree.

- [ ] **Step 2: Replace source-only claims with verified evidence**

  State Swift 3.20.0 is installable from
  `https://github.com/thekaveh/VMx.git` using `from: "3.20.0"`; explain the
  semantic/operational tags, platform floors, GitHub Release, and exact public
  smoke result. Correct stale Swift source-version claims on every touched page.

- [ ] **Step 3: Verify all three documentation surfaces**

  Run canonical generation, strict MkDocs build, wiki dry-run, link/determinism
  checks, empty-artifact sweep, pre-commit, and `git diff --check`.

- [ ] **Step 4: Complete the second develop/main PR pair**

  Squash-merge the docs PR to develop; open a ticket-only develop-to-main PR
  with `Closes #58`; require green CI and merge-commit.

- [ ] **Step 5: Verify live Pages/wiki and finalize**

  Confirm the public installation page and wiki show 3.20.0. Comment with all
  four PRs, commits, tags, release, workflow, resource and fresh-consumer
  evidence. Set Done/Completed, clear Priority/Work order, close the issue, and
  remove both clean worktrees/local branches.
