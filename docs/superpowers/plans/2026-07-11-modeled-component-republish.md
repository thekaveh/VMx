# Explicit Modeled-Component Republish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a narrow, allocation-free modeled-component republish operation with identical observable behavior in all five VMx flavors.

**Architecture:** Writable, read-only, and forwarding modeled leaf components expose one idiomatically named operation that delegates to the existing dual-channel property-notification helper for the model property. It does not assign, compare, recompute the modeled hint, or invoke model callbacks. Chapter 05, ADR-0093, and `CVM-010` define the portable contract; canonical docs generate the repository, Pages, and wiki mirrors.

**Tech Stack:** Markdown specification/ADR, C#/.NET + System.Reactive, Python + reactivex, TypeScript + rxjs/Vitest, Swift + Combine/XCTest, Rust + VMx rxrust facade, MkDocs documentation tooling.

## Global Constraints

- Work only in `/Users/kaveh/repos/VMx-worktrees/issue-89` on `codex/issue-89-explicit-model-republish`.
- `spec/` is the behavior source of truth; the chapter change and ADR-0093 land together.
- Public conceptual shape is identical across flavors: `RepublishModel`, `republish_model`, `republishModel`, `republishModel`, `republish_model`.
- Cover writable, read-only, and forwarding modeled leaf components; do not add the API to `FormVM`, modeled composites, `DerivedProperty`, or non-modeled components.
- Preserve model identity/value and cached modeled hint; do not evaluate equality, run the hinter, or invoke `OnModelChanged`.
- Emit through the existing helper exactly once using `"Model"` in C# and `"model"` elsewhere; do not duplicate ordering or lifecycle logic.
- Stable flavors advance 3.12.0→3.13.0; Rust advances 0.12.0→0.13.0 and declares spec 3.13.0.
- Add exactly one real `CVM-010` marker per full-parity flavor; counts advance 341→342 library and 346→347 total.
- Generated docs are produced from `docs/content`; never hand-edit generated mirrors.
- Swift XCTest requires full Xcode; local release build plus macOS CI is authoritative when `XCTest` is unavailable.
- The DayDreams pilot uses a disposable clone, never the user's dirty checkout, and never pushes.

______________________________________________________________________

### Task 1: Specify the public contract

**Files:**

- Create: `spec/ADRs/0093-explicit-modeled-component-republish.md`
- Modify: `spec/ADRs/README.md`
- Modify: `spec/05-component-vm.md`
- Modify: `spec/12-conformance.md`
- Modify: `spec/VERSION`

**Interfaces:**

- Consumes: chapter 05 §2.3 dual-channel helper and ADR-0091 disposal admission.

- Produces: spec 3.13.0 contract and catalog key `CVM-010` used by every flavor test.

- [ ] **Step 1: Add ADR-0093**

Record the dedicated API decision, writable/read-only/forwarding scope, FormVM exclusion, exact no-mutation/no-hint/no-callback semantics, helper ordering, null-hub and re-entry behavior, 3.13.0 versioning, and rejected force/touch/copy alternatives.

- [ ] **Step 2: Extend chapter 05**

Add the operation to both modeled variant surfaces and specify:

```text
republish_model():
  retain Model identity/value and ModeledHint
  do not compare, assign, recompute, or call OnModelChanged
  call the dual-channel helper once for the idiomatic model name
  remain inert after disposal
```

State that forwarding delegates to the wrapped sender/stream and that re-entry follows §2.3 rather than defining a new global order.

- [ ] **Step 3: Add `CVM-010`**

Catalog one scenario covering writable state preservation and pair order/count, read-only and forwarding availability, null hub, disposal, re-entry, and unchanged ordinary setter behavior. Update chapter 05's conformance summary.

- [ ] **Step 4: Advance the spec version**

Set `spec/VERSION` to `3.13.0` and add ADR-0093 to the ledger.

- [ ] **Step 5: Verify spec discipline inputs**

Run:

```bash
git diff --name-status origin/develop...HEAD -- spec/
rg -n "ADR-0093|CVM-010|3\.13\.0" spec
```

Expected: the chapter edit is paired with a newly added ADR-0093, and there is
one catalog definition for `CVM-010`. The repository has no standalone local
spec-discipline script; its CI workflow and Task 7's authoritative conformance
coverage check validate the completed diff after all five stubs exist.

- [ ] **Step 6: Commit**

```bash
git add spec
git commit -m "spec: define explicit model republish for #89"
```

### Task 2: Add red `CVM-010` conformance tests

**Files:**

- Modify: `langs/csharp/tests/VMx.Conformance.Tests/ComponentVMConformanceTests.cs`
- Modify: `langs/python/tests/conformance/test_component_vm.py`
- Modify: `langs/typescript/tests/conformance/componentVM.test.ts`
- Modify: `langs/swift/Tests/VMxTests/ComponentVMTests.swift`
- Modify: `langs/rust/tests/conformance/component_vm.rs`

**Interfaces:**

- Consumes: the exact five API spellings from Task 1.

- Produces: one discoverable `CVM-010` marker per flavor and behavioral expectations that initially fail to compile/typecheck.

- [ ] **Step 1: Cover the writable operation**

In each flavor build a reference-shaped model, a counting hinter, and a counting model callback where supported. Subscribe to hub and local channels, call republish, and assert:

```text
same model identity/value
same modeled hint
hinter count unchanged
callback count unchanged
trace == [hub:model, local:model]
```

Rust has no modeled callback surface, so prove identity/value, hint, and pair behavior without inventing one.

- [ ] **Step 2: Cover variants and boundaries**

Within the same catalog test or adjacent plain helpers, assert read-only publication, forwarding delegation to the wrapped sender/local stream, null-hub local emission, disposed silence, guarded one-level re-entry yielding two complete pairs, equal assignment silence, and unequal assignment's existing one-pair behavior.

- [ ] **Step 3: Run the red tests**

Run:

```bash
dotnet test langs/csharp/tests/VMx.Conformance.Tests/VMx.Conformance.Tests.csproj -c Release --filter 'Conformance=CVM-010'
uv --project langs/python run pytest langs/python/tests/conformance/test_component_vm.py -k CVM_010 -q
npm --prefix langs/typescript test -- --run tests/conformance/componentVM.test.ts -t CVM-010
cargo test --manifest-path langs/rust/Cargo.toml --test conformance component_vm
swift build --package-path langs/swift -c release
```

Expected: C#/Python/TypeScript/Rust fail because republish APIs do not exist; Swift source compiles only after implementation and XCTest remains deferred locally.

- [ ] **Step 4: Commit the red tests**

```bash
git add langs/*/tests langs/swift/Tests
git commit -m "test: specify modeled component republish for #89"
```

### Task 3: Implement the five-flavor API

**Files:**

- Modify: `langs/csharp/src/VMx/Components/IComponentVMOfM.cs`
- Modify: `langs/csharp/src/VMx/Components/IReadonlyComponentVM.cs`
- Modify: `langs/csharp/src/VMx/Components/ComponentVMBaseOfM.cs`
- Modify: `langs/csharp/src/VMx/Components/ReadonlyComponentVM.cs`
- Modify: `langs/csharp/src/VMx/Forwarding/ForwardingComponentVM.cs`
- Modify: `langs/python/src/vmx/components/protocols.py`
- Modify: `langs/python/src/vmx/components/component_vm.py`
- Modify: `langs/python/src/vmx/components/readonly_component_vm.py`
- Modify: `langs/python/src/vmx/forwarding/component.py`
- Modify: `langs/typescript/src/components/types.ts`
- Modify: `langs/typescript/src/components/componentVMOf.ts`
- Modify: `langs/typescript/src/components/readonlyComponentVMOf.ts`
- Modify: `langs/typescript/src/forwarding/forwardingComponentVM.ts`
- Modify: `langs/swift/Sources/VMx/Components/ComponentVMOf.swift`
- Modify: `langs/swift/Sources/VMx/Forwarding/ForwardingComponentVM.swift`
- Modify: `langs/rust/src/lib.rs`

**Interfaces:**

- Consumes: each flavor's existing dual-channel helper and disposal guard.

- Produces: the public API tested by `CVM-010` without new storage or dependencies.

- [ ] **Step 1: Implement C#**

Declare `void RepublishModel()` on both modeled interfaces. Implement writable and read-only behavior only as:

```csharp
public void RepublishModel() => NotifyPropertyChanged("Model");
```

Place the writable implementation on `ComponentVMBaseOfM<M>` so concrete writable components inherit it. Forwarding uses:

```csharp
public virtual void RepublishModel() => _wrapped.RepublishModel();
```

- [ ] **Step 2: Implement Python**

Add both protocol methods and these class methods:

```python
def republish_model(self) -> None:
    self._notify_property_changed("model")
```

Forwarding delegates with `self._wrapped.republish_model()`.

- [ ] **Step 3: Implement TypeScript**

Add `republishModel(): void` to `IComponentVMOf<M>`. Writable and read-only classes call:

```typescript
republishModel(): void {
  this._notifyPropertyChanged("model");
}
```

Forwarding delegates to `this._wrapped.republishModel()`.

- [ ] **Step 4: Implement Swift**

Add an open inherited operation to `ComponentVMOf`:

```swift
open func republishModel() {
    _notifyPropertyChanged("model")
}
```

`ReadonlyComponentVMOf` inherits it. Override it in `ForwardingComponentVM` to call `_wrapped.republishModel()` so notification identity and local delivery remain wrapped-target behavior.

- [ ] **Step 5: Implement Rust**

Add to `ComponentVm`:

```rust
pub fn republish_model(&self) {
    self.core.notify_property_changed("model");
}
```

Add delegating methods on `ReadonlyComponentVm` and `ForwardingComponentVm`.

- [ ] **Step 6: Run focused green verification**

Repeat Task 2's commands. Expected: all executable focused tests pass and Swift release build succeeds.

- [ ] **Step 7: Commit**

```bash
git add langs
git commit -m "feat: add explicit modeled component republish for #89"
```

### Task 4: Advance flavor metadata and parity claims

**Files:**

- Modify: `langs/csharp/src/VMx/VMx.csproj`
- Modify: `langs/python/src/vmx/__about__.py`
- Modify: `langs/typescript/package.json`
- Modify: `langs/typescript/package-lock.json`
- Modify: `langs/typescript/src/version.ts`
- Modify: `langs/swift/Sources/VMx/Version.swift`
- Modify: `langs/rust/Cargo.toml`
- Modify: `langs/rust/Cargo.lock`
- Modify: `README.md`
- Modify: `spec/README.md`
- Modify: `compatibility-matrix.md`
- Modify: `langs/csharp/README.md`
- Modify: `langs/python/README.md`
- Modify: `langs/typescript/README.md`
- Modify: `langs/swift/README.md`
- Modify: `langs/rust/README.md`
- Modify: `langs/csharp/CHANGELOG.md`
- Modify: `langs/python/CHANGELOG.md`
- Modify: `langs/typescript/CHANGELOG.md`
- Modify: `langs/swift/CHANGELOG.md`
- Modify: `langs/rust/CHANGELOG.md`

**Interfaces:**

- Consumes: spec 3.13.0 and 342-ID catalog.

- Produces: internally consistent package versions, locks, compatibility matrix, change logs, and count claims.

- [ ] **Step 1: Update package metadata through native tools**

Set stable versions/minimum spec to 3.13.0 and Rust to 0.13.0/spec 3.13.0. Run `npm install --package-lock-only` and `cargo check` to refresh locks rather than hand-editing generated lock content.

- [ ] **Step 2: Update release documentation**

Add bracketed Keep-a-Changelog entries naming ADR-0093/`CVM-010`, the exact republish semantics, and parity 342/342. Update root/spec/flavor README and compatibility matrix counts to 342 library / 347 total without rewriting historical claims.

- [ ] **Step 3: Verify metadata**

```bash
python3 tools/check-version-consistency.py
python3 tools/check-conformance-coverage.py
rg -n "3\.12\.0|0\.12\.0|341|346" README.md spec/README.md compatibility-matrix.md langs/*/README.md langs/*/CHANGELOG.md
```

Expected: version check passes; coverage reports 342/342 in all five flavors; remaining old values occur only in historical entries.

- [ ] **Step 4: Commit**

```bash
git add README.md spec/README.md compatibility-matrix.md langs
git commit -m "chore: advance VMx flavors for model republish #89"
```

### Task 5: Publish synchronized documentation

**Files:**

- Modify: `docs/content/primitives/viewmodel-families/component-family.md`
- Modify: generated files selected by `docs/manifest.yaml`, including `generated/site/primitives/viewmodel-families/component-family.md`, `generated/wiki/6-2-2-Component-Family.md`, and `mkdocs.yml` only if generation changes it.

**Interfaces:**

- Consumes: ADR-0093 and the implemented five-flavor API.

- Produces: synchronized canonical/in-repo, Pages, and wiki explanations.

- [ ] **Step 1: Document legitimate republish use**

Add a dedicated section with the five spellings, exact identity/hint/callback/order/disposal/null-hub semantics, forwarding/read-only scope, and this warning:

```text
Use republish only when observable state reachable through the retained model changed outside ordinary replacement. Do not use it to hide a model replacement or mutation that should be expressed through the normal assignment path.
```

- [ ] **Step 2: Regenerate both outputs**

```bash
uv --project langs/python run python -m scripts.docs.build_docs --site
uv --project langs/python run python -m scripts.docs.build_docs --wiki
```

- [ ] **Step 3: Run strict documentation gates**

```bash
uv --project langs/python run python -m scripts.docs.build_docs --site --check
uv --project langs/python run python -m scripts.docs.build_docs --wiki --check
uv --project langs/python run python -m scripts.docs.check_docs
uv --project langs/python run mkdocs build --strict
```

Expected: deterministic generation, links/drift clean, and strict site build succeeds.

- [ ] **Step 4: Commit**

```bash
git add docs/content generated mkdocs.yml
git commit -m "docs: explain explicit model republish for #89"
```

### Task 6: Prove the DayDreams consumer migration without pushing

**Files (disposable clone only):**

- Modify: `packages/viewmodel/src/worldVm.ts`
- Update: disposable clone's `vendor/VMx` reference to this completed VMx branch/commit.

**Interfaces:**

- Consumes: TypeScript `ComponentVMOf.republishModel()` from Task 3.

- Produces: evidence that the one allocation-only spread is removable with unchanged renderer behavior.

- [ ] **Step 1: Create a disposable clone**

Clone DayDreams outside both user checkouts, initialize its VMx dependency, and record its clean baseline SHA. Never stage, push, or alter `/Users/kaveh/repos/daydreams`.

- [ ] **Step 2: Establish a red consumer proof**

Add or adapt a focused trace assertion that expects `setHeightField` to republish through the dedicated API, then confirm it fails before the consumer source migration.

- [ ] **Step 3: Replace only the allocation workaround**

Change:

```typescript
if (cellVm) cellVm.model = { ...cellVm.model };
```

to:

```typescript
if (cellVm) cellVm.republishModel();
```

Rewrite the nearby comment to describe the intentional external height-field repaint. Leave `applyManifestDelta` unchanged.

- [ ] **Step 4: Verify consumer behavior**

Run the focused renderer/viewmodel trace, relevant workspace typechecks, tests, and production builds discovered from the clone's package scripts. Record exact totals and any pre-existing warnings. Commit locally only if needed for a stable evidence SHA; do not push.

- [ ] **Step 5: Remove the disposable clone**

After recording evidence, delete only the temporary clone. Recheck the user's real DayDreams checkout SHA/status to prove it was untouched.

### Task 7: Full verification, review, and protected PR flow

**Files:**

- Review every change from `origin/develop...HEAD`.

**Interfaces:**

- Consumes: completed Tasks 1–6.

- Produces: green feature PR to `develop`, then green promotion PR from `develop` to `main`, released three-surface docs, and completed issue/card evidence.

- [ ] **Step 1: Run complete flavor gates**

Run the repository-prescribed C#, Python, TypeScript, Swift, and Rust restore/build/test/lint/type/format commands. Use Swift release build locally and require the macOS XCTest job in CI.

- [ ] **Step 2: Run repository gates**

Run tools tests, conformance coverage, version consistency, fixture sync checks, example contract checks, deterministic docs/wiki generation, strict MkDocs, diagram validation, spec discipline, and full pre-commit.

- [ ] **Step 3: Review against the issue**

Confirm exactly one `CVM-010` marker per flavor, no FormVM/comparator/non-modeled expansion, no changed ordinary assignment behavior, no secrets, no generated drift, and every changed line traces to #89.

- [ ] **Step 4: Feature PR to `develop`**

Push the issue branch, open a PR against `develop` with issue/ADR/test/pilot evidence, wait for all checks, resolve every thread, and squash-merge only when green.

- [ ] **Step 5: Promotion PR to `main`**

Open `develop`→`main`, require the exact squash commit and all checks, then merge with a merge commit. Verify the second parent is the develop commit and all post-main workflows pass.

- [ ] **Step 6: Verify publication and complete tracking**

Confirm the live Pages component-family page, native wiki page, and raw `main` source contain the republish contract. Post final issue evidence, set Status `Done` and Disposition `Completed`, clear priority/work order, remove the clean worktree/branch, and proceed to #88.
