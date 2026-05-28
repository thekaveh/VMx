# VMx Absorption Audit — Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt the 15 candidates from `spec/proposals/2026-05-27-vmx-absorption-audit.md` into the VMx spec and all three flavors (C#, Python, TypeScript), bringing the spec to version 2.1.0.

**Architecture:** Six sequential stages on one long-running feature branch (`feat/v2.1-absorption-audit`). Each stage is its own internally-cohesive unit of work that ends with a multi-agent audit pass before the next stage begins. The branch does not merge to `main` until Stage 6 (release) completes.

**Tech Stack:** Markdown (spec, ADRs, proposals); C# (.NET) with `System.Reactive` and xUnit + `[Trait("Conformance", ...)]`; Python with `reactivex`, hatchling, pytest, mypy strict, ruff; TypeScript with `rxjs`, tsup, vitest, eslint; pre-commit with mdformat (pinned 0.7.x), ruff, dotnet format; `tools/check-conformance-coverage.py` for cross-flavor coverage enforcement.

______________________________________________________________________

## Plan structure

This is a master plan covering 6 stages. **Stage 1 is fully decomposed** into bite-sized TDD tasks because it executes immediately. **Stages 2–6 are artifact-level outlines** — each will be expanded into its own detailed plan via the `superpowers:writing-plans` skill at the start of that stage. This avoids one 5000-line monolith that goes stale before half of it is reached, and lets later stages benefit from lessons learned in earlier ones.

Each stage ends with an inter-stage audit (see §[Inter-stage audit protocol](#inter-stage-audit-protocol)). The branch only advances when the audit returns the required number of consecutive zero-finding passes (per user's strict-clean-pass-gate preference).

Source proposal: `spec/proposals/2026-05-27-vmx-absorption-audit.md` (commit `18bae00`).

## Repository conventions (subagent quick-reference)

A subagent picking this up cold must follow these:

- **Source of truth:** `spec/` is the contract. Behavior changes start in spec/ chapters, get an ADR, get a conformance ID, and only then land in flavor code.
- **CI gates on every spec change:**
  - Any change under `spec/` (except `README.md`, `VERSION`, `ADRs/**`, `fixtures/**`, `12-conformance.md`) requires a new ADR in the same PR. Apply `no-adr-needed` label only for typos.
  - A new conformance ID requires a matching test stub in every active flavor in the same PR. Recognized stub patterns: Python `@pytest.mark.conformance("XXX-NNN")`, C# `[Trait("Conformance", "XXX-NNN")]`, TS `describe("XXX-NNN", ...)`.
- **Pre-commit** runs ruff, mdformat, dotnet format, eslint. mdformat WILL reformat markdown — re-stage and re-commit after the first failure (never `--amend`).
- **Idiomatic per flavor (ADR-0006):** C# PascalCase, Python snake_case, TS camelCase. Same conceptual shape, idiomatic surface.
- **No AI attribution in commits** (user preference): never add a `Co-Authored-By: Claude...` trailer. Verify each commit with `git log -1 --format='%B'` after committing.
- **Per-flavor commands:**
  - Python: `cd langs/python && uv sync --all-extras && uv run pytest && uv run ruff check && uv run mypy --strict src/vmx`
  - C#: `cd langs/csharp && dotnet restore && dotnet build && dotnet test && dotnet format --verify-no-changes`
  - TypeScript: `cd langs/typescript && npm ci && npm run sync-fixtures && npm run typecheck && npm run lint && npm run build && npm test`
  - Coverage: `uv --project langs/python run python tools/check-conformance-coverage.py --require csharp --require python --require typescript`
- **Commits:** small and frequent (per stage TDD cycles); commit messages follow the existing `type(scope): subject` style seen in `git log`.
- **Disambiguation note:** `langs/<flavor>/.../capabilities/Dialog.*` already exists as a *capability* interface (a VM-side participant contract). The new `IDialogService` from this audit (item C2) is a *host-side service* contract — distinct and must not be conflated. Stage 3 starts by confirming the existing Dialog capability semantics before naming the new service.

## Inter-stage audit protocol

At the end of each stage, before declaring the stage complete:

1. Run all three flavor test suites + the conformance coverage tool. All must pass.
1. Dispatch a multi-agent parallel audit (one agent per flavor + one for spec/docs) returning Critical/Important/Minor findings.
1. Address every Critical and Important finding (Minor at discretion). Each fix is a new commit.
1. Re-run the multi-agent audit. Must return a zero-finding pass.
1. Per user's strict-clean-pass-gate: require **2 consecutive zero-finding passes** before stage advancement. An agent miss between passes resets the counter (own-spot-check between agent runs).
1. Update the master plan's "stage X complete" checkbox below.

______________________________________________________________________

## Stage progress tracker

- [x] **Stage 0** — Pre-work and decisions
- [x] **Stage 1** — Foundations: capabilities (I5 `IFilterable`, IPageable), collections chapter (I2, I3, I4), paging (C3), fluent command extensions (I1)
- [x] **Stage 2** — `HierarchicalVM` (C1)
- [x] **Stage 3** — Forms & Dialogs (C4 `FormVM`, C2 `IDialogService`)
- [ ] **Stage 4** — Notification rendering VMs (C5, I6)
- [ ] **Stage 5** — Minors (M1, M2, M3, M4)
- [ ] **Stage 6** — Release (version bumps, docs, compatibility matrix, final audit, merge to main)

______________________________________________________________________

# Stage 0 — Pre-work and decisions

Two decisions and one verification block the rest of the plan. Resolve all three before Stage 1 begins.

### Task 0.1: Resolve paging chapter-vs-section question

**Files:**

- Modify: `spec/proposals/2026-05-27-vmx-absorption-audit.md`

- Modify: this plan file (sync the decision)

- [x] **Step 1: Make the call.**

**Decision (made):** Paging (C3) lands as a section inside `21-collections.md` (not a standalone chapter). Rationale: paging is a collection-view behavior; conceptually cohesive with `ServicedObservableCollection`, `ObservableList`, multi-key `ObservableDictionary`; reduces chapter sprawl. The four new chapters are: 18-hierarchical-vm, 19-dialogs, 20-form-vm, 21-collections.

- [x] **Step 2: Record the decision.**

Edit `spec/proposals/2026-05-27-vmx-absorption-audit.md` §3, §5 (C3), §6 (I2), §9 to reflect: paging is a section in the new collections chapter; new chapters are 18-hierarchical-vm, 19-dialogs, 20-form-vm, 21-collections (four, not five).

- [x] **Step 3: Sync this plan.**

Update §"Stage progress tracker" and stage outlines below to say "4 new chapters" instead of "5".

- [x] **Step 4: Commit.**

```bash
git add spec/proposals/2026-05-27-vmx-absorption-audit.md docs/superpowers/plans/2026-05-27-vmx-absorption-audit.md
git commit -m "docs(proposal): fold paging into collections chapter (Stage 0 decision)"
git log -1 --format='%B' | grep -i 'co-authored-by' && echo "BUG: AI attribution present" || echo "clean"
```

### Task 0.2: Resolve spec version target (2.1.0 vs 3.0.0)

**Files:**

- Modify: `spec/proposals/2026-05-27-vmx-absorption-audit.md` §10

- Modify: this plan file (header references)

- [x] **Step 1: Make the call.**

Recommended: **2.1.0**. The change is purely additive (no removed/renamed contracts). 3.0.0 is defensible only as a marketing-the-size signal. Going with 2.1.0 keeps the SemVer policy clean and matches the spec README's stated rule.

- [x] **Step 2: Lock the decision.**

Edit proposal §10 to remove the alternative-discussed framing and state 2.1.0 as the target. Per-flavor versions: each flavor moves to its own 2.1.0 (matching the lockstep convention used through v2.0).

- [x] **Step 3: Commit.**

```bash
git add spec/proposals/2026-05-27-vmx-absorption-audit.md
git commit -m "docs(proposal): lock spec target to 2.1.0 (Stage 0 decision)"
git log -1 --format='%B' | grep -i 'co-authored-by' && echo "BUG" || echo "clean"
```

### Task 0.3: Disambiguate the existing `Dialog` capability

**Files:**

- Read: `langs/csharp/src/VMx/Capabilities/Dialog.cs`

- Read: `langs/python/src/vmx/capabilities/dialog.py`

- Read: `langs/typescript/src/capabilities/dialog.ts`

- Read: relevant section of `spec/14-capabilities.md` (find "Dialog" group)

- Modify: this plan file (Stage 3 outline) to record the disambiguation

- [x] **Step 1: Read the existing Dialog capability in all three flavors.**

```bash
sed -n '1,80p' langs/csharp/src/VMx/Capabilities/Dialog.cs
sed -n '1,80p' langs/python/src/vmx/capabilities/dialog.py
sed -n '1,80p' langs/typescript/src/capabilities/dialog.ts
grep -n -A 20 'Dialog' spec/14-capabilities.md
```

- [x] **Step 2: Record what it actually is.**

Append a paragraph to this plan's Stage 3 outline (below) stating: existing `Dialog` capability is a VM-side participant contract for X (whatever X turns out to be); the new `IDialogService` (C2) is a host-side modal-interaction service — distinct names, distinct files, no conflict. If they DO conflict, escalate before proceeding.

- [x] **Step 3: Commit.**

```bash
git add docs/superpowers/plans/2026-05-27-vmx-absorption-audit.md
git commit -m "docs(plan): record disambiguation between Dialog capability and IDialogService"
git log -1 --format='%B' | grep -i 'co-authored-by' && echo "BUG" || echo "clean"
```

______________________________________________________________________

# Stage 1 — Foundations

**Stage goal:** Land the easy, high-leverage items that lay groundwork for later stages.

**Items in this stage:**

- **I5** — `IFilterable<T>` capability (extends `14-capabilities.md`)
- **C3** — Paging: `IPageable` capability + `PagedComposition` helper (section in new collections chapter per Stage 0 decision)
- **I2** — `ServicedObservableCollection<T>` (hub-aware collection)
- **I3** — Multi-key `ObservableDictionary` (composite-key)
- **I4** — `ObservableList<T>` (granular collection notifications)
- **I1** — Fluent command extensions

**New chapter introduced:** `21-collections.md` (per Stage 0 decision)

**New ADRs introduced:** 0022 (IFilterable), 0023 (paging), 0024 (hub-aware collection), 0025 (multi-key dict), 0026 (granular list), 0027 (fluent commands)

**New conformance ID prefixes:** `COL-` (collections — I2 + I3 + I4 + paging C3); `CAP-` extensions for `CAP-021` (IFilterable) and `CAP-022` (IPageable); `CMD-` extensions for fluent commands.

**Estimated stage size:** ~60 bite-sized tasks across 6 substages.

### Substage 1A — Capability additions (I5 + IPageable)

Smallest, lowest-risk. Establishes the pattern for the rest of the stage.

#### Task 1A.1: Write ADR-0022 for `IFilterable<T>`

**Files:**

- Create: `spec/ADRs/0022-filterable-capability.md`

- Modify: `spec/ADRs/README.md` (register the new ADR)

- [x] **Step 1: Write the ADR.**

Create `spec/ADRs/0022-filterable-capability.md` with the standard 4-section template (Context, Options, Decision, Consequences). Content sketch:

```markdown
# ADR 0022 — `IFilterable<T>` capability

**Status:** Accepted (2026-05-27)
**Spec version:** introduced in 2.1.0

## 1. Context

`SearchableState<TItem>` (per ADR-0014) gives consumers a debounced search-string
filter with a consumer-supplied predicate builder. The underlying capability —
"this collection/composition can be filtered by an arbitrary predicate" — is
implicit, not surfaced. GuideArch and its predecessor both invented their own
predicate-based filter contract (`IFilterable<T>` in
`GuideArch.Old/VMx/Contract/Receivers.cs:228-239`) and used it in places that
were not search-string-shaped.

## 2. Options considered

1. **Skip — keep `SearchableState` as the only filter primitive.** Consumers
   who want a predicate-only filter wrap a no-op search term. Awkward.
2. **Add `IFilterable<T>` as a 21st capability.** Surface the predicate
   directly. `SearchableState<TItem>` is reframed as a predicate-builder over the
   capability — no breaking change to its surface.
3. **Add a standalone `IPredicateFilter<T>` distinct from capabilities.**
   Avoids growing the capability set. Inconsistent with ADR-0010.

## 3. Decision

Option 2. `IFilterable<T>` joins the capability set as the 21st member with
two members: `Filter: Predicate<T>?` (null means no filter) and
`CanFilter() : bool`.

## 4. Consequences

- `spec/14-capabilities.md` adds a new 2.x subsection.
- One new conformance ID `CAP-021` covers the capability's contract surface.
- Each flavor's `capabilities/` directory adds an `IFilterable<T>` interface
  declaration (no implementation; capabilities are opt-in per ADR-0010).
- `SearchableState<TItem>`'s public surface does not change; an internal cycle
  may refactor it to implement `IFilterable<T>` in a future minor version.
```

- [x] **Step 2: Register the ADR.**

Edit `spec/ADRs/README.md` to add `0022-filterable-capability.md` to the registry.

- [x] **Step 3: Verify pre-commit passes locally.**

```bash
git add spec/ADRs/0022-filterable-capability.md spec/ADRs/README.md
git diff --cached --check
```

- [x] **Step 4: Commit.**

```bash
git commit -m "spec(adr): add ADR-0022 IFilterable<T> capability"
git log -1 --format='%B' | grep -i 'co-authored-by' && echo "BUG" || echo "clean"
```

If mdformat reformats: re-stage, re-commit (do NOT --amend).

#### Task 1A.2: Add `IFilterable<T>` to `spec/14-capabilities.md`

**Files:**

- Modify: `spec/14-capabilities.md` (add subsection 2.x)

- [x] **Step 1: Find the insertion point.**

```bash
grep -n '^## 2\.' spec/14-capabilities.md
grep -n '^### 2\.' spec/14-capabilities.md
```

- [x] **Step 2: Insert a new subsection at an appropriate spot** (likely after the search-related capabilities subsection).

```markdown
### 2.X Filter capability

```

IFilterable<T>:
Filter : Predicate<T>? # null means no filter; setter triggers re-filter
can_filter() : bool # whether filtering is currently allowed

```

The capability says nothing about *how* the filtered view is exposed (an
observable, a paged slice, a snapshot) — that is the concrete collection's
responsibility. `SearchableState<T>` (cycle 7) provides a string-debounced
predicate builder over this capability.

See ADR-0022.
```

- [x] **Step 3: Update the chapter intro to say "21 capability interfaces" instead of 20.**

```bash
grep -n '20 capability' spec/14-capabilities.md
```

Replace each occurrence with "21" (in §1 and any other counts).

- [x] **Step 4: Commit.**

```bash
git add spec/14-capabilities.md
git commit -m "spec(cap): add IFilterable<T> as 21st capability"
git log -1 --format='%B' | grep -i 'co-authored-by' && echo "BUG" || echo "clean"
```

#### Task 1A.3: Add `CAP-021` conformance ID

**Files:**

- Modify: `spec/12-conformance.md`

- [x] **Step 1: Find the `CAP-` block in the conformance catalog.**

```bash
grep -n '^### CAP' spec/12-conformance.md
grep -n 'CAP-020' spec/12-conformance.md
```

- [x] **Step 2: Add `CAP-021` immediately after `CAP-020`** with text:

```markdown
- `CAP-021` — `IFilterable<T>` capability contract surface and opt-in behavior.
  A VM that implements `IFilterable<T>` exposes a settable `Filter` predicate
  and a `can_filter()` decision; setting `Filter` to null clears the filter.
  Verified per flavor with a minimal `CompositeVM` wrapper that opts in.
```

- [x] **Step 3: Commit.**

```bash
git add spec/12-conformance.md
git commit -m "spec(conf): add CAP-021 conformance ID for IFilterable<T>"
```

#### Task 1A.4: Add `CAP-021` stub in each flavor (CI rule)

**Files:**

- Create: `langs/csharp/tests/conformance/CAP_021_Filterable_Tests.cs`

- Create: `langs/python/tests/conformance/test_cap_021_filterable.py`

- Create: `langs/typescript/tests/conformance/cap-021-filterable.test.ts`

- [x] **Step 1: Look at an existing CAP- stub in each flavor to copy the pattern.**

```bash
find langs/csharp/tests/conformance -name 'CAP_020*' -exec cat {} \;
find langs/python/tests/conformance -name 'test_cap_020*' -exec cat {} \;
find langs/typescript/tests/conformance -name 'cap-020*' -exec cat {} \;
```

- [x] **Step 2: Create the C# stub** mirroring the existing CAP-020 file structure (xUnit class + `[Trait("Conformance", "CAP-021")]`, single test method that throws `NotImplementedException` or asserts `Assert.True(false, "not yet implemented")`).

- [x] **Step 3: Create the Python stub** with `@pytest.mark.conformance("CAP-021")` and an `xfail` or `pytest.skip("not yet implemented")` body.

- [x] **Step 4: Create the TypeScript stub** with `describe("CAP-021", ...)` and a single `it.todo("verify IFilterable contract surface")`.

- [x] **Step 5: Run conformance coverage tool to verify CI rule passes.**

```bash
uv --project langs/python run python tools/check-conformance-coverage.py --require csharp --require python --require typescript
```

Expected: exits 0 (no missing IDs in any flavor).

- [x] **Step 6: Commit.**

```bash
git add langs/csharp/tests/conformance/CAP_021_Filterable_Tests.cs langs/python/tests/conformance/test_cap_021_filterable.py langs/typescript/tests/conformance/cap-021-filterable.test.ts
git commit -m "test(conf): add CAP-021 stubs in all three flavors"
```

#### Task 1A.5: Implement `IFilterable<T>` in C# (TDD)

**Files:**

- Create: `langs/csharp/src/VMx/Capabilities/Filter.cs`

- Modify: `langs/csharp/tests/conformance/CAP_021_Filterable_Tests.cs` (turn stub into real test)

- [x] **Step 1: Write the failing real conformance test.**

Replace the stub body with a real test that constructs a minimal opt-in implementer and verifies `Filter` getter/setter and `CanFilter()`.

```csharp
[Fact]
[Trait("Conformance", "CAP-021")]
public void Filterable_Contract_Surface()
{
    var sut = new TestFilterable<int>();
    Assert.Null(sut.Filter);
    Assert.True(sut.CanFilter());

    Predicate<int> p = x => x > 0;
    sut.Filter = p;
    Assert.Same(p, sut.Filter);

    sut.Filter = null;
    Assert.Null(sut.Filter);
}

private sealed class TestFilterable<T> : IFilterable<T>
{
    public Predicate<T>? Filter { get; set; }
    public bool CanFilter() => true;
}
```

- [x] **Step 2: Run the test to verify it fails.**

```bash
cd langs/csharp && dotnet test --filter "Conformance=CAP-021"
```

Expected: FAIL (interface IFilterable<T> does not exist).

- [x] **Step 3: Create the interface.**

`langs/csharp/src/VMx/Capabilities/Filter.cs`:

```csharp
namespace VMx.Capabilities;

public interface IFilterable<T>
{
    System.Predicate<T>? Filter { get; set; }
    bool CanFilter();
}
```

- [x] **Step 4: Run the test to verify it passes.**

```bash
cd langs/csharp && dotnet test --filter "Conformance=CAP-021"
```

Expected: PASS.

- [x] **Step 5: Verify lint.**

```bash
cd langs/csharp && dotnet format --verify-no-changes
```

- [x] **Step 6: Commit.**

```bash
git add langs/csharp/src/VMx/Capabilities/Filter.cs langs/csharp/tests/conformance/CAP_021_Filterable_Tests.cs
git commit -m "feat(csharp,cap): implement IFilterable<T> (CAP-021)"
```

#### Task 1A.6: Implement `IFilterable<T>` in Python (TDD)

**Files:**

- Create: `langs/python/src/vmx/capabilities/filter.py`

- Modify: `langs/python/src/vmx/capabilities/__init__.py` (export)

- Modify: `langs/python/tests/conformance/test_cap_021_filterable.py` (real test)

- [x] **Step 1: Replace the stub with the real failing test.**

```python
import pytest
from typing import Callable, TypeVar, Optional

T = TypeVar("T")


@pytest.mark.conformance("CAP-021")
def test_filterable_contract_surface() -> None:
    from vmx.capabilities import Filterable

    class TestFilterable(Filterable[int]):
        def __init__(self) -> None:
            self._filter: Optional[Callable[[int], bool]] = None

        @property
        def filter(self) -> Optional[Callable[[int], bool]]:
            return self._filter

        @filter.setter
        def filter(self, value: Optional[Callable[[int], bool]]) -> None:
            self._filter = value

        def can_filter(self) -> bool:
            return True

    sut = TestFilterable()
    assert sut.filter is None
    assert sut.can_filter() is True

    p: Callable[[int], bool] = lambda x: x > 0
    sut.filter = p
    assert sut.filter is p

    sut.filter = None
    assert sut.filter is None
```

- [x] **Step 2: Run the test, verify failure.**

```bash
cd langs/python && uv run pytest tests/conformance/test_cap_021_filterable.py -v
```

Expected: FAIL with import error or `Filterable` not found.

- [x] **Step 3: Create the protocol.**

`langs/python/src/vmx/capabilities/filter.py`:

```python
"""IFilterable capability (CAP-021, ADR-0022)."""
from __future__ import annotations

from typing import Callable, Optional, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


@runtime_checkable
class Filterable(Protocol[T]):
    """A collection/composition that supports filtering by an arbitrary predicate.

    `filter` is the predicate; None means no filter. `can_filter()` reports
    whether filtering is currently allowed.
    """

    @property
    def filter(self) -> Optional[Callable[[T], bool]]:
        ...

    @filter.setter
    def filter(self, value: Optional[Callable[[T], bool]]) -> None:
        ...

    def can_filter(self) -> bool:
        ...
```

- [x] **Step 4: Export from package init.**

Append to `langs/python/src/vmx/capabilities/__init__.py`:

```python
from vmx.capabilities.filter import Filterable

__all__ = [*__all__, "Filterable"]  # adjust per existing __all__ convention
```

(Inspect the existing `__init__.py` and follow its export pattern exactly.)

- [x] **Step 5: Run the test, verify pass.**

```bash
cd langs/python && uv run pytest tests/conformance/test_cap_021_filterable.py -v
```

- [x] **Step 6: Run mypy strict to verify type safety.**

```bash
cd langs/python && uv run mypy --strict src/vmx
```

Expected: clean.

- [x] **Step 7: Run ruff.**

```bash
cd langs/python && uv run ruff check && uv run ruff format --check
```

- [x] **Step 8: Commit.**

```bash
git add langs/python/src/vmx/capabilities/filter.py langs/python/src/vmx/capabilities/__init__.py langs/python/tests/conformance/test_cap_021_filterable.py
git commit -m "feat(python,cap): implement Filterable (CAP-021)"
```

#### Task 1A.7: Implement `IFilterable<T>` in TypeScript (TDD)

**Files:**

- Create: `langs/typescript/src/capabilities/filter.ts`

- Modify: `langs/typescript/src/capabilities/index.ts` (export)

- Modify: `langs/typescript/tests/conformance/cap-021-filterable.test.ts` (real test)

- [x] **Step 1: Real failing test.**

```typescript
import { describe, it, expect } from "vitest";
import type { Filterable } from "../../src/capabilities";

describe("CAP-021", () => {
  it("Filterable contract surface", () => {
    class TestFilterable<T> implements Filterable<T> {
      filter: ((item: T) => boolean) | null = null;
      canFilter(): boolean { return true; }
    }

    const sut = new TestFilterable<number>();
    expect(sut.filter).toBeNull();
    expect(sut.canFilter()).toBe(true);

    const p = (x: number) => x > 0;
    sut.filter = p;
    expect(sut.filter).toBe(p);

    sut.filter = null;
    expect(sut.filter).toBeNull();
  });
});
```

- [x] **Step 2: Run test, verify failure.**

```bash
cd langs/typescript && npm test -- cap-021
```

Expected: FAIL (no Filterable export).

- [x] **Step 3: Create the interface.**

`langs/typescript/src/capabilities/filter.ts`:

```typescript
/** IFilterable capability (CAP-021, ADR-0022). */
export interface Filterable<T> {
  filter: ((item: T) => boolean) | null;
  canFilter(): boolean;
}
```

- [x] **Step 4: Export from capabilities index.**

Append to `langs/typescript/src/capabilities/index.ts`:

```typescript
export type { Filterable } from "./filter";
```

(Inspect existing index.ts to match its export style — `export *` vs named.)

- [x] **Step 5: Run test, verify pass.**

```bash
cd langs/typescript && npm test -- cap-021
```

- [x] **Step 6: Typecheck + lint.**

```bash
cd langs/typescript && npm run typecheck && npm run lint
```

- [x] **Step 7: Commit.**

```bash
git add langs/typescript/src/capabilities/filter.ts langs/typescript/src/capabilities/index.ts langs/typescript/tests/conformance/cap-021-filterable.test.ts
git commit -m "feat(typescript,cap): implement Filterable (CAP-021)"
```

#### Task 1A.8: Repeat the 1A.1–1A.7 sequence for `IPageable` (CAP-022, ADR-0023)

**Important:** `IPageable` is *part of* the paging item (C3) but its capability-interface portion lands in Stage 1A alongside `IFilterable` because they're both capability additions and the pattern is identical. The `PagedComposition` helper lands in Substage 1C.

ADR-0023 should be written here in scope of the capability portion; expand the ADR in Substage 1C when the helper lands. The recommended approach is one ADR covering both the capability + helper to avoid ADR fragmentation — see ADR-0023 draft below.

Subagent: when expanding this task, mirror tasks 1A.1 through 1A.7 exactly, substituting:

- ADR number: `0023`, title: `paging (IPageable capability + PagedComposition helper)`
- Capability name: `IPageable`
- Conformance ID: `CAP-022`
- Capability members: `PageSize: int`, `CurrentPageIndex: int`, `PageCount: int` (derived), `IsPagingEnabled: bool` (derived), `MoveToFirstPage()`, `MoveToPreviousPage()`, `MoveToNextPage()`, `MoveToLastPage()`
- For ADR-0023 §4 Consequences, note that the helper `PagedComposition<TVM>` will land in Substage 1C and add its own conformance IDs in the `COL-` block.

ADR-0023 draft (write in full):

```markdown
# ADR 0023 — Paging (IPageable capability + PagedComposition helper)

**Status:** Accepted (2026-05-27)
**Spec version:** introduced in 2.1.0

## 1. Context
GuideArch and its predecessor both wrap `PagedCollectionView`-style paging
around compositions. The 2012 VMx predecessor added an `IPageable` interface
to `Contract/Receivers.cs` (lines 241-260). The current VMx has no paging
primitive; `SearchableState<T>` filters but does not page.

## 2. Options considered
1. Skip paging — consumer-owned.
2. Capability-only — add `IPageable` to capabilities, no helper.
3. Capability + helper — add `IPageable` AND a `PagedComposition<TVM>`
   decorator (analogous to `SearchableState` / `ExpandableState`) that wraps
   any `IComposition<TVM>` and exposes a paged view.

## 3. Decision
Option 3. Capability lands in `14-capabilities.md` as CAP-022; helper lands
in `21-collections.md` §"Paging" with conformance IDs in the `COL-` block.

## 4. Consequences
- `spec/14-capabilities.md` adds `IPageable` (capability 22).
- One conformance ID `CAP-022` for the capability surface.
- `spec/21-collections.md` (new chapter in Substage 1B) defines
  `PagedComposition<TVM>` and contributes `COL-NNN` IDs (count finalized in 1C).
- Per-flavor implementation: `IPageable` interface in `capabilities/`;
  `PagedComposition<TVM>` in `collections/` (or per-flavor equivalent).
- Composition with `SearchableState<T>` is well-defined: filter first, then
  page. The chapter §"Composition with other helpers" pins ordering.
```

**Specification-phase progress (equivalent to 1A.1–1A.4):**

- [x] **Step 1: Write ADR-0023.** `spec/ADRs/0023-paging-capability-and-paged-composition.md` created; registered in `spec/ADRs/README.md`.
- [x] **Step 2: Add §2.10 to `spec/14-capabilities.md`.** Count updated to 22; §5 conformance range updated to CAP-001–CAP-022.
- [x] **Step 3: Add CAP-022 to `spec/12-conformance.md`.** Given/When/Then entry added after CAP-021.
- [x] **Step 4: Add CAP-022 stubs in all three flavors.** C# (`CapabilitiesConformanceTests.cs`), Python (`test_cap_022_pageable.py`), TypeScript (`cap-022-pageable.test.ts`). Coverage tool: 154/154 all flavors.

**Implementation-phase steps (equivalent to 1A.5–1A.7 — deferred):**

- [x] **Step 5: Implement `IPageable` in C# (`langs/csharp/src/VMx/Capabilities/`).**
- [x] **Step 6: Implement `IPageable` in Python (`langs/python/src/vmx/capabilities/`).**
- [x] **Step 7: Implement `IPageable` in TypeScript (`langs/typescript/src/capabilities/`).**

### Substage 1B — Collections chapter and ADRs

#### Task 1B.1: Write ADR-0024 (ServicedObservableCollection)

**Files:**

- Create: `spec/ADRs/0024-hub-aware-observable-collection.md`

- Modify: `spec/ADRs/README.md`

- [x] **Step 1:** Write the ADR using the 4-section template. Key decisions to record:

  - Naming: `ServicedObservableCollection<T>` (matches the 2012 name; recognizable to readers of legacy code).
  - Hub publication: in addition to (not instead of) local `CollectionChanged` events.
  - Null-hub behavior: if no hub injected, behaves exactly like `ObservableCollection<T>` (no publication, no errors).
  - Threading: publication happens on the same thread as the mutation (not marshaled).

- [x] **Step 2:** Register in `spec/ADRs/README.md`.

- [x] **Step 3:** Commit.

#### Task 1B.2: Write ADR-0025 (Multi-key ObservableDictionary)

- [x] **Step 1:** Write the ADR. Key decisions:

  - Surface: `ObservableDictionary<TKey1, TKey2, TValue>` as the documented common case, with a `ObservableDictionary<TKey, TValue>` base where `TKey` is a per-flavor tuple type (option 3 from proposal §6).
  - Distinct-key observables: yes (mirror legacy `Keys1`, `Keys2`).
  - Cascading insertion (legacy `Dictionary<K1,K2,V>` auto-creates entries on Key1 add): **no** — too domain-specific; consumers do it explicitly.

- [x] **Step 2:** Register, commit.

#### Task 1B.3: Write ADR-0026 (Granular ObservableList)

- [x] **Step 1:** Write the ADR. Key decisions:

  - Surface: `ObservableList<T>` with per-mutation events (`ItemAdded`, `ItemRemoved`, `ItemReplaced`, `Reset`).
  - Relationship to `INotifyCollectionChanged`: also raises the standard event (compatibility) — flavor-idiomatic where the standard event exists.
  - Interaction with `BatchUpdate()` semantics (defined in `06-composite-vm.md`): inside a batch, only the final `Reset` fires; granular events are suppressed.

- [x] **Step 2:** Register, commit.

#### Task 1B.4: Write `spec/21-collections.md`

**Files:**

- Create: `spec/21-collections.md`

- Modify: `spec/README.md` (add to TOC §1.2)

- [x] **Step 1:** Author the chapter. Sections:

  - §1 — Overview & rationale (why a collections chapter; relationship to ADR-0010 capabilities; relationship to `CompositeVM`'s `BatchUpdate()`)
  - §2 — `ServicedObservableCollection<T>` (per ADR-0024)
  - §3 — `ObservableList<T>` granular events (per ADR-0026)
  - §4 — Multi-key `ObservableDictionary` (per ADR-0025)
  - §5 — Paging: `PagedComposition<TVM>` helper (per ADR-0023)
  - §6 — Composition rules (filter-then-page ordering, batch interaction)

- [x] **Step 2:** Add the chapter to `spec/README.md` §1.3 chapter list (v2.1 additions).

- [x] **Step 3:** Commit.

#### Task 1B.5: Add `COL-NNN` conformance IDs to `spec/12-conformance.md`

Specific IDs (21 total, mapped to the chapter's sections):

- `COL-001..COL-004` — `ServicedObservableCollection` (publish on add/remove/replace/reset; ordering vs local handlers; null-hub no-op; threading non-marshal)

- `COL-005..COL-009` — `ObservableList` (per-event payload shape: add, remove, replace, reset; opt-out of legacy `CollectionChanged` if applicable; batch suppression)

- `COL-010..COL-015` — Multi-key `ObservableDictionary` (insert/remove/replace; distinct-key observable views; enumeration order; hub messages on mutation; null-key behavior; clear)

- `COL-016..COL-021` — `PagedComposition` (clamping; page-count derivation under add/remove; nav no-op at bounds; `PageSize=0` semantics; empty source; composition with `SearchableState`)

- [x] **Step 1:** Add all IDs as a new `### COL-` section in `12-conformance.md` with one-paragraph descriptions each.

- [x] **Step 2:** Commit.

#### Task 1B.6: Add stubs for all 21 `COL-NNN` IDs in all three flavors

This produces 63 new stub test files (21 IDs × 3 flavors). Group by ID prefix in each flavor's tests/conformance directory:

- C#: `langs/csharp/tests/conformance/COL_001_to_004_ServicedObservableCollection_Tests.cs` (grouped per chapter section)
- Python: `langs/python/tests/conformance/test_col_001_to_004_serviced.py`
- TypeScript: `langs/typescript/tests/conformance/col-001-to-004-serviced.test.ts`

Group sub-batches: 001-004 (serviced), 005-009 (granular list), 010-015 (multi-key dict), 016-021 (paged composition). 4 groups × 3 flavors = 12 files (each with 4-6 stubs inside).

- [x] **Step 1:** Create 4 grouped stub files per flavor following each flavor's existing conformance stub idioms.

- [x] **Step 2:** Run conformance coverage tool — 175/175 in each flavor.

- [x] **Step 3:** Commit (one commit per flavor for clarity).

### Substage 1C — Implementation per item, per flavor (TDD)

This substage executes 4 items × 3 flavors = 12 implementation tracks. Each track is its own TDD cycle: turn the stubs into real tests, run, implement, verify, lint, commit.

**Subagent: when expanding this substage into bite-sized tasks, follow the 1A.5–1A.7 pattern for each item-flavor combination.** The 12 tracks:

1. ServicedObservableCollection — C# (`langs/csharp/src/VMx/Collections/ServicedObservableCollection.cs`)
1. ServicedObservableCollection — Python (`langs/python/src/vmx/collections/serviced_observable_collection.py`)
1. ServicedObservableCollection — TypeScript (`langs/typescript/src/collections/servicedObservableCollection.ts`)
1. ObservableList — C# (`langs/csharp/src/VMx/Collections/ObservableList.cs`)
1. ObservableList — Python (`langs/python/src/vmx/collections/observable_list.py`)
1. ObservableList — TypeScript (`langs/typescript/src/collections/observableList.ts`)
1. ✅ Multi-key ObservableDictionary — C# (`langs/csharp/src/VMx/Collections/ObservableDictionary.cs`)
1. ✅ Multi-key ObservableDictionary — Python (`langs/python/src/vmx/collections/observable_dictionary.py`)
1. ✅ Multi-key ObservableDictionary — TypeScript (`langs/typescript/src/collections/observableDictionary.ts`)
1. PagedComposition — C# (`langs/csharp/src/VMx/Collections/PagedComposition.cs`)
1. PagedComposition — Python (`langs/python/src/vmx/collections/paged_composition.py`)
1. PagedComposition — TypeScript (`langs/typescript/src/collections/pagedComposition.ts`)

**Per-flavor directory note:** Python and TypeScript already have `collections/` subpackages (per `CLAUDE.md`). C# does not yet — Substage 1C task 1 also creates `langs/csharp/src/VMx/Collections/` directory and adds it to the csproj.

**Test target per item:**

- Each item gets ≥1 test per conformance ID (so ~16 conformance tests across the substage per flavor).
- Each item additionally gets per-flavor unit tests for edge cases not covered by conformance: empty-collection mutations, concurrent access (where applicable), large-N performance smoke (10k items, asserting O(n) bounds via a coarse timing).
- Target: ~12 unit tests per item per flavor = ~48 unit tests per flavor on top of conformance.

### Substage 1D — Fluent command extensions (I1, ADR-0027)

#### Task 1D.1: Write ADR-0027 (Fluent command extensions)

**Files:**

- Create: `spec/ADRs/0027-fluent-command-extensions.md`

- Modify: `spec/ADRs/README.md`

- [x] **Step 1:** Write the ADR. Key decisions:

  - Methods: `Confirm(prompt)`, `PrecedeWith(other)`, `SucceedWith(other)`, `WrapWith(predicate?, pre?, post?)`.
  - For `Confirm`: the *default* form uses the confirm-delegate shape from ADR-0012 (delegate-shaped, no notification-hub dependency). An *optional* overload takes a notification hub and constructs the delegate from it.
  - Per-flavor idiom: C# extension methods on `ICommand`; Python module-level functions in `vmx.commands.fluent`; TypeScript standalone exports.

- [x] **Step 2:** Register, commit.

#### Task 1D.2: Extend `spec/04-commands.md`

**Files:**

- Modify: `spec/04-commands.md` — add a new §"Fluent composition" subsection.

- [x] **Step 1:** Add the subsection documenting the 4 methods and their equivalence to explicit constructor calls.

- [x] **Step 2:** Commit.

#### Task 1D.3: Add `CMD-NNN` conformance IDs (extend existing CMD- range)

Find next available CMD- ID. Add 4 IDs: `CMD-NNN.Confirm`, `CMD-NNN.Precede`, `CMD-NNN.Succeed`, `CMD-NNN.Wrap` — each asserting "fluent form produces equivalent command graph to explicit constructor".

- [x] **Step 1:** Add to `spec/12-conformance.md`.

- [x] **Step 2:** Commit.

#### Task 1D.4: Stubs in all 3 flavors

- [x] One grouped stub file per flavor with 4 stubs each.

#### Task 1D.5: Implement in each flavor (TDD)

- [x] **C#:** `langs/csharp/src/VMx/Commands/FluentCommandExtensions.cs` +
  `langs/csharp/src/VMx.Notifications/FluentNotificationExtensions.cs`.
  All 199 conformance tests pass; `dotnet format` clean.
- [x] **Python:** `langs/python/src/vmx/commands/fluent.py`. All 601 tests pass;
  `mypy --strict` clean; `ruff` clean.
- [x] **TypeScript:** `langs/typescript/src/commands/fluent.ts`. All 292 tests
  pass; typecheck + lint clean; build succeeds.
- [x] Coverage tool: 179/179 across all three flavors.

Follow 1A.5–1A.7 TDD cycle pattern per flavor.

### Substage 1E — Stage 1 audit and stage close

- [ ] **Step 1:** Run all three flavor test suites + coverage tool. All must pass.
- [ ] **Step 2:** Dispatch multi-agent parallel audit (one Explore agent per flavor + one for spec/docs).
- [ ] **Step 3:** Address Critical + Important findings; recommit.
- [ ] **Step 4:** Re-audit. Must return zero findings.
- [ ] **Step 5:** Run audit a second time (consecutive zero-finding pass requirement). Must return zero findings.
- [ ] **Step 6:** Check the Stage 1 box in the stage progress tracker above; commit the plan-file update.
- [ ] **Step 7:** Spawn the Stage 2 detailed plan via `superpowers:writing-plans` skill (input: this plan's Stage 2 outline below + the proposal doc's C1 entry).

______________________________________________________________________

# Stage 2 — `HierarchicalVM` (C1)

**Outline only.** Detailed bite-sized plan to be authored via `superpowers:writing-plans` at the start of this stage.

**Items:** C1 only.

**New chapter:** `18-hierarchical-vm.md` (per Stage 0 numbering).

**New ADR:** `0028-hierarchical-vm.md` resolving the 6 open design questions from the prior `hierarchical-vm.md` proposal (lazy vs eager loading, recursive generic constraint per flavor, construction order, hub messages on structural change, path semantics, IExpandable auto-implementation).

**New conformance IDs:** ~12 `HIER-NNN` (identity, recursion invariants, parent/depth/path, eager-vs-lazy, construct order, structural-change messages, search/expand integration, lifecycle propagation, modeled-vs-non-modeled variant).

**Per-flavor work:**

- C# `langs/csharp/src/VMx/Hierarchical/HierarchicalVM.cs` (recursive generic `where TVM : HierarchicalVM<TModel, TVM>`)
- Python `langs/python/src/vmx/hierarchical/hierarchical_vm.py` (TypeVar bound recursive)
- TypeScript `langs/typescript/src/hierarchical/hierarchicalVm.ts` (`T extends HierarchicalVM<TModel, T>`)

**Cross-chapter impact:**

- Extend `06-composite-vm.md` cross-references (one paragraph).
- Extend `13-tree-utilities.md` (`walk` / `walk_expanded` integration).
- Possibly extend `14-capabilities.md` if HierarchicalVM auto-implements IExpandable (ADR decision).

**Diagrams:** Tree structure diagram (chapter §1); construct-order sequence (chapter §3).

**Tests:**

- ~12 conformance tests per flavor (~36 total)
- ~25 unit tests per flavor (recursive construction, parent/child invariants under mutation, depth/path recompute, hub message ordering, lifecycle propagation, integration with ExpandableState/SearchableState)

**Cleanup:** Delete `spec/proposals/hierarchical-vm.md` (now superseded by chapter 18).

**Estimated stage size:** ~50 bite-sized tasks.

**Stage exit:** 2 consecutive zero-finding multi-agent audit passes.

______________________________________________________________________

# Stage 3 — Forms & Dialogs (C4 + C2)

**Outline only.** Detailed plan to be authored at stage start.

**Items:** C4 (`FormVM`) and C2 (`IDialogService`) — bundled because they're often used together.

**New chapters:**

- `20-form-vm.md` (per Stage 0 numbering)
- `19-dialogs.md`

**New ADRs:**

- `0029-dialog-service-in-core.md` (host-modal interactions; in core per user decision; null impl per ADR-0017 convention)
- `0030-form-vm.md` (snapshot/revert; ORM-agnostic; configurable deep-vs-shallow snapshot policy)

**New conformance IDs:** ~10 `FORM-NNN` + ~8 `DIA-NNN`.

**Disambiguation note** (resolved in Stage 0 task 0.3 — no conflict):

The three files `langs/csharp/src/VMx/Capabilities/Dialog.cs`,
`langs/python/src/vmx/capabilities/dialog.py`, and
`langs/typescript/src/capabilities/dialog.ts` implement the
**spec/14-capabilities.md §2.4 "Dialog / form capabilities"** group. They
define three fine-grained VM-side participant interfaces that a ViewModel class
opts into: `IClosable` (`can_close()` / `close()`), `IApprovable`
(`can_approve()` / `approve()`), and `ICancelable` (`can_cancel()` /
`cancel()`). These describe what a ViewModel *can do* when hosted in a dialog
shell — they carry no host-side plumbing.

The new `IDialogService` (item C2) is an entirely different concept: a
**host-side service** injected into ViewModels to trigger modal interactions
(Confirm, PickFileToOpen, etc.). It belongs in a new `dialogs/` directory, not
in `capabilities/`. Names, files, and responsibilities are orthogonal; no
renaming of the existing capability interfaces is required.

**Per-flavor work:**

- `langs/<flavor>/src/<vmx>/dialogs/` (new directory; contracts + `NullDialogService`)
- `langs/<flavor>/src/<vmx>/forms/` (new directory; `FormVM<TM>`)

**Cross-chapter impact:** Extend `16-notifications.md` with a paragraph distinguishing `INotificationHub` (toast/banner) from `IDialogService` (modal).

**Diagrams:**

- `IDialogService` vs `INotificationHub` responsibility split (ch.19)
- `FormVM` state diagram: Pristine → Dirty → Approved / Reverted (ch.20)

**Integration test:** `ConfirmationDecoratorCommand` wired to `IDialogService.Confirm()` (per ADR-0029 §4). Lives in each flavor's integration tests.

**Estimated stage size:** ~70 bite-sized tasks.

______________________________________________________________________

# Stage 4 — Notification rendering VMs (C5 + I6)

**Outline only.**

**Items:** C5 (`NotificationVM` / `ConfirmationVM`) + I6 (service-as-VM adapter recipe).

**Chapter extension:** `16-notifications.md` gains two subsections (NotificationVM, ConfirmationVM) and a "Patterns" section at the end with the service-as-VM recipe.

**New ADR:** `0031-notification-rendering-vms.md`. I6 stays a recipe (no ADR) unless the writing-plans pass for this stage decides to formalize it (then `0032-service-as-vm-adapter.md`).

**New conformance IDs:** ~6 extension to `NOTIF-` range (opacity decay, auto-dismiss, dual-action, manual dismiss cancels timer, hub resolution propagates, fake-clock determinism).

**Per-flavor work:** New files in each flavor's `notifications/` sub-package (C# `VMx.Notifications` assembly; Python `vmx.notifications`; TS `vmx/notifications` subpath).

**Diagram:** Lifespan / opacity timeline.

**Test approach:** Fake-clock / virtual-time schedulers (Rx has them built in: `TestScheduler` in C#, `reactivex.testing` in Python, `TestScheduler` from `rxjs/testing` in TS).

**Estimated stage size:** ~30 bite-sized tasks.

______________________________________________________________________

# Stage 5 — Minors (M1–M4)

**Outline only.**

**Items:** M1 (`PropertyValueChangedMessages<P>`), M2 (reactive-init-token recipe — verify-or-add), M3 (`RelayCommand` auto-resubscribe — verify-or-add), M4 (`CartesianProduct`, `Sample`, `Product` LINQ helpers — C# only).

**Verify-or-add tasks (M2, M3):**

- M2: Inspect `DerivedProperty` implementations in all three flavors. If they already handle the double-subscription concern internally (almost certain), document as a recipe in `15-derived-properties.md` with a "you don't need to do this; DerivedProperty handles it" note. If not, add an internal helper.
- M3: Inspect `RelayCommand.triggers` in all three flavors. If `IObservable<Unit>` triggers can be built trivially from `IMessageHub.PropertyChangedMessagesFor(obj, "prop")`, document the pattern in `04-commands.md`. If awkward, add a small ergonomic overload.

**New ADRs (conditional):**

- `0033-property-value-changed-messages.md` (M1; may be informative-only)
- `0034-linq-utility-helpers-csharp-only.md` (M4; records asymmetric per-flavor decision)

**Conformance IDs:** None for M1 (helper, not contract) unless tests warrant. None for M2-M4 (recipes / utility / asymmetric).

**Per-flavor work:**

- M1: One small helper file per flavor in `messages/` (or `extensions/`).
- M4: C# only — `langs/csharp/src/VMx/Extensions/LinqHelpers.cs` (consider whether this belongs in the existing `VMx.Extensions.DependencyInjection` companion package instead — ADR decision).

**Estimated stage size:** ~25 bite-sized tasks.

______________________________________________________________________

# Stage 6 — Release

**Outline only.**

**Items:** Version bumps; documentation pass; diagram pass; compatibility matrix; release notes; final cross-flavor audit; merge to main.

**Files to touch:**

- `spec/VERSION` — bump to `2.1.0`
- `spec/README.md` — finalize §1.2 chapter list (now includes 18, 19, 20, 21)
- `spec/00-overview.md` — refresh concept inventory (HierarchicalVM, FormVM, IDialogService, new collections)
- `spec/01-concepts.md` — extend VM types section; add new collections; cross-reference dialogs
- `spec/ADRs/README.md` — verify all new ADRs (0022-0034) registered
- `compatibility-matrix.md` — bump spec to 2.1.0; per-flavor versions to 2.1.0
- `langs/csharp/src/VMx/VMx.csproj` (and `Directory.Packages.props` if version centralized) — bump `<Version>` to `2.1.0`
- `langs/python/pyproject.toml` — bump `version` to `2.1.0`; update `__min_spec_version__` constant
- `langs/typescript/package.json` — bump `version` to `2.1.0`; update `__minSpecVersion__` constant
- `langs/csharp/src/VMx.Notifications/VMx.Notifications.csproj` — bump per ADR-0013 independent versioning
- New CHANGELOG entry per flavor or unified — author release notes summarizing the 15 candidates absorbed

**Diagrams cross-check:** Verify every diagram referenced in Stages 1–5 actually exists and renders correctly. Audit `spec/` for any *existing* diagrams that reference the VM hierarchy and need a refresh to add HierarchicalVM / FormVM.

**Final audit:**

- 2 consecutive zero-finding multi-agent audits (per user's strict-clean-pass-gate).
- All three flavor test suites + conformance coverage tool clean.
- `tools/check-conformance-coverage.py --require csharp --require python --require typescript` clean.
- Pre-commit clean across the whole branch.

**Merge:**

- Create PR `feat/v2.1-absorption-audit` → `main`. Title: `feat(v2.1): absorb 15 post-v2.0 candidates`. Body: link the proposal doc commit + list candidates.
- Per user preference, do NOT push or merge until the audit gate passes.
- After merge: tag `v2.1.0` on each flavor's release pipeline per existing release process.

**Estimated stage size:** ~20 bite-sized tasks.

______________________________________________________________________

## Self-review checklist (run by plan author after writing)

1. **Spec coverage:** Each of the 15 candidates (C1-C5, I1-I6, M1-M4) maps to at least one stage and one substage. ✓ (matrix below)

| Proposal item                     | Stage | Substage / placement                              |
| --------------------------------- | ----- | ------------------------------------------------- |
| C1 HierarchicalVM                 | 2     | Whole stage                                       |
| C2 IDialogService                 | 3     | Bundled with C4                                   |
| C3 Paging                         | 1     | Substage 1A (capability portion) + 1B/1C (helper) |
| C4 FormVM                         | 3     | Bundled with C2                                   |
| C5 Notification VMs               | 4     | Whole stage                                       |
| I1 Fluent command ext             | 1     | Substage 1D                                       |
| I2 ServicedObservableCollection   | 1     | Substage 1B + 1C                                  |
| I3 Multi-key ObservableDictionary | 1     | Substage 1B + 1C                                  |
| I4 Granular ObservableList        | 1     | Substage 1B + 1C                                  |
| I5 IFilterable                    | 1     | Substage 1A                                       |
| I6 Service-as-VM adapter          | 4     | Bundled with C5                                   |
| M1 PropertyValueChangedMessages   | 5     | Minor stage                                       |
| M2 Reactive-init-token recipe     | 5     | Verify-or-add                                     |
| M3 RelayCommand auto-resubscribe  | 5     | Verify-or-add                                     |
| M4 CartesianProduct etc.          | 5     | C# only                                           |

2. **Placeholder scan:** Stage 1 has full bite-sized content; Stages 2-6 are explicitly labeled "outline only — detailed plan to be authored at stage start". This is not a placeholder — it's a deferred just-in-time plan, called out explicitly. ✓

1. **Type consistency:** Names used in this plan (`IFilterable`, `IPageable`, `ServicedObservableCollection`, `ObservableList`, `ObservableDictionary`, `PagedComposition`, `HierarchicalVM`, `FormVM`, `IDialogService`, `NotificationVM`, `ConfirmationVM`) match the proposal doc throughout. ✓

1. **CI rules respected:** Every spec change has an ADR in the same task block; every conformance ID has a stub-in-all-flavors task immediately following. ✓
