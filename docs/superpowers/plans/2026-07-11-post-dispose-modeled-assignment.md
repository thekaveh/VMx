# Post-Dispose Modeled Assignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make modeled assignment a complete no-op when it begins after VM disposal, with one portable contract and real coverage in all five VMx flavors.

**Architecture:** Put a terminal-state admission guard at the first line of each real modeled setter, before equality, retained-state mutation, hinting, validation, callbacks, command-state work, or notification. Specify that rule in the lifecycle, component, and form contracts; cover it with one cross-cutting `DISP-014` scenario per flavor; publish the same explanation from the canonical three-surface documentation source.

**Tech Stack:** Markdown specification and ADRs; C#/.NET/System.Reactive/xUnit; Python/reactivex/pytest; TypeScript/RxJS/Vitest; Swift/Combine/XCTest; Rust/rxrust facade/cargo tests; MkDocs and repository documentation generators.

## Global Constraints

- `spec/` is the behavior source of truth; every changed numbered spec chapter ships with new ADR-0091.
- Public conceptual shape remains identical across C#, Python, TypeScript, Swift, and Rust, with idiomatic names per ADR-0006.
- No new public API, dependency, lifecycle lock, cancellation abstraction, fixture, or architecture boundary is introduced.
- An assignment admitted before disposal keeps existing behavior; only an assignment that starts after terminal status is visible is inert.
- Stable packages advance from 3.10.0 to 3.11.0; Rust advances from 0.10.0 to 0.11.0 and all flavors declare spec 3.11.0.
- `DISP-014` is a real behavioral conformance test in all five full-parity flavors.
- Library count advances 339→340 and catalog count advances 344→345, including the unchanged five `THEME-00x` scenarios.
- Canonical docs generate the in-repo, `.io` MkDocs, and GitHub-wiki surfaces; generated output is never hand-edited.
- Swift XCTest execution requires full Xcode; when unavailable locally, `swift build -c release` is required and macOS CI is authoritative.
- Consumer validation uses a temporary DayDreams clone and never pushes consumer changes.

______________________________________________________________________

### Task 1: Define the normative contract

**Files:**

- Create: `spec/ADRs/0091-post-dispose-modeled-assignment.md`
- Modify: `spec/ADRs/README.md`
- Modify: `spec/02-lifecycle.md`
- Modify: `spec/05-component-vm.md`
- Modify: `spec/20-form-vm.md`
- Modify: `spec/12-conformance.md`
- Modify: `spec/VERSION`

**Interfaces:**

- Consumes: VM lifecycle terminal state and existing modeled component/FormVM mutators.

- Produces: spec 3.11.0 rule and catalog key `DISP-014` used by every flavor test.

- [ ] **Step 1: Add ADR-0091 and its index row**

Record Accepted status, date 2026-07-11, spec 3.11.0, the early-guard decision, affected setters, admission semantics, version rationale, alternatives, and `DISP-014`. The decision text must state:

```text
When modeled assignment begins after the VM is disposed, it returns before
candidate equality, retained-state mutation, hint/snapshot work, validation,
command-state work, consumer callbacks, local notifications, or hub messages.
An assignment admitted before disposal completes under the existing contract.
```

- [ ] **Step 2: Add normative lifecycle, component, and form wording**

Add the same admission rule to the lifecycle disposal section, the modeled-component mutation section, and `FormVM.SetModel`. Explicitly identify modeled composites as factory-only and forwarding/read-only surfaces as inheriting the guarded target.

- [ ] **Step 3: Add the conformance entry**

Append this scenario after `DISP-013`:

```markdown
### DISP-014 — Modeled assignment after disposal is inert

**Given** a modeled component and a form with observable equality, hinting or
validation, callbacks, retained state, and notification/command signals
**When** each VM is disposed and a late completion attempts modeled assignment
**Then** the attempt performs none of that work and every retained value and
signal remains unchanged
```

Update the lifecycle chapter's conformance range to `DISP-007` through `DISP-014`.

- [ ] **Step 4: Advance the spec version**

Replace the sole contents of `spec/VERSION` with `3.11.0`.

- [ ] **Step 5: Verify the spec delta**

Run: `git diff --check && rg -n "DISP-014|3\.11\.0" spec`

Expected: no whitespace errors; ADR index, three chapters, catalog, and version expose the new contract.

### Task 2: Add red five-flavor conformance tests

**Files:**

- Create: `langs/csharp/tests/VMx.Conformance.Tests/PostDisposeModeledAssignmentConformanceTests.cs`
- Create: `langs/python/tests/conformance/test_disp_014_post_dispose_modeled_assignment.py`
- Create: `langs/typescript/tests/conformance/postDisposeModeledAssignment.test.ts`
- Create: `langs/swift/Tests/VMxTests/PostDisposeModeledAssignmentConformanceTests.swift`
- Create: `langs/rust/tests/conformance/post_dispose_modeled_assignment.rs`
- Modify: `langs/rust/tests/conformance.rs`
- Modify: `langs/swift/Tests/VMxTests/ComponentVMTests.swift`

**Interfaces:**

- Consumes: existing public builders/setters, lifecycle disposal, local property streams, shared hub messages, form validation, and command can-execute streams.

- Produces: exactly one discoverable `DISP-014` marker per flavor and regression assertions for component plus form behavior.

- [ ] **Step 1: Write the modeled-component half in each test**

Use counters and sentinel values to exercise this invariant:

```text
initial model = A; initial hint = hint-A; dispose; queue/invoke late set(B)
assert model == A; hint == hint-A; equality == 0; hinter == 0;
assert onModelChanged == 0; local notifications == 0; hub messages == 0
```

Reset construction/disposal noise before the late call. For C#/Python/Rust use a model whose equality increments a counter; for TypeScript use the configured hint/callback counters; for Swift use `modelEquals`, `modelToHint`, and callback closures.

- [ ] **Step 2: Write the FormVM half in each test**

Use a valid initial model and invalid replacement:

```text
initial model/snapshot/errors/canApprove captured; dispose; late set(invalid B)
assert model, snapshot, errors, isDirty, and canApprove equal captured values;
assert equality/validator counters and property/can-execute signals remain zero
```

Represent the late completion as a closure created before disposal and invoked afterward. C#, Python, and Rust are expected to pass already; TypeScript and Swift must fail on retained model or validation work before production changes.

- [ ] **Step 3: Replace Swift's opposite legacy assertion**

In `ComponentVMTests.swift`, change the VMX-102 post-dispose test from expecting model mutation to expecting unchanged retained model and no callback/notification. Keep only one `DISP-014` marker in the dedicated conformance file.

- [ ] **Step 4: Run focused tests and preserve red evidence**

Run:

```bash
dotnet test langs/csharp/tests/VMx.Conformance.Tests/VMx.Conformance.Tests.csproj -c Release --filter 'Conformance=DISP-014'
uv --project langs/python run pytest langs/python/tests/conformance/test_disp_014_post_dispose_modeled_assignment.py -q
npm --prefix langs/typescript test -- --run tests/conformance/postDisposeModeledAssignment.test.ts
cargo test --manifest-path langs/rust/Cargo.toml --test conformance post_dispose_modeled_assignment
cd langs/swift && swift test --filter PostDisposeModeledAssignmentConformanceTests
```

Expected before implementation: C#/Python/Rust FormVM portions may pass, while every modeled component fails; TypeScript and Swift FormVM portions also fail. If local Swift lacks XCTest, record `no such module 'XCTest'` and use macOS CI for execution.

### Task 3: Implement the smallest terminal guards

**Files:**

- Modify: `langs/csharp/src/VMx/Components/ComponentVMBaseOfM.cs`
- Modify: `langs/python/src/vmx/components/component_vm.py`
- Modify: `langs/typescript/src/components/componentVMOf.ts`
- Modify: `langs/typescript/src/forms/formVm.ts`
- Modify: `langs/swift/Sources/VMx/Components/ComponentVMOf.swift`
- Modify: `langs/swift/Sources/VMx/Forms/FormVM.swift`
- Modify: `langs/rust/src/lib.rs`

**Interfaces:**

- Consumes: each VM's existing disposed/status accessor.

- Produces: no new callable interface; only earlier return from existing setters.

- [ ] **Step 1: Add the guard as the first executable setter statement**

Use each flavor's established terminal-state spelling:

```csharp
if (Status == ConstructionStatus.Disposed) return;
```

```python
if self._is_disposed():
    return
```

```typescript
if (this.status === ConstructionStatus.Disposed) return; // ComponentVMOf
if (this.#disposed) return;                              // FormVM
```

```swift
guard status != .disposed else { return } // ComponentVMOf
guard !_disposed else { return }          // FormVM
```

```rust
if self.status() == ConstructionStatus::Disposed {
    return;
}
```

Apply the guard to every modeled component setter, plus TypeScript and Swift FormVM setters. Leave the already-guarded C#/Python/Rust FormVM implementations unchanged. In Swift, move the component's existing guard ahead of equality and assignment rather than adding a second check.

- [ ] **Step 2: Re-run focused DISP-014 tests**

Run the five commands from Task 2, Step 4.

Expected: C#, Python, TypeScript, and Rust pass; Swift passes with full Xcode or at minimum the package release build succeeds when XCTest is unavailable.

- [ ] **Step 3: Run adjacent lifecycle/form suites**

Run:

```bash
uv --project langs/python run pytest langs/python/tests/conformance/test_property_change.py langs/python/tests/conformance/test_form_vm.py -q
dotnet test langs/csharp/VMx.sln -c Release --filter 'Conformance~DISP|Conformance~FORM'
npm --prefix langs/typescript test -- --run tests/conformance/propertyChanged.test.ts tests/conformance/form-001-to-010-form-vm.test.ts
cargo test --manifest-path langs/rust/Cargo.toml --test conformance disposition
cd langs/swift && swift build -c release
```

Expected: all applicable adjacent tests and builds pass; correct any command-level test filter mismatch by using the owning suite's documented focused invocation, without broadening implementation.

### Task 4: Publish version and compatibility metadata

**Files:**

- Modify: `langs/csharp/src/VMx/VMx.csproj`, `langs/csharp/README.md`, `langs/csharp/CHANGELOG.md`
- Modify: `langs/python/src/vmx/__about__.py`, `langs/python/README.md`, `langs/python/CHANGELOG.md`
- Modify: `langs/typescript/package.json`, `langs/typescript/package-lock.json`, `langs/typescript/src/version.ts`, `langs/typescript/README.md`, `langs/typescript/CHANGELOG.md`
- Modify: `langs/swift/Package.swift`, `langs/swift/Sources/VMx/Version.swift`, `langs/swift/README.md`, `langs/swift/CHANGELOG.md`
- Modify: `langs/rust/Cargo.toml`, `langs/rust/Cargo.lock`, `langs/rust/src/lib.rs`, `langs/rust/README.md`, `langs/rust/CHANGELOG.md`
- Modify: `compatibility-matrix.md`, `README.md`, `spec/README.md`

**Interfaces:**

- Consumes: completed 3.11.0 contract and 340-test catalog.

- Produces: consistent package/spec declarations, changelogs, compatibility table, and count claims.

- [ ] **Step 1: Update exact version declarations**

Set C#/Python/TypeScript/Swift package and min-spec versions to `3.11.0`; set Rust package to `0.11.0` and `MIN_SPEC_VERSION` to `3.11.0`. Regenerate lock metadata only through `npm install --package-lock-only --ignore-scripts` and `cargo check --manifest-path langs/rust/Cargo.toml`.

- [ ] **Step 2: Add 2026-07-11 changelog entries**

Each flavor entry names ADR-0091, `DISP-014`, inert modeled component/FormVM assignment, 340/340 library parity, and spec 3.11.0. Rust's heading is `[0.11.0]`; all others use `[3.11.0]`.

- [ ] **Step 3: Update every current-facing count/version claim**

Change current-source claims from 339/344 to 340/345 and 3.10.0 to 3.11.0 (Rust 0.10.0→0.11.0). Preserve historical changelog and version-history text.

- [ ] **Step 4: Check metadata consistency**

Run: `uv --project langs/python run python tools/check-version-consistency.py && rg -n "339|344|3\.10\.0|0\.10\.0" README.md compatibility-matrix.md spec/README.md langs/*/README.md`

Expected: version checker passes; remaining old values are explicitly historical, published-package facts, or release history rather than current-source claims.

### Task 5: Update and regenerate all documentation surfaces

**Files:**

- Modify: `docs/content/primitives/disposal-contract.md`
- Modify: `docs/content/primitives/viewmodel-families/component-family.md`
- Modify: `docs/content/primitives/viewmodel-families/specialized/form-vm.md`
- Modify: `docs/content/core-concepts.md`
- Modify: `docs/content/installation.md`
- Modify: `docs/content/specification-conformance.md`
- Modify generated mirrors under `generated/site/` and `generated/wiki/`, plus generated `mkdocs.yml` when content generation changes it.

**Interfaces:**

- Consumes: canonical 3.11.0 contract, versions, and counts.

- Produces: synchronized GitHub-rendered docs, MkDocs `.io` source/output, and native wiki export.

- [ ] **Step 1: Document the user-facing rule and async guidance**

State that post-disposal assignment is inert before equality or user callbacks, that cancellation remains necessary for resource control, and that modeled composites/forwarders/read-only wrappers require no separate call pattern. Add a FormVM note that the snapshot, validation errors, dirty state, and commands remain terminal.

- [ ] **Step 2: Regenerate through repository tools**

Run: `uv --project langs/python run python -m scripts.docs.build_docs --site --wiki`

Expected: `generated/site/` and `generated/wiki/` are rebuilt solely from `docs/manifest.yaml` canonical sources and `mkdocs.yml` is regenerated.

- [ ] **Step 3: Verify all docs surfaces**

Run:

```bash
uv --project langs/python run python -m scripts.docs.check_docs
uv --project langs/python run python -m scripts.docs.validate_diagrams
uv --project langs/python run mkdocs build --strict
uv --project langs/python run python -m scripts.docs.push_wiki --check
```

Expected: all generators are idempotent and every check passes without architecture-diagram changes.

### Task 6: Prove consumer applicability without pushing

**Files:**

- Temporary clone only: DayDreams files returned by `rg -n "VMx|zombie|disposed|cancel|late|model" .` after reading that repository's `AGENTS.md`.
- No VMx repository files are produced by this task.

**Interfaces:**

- Consumes: local VMx ticket worktree and DayDreams' documented build/test workflow.

- Produces: issue/PR evidence showing VMx-specific late-model defense can be removed while resource cancellation remains.

- [ ] **Step 1: Clone DayDreams into a temporary directory and read its instructions**

Run `pilot_root=$(mktemp -d) && gh repo clone thekaveh/DayDreams "$pilot_root/DayDreams"`, then read every applicable `AGENTS.md`; never use or modify an existing consumer checkout.

- [ ] **Step 2: Point the consumer at this VMx worktree**

Run `rg -n "VMx|zombie|disposed|cancel|late|model" .` in the clone, inspect the matching dependency manifest and guard, and point that manifest to `/Users/kaveh/repos/VMx-worktrees/issue-141` using the ecosystem's existing local-path dependency syntax. Remove only a condition whose sole purpose is to suppress a late VMx model assignment after disposal; leave every task/network/render cancellation call intact.

- [ ] **Step 3: Run the consumer's focused and full applicable checks**

Expected: unchanged behavior and green tests/build. Record commit SHA, exact commands, results, and any environmental skip. Delete the temporary clone after capturing evidence; never commit or push it.

### Task 7: Run full gates and prepare the ticket branch

**Files:**

- Modify: only files listed by Tasks 1–5 plus the committed design and plan documents.

**Interfaces:**

- Consumes: complete code, spec, tests, metadata, docs, and consumer evidence.

- Produces: a clean, reviewable branch ready for PR to `develop`.

- [ ] **Step 1: Run the exact flavor gates**

Run:

```bash
cd langs/python && uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy --strict src/vmx
cd langs/csharp && dotnet restore VMx.sln --locked-mode && dotnet build VMx.sln -c Release --no-restore && dotnet test VMx.sln -c Release --no-build && dotnet format VMx.sln --verify-no-changes
cd langs/typescript && npm run sync-fixtures && npm run typecheck && npm run typecheck:tests && npm run lint && npm run build && npm test && npm audit --package-lock-only --audit-level=low
cd langs/swift && swift build -c release && swift test
cd langs/rust && cargo fmt --all -- --check && cargo clippy --all-targets --all-features -- -D warnings && cargo test --all-features && cargo doc --all-features --no-deps && cargo package --allow-dirty
```

Expected: every available gate passes. The only anticipated local skip is `swift test` when the machine reports `no such module 'XCTest'`; macOS CI must then pass it.

- [ ] **Step 2: Run repository-wide gates**

Run:

```bash
uv --project langs/python run pytest tools/tests/ -q
uv --project langs/python run python tools/check-version-consistency.py
uv --project langs/python run python tools/check-python-fixture-sync.py
uv --project langs/python run python tools/check-swift-fixture-sync.py
uv --project langs/python run python tools/check-conformance-coverage.py --require csharp --require python --require typescript --require swift --require rust
uv --project langs/python run python -m scripts.docs.check_docs
uv --project langs/python run python -m scripts.docs.validate_diagrams
uv --project langs/python run mkdocs build --strict
pre-commit run --all-files
git diff --check
```

Expected: all commands pass and the coverage tool reports 340/340 for each flavor.

- [ ] **Step 3: Inspect the final patch**

Run: `git status --short && git diff --stat origin/develop...HEAD && git diff --check && git diff origin/develop...HEAD`

Expected: only #141 files, no secrets/temp outputs, no fixture drift, no unexplained behavior/API changes, and exactly one real `DISP-014` marker per flavor.

- [ ] **Step 4: Commit the implementation**

```bash
git add spec docs/content generated mkdocs.yml README.md compatibility-matrix.md langs/csharp langs/python langs/typescript langs/swift langs/rust
git add -f docs/superpowers/plans/2026-07-11-post-dispose-modeled-assignment.md
git commit -m "fix: make disposed modeled assignment inert (#141)"
```

Expected: hooks pass and the branch is clean. Then follow the active goal's develop PR, green-CI/review, squash merge, develop→main promotion PR, live-doc verification, issue/card completion, and worktree cleanup flow before selecting #128.
