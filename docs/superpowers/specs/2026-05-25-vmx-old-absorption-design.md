# VMx.old Absorption — Design

**Date:** 2026-05-25
**Status:** Approved (brainstorming → ready for implementation plan)
**Target spec version:** 2.0.0
**Target branch:** `feat/absorb-vmx-old`

______________________________________________________________________

## 1. Background

A 2012 C# Silverlight 5 predecessor of the current VMx project (~65 `.cs` files, MEF for composition, Rx 1.x, no tests) was unearthed at `/Users/kaveh/repos/VMx.old/`. It encodes a substantial body of opinionated MVVM machinery — derived properties, command decorators, a notification service, capability micro-interfaces, search/filter, expand/collapse semantics — none of which exist in the current multi-flavor (`csharp` / `python` / `typescript`) spec.

The goal of this absorption is to bring forward every old-VMx concept that fills a real conceptual gap in the current spec, plus three "best-effort" curiosities, while preserving the architectural invariants the current project has already settled (constructor injection over service locator, no virtualization, etc.).

______________________________________________________________________

## 2. Scope contract

### 2.1 Absorb fully (8 items)

Every item in this group lands as a spec chapter delta + new ADR + new conformance IDs + parity implementation in C#, Python, and TypeScript.

1. **Capability micro-interfaces** (additive)
1. **Derived/Computed properties** (multi-source dependency tracking)
1. **Command decorators** (Composite / Decorator / Confirmation)
1. **Notification / Confirmation service**
1. **Search / filter on container VMs**
1. **Tree expand / collapse state on VMs**
1. **Modeled CRUD command set**
1. **Null-object service convention**

### 2.2 Best-effort absorb (3 items)

9. **Inheritance philosophy ADR** — teaching ADR contrasting the new flat VM hierarchy with the old `Unit → ObservableBase → Component → VMBase` chain (no code)
1. **HierarchicalViewModel research draft** — captured as a `spec/proposals/` doc; deferred decision
1. **Localization conventions** — new chapter + null-default localizer per flavor

### 2.3 Explicitly skip (already covered or deliberately rejected)

- MEF / `FactoryService` / service locator → rejected by ADR-0003
- Virtualization → rejected by ADR-0005
- `IVMx<C1..C4>` multi-composition → already covered by `AggregateVM1..5` per ADR-0007
- Expression-based `RaisePropertyChanged` → obviated by the modern message hub

### 2.4 Cross-cutting rules (apply to every cycle)

- **No breaking changes to v1.x APIs.** Every absorbed concept is additive. If a cycle's design tries to alter an existing type's signature, re-derive it as a capability interface or sub-type.
- **Strict 3-flavor parity.** Every absorbed item lands in all three flavors. Per-language idioms allowed (Pascal/snake/camel) per ADR-0006, but conceptual shape and behavior must match.
- **Capability interfaces are the seam.** When an old-VMx behavior touched an existing VM (expand/collapse, search, CRUD), it lands as opt-in capability interfaces (Item 1) that existing VMs may or may not implement.
- **The message hub is the only event spine.** Derived-property updates, search throttling, notification arrival, CanExecuteChanged on decorated commands — all flow through the existing hub. No new event channels.
- **No service locator, ever.** All new services (`INotificationHub`, null variants) are constructor-injected.
- **Tests follow the per-flavor test layout** (`tests/conformance/<feature>/`), not a new structure.

______________________________________________________________________

## 3. Concept catalog (spec mapping)

### 3.1 Absorb-fully items

| #   | Concept                             | Source in old                                                                                                              | Target spec home                                                                                            | ADR                                   | Conformance IDs                 |
| --- | ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------- | ------------------------------- |
| 1   | Capability micro-interfaces         | `Contract/Receivers.cs` (20 micro-interfaces)                                                                              | New chapter `14-capabilities.md`; existing VMs additively implement relevant ones                           | `0010-capability-micro-interfaces.md` | `CAP-001..CAP-020`              |
| 2   | Derived/Computed properties         | `Core/Property.cs`, `Property/TransformationProperty.cs`                                                                   | New chapter `15-derived-properties.md`; sources are property-change messages on hub                         | `0011-derived-properties.md`          | `DPROP-001..DPROP-012`          |
| 3   | Command decorators                  | `Command/{Composite,Decorator,ConfirmationDecorator}Command.cs`                                                            | Extend chapter `04-commands.md` (new "Decorators" section)                                                  | `0012-command-decorators.md`          | `CMDD-001..CMDD-009`            |
| 4   | Notification / Confirmation service | `Services/NotificationService.cs` + `Primitives/Notification*.cs`                                                          | New chapter `16-notifications.md`; new `INotificationHub` service in sub-package                            | `0013-notification-service.md`        | `NOTIF-001..NOTIF-010`          |
| 5   | Search / filter on containers       | `Core/CompositionBase` (`SearchTerm`, `SearchPredicate`, 1s throttle, `SearchCommand`)                                     | Extend chapter `06-composite-vm.md` and `07-group-vm.md`                                                    | `0014-search-and-filter.md`           | `COMP-014..018`, `GRP-007..010` |
| 6   | Tree expand / collapse state        | `Core/VMBase` (`IsExpanded`, Expand / Collapse / Toggle commands)                                                          | Extend `05-component-vm.md` (`IExpandable` integration) and `13-tree-utilities.md` (expand-aware traversal) | `0015-expand-collapse-state.md`       | `EXP-001..EXP-005`              |
| 7   | Modeled CRUD command set            | `Core/CompositionBase<M,VM,C,P>` (`CreateNewCommand`, `UpdateCurrentCommand`, `DeleteCurrentCommand` with `.Confirm(...)`) | Extend `06-composite-vm.md` for `CompositeVM<M,VM>`                                                         | `0016-modeled-crud-commands.md`       | `COMP-019..024`                 |
| 8   | Null-object service convention      | `NullObjects/NullMessagingService.cs`                                                                                      | Extend `03-messages.md` and `11-threading.md`; add null variant per service contract                        | `0017-null-object-services.md`        | `NULL-001..NULL-003`            |

### 3.2 Best-effort items

| #   | Concept                              | Source                                           | Target home                                                          | Treatment                                                    |
| --- | ------------------------------------ | ------------------------------------------------ | -------------------------------------------------------------------- | ------------------------------------------------------------ |
| 9   | Inheritance philosophy               | `Core/{Unit,ObservableBase,Component,VMBase}.cs` | ADR-only `0018-flat-vm-hierarchy-vs-old-chain.md`                    | Teaching doc; no code                                        |
| 10  | HierarchicalViewModel research draft | `ToDo/` (commented-out)                          | New doc `spec/proposals/hierarchical-vm.md`                          | Capture as proposal; deferred decision                       |
| 11  | Localization conventions             | 9-language satellite assemblies (empty shells)   | New chapter `17-localization.md` + null-default localizer per flavor | `0019-localization-hooks.md`; conformance `LOC-001..LOC-003` |

### 3.3 Pre-decided design points (settled during brainstorming)

- **Item 2 — N sources, not 5.** Old hard-capped at 5 due to C# overload patterns. Spec requires support for ≥5 source dependencies; implementations may go higher (Python/TS trivially, modern C# via `params` / tuples).
- **Item 4 — Sub-package distribution (hybrid).** C#: separate assembly `VMx.Notifications` (deps on `VMx`). Python: subpackage `vmx.notifications` (same dist). TypeScript: subpath export `vmx/notifications` (same dist). Asymmetric on purpose — preserves "opt-in, no core surface impact" without forcing a TS monorepo restructure.
- **Item 3 — Confirmation decorator is delegate-based.** Takes a `Func<Task<bool>>` (or equivalent per-flavor async prompt). Does *not* depend on the notification service. An optional bridge helper in the notifications sub-package wires it to `INotificationHub`.

### 3.4 Open questions deferred to per-cycle ADRs

- **Item 2 — fixture format for derived properties.** Need a JSON fixture analogous to `spec/fixtures/command-truthtable.json` describing dependency-update scenarios. Shape decided when writing chapter 15.
- **Item 7 — "Current" semantics for an empty modeled `CompositeVM`.** Old auto-selected the first added item; new spec does not yet specify. Resolved in the chapter 06 extension.

______________________________________________________________________

## 4. Execution model

### 4.1 Branch & merge strategy

- All work happens on `feat/absorb-vmx-old`. Nothing touches `main` until the whole absorption goal is done and audited.
- Rebase onto `main` after every cycle to catch drift early.
- Single final merge to `main` after the cross-cutting finale audit (cycle 12).

### 4.2 Per-concept mini-cycle (the unit of work)

Every absorbed item goes through this 8-step cycle. If a step fails its gate, the cycle does not advance.

```
1. Spec delta           → write the new chapter or chapter extension
2. ADR                  → write the new ADR explaining the decision
3. Conformance IDs      → add IDs to spec/12-conformance.md
4. Cross-flavor stubs   → add per-flavor stub tests
                          (Python @pytest.mark.conformance,
                           C# [Trait("Conformance", "…")],
                           TS describe("…"))
                          — required by .github/workflows/spec-discipline.yml
5. C# implementation    → land in langs/csharp/src + tests
6. Python impl          → land in langs/python/src/vmx + tests
7. TypeScript impl      → land in langs/typescript/src + tests
8. Per-concept audit    → 3-agent parallel review
                          (spec / cross-flavor / code-quality);
                          punchlist closed before next cycle
```

**Parallelism:**

- **Within a cycle:** steps 5, 6, 7 run as parallel dispatched subagents (no shared state once stubs are in).
- **Across cycles:** strictly sequential. Each cycle's audit must close before the next cycle starts.

**Gates between steps:**

- 1→2: spec delta must be self-consistent (no forward references to undefined terms).
- 3→4: stubs must satisfy `.github/workflows/spec-discipline.yml` (one stub per ID per active flavor).
- 5/6/7: each flavor's full test suite must pass — including all prior conformance tests *plus* the new stubs (failing → passing).
- 8: audit punchlist must be closed (Critical/Important resolved; Minor either fixed or explicitly deferred with a tracking note on the branch).

### 4.3 Audit shape (per-cycle gate)

Three parallel review agents:

- **Spec reviewer** — does the chapter delta + ADR match what was implemented? Are conformance IDs covered? Any spec ambiguities?
- **Cross-flavor reviewer** — do C#/Py/TS implementations match each other in shape and behavior? Any flavor-divergence not documented?
- **Code-quality reviewer** — type-checking, lint, idiomatic per-flavor, no regressions in the existing 75 conformance tests.

Output: a consolidated punchlist of Critical / Important / Minor findings. The cycle does not close until Critical and Important are resolved.

### 4.4 Final cross-cutting finale (cycle 12)

After all 11 absorption cycles close:

- Full conformance run across all flavors (target: 152 IDs all passing).
- `tools/check-conformance-coverage.py --require csharp --require python --require typescript`.
- `compatibility-matrix.md` updated with the v2.0.0 row.
- Bump `spec/VERSION` and each flavor's package version to 2.0.0.
- Bump `MinSpecVersion` / `__min_spec_version__` / `__minSpecVersion__` constants.
- Final cross-cutting multi-agent audit on the whole branch.
- Merge to `main`.

______________________________________________________________________

## 5. Concept sequencing

Twelve sequential cycles + one finale, ordered by dependency:

| Cycle | Item                                    | Why this slot                                                    |
| ----- | --------------------------------------- | ---------------------------------------------------------------- |
| 1     | Item 1 — Capability micro-interfaces    | Foundation; unlocks Items 6, 7                                   |
| 2     | Item 8 — Null-object service convention | Foundation; convention referenced by Item 4                      |
| 3     | Item 2 — Derived properties             | Independent; unlocks Item 5; longest implementation, start early |
| 4     | Item 3 — Command decorators             | Independent; unlocks Item 7                                      |
| 5     | Item 4 — Notification sub-package       | Independent; uses Item 8 convention; unlocks Item 11             |
| 6     | Item 6 — Expand / collapse              | Needs Item 1                                                     |
| 7     | Item 5 — Search / filter                | Uses Item 2                                                      |
| 8     | Item 7 — Modeled CRUD                   | Needs Items 1 and 3                                              |
| 9     | Item 11 — Localization                  | Touches strings introduced by Items 3 and 4                      |
| 10    | Item 9 — Inheritance philosophy ADR     | Best written after seeing the absorbed shape                     |
| 11    | Item 10 — HierarchicalVM proposal       | Best-effort; capture as proposal doc                             |
| 12    | Cross-cutting finale                    | Compat matrix, version bumps, full-tree audit, merge prep        |

Dependency graph:

```
Foundation:
  Item 1 (capabilities) ──┐
  Item 8 (null-object) ───┤
                          │
Independent middle:       ▼
  Item 2 (derived props)  → enables Item 5
  Item 3 (decorators)     → enables Item 7
  Item 4 (notifications)  → enables Item 11
                          │
Dependent:                ▼
  Item 6 (expand/collapse)    ← needs Item 1
  Item 5 (search/filter)      ← uses Item 2
  Item 7 (modeled CRUD)       ← needs Items 1 + 3
                          │
Tail:                     ▼
  Item 11 (localization)   ← uses strings from Items 3 + 4
  Item 9 (inheritance ADR)
  Item 10 (HierarchicalVM proposal)
```

______________________________________________________________________

## 6. Spec, conformance & version impact

### 6.1 Spec chapter changes

| Action  | Chapter                    | Source                             |
| ------- | -------------------------- | ---------------------------------- |
| New     | `14-capabilities.md`       | Item 1                             |
| New     | `15-derived-properties.md` | Item 2                             |
| New     | `16-notifications.md`      | Item 4                             |
| New     | `17-localization.md`       | Item 11                            |
| Extend  | `03-messages.md`           | Item 8 (null hub)                  |
| Extend  | `04-commands.md`           | Item 3 (decorator section)         |
| Extend  | `05-component-vm.md`       | Item 6 (`IExpandable` integration) |
| Extend  | `06-composite-vm.md`       | Items 5, 7 (search + CRUD)         |
| Extend  | `07-group-vm.md`           | Item 5 (search)                    |
| Extend  | `11-threading.md`          | Item 8 (null dispatcher)           |
| Extend  | `13-tree-utilities.md`     | Item 6 (expand-aware traversal)    |
| New dir | `spec/proposals/`          | Item 10                            |

### 6.2 ADRs to add (10 new)

- `0010-capability-micro-interfaces.md`
- `0011-derived-properties.md`
- `0012-command-decorators.md`
- `0013-notification-service.md`
- `0014-search-and-filter.md`
- `0015-expand-collapse-state.md`
- `0016-modeled-crud-commands.md`
- `0017-null-object-services.md`
- `0018-flat-vm-hierarchy-vs-old-chain.md`
- `0019-localization-hooks.md`

### 6.3 Conformance growth — 77 new IDs (75 → 152)

| Prefix   | Range              | Item |
| -------- | ------------------ | ---- |
| `CAP-`   | 001..020           | 1    |
| `DPROP-` | 001..012           | 2    |
| `CMDD-`  | 001..009           | 3    |
| `NOTIF-` | 001..010           | 4    |
| `COMP-`  | 014..024 (extends) | 5, 7 |
| `GRP-`   | 007..010 (extends) | 5    |
| `EXP-`   | 001..005           | 6    |
| `NULL-`  | 001..003           | 8    |
| `LOC-`   | 001..003           | 11   |

After absorption, `tools/check-conformance-coverage.py` will require 152 IDs × 3 flavors = 456 stubs (vs current 225).

### 6.4 Version bumps

- `spec/VERSION`: **1.1.0 → 2.0.0**
- `langs/csharp` package `VMx`: **1.2.0 → 2.0.0**
- `langs/python` package `vmx`: **1.1.0 → 2.0.0**
- `langs/typescript` package `vmx`: **1.2.0 → 2.0.0**

Rationale for major bump (despite all-additive changes): spec roughly doubles in size; cleanly re-syncs the three flavors (currently at three different versions) to one coherent v2.0.0; per CLAUDE.md the spec major bump triggers a major bump in every active flavor; gives a single milestone to communicate.

### 6.5 New sub-packages (start at 1.0.0)

| Flavor | Distribution shape                                    | Rationale                                                                                     |
| ------ | ----------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| C#     | Separate assembly `VMx.Notifications` (deps on `VMx`) | Natural .NET assembly boundary; matches existing `VMx.Extensions.DependencyInjection` pattern |
| Python | Subpackage `vmx.notifications` (same dist)            | Avoids extra packaging pipeline; opt-in via import path                                       |
| TS     | Subpath export `vmx/notifications` (same dist)        | Avoids npm workspace restructure                                                              |

### 6.6 `compatibility-matrix.md` update

- Add row: `spec 2.0.0 ↔ VMx 2.0.0 (C#) ↔ vmx 2.0.0 (Python) ↔ vmx 2.0.0 (TS)`
- Bump per-flavor min-spec constants: `MinSpecVersion`, `__min_spec_version__`, `__minSpecVersion__`

### 6.7 CI / pre-commit implications

- Spec-discipline workflow auto-handles new IDs as long as stubs land in the same PR — no workflow changes needed.
- Each new ADR satisfies the "any spec change requires an ADR" rule.
- Conformance count doubling (75 → 152) raises CI runtime modestly; revisit if any per-flavor suite crosses 60s.

______________________________________________________________________

## 7. Risks

| Risk                                                                                                                                                                                 | Mitigation                                                                                                                                          |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cycle 3 (derived properties) is the longest implementation and hardest to test cross-flavor — semantics around source-disposal, transitive dependencies, write-back races are subtle | Front-loaded in sequence; conformance fixture `spec/fixtures/derived-properties.json` added so all 3 flavors test from a single source of truth     |
| Item 4 (notifications) is the most UI-adjacent — risk of leaking presentation concerns into spec                                                                                     | Spec defines hub + reaction contract only; no rendering, no styling, no "dialog" verbs. Confirmation decorator uses a generic delegate, not the hub |
| 12 sequential audit cycles is a long branch life — risk of `main` drifting                                                                                                           | Rebase `feat/absorb-vmx-old` onto `main` after every cycle; spec-discipline CI catches drift early                                                  |
| TS subpath export (`vmx/notifications`) may surprise consumers used to single-import packages                                                                                        | Document in chapter 16 + README; add explicit export map in `package.json`                                                                          |
| Conformance count doubling raises CI runtime                                                                                                                                         | Acceptable for current suite (fast); revisit if any per-flavor suite crosses 60s                                                                    |
| Per-flavor implementation drift across cycle 5/6/7 parallel agents                                                                                                                   | Cross-flavor reviewer in audit gate (step 8) explicitly checks shape/behavior parity                                                                |

______________________________________________________________________

## 8. Design summary

Create a long-lived feature branch `feat/absorb-vmx-old`. Walk through 12 sequential mini-cycles in the order set in §5 (foundation → independent middle → dependent → tail → finale). Each mini-cycle: write spec delta + new ADR + conformance IDs → land per-flavor stubs (CI-gated) → implement C#/Python/TS in parallel via dispatched subagents → 3-agent audit (spec / cross-flavor / code-quality) → close punchlist before next cycle. Across all cycles: 4 new chapters, 10 new ADRs, 77 new conformance IDs (75 → 152), one notifications sub-package per flavor (hybrid distribution), strict-additive API. Bump spec + all three flavors to v2.0.0 at finale, update compatibility matrix, run cross-cutting audit, then single merge to `main`.
