# VMx Absorption Audit — Stage 6 (Release) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to execute. Checkboxes (`- [ ]`) track progress. Final stage of the master audit at `docs/superpowers/plans/2026-05-27-vmx-absorption-audit.md`.

**Goal:** Finalize the v2.1.0 release: bump versions, refresh docs, final cross-flavor audit (2 consecutive zero-finding passes), CHANGELOG, and open a PR. **Do NOT merge** — final merge is the user's explicit confirmation point.

**Architecture:** Mostly mechanical version-bump and documentation work. The hard work landed in Stages 1-5; Stage 6 ties it off. The branch must remain local until the user merges the PR they review.

**Tech Stack:** Markdown spec/docs; C# .csproj + Directory.Packages.props; Python pyproject.toml + `__min_spec_version__` constant; TypeScript package.json + `__minSpecVersion__` constant.

______________________________________________________________________

## Context

- **Branch:** `feat/v2.1-absorption-audit` (Stage 5 closed at commit ef1f333; 146 commits on branch).
- **Spec version:** currently `2.1.0-dev`; target `2.1.0`.
- **Conformance count:** 219 IDs in `spec/12-conformance.md`.
- **ADRs:** 0001-0033 (28 new since the audit started).
- **Repo conventions:** see master plan §"Repository conventions". No AI attribution; mdformat may reformat (re-stage + re-commit, never `--amend`); push only when the user approves.

## What landed in Stages 1-5 (release-note material)

| Stage | Item                                                           | Reference              |
| ----- | -------------------------------------------------------------- | ---------------------- |
| 1     | `IFilterable<TItem>` (CAP-021)                                 | ADR-0022               |
| 1     | `IPageable` + `PagedComposition<TVM>` (CAP-022, COL-016..021)  | ADR-0023               |
| 1     | `ServicedObservableCollection<T>` (COL-001..004)               | ADR-0024               |
| 1     | `ObservableDictionary<K1,K2,V>` (COL-010..015, COL-022)        | ADR-0025               |
| 1     | `ObservableList<T>` granular events (COL-005..009, COL-023)    | ADR-0026               |
| 1     | Fluent command extensions (CMD-008..011)                       | ADR-0027               |
| 1     | Chapter `21-collections.md` (new)                              | —                      |
| 2     | `HierarchicalVM<TModel, TVM>` (HIER-001..014)                  | ADR-0028               |
| 2     | `TreeStructureChangedMessage` (new type)                       | —                      |
| 2     | Chapter `18-hierarchical-vm.md` (new)                          | —                      |
| 3     | `IDialogService` + `NullDialogService` (DIA-001..008)          | ADR-0029               |
| 3     | `FormVM<TM>` + `FormRevertedMessage` (FORM-001..010)           | ADR-0030               |
| 3     | Chapters `19-dialogs.md`, `20-form-vm.md` (new)                | —                      |
| 4     | `NotificationVM` + `ConfirmationVM` (NOTIF-011..016)           | ADR-0031               |
| 5     | `PropertyValueChangedMessagesFor` helper                       | ADR-0032 (informative) |
| 5     | LINQ helpers C#-only (`CartesianProduct`, `Sample`, `Product`) | ADR-0033               |
| 5     | Init-token recipe in `15-derived-properties.md`                | (recipe)               |
| 5     | RelayCommand property-trigger recipe in `04-commands.md`       | (recipe)               |

Net additions: **27 new conformance IDs** (152 → 195 → 213 → 219; final 219), **12 new ADRs** (0022-0033), **4 new spec chapters** (18, 19, 20, 21), **6 chapter extensions** (03, 04, 13, 14, 15, 16).

## Files to be created or modified

### Modified

- `spec/VERSION` (2.1.0-dev → 2.1.0)
- `langs/csharp/src/VMx/VMx.csproj` (bump `<Version>` or `Directory.Packages.props` if centralized)
- `langs/csharp/src/VMx.Notifications/VMx.Notifications.csproj` (bump if independent versioning)
- `langs/csharp/Directory.Build.props` or central props file (if Version lives there)
- `langs/python/pyproject.toml` (bump `version`)
- `langs/python/src/vmx/__init__.py` or `_version.py` (bump `__min_spec_version__` constant)
- `langs/typescript/package.json` (bump `version`)
- `langs/typescript/src/index.ts` or similar (bump `__minSpecVersion__` constant)
- `compatibility-matrix.md` (add a v2.1.0 row matching spec ↔ flavor versions)
- `spec/README.md` (remove `-dev` suffix from VERSION reference; final ID/chapter/ADR counts)
- `spec/00-overview.md` (vision/concepts refresh to mention new chapters)
- `spec/01-concepts.md` (extend VM types section, new collections, dialog/form references)
- `spec/ADRs/README.md` (verify all 12 new ADRs (0022-0033) registered)
- `docs/superpowers/plans/2026-05-27-vmx-absorption-audit.md` (tick Stage 6 at close)

### Created (potentially)

- `CHANGELOG.md` at repo root with v2.1.0 entry (or per-flavor CHANGELOG files if convention exists; check)
- PR description (transient — used in `gh pr create`)

______________________________________________________________________

## Stage 6 progress tracker

- [x] **Substage 6A** — Version bumps (spec/VERSION + 4-5 package files + constants)
- [x] **Substage 6B** — Documentation refresh (overview, concepts, README, compat matrix, ADR registry)
- [x] **Substage 6C** — CHANGELOG entries
- [ ] **Substage 6D** — Final cross-flavor audit (2 consecutive zero-finding passes)
- [ ] **Substage 6E** — PR creation (DO NOT MERGE — user review)

______________________________________________________________________

# Substage 6A — Version bumps

### Task 6A.1: Bump `spec/VERSION` to 2.1.0

**Files:**

- Modify: `spec/VERSION`

- [ ] **Step 1: Verify current content.**

```bash
cat spec/VERSION
```

Expected: `2.1.0-dev` (single line, no trailing whitespace).

- [ ] **Step 2: Bump.**

```bash
echo "2.1.0" > spec/VERSION
cat spec/VERSION
```

Verify: `2.1.0`.

- [ ] **Step 3: Commit.**

```bash
git add spec/VERSION
git commit -m "spec: bump VERSION to 2.1.0 (release)"
git log -1 --format='%B' | grep -i 'co-authored-by' && echo "BUG" || echo "clean"
```

### Task 6A.2: Bump C# package versions

**Files:**

- Locate and modify: `langs/csharp/src/VMx/VMx.csproj`, `langs/csharp/src/VMx.Notifications/VMx.Notifications.csproj`, OR `langs/csharp/Directory.Build.props`, OR `langs/csharp/Directory.Packages.props`

- [ ] **Step 1: Locate current version declaration.**

```bash
cd langs/csharp
grep -rn '<Version>\|<VersionPrefix>\|<PackageVersion' . 2>/dev/null | grep -v bin | grep -v obj | head
```

Per CLAUDE.md: "Central package versions live in `Directory.Packages.props`" — so the version declarations are likely in one of:

- `Directory.Packages.props` (NuGet central package management)
- `Directory.Build.props` (per-csproj `<Version>` inheritance)
- Individual `.csproj` files

Find where 2.0.x is currently declared.

- [ ] **Step 2: Bump VMx version from current 2.0.x to 2.1.0** in the appropriate file. Likely a one-line `<Version>2.0.X</Version>` → `<Version>2.1.0</Version>` edit.

- [ ] **Step 3: Bump VMx.Notifications.** Per ADR-0013 sub-packages have **independent** versioning. Check its current version; bump appropriately. If it was at 1.0.0, going to 1.1.0 or 2.0.0 depending on whether new types (NotificationVM/ConfirmationVM) constitute a major. Per SemVer additive-changes-rule, **1.1.0** is the natural choice.

- [ ] **Step 4: Verify build still works.**

```bash
cd /Users/kaveh/repos/VMx/langs/csharp && dotnet restore && dotnet build 2>&1 | tail -5
```

Expected: build succeeds at the new version.

- [ ] **Step 5: Commit.**

```bash
git add langs/csharp/
git commit -m "csharp: bump VMx 2.0.x → 2.1.0 and VMx.Notifications → 1.1.0"
```

### Task 6A.3: Bump Python package version + `__min_spec_version__`

**Files:**

- Modify: `langs/python/pyproject.toml`

- Modify: `langs/python/src/vmx/__init__.py` (or `_version.py`)

- [ ] **Step 1: Inspect current state.**

```bash
grep '^version' langs/python/pyproject.toml
grep '__version__\|__min_spec_version__' langs/python/src/vmx/__init__.py langs/python/src/vmx/_version.py 2>/dev/null
```

- [ ] **Step 2: Bump `version` in `pyproject.toml`** from 2.0.x to 2.1.0.

- [ ] **Step 3: Bump `__min_spec_version__`** (and `__version__` if present) constant to 2.1.0.

- [ ] **Step 4: Verify install + tests still pass.**

```bash
cd langs/python && uv sync --all-extras && uv run pytest 2>&1 | tail -5
```

- [ ] **Step 5: Commit.**

```bash
git add langs/python/
git commit -m "python: bump vmx 2.0.x → 2.1.0 (pyproject + __min_spec_version__)"
```

### Task 6A.4: Bump TypeScript package version + `__minSpecVersion__`

**Files:**

- Modify: `langs/typescript/package.json`

- Modify: `langs/typescript/src/index.ts` (or version module — likely a constant or env-injected value)

- [ ] **Step 1: Inspect.**

```bash
grep '"version"' langs/typescript/package.json
grep -rn '__minSpecVersion__\|MIN_SPEC_VERSION' langs/typescript/src 2>/dev/null
```

- [ ] **Step 2: Bump `version` in `package.json`** to `2.1.0`.

- [ ] **Step 3: Bump `__minSpecVersion__`** constant to `2.1.0`.

- [ ] **Step 4: Verify build + tests.**

```bash
cd langs/typescript && npm ci && npm run sync-fixtures && npm run typecheck && npm test 2>&1 | tail -5
```

- [ ] **Step 5: Commit.**

```bash
git add langs/typescript/
git commit -m "typescript: bump vmx 2.0.x → 2.1.0 (package.json + __minSpecVersion__)"
```

### Task 6A.5: Tick Substage 6A

- [ ] Commit `docs(plan): tick Substage 6A — version bumps`

______________________________________________________________________

# Substage 6B — Documentation refresh

### Task 6B.1: Refresh `compatibility-matrix.md`

**Files:**

- Modify: `compatibility-matrix.md` (at repo root)

- [ ] **Step 1: Inspect current content.**

```bash
cat compatibility-matrix.md
```

- [ ] **Step 2: Add a new row** for spec 2.1.0 ↔ each flavor's new version.

Likely format (mirror existing rows):

```markdown
| Spec     | C# VMx | C# VMx.Notifications | Python vmx | TypeScript vmx |
|----------|--------|---------------------|------------|----------------|
| 2.0.0    | 2.0.0  | 1.0.0               | 2.0.0      | 2.0.0          |
| 2.1.0    | 2.1.0  | 1.1.0               | 2.1.0      | 2.1.0          |
```

(Adapt to the actual table shape — check existing rows.)

- [ ] **Step 3: Commit.**

```bash
git add compatibility-matrix.md
git commit -m "docs: add v2.1.0 row to compatibility-matrix.md"
```

### Task 6B.2: Refresh `spec/README.md`

**Files:**

- Modify: `spec/README.md`

- [ ] **Step 1: Inspect for remaining `-dev` suffix or stale counts.**

```bash
grep -n '2\.1\.0-dev\|2\.0\.0\|180 IDs\|181 IDs\|195 IDs\|213 IDs\|0001-0027\|0001-0028\|0001-0029\|0001-0030\|0001-0031\|0001-0032' spec/README.md
```

- [ ] **Step 2: Update all stale references:**

- VERSION: `2.1.0-dev` → `2.1.0`

- Conformance ID count: → `219 IDs`

- ADR range: → `0001-0033`

- [ ] **Step 3: Commit.**

```bash
git add spec/README.md
git commit -m "docs(spec): finalize README for v2.1.0 (VERSION, ID count, ADR range)"
```

### Task 6B.3: Refresh `spec/00-overview.md`

**Files:**

- Modify: `spec/00-overview.md`

- [ ] **Step 1: Read current overview** and find sections that need to mention v2.1 additions.

```bash
cat spec/00-overview.md
```

- [ ] **Step 2: Update the "scope" / "what's included" section** to mention:
- New VM types: `HierarchicalVM`, `FormVM`
- New host service: `IDialogService`
- New rendering VMs (in notifications sub-package): `NotificationVM`, `ConfirmationVM`
- New collection primitives: `ServicedObservableCollection`, `ObservableList`, `ObservableDictionary`, `PagedComposition`
- New capabilities: `IFilterable`, `IPageable`

Keep the additions concise — one paragraph or a few bullets at most. The chapter-level detail is in the individual chapters.

- [ ] **Step 3: Commit.**

```bash
git add spec/00-overview.md
git commit -m "spec(ch): refresh chapter 00 overview for v2.1 additions"
```

### Task 6B.4: Refresh `spec/01-concepts.md`

**Files:**

- Modify: `spec/01-concepts.md`

- [ ] **Step 1: Read** and find the VM-types section (likely §2 or similar).

- [ ] **Step 2: Extend the VM type list** with HierarchicalVM and FormVM (mention they're chapters 18 and 20). Add a brief note about the notifications sub-package's rendering VMs (chapter 16) and the new collections chapter (21).

- [ ] **Step 3: Commit.**

```bash
git add spec/01-concepts.md
git commit -m "spec(ch): refresh chapter 01 concepts for v2.1 (HierarchicalVM, FormVM, …)"
```

### Task 6B.5: Verify `spec/ADRs/README.md` is complete

**Files:**

- Read (and modify if needed): `spec/ADRs/README.md`

- [ ] **Step 1: Verify all 33 ADRs are registered.**

```bash
ls spec/ADRs/*.md | grep -v README.md | wc -l   # expect 33
grep -c '\[ADR-00' spec/ADRs/README.md  # should also be 33 (or match the actual link format)
```

If counts match, no edit needed.

- [ ] **Step 2: If any ADR is missing from the registry**, add the row.

- [ ] **Step 3: Commit if anything changed.**

```bash
git add spec/ADRs/README.md
git commit -m "spec(adr): finalize ADR registry for v2.1"
```

### Task 6B.6: Cross-check diagrams render

**Files:**

- Read (and fix if needed): `spec/18-hierarchical-vm.md`, `spec/19-dialogs.md`, `spec/20-form-vm.md`, `spec/16-notifications.md`

- [ ] **Step 1: Search for all mermaid code blocks.**

````bash
grep -l '^```mermaid' spec/*.md
````

- [ ] **Step 2: Manually verify each diagram has matching opening + closing fences and a recognized mermaid diagram type** (`graph`, `sequenceDiagram`, `stateDiagram-v2`, `gantt`).

- [ ] **Step 3: Optionally check rendering** with a mermaid CLI if available:

```bash
which mmdc || echo "mmdc not installed — skipping live render check"
```

If `mmdc` is available, render each diagram. If not, skip (mermaid syntax errors typically surface on GitHub render rather than local).

- [ ] **Step 4: No commit unless something was broken** and you fixed it.

### Task 6B.7: Tick Substage 6B

- [ ] Commit `docs(plan): tick Substage 6B — documentation refresh`

______________________________________________________________________

# Substage 6C — CHANGELOG entries

### Task 6C.1: Determine CHANGELOG convention

**Files:**

- Check for existing `CHANGELOG.md` at repo root, in `spec/`, or per-flavor.

- [ ] **Step 1: Survey existing changelogs.**

```bash
find . -name 'CHANGELOG*' -not -path './node_modules/*' -not -path './.git/*' 2>/dev/null | head
```

- [ ] **Step 2: Decision.**
- If a unified `CHANGELOG.md` at repo root exists, use it.
- If per-flavor changelogs exist, add an entry to each.
- If none exist, create one unified `CHANGELOG.md` at the repo root.

### Task 6C.2: Write the v2.1.0 CHANGELOG entry

**Files:**

- Create or modify: `CHANGELOG.md` (per Task 6C.1 decision)

- [ ] **Step 1: Write the entry.**

```markdown
## v2.1.0 — 2026-05-28

### Added

#### Spec
- Four new chapters: `18-hierarchical-vm.md`, `19-dialogs.md`, `20-form-vm.md`, `21-collections.md`.
- Twelve new ADRs: 0022-0033.
- 67 new conformance IDs: HIER-001..014, DIA-001..008, FORM-001..010, COL-001..023, CMD-008..011, NOTIF-011..016, CAP-021, CAP-022.
- Total catalog now: 219 IDs.

#### Per-flavor

- **`HierarchicalVM<TModel, TVM>`** — first-class recursive tree VM with lazy/eager child loading, depth-first construction, materialized path, parent change + structural-change hub messages. `TreeStructureChangedMessage` new type.
- **`IDialogService`** + **`NullDialogService`** — host-side modal interactions (file pick, confirm, severity-tagged notify) distinct from `INotificationHub`.
- **`FormVM<TM>`** — snapshot/revert edit lifecycle, ORM-agnostic, with `DenyCommand`, `ApproveCommand`, `OnApproved` event, optional strict mode. `FormRevertedMessage` new type.
- **`NotificationVM`** + **`ConfirmationVM`** — render-side ViewModels with auto-dismiss lifecycle (60s/300s default), opacity decay, dismiss/approve/reject commands.
- **`ServicedObservableCollection<T>`** — observable collection that publishes to a message hub.
- **`ObservableList<T>`** — granular per-mutation events (ItemAdded/Removed/Replaced/Reset) with batch suppression.
- **`ObservableDictionary<K1, K2, V>`** — composite-key observable dictionary with Keys1/Keys2 observable views and hub publication.
- **`PagedComposition<TVM>`** — paging helper decorating any composition with the `IPageable` capability.
- **`IFilterable<TItem>`** — capability for predicate-based filtering. **`IPageable`** — capability for paged navigation.
- **Fluent command extensions**: `cmd.Confirm(delegate | hub | dialogService)`, `cmd.PrecedeWith(other)`, `cmd.SucceedWith(other)`, `cmd.WrapWith(predicate?, pre?, post?)`.
- **`PropertyValueChangedMessagesFor`** helper (informative).
- **C#-only LINQ helpers** in `VMx.Extensions`: `CartesianProduct`, `Sample`, `Product`.

### Changed

- C# `VMx` 2.0.x → **2.1.0**
- C# `VMx.Notifications` 1.0.0 → **1.1.0**
- Python `vmx` 2.0.x → **2.1.0**
- TypeScript `vmx` 2.0.x → **2.1.0**
- Spec version 2.0.0 → **2.1.0**.

### No breaking changes

This release is purely additive. Existing v2.0 surface is unchanged. Consumers upgrading from 2.0 → 2.1 require no code changes.
```

- [ ] **Step 2: Commit.**

```bash
git add CHANGELOG.md   # or whichever path Task 6C.1 chose
git commit -m "docs: add v2.1.0 CHANGELOG entry"
```

### Task 6C.3: Tick Substage 6C

- [ ] Commit `docs(plan): tick Substage 6C — changelog`

______________________________________________________________________

# Substage 6D — Final cross-flavor audit

### Task 6D.1: Pass A — multi-agent parallel audit

- [ ] **Step 1: Dispatch combined audit subagent** (single dispatch covering all four perspectives: C#, Python, TypeScript, spec/docs).

Audit verifies:

- All 5 stages' deliverables present and integrated

- `spec/VERSION` = `2.1.0`

- All 4 package files at the bumped versions

- `compatibility-matrix.md` has the v2.1.0 row

- `spec/README.md`, `spec/00-overview.md`, `spec/01-concepts.md` reflect final state

- ADR registry complete (0001-0033)

- All 28 new conformance IDs covered in all 3 flavors (catalog at 219)

- All 3 flavor tooling clean (build / test / format / lint / mypy / typecheck)

- Pre-commit clean

- No AI attribution in any commit on `main..HEAD`

- CHANGELOG entry present and accurate

- Diagrams present and syntactically valid

- [ ] **Step 2: Address Critical + Important findings. Consider Minors.**

- [ ] **Step 3: Verdict CLEAN → counter 1/2.**

### Task 6D.2: Own spot-check between passes

- [ ] Verify key invariants yourself:

```bash
cat spec/VERSION   # 2.1.0
grep -n '2\.1\.0-dev' spec/ langs/ 2>/dev/null   # should be empty
uv --project langs/python run python tools/check-conformance-coverage.py --require csharp --require python --require typescript
for sha in $(git log main..HEAD --format='%H'); do msg=$(git log -1 $sha --format='%B'); echo "$msg" | grep -qi 'co-authored-by\|claude.com\|anthropic' && echo "BAD: $sha"; done
git log --oneline main..HEAD | wc -l
```

### Task 6D.3: Pass B — fresh audit subagent

- [ ] Dispatch fresh combined audit subagent. Independent verification — do NOT assume Pass A's coverage.

- [ ] Counter advances to 2/2 → Stage 6 final audit CLEAN.

### Task 6D.4: Tick Substage 6D

- [ ] Commit `docs(plan): tick Substage 6D — final cross-flavor audit clean (2/2)`

______________________________________________________________________

# Substage 6E — PR creation (DO NOT MERGE)

### Task 6E.1: Tick Stage 6 box in master plan

**Files:**

- Modify: `docs/superpowers/plans/2026-05-27-vmx-absorption-audit.md`

- [ ] **Step 1: Edit** the stage progress tracker:

```
- [ ] **Stage 6** — Release (version bumps, docs, compatibility matrix, final audit, merge to main)
```

becomes:

```
- [x] **Stage 6** — Release (version bumps, docs, compatibility matrix, final audit, merge to main)
```

- [ ] **Step 2: Commit.**

```bash
git add docs/superpowers/plans/2026-05-27-vmx-absorption-audit.md
git commit -m "docs(plan): close Stage 6 (Release) — final audit clean, ready for PR"
git log -1 --format='%B' | grep -i 'co-authored-by' && echo "BUG" || echo "clean"
```

### Task 6E.2: Push the branch

**Important:** This is the first time the branch leaves the local machine. Per user preference, push is OK at this point because PR creation requires it; merging requires explicit user approval.

- [ ] **Step 1: Verify branch is ahead of main + clean.**

```bash
git status   # expect clean working tree
git log --oneline main..HEAD | wc -l   # ~150 commits
```

- [ ] **Step 2: Push.**

```bash
git push -u origin feat/v2.1-absorption-audit
```

- [ ] **Step 3: Verify remote tracking.**

```bash
git branch -vv | grep feat/v2.1-absorption-audit
```

### Task 6E.3: Create the PR

**Note:** Per user preference, do NOT merge. Just create the PR for review.

- [ ] **Step 1: Construct the PR body** in a temp file:

```bash
cat > /tmp/pr-body.md <<'EOF'
## Summary

Absorption audit cycle — bumps spec to v2.1.0 by adopting 15 candidates identified in `spec/proposals/2026-05-27-vmx-absorption-audit.md` from the legacy VMx codebases (VMx.old, My.Architecture.New, My.Architecture.View, GuideArch.Old, GuideArch).

### What's new
- **4 new spec chapters**: 18 HierarchicalVM, 19 IDialogService, 20 FormVM, 21 collections.
- **12 new ADRs** (0022-0033).
- **67 new conformance IDs** (catalog now 219 total).
- **HierarchicalVM, FormVM, IDialogService, NotificationVM/ConfirmationVM, ServicedObservableCollection, ObservableList, ObservableDictionary, PagedComposition, IFilterable, IPageable, fluent command extensions, PropertyValueChangedMessagesFor, C#-only LINQ helpers**.

### Versions
- Spec: 2.0.0 → **2.1.0**
- C# VMx: 2.0.x → **2.1.0**
- C# VMx.Notifications: 1.0.0 → **1.1.0**
- Python vmx: 2.0.x → **2.1.0**
- TypeScript vmx: 2.0.x → **2.1.0**

Purely additive — no breaking changes.

### Audit cycle
6 stages, each closed via 2 consecutive zero-finding multi-agent audits (strict-clean-pass-gate).

### Test plan
- [x] `dotnet test` clean
- [x] `uv run pytest` clean
- [x] `npm test` clean
- [x] `dotnet format --verify-no-changes` clean
- [x] `uv run mypy --strict src/vmx` clean
- [x] `uv run ruff check && uv run ruff format --check` clean
- [x] `npm run typecheck && npm run lint` clean
- [x] `tools/check-conformance-coverage.py --require csharp --require python --require typescript`: 219/219 × 3
- [x] All commits clean of AI attribution

### Plan + proposal
- Audit proposal: `spec/proposals/2026-05-27-vmx-absorption-audit.md`
- Master implementation plan: `docs/superpowers/plans/2026-05-27-vmx-absorption-audit.md`
- Per-stage detailed plans: `docs/superpowers/plans/2026-05-28-vmx-absorption-stage-{2..6}-*.md`
EOF
```

- [ ] **Step 2: Create the PR.**

```bash
gh pr create \
    --title "feat(v2.1): absorb 15 post-v2.0 candidates" \
    --body-file /tmp/pr-body.md \
    --base main \
    --head feat/v2.1-absorption-audit
```

- [ ] **Step 3: Verify the PR was created** and return the URL to the user.

```bash
gh pr view --json url --jq .url
```

- [ ] **Step 4: DO NOT MERGE.** Report the PR URL to the user; await their explicit "merge it" instruction.

### Task 6E.4: Tick Substage 6E

- [ ] Commit `docs(plan): tick Substage 6E — PR created, awaiting user review/merge`. Push the tick commit so the PR shows it.

```bash
git push
```

______________________________________________________________________

## Self-review checklist

1. **Version bumps**: spec/VERSION + all 4 flavor package files. ✓ (Tasks 6A.1-6A.4)
1. **Independent versioning for VMx.Notifications** per ADR-0013. ✓ (Task 6A.2)
1. **Compatibility matrix updated**. ✓ (Task 6B.1)
1. **spec/README, spec/00-overview, spec/01-concepts refreshed**. ✓ (Tasks 6B.2-6B.4)
1. **ADR registry complete (0001-0033)**. ✓ (Task 6B.5)
1. **Diagrams cross-checked**. ✓ (Task 6B.6)
1. **CHANGELOG entry**. ✓ (Substage 6C)
1. **Final audit 2 consecutive zero-finding passes**. ✓ (Substage 6D)
1. **PR created without merging**. ✓ (Task 6E.3 + explicit DO NOT MERGE note)
1. **No AI attribution on any commit**. ✓ (verify-step on every commit)
1. **No placeholders**. ✓ (every step has concrete command/code)
