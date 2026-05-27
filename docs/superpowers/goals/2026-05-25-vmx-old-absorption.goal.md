# Goal — Absorb VMx.old into current VMx (v2.0.0)

**Created:** 2026-05-25
**Design doc:** [`docs/superpowers/specs/2026-05-25-vmx-old-absorption-design.md`](../specs/2026-05-25-vmx-old-absorption-design.md)
**Branch:** `feat/absorb-vmx-old`
**Resume rule:** On each `/goal` invocation, evaluate every condition in order. For any unmet condition, do the next concrete piece of work toward meeting it (do not skip ahead). Stop only when every condition in §2 and §3 is `MET`.

______________________________________________________________________

## 1. Objective

Bring forward every conceptual gap from the 2012 C# Silverlight VMx predecessor at `/Users/kaveh/repos/VMx.old/` into the current multi-flavor spec, plus three best-effort curiosities, while preserving every architectural invariant already settled by ADRs 0001-0009. Execute as 12 sequential mini-cycles on `feat/absorb-vmx-old`, with strict 3-flavor parity, all-additive APIs, and per-cycle 3-agent audits. Land as `spec/VERSION 2.0.0` + all flavors at `2.0.0` in a single final merge to `main`.

______________________________________________________________________

## 2. Done Conditions (binary, all must be `MET`)

Each condition is verifiable via the listed command, file check, or count. If a condition is `UNMET`, the next iteration's work is whatever moves it closer to `MET`, following the cycle order in §4.

### 2.1 Branch & workspace

- [ ] **D-01 — Feature branch exists.** `git branch --list feat/absorb-vmx-old` returns a line.
- [ ] **D-02 — All work committed on branch.** Working tree clean on `feat/absorb-vmx-old`: `git status --porcelain` empty.
- [ ] **D-03 — Branch rebased on current `main`.** `git merge-base feat/absorb-vmx-old main` equals `git rev-parse main`.

### 2.2 Spec deltas (chapters)

- [ ] **D-04 — Chapter 14 exists.** `spec/14-capabilities.md` present (Item 1).
- [ ] **D-05 — Chapter 15 exists.** `spec/15-derived-properties.md` present (Item 2).
- [ ] **D-06 — Chapter 16 exists.** `spec/16-notifications.md` present (Item 4).
- [ ] **D-07 — Chapter 17 exists.** `spec/17-localization.md` present (Item 11).
- [ ] **D-08 — Chapter 03 extended** with null-hub variant section (Item 8).
- [ ] **D-09 — Chapter 04 extended** with command-decorators section (Item 3).
- [ ] **D-10 — Chapter 05 extended** with `IExpandable` integration (Item 6).
- [ ] **D-11 — Chapter 06 extended** with search/filter (Item 5) and modeled CRUD (Item 7).
- [ ] **D-12 — Chapter 07 extended** with search/filter (Item 5).
- [ ] **D-13 — Chapter 11 extended** with null-dispatcher section (Item 8).
- [ ] **D-14 — Chapter 13 extended** with expand-aware traversal (Item 6).
- [ ] **D-15 — Proposals directory exists** with HierarchicalVM draft: `spec/proposals/hierarchical-vm.md` present (Item 10).

### 2.3 ADRs (10 new)

- [ ] **D-16 — ADR-0010** `spec/ADRs/0010-capability-micro-interfaces.md` present.
- [ ] **D-17 — ADR-0011** `spec/ADRs/0011-derived-properties.md` present.
- [ ] **D-18 — ADR-0012** `spec/ADRs/0012-command-decorators.md` present.
- [ ] **D-19 — ADR-0013** `spec/ADRs/0013-notification-service.md` present.
- [ ] **D-20 — ADR-0014** `spec/ADRs/0014-search-and-filter.md` present.
- [ ] **D-21 — ADR-0015** `spec/ADRs/0015-expand-collapse-state.md` present.
- [ ] **D-22 — ADR-0016** `spec/ADRs/0016-modeled-crud-commands.md` present.
- [ ] **D-23 — ADR-0017** `spec/ADRs/0017-null-object-services.md` present.
- [ ] **D-24 — ADR-0018** `spec/ADRs/0018-flat-vm-hierarchy-vs-old-chain.md` present.
- [ ] **D-25 — ADR-0019** `spec/ADRs/0019-localization-hooks.md` present.

### 2.4 Conformance catalog (77 new IDs, total 152)

- [ ] **D-26 — `CAP-001..CAP-020` registered** in `spec/12-conformance.md` (20 IDs).
- [ ] **D-27 — `DPROP-001..DPROP-012` registered** (12 IDs).
- [ ] **D-28 — `CMDD-001..CMDD-009` registered** (9 IDs).
- [ ] **D-29 — `NOTIF-001..NOTIF-010` registered** (10 IDs).
- [ ] **D-30 — `COMP-014..COMP-024` registered** (11 IDs, extends existing).
- [ ] **D-31 — `GRP-007..GRP-010` registered** (4 IDs, extends existing).
- [ ] **D-32 — `EXP-001..EXP-005` registered** (5 IDs).
- [ ] **D-33 — `NULL-001..NULL-003` registered** (3 IDs).
- [ ] **D-34 — `LOC-001..LOC-003` registered** (3 IDs).
- [ ] **D-35 — Total conformance ID count is 152** (grep IDs from `spec/12-conformance.md`).

### 2.5 Per-flavor implementations (strict parity)

For each conformance ID in §2.4 there must be a passing test (not just a stub) in **all three** flavors. The coverage tool enforces presence; the test suites enforce passing.

- [ ] **D-36 — C# conformance stubs present** for every new ID (`[Trait("Conformance", "XXX-NNN")]` in `langs/csharp/tests/VMx.Conformance.Tests/`).
- [ ] **D-37 — Python conformance stubs present** for every new ID (`@pytest.mark.conformance("XXX-NNN")` in `langs/python/tests/conformance/`).
- [ ] **D-38 — TypeScript conformance stubs present** for every new ID (`describe("XXX-NNN", ...)` in `langs/typescript/tests/conformance/`).
- [ ] **D-39 — `tools/check-conformance-coverage.py --require csharp --require python --require typescript`** exits 0.
- [ ] **D-40 — All C# tests pass.** `cd langs/csharp && dotnet test` exits 0 with 75 prior + new conformance tests all green.
- [ ] **D-41 — All Python tests pass.** `cd langs/python && uv run pytest` exits 0 with 75 prior + new conformance tests all green.
- [ ] **D-42 — All TypeScript tests pass.** `cd langs/typescript && npm test` exits 0 with 75 prior + new conformance tests all green.

### 2.6 Sub-packages (notifications, Item 4)

- [ ] **D-43 — C# notifications assembly exists.** `langs/csharp/src/VMx.Notifications/VMx.Notifications.csproj` present; package version `1.0.0`; declares dep on `VMx`.
- [ ] **D-44 — Python notifications subpackage exists.** `langs/python/src/vmx/notifications/__init__.py` present; importable as `from vmx.notifications import ...`.
- [ ] **D-45 — TypeScript notifications subpath export exists.** `langs/typescript/package.json` exports map includes `./notifications`; importable as `import {...} from 'vmx/notifications'`.

### 2.7 Version & compatibility bookkeeping

- [ ] **D-46 — `spec/VERSION`** contains exactly `2.0.0`.
- [ ] **D-47 — C# package `VMx`** declares `<Version>2.0.0</Version>` and `MinSpecVersion = "2.0.0"`.
- [ ] **D-48 — Python package `vmx`** declares `version = "2.0.0"` in `pyproject.toml` and `__min_spec_version__ = "2.0.0"`.
- [ ] **D-49 — TypeScript package `vmx`** declares `"version": "2.0.0"` in `package.json` and `__minSpecVersion__ = "2.0.0"`.
- [ ] **D-50 — `compatibility-matrix.md`** has a row for `spec 2.0.0 ↔ VMx 2.0.0 (C#) ↔ vmx 2.0.0 (Python) ↔ vmx 2.0.0 (TS)`.

### 2.8 Final integration

- [ ] **D-51 — Cross-cutting finale audit punchlist closed** (audit run #12 reports Critical: 0, Important: 0; Minor either fixed or explicitly deferred with a tracking note in the branch's CHANGELOG or audit log).
- [ ] **D-52 — Branch merged to `main`** via fast-forward or merge commit; `git log main --oneline | head -1` includes the absorption commit.

______________________________________________________________________

## 3. Quality Assurance (binary, all must be `MET`)

These run alongside §2 and must hold for the goal to be considered done.

### 3.1 Non-regression invariants

- [ ] **QA-01 — All prior 75 conformance IDs still pass** in all three flavors (no regressions).
- [ ] **QA-02 — No breaking changes to v1.x public APIs.** Sanity check: any consumer using `ComponentVM`, `CompositeVM`, `GroupVM`, `AggregateVM1..5`, `RelayCommand`, `IMessageHub`, `IDispatcher` against v1.x continues to compile / type-check against v2.0.0 without source modification (modulo `using`/import path changes for opt-in new types).
- [ ] **QA-03 — No service locator introduced.** Search: `grep -RE "ServiceLocator|GetService\(|Resolve<" langs/` shows no new occurrences beyond existing baseline.
- [ ] **QA-04 — No new event channels.** Every new event surface flows through `IMessageHub` / `MessageHub` / `messageHub`; grep confirms no parallel pub/sub primitive added.

### 3.2 Per-cycle audit gates (12 total)

- [ ] **QA-05 — Cycle 1 audit closed** (Item 1 — capabilities).
- [ ] **QA-06 — Cycle 2 audit closed** (Item 8 — null-object).
- [ ] **QA-07 — Cycle 3 audit closed** (Item 2 — derived properties).
- [ ] **QA-08 — Cycle 4 audit closed** (Item 3 — command decorators).
- [ ] **QA-09 — Cycle 5 audit closed** (Item 4 — notifications).
- [ ] **QA-10 — Cycle 6 audit closed** (Item 6 — expand/collapse).
- [ ] **QA-11 — Cycle 7 audit closed** (Item 5 — search/filter).
- [ ] **QA-12 — Cycle 8 audit closed** (Item 7 — modeled CRUD).
- [ ] **QA-13 — Cycle 9 audit closed** (Item 11 — localization).
- [ ] **QA-14 — Cycle 10 audit closed** (Item 9 — inheritance philosophy ADR).
- [ ] **QA-15 — Cycle 11 audit closed** (Item 10 — HierarchicalVM proposal).
- [ ] **QA-16 — Cycle 12 cross-cutting audit closed** (finale).

Each per-cycle audit consists of 3 parallel review agents (spec / cross-flavor / code-quality) producing a single consolidated Critical/Important/Minor punchlist. "Closed" means Critical = 0 and Important = 0.

### 3.3 Lint, format, type-checking

- [ ] **QA-17 — C# format clean.** `cd langs/csharp && dotnet format --verify-no-changes` exits 0.
- [ ] **QA-18 — C# treat-warnings-as-errors holds.** Full build green with no warnings.
- [ ] **QA-19 — Python lint clean.** `cd langs/python && uv run ruff check && uv run ruff format --check` exits 0.
- [ ] **QA-20 — Python type-check strict.** `cd langs/python && uv run mypy --strict src/vmx` exits 0.
- [ ] **QA-21 — TypeScript lint clean.** `cd langs/typescript && npm run lint` exits 0.
- [ ] **QA-22 — TypeScript type-check clean.** `cd langs/typescript && npm run typecheck` exits 0.
- [ ] **QA-23 — TypeScript build clean.** `cd langs/typescript && npm run build` exits 0 (dual ESM + CJS).

### 3.4 Spec discipline (CI gates)

- [ ] **QA-24 — Spec-discipline workflow green** on the latest `feat/absorb-vmx-old` commit (every spec change has a matching ADR; every new conformance ID has stubs in all 3 flavors).
- [ ] **QA-25 — `tools/check-conformance-coverage.py`** reports 100% coverage across all three flavors for all 152 IDs.
- [ ] **QA-26 — `tools/tests/`** (the coverage tool's own unit tests) pass: `uv --project langs/python run pytest tools/tests/` exits 0.

### 3.5 Pre-commit hygiene

- [ ] **QA-27 — Pre-commit clean.** `pre-commit run --all-files` exits 0 (mdformat / ruff / dotnet format / whitespace / EOL).

______________________________________________________________________

## 4. Cycle ordering (the work plan)

The 12 cycles are executed sequentially; the next iteration of `/goal` advances the earliest unmet cycle. Each cycle is the 8-step mini-cycle from §4.2 of the design doc.

| Cycle | Item                                    | Unmet-cycle marker (the "next thing to do")                                                                 |
| ----- | --------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| 1     | Item 1 — Capability micro-interfaces    | D-04, D-16, D-26, D-36..D-38 for `CAP-*`, QA-05                                                             |
| 2     | Item 8 — Null-object service convention | D-08, D-13, D-23, D-33, D-36..D-38 for `NULL-*`, QA-06                                                      |
| 3     | Item 2 — Derived properties             | D-05, D-17, D-27, D-36..D-38 for `DPROP-*`, QA-07                                                           |
| 4     | Item 3 — Command decorators             | D-09, D-18, D-28, D-36..D-38 for `CMDD-*`, QA-08                                                            |
| 5     | Item 4 — Notification sub-package       | D-06, D-19, D-29, D-43..D-45, D-36..D-38 for `NOTIF-*`, QA-09                                               |
| 6     | Item 6 — Expand/collapse                | D-10, D-14, D-21, D-32, D-36..D-38 for `EXP-*`, QA-10                                                       |
| 7     | Item 5 — Search/filter                  | D-11 (search portion), D-12, D-20, D-30 (014..018), D-31, D-36..D-38 for `COMP-014..018` and `GRP-*`, QA-11 |
| 8     | Item 7 — Modeled CRUD                   | D-11 (CRUD portion), D-22, D-30 (019..024), D-36..D-38 for `COMP-019..024`, QA-12                           |
| 9     | Item 11 — Localization                  | D-07, D-25, D-34, D-36..D-38 for `LOC-*`, QA-13                                                             |
| 10    | Item 9 — Inheritance philosophy ADR     | D-24, QA-14 (no code; ADR-only)                                                                             |
| 11    | Item 10 — HierarchicalVM proposal       | D-15, QA-15 (proposal doc only)                                                                             |
| 12    | Cross-cutting finale                    | D-03, D-35, D-46..D-50, D-51, D-52, QA-01..QA-04, QA-16, QA-17..QA-27                                       |

______________________________________________________________________

## 5. `/goal` evaluation protocol

On each invocation:

1. **Check branch context.** Ensure on `feat/absorb-vmx-old`. If not, switch.
1. **Walk §2 and §3 in order.** For each condition, run its verification (file existence, command exit code, count, grep). Mark each as `MET` or `UNMET`.
1. **Report status.** Output a compact summary: total met / total unmet, plus the first 3 unmet items with their cycle.
1. **Identify the next concrete piece of work.** The first unmet condition (by document order) determines which cycle is active. Within that cycle, take the next step of the 8-step mini-cycle from the design doc §4.2.
1. **Execute the next piece.** If it's a "land code" step (5/6/7), dispatch parallel C#/Py/TS subagents per the design. If it's an audit step (8), dispatch the 3-agent audit.
1. **Stop and report.** Either when every condition is `MET` (goal complete — propose merge to `main` if D-52 unmet) or when blocked (e.g., audit punchlist requires user decision).

**The goal is "done" only when every checkbox in §2 and §3 is `MET`.** No partial credit.

______________________________________________________________________

## 6. Out of scope (explicit non-goals)

To prevent scope creep on re-invocations:

- Re-litigating ADRs 0001-0009 (already settled).
- Restructuring TypeScript into an npm workspace.
- Shipping notifications as separate distributions for Python/TS (hybrid sub-package shape is intentional).
- Implementing the HierarchicalViewModel (only the proposal doc; full design is a separate future goal).
- Localized string content (only the i18n hook contract + null-default localizer; actual translations are out).
- Hard-capping derived properties at 5 sources (spec requires ≥5; implementations may exceed).
- Adding any new service via service locator pattern (constructor injection only).

______________________________________________________________________

## 7. References

- **Design doc:** [`docs/superpowers/specs/2026-05-25-vmx-old-absorption-design.md`](../specs/2026-05-25-vmx-old-absorption-design.md) — full rationale, dependency graph, risks.
- **CLAUDE.md** — repo-wide invariants (spec discipline, parity rule, build commands).
- **Source archive:** `/Users/kaveh/repos/VMx.old/` (read-only; do not modify).
