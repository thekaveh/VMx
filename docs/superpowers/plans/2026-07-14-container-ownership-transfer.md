# Container Ownership Transfer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement single-owner, automatic, atomic child transfer for composite and group containers in all five VMx flavors, including a usable weak Rust parent link.

**Architecture:** Each flavor adds an internal parent-ownership protocol and a one-shot transfer token. A destination validates first, asks the old parent to detach without publishing, attaches and constructs the child, then commits notifications in remove-before-add order; failure rolls the token back. Rust stores a weak type-erased parent owner instead of an authoritative numeric ID, while preserving `parent_id()` as a derived compatibility accessor.

**Tech Stack:** Markdown specification and ADRs; C#/.NET/System.Reactive; Python/reactivex/pytest; TypeScript/rxjs/Vitest; Swift/Combine/XCTest; Rust/std synchronization/cargo.

## Global Constraints

- `spec/` is the source of truth; every behavioral spec edit requires a new ADR in the same change.
- A new conformance ID requires real markers and coverage in C#, Python, TypeScript, Swift, and Rust.
- Parent links remain internal and consumer-non-settable.
- Transfers never destruct or dispose a child.
- Reactive dependencies remain System.Reactive, reactivex, rxjs, Combine, and VMx-owned Rust streams respectively.
- Public names remain idiomatic: PascalCase C#, snake_case Python/Rust, camelCase TypeScript/Swift.
- Stay on `codex/overnight-maintenance`; do not create worktrees, switch branches, touch submodules, or push before terminal validation.
- Use numbered headings in current-facing documentation and regenerate the MkDocs site and GitHub wiki from canonical sources.

______________________________________________________________________

### Task 1: Normative ownership contract

**Files:**

- Create: `spec/ADRs/0107-atomic-container-ownership-transfer.md`
- Modify: `spec/ADRs/README.md`
- Modify: `spec/02-lifecycle.md`
- Modify: `spec/05-component-vm.md`
- Modify: `spec/06-composite-vm.md`
- Modify: `spec/07-group-vm.md`
- Modify: `spec/08-aggregate-vm.md`
- Modify: `spec/12-conformance.md`
- Modify: `spec/VERSION`

**Interfaces:**

- Produces: `COMP-038` cross-parent transfer, `COMP-039` duplicate/cycle rejection, `COMP-040` transfer rollback, and `COMP-041` remove-before-add observation order.

- Produces: specification version `3.21.0`.

- [ ] **Step 1: Add the accepted ADR**

Record automatic transfer, one-parent membership, weak/non-owning child-to-parent links, no lifecycle transition on detach, staged notifications, rollback, fixed-aggregate rejection, and the rejected alternatives of fail-until-explicit-remove and DAG membership.

```markdown
# ADR 0107 — Transfer container ownership atomically

**Status:** Accepted (2026-07-14)
**Spec version:** introduced in 3.21.0
```

- [ ] **Step 2: Define the contract in the source chapters**

State this algorithm exactly: validate destination and ancestry; stage-detach from a different mutable parent; attach and auto-construct; commit old removal before new addition; otherwise restore old parent/index/current state and publish no membership event. State that same-parent duplicates and cycles fail without mutation and aggregate slots reject already-owned components.

- [ ] **Step 3: Add four conformance clauses**

Use identity-distinct containers and assert membership, parent-derived selection, lifecycle preservation, event ordering, and complete rollback. Each clause must cover both `CompositeVM` and `GroupVM` in one test group per flavor.

- [ ] **Step 4: Bump and format the specification**

Run:

```bash
pre-commit run mdformat --files spec/02-lifecycle.md spec/05-component-vm.md spec/06-composite-vm.md spec/07-group-vm.md spec/08-aggregate-vm.md spec/12-conformance.md spec/ADRs/0107-atomic-container-ownership-transfer.md spec/ADRs/README.md
```

Expected: all hooks pass after any automatic formatting.

### Task 2: C# transfer token and conformance

**Files:**

- Modify: `langs/csharp/src/VMx/Components/ComponentVMBase.cs`
- Modify: `langs/csharp/src/VMx/Composites/CompositeVMBase.cs`
- Modify: `langs/csharp/src/VMx/Groups/GroupVMBase.cs`
- Modify: `langs/csharp/tests/VMx.Conformance.Tests/CompositeVMConformanceTests.cs`
- Modify: `langs/csharp/tests/VMx.Conformance.Tests/GroupVMConformanceTests.cs`

**Interfaces:**

- Produces: internal `IParentCompositeVM.Owner`, `OwnerParent`, `ContainsChild`, and `DetachForTransfer`.

- Produces: internal one-shot `ParentTransferToken` with `Commit()` and `Rollback()`.

- [ ] **Step 1: Write failing COMP-038 through COMP-041 tests**

Add traits for all four IDs. Exercise composite-to-group, group-to-composite, duplicate and self/ancestor rejection, auto-construction failure, original index/current restoration, and observed `Remove` then `Add` events.

```csharp
[Fact, Trait("Conformance", "COMP-038")]
public void Add_Transfers_Child_From_Previous_Parent()
{
    oldParent.Add(child);
    newParent.Add(child);
    oldParent.Should().NotContain(child);
    newParent.Should().ContainSingle(x => ReferenceEquals(x, child));
}
```

- [ ] **Step 2: Run the focused tests and capture failure**

Run:

```bash
dotnet test langs/csharp/VMx.sln --filter "Conformance=COMP-038|Conformance=COMP-039|Conformance=COMP-040|Conformance=COMP-041"
```

Expected before implementation: at least COMP-038 fails because the old parent retains the child.

- [ ] **Step 3: Add the internal ownership protocol**

Use these responsibilities without exposing them publicly:

```csharp
internal interface IParentCompositeVM
{
    IComponentVM Owner { get; }
    IParentCompositeVM? OwnerParent { get; }
    bool ContainsChild(IComponentVM child);
    ParentTransferToken DetachForTransfer(IComponentVM child);
}
```

`ParentTransferToken` captures the typed reinsertion callback, old index/current state, and deferred removal publication. It permits exactly one `Commit()` or `Rollback()`.

- [ ] **Step 4: Route Add, Insert, and index replacement through transfer**

Prevalidate index, duplicate identity, and the destination's parent chain. Stage the old detach, mutate and auto-construct, then commit old removal before raising destination addition. Catch any failure, undo destination state, roll back the token, and rethrow the original exception.

- [ ] **Step 5: Make factory/bulk population transactional**

Retain transfer tokens until the full population succeeds. On failure, remove newly attached children in reverse order and roll back tokens in reverse order. Do not mark lazy group population complete until commit.

- [ ] **Step 6: Run focused and C# suites**

Run the focused command, then locked restore, Release build/test, and format. Expected: four new IDs pass and existing 935 tests remain green before new-test count adjustment.

### Task 3: Python transfer token and conformance

**Files:**

- Modify: `langs/python/src/vmx/components/base.py`
- Modify: `langs/python/src/vmx/composites/composite_vm.py`
- Modify: `langs/python/src/vmx/groups/group_vm.py`
- Modify: `langs/python/tests/conformance/test_composite_vm.py`
- Modify: `langs/python/tests/conformance/test_group_vm.py`

**Interfaces:**

- Produces: `_ParentContainer` ownership methods and `_ParentTransfer` token.

- Consumes: `COMP-038` through `COMP-041`.

- [ ] **Step 1: Write failing pytest conformance tests**

```python
@pytest.mark.conformance("COMP-038")
def test_add_transfers_child_from_previous_parent() -> None:
    old_parent.add(child)
    new_parent.add(child)
    assert list(old_parent) == []
    assert list(new_parent) == [child]
```

Include group/composite crossings, identity duplicates, cycle rejection, invalid-index prevalidation, construction failure rollback, selection restoration, and event order.

- [ ] **Step 2: Run focused tests and capture failure**

Run:

```bash
uv --project langs/python run pytest langs/python/tests/conformance/test_composite_vm.py langs/python/tests/conformance/test_group_vm.py -k 'COMP_038 or COMP_039 or COMP_040 or COMP_041' -q
```

Expected before implementation: transfer and rollback assertions fail.

- [ ] **Step 3: Implement `_ParentTransfer`**

```python
@dataclass(slots=True)
class _ParentTransfer:
    commit_removal: Callable[[], None]
    restore: Callable[[], None]
    _finished: bool = False
```

Extend the internal parent protocol with owner identity, owner-parent traversal, membership lookup, and staged detach. Group adaptors delegate to their owning group.

- [ ] **Step 4: Make all mutation paths atomic**

Add shared `_begin_child_transfer` validation to composite and group operations. Preserve Python's documented insertion-index normalization before detaching. Roll back list membership, `_parent`, `_current`, `is_current`, and lazy-population state on every exception.

- [ ] **Step 5: Run focused and Python gates**

Run pytest, Ruff, formatting, and strict mypy. Expected: all pass with four new markers reported.

### Task 4: TypeScript transfer token and conformance

**Files:**

- Modify: `langs/typescript/src/components/componentVMBase.ts`
- Modify: `langs/typescript/src/composites/compositeVMBase.ts`
- Modify: `langs/typescript/src/groups/groupVM.ts`
- Modify: `langs/typescript/tests/conformance/compositeVM.test.ts`
- Modify: `langs/typescript/tests/conformance/groupVM.test.ts`

**Interfaces:**

- Produces: internal `IOwningParentVM` and `ParentTransfer` token while preserving the exported selection-only `IParentVM`.

- Consumes: `COMP-038` through `COMP-041`.

- [ ] **Step 1: Write failing Vitest conformance tests**

```typescript
describe("COMP-038", () => {
  it("transfers a child from its previous parent", () => {
    oldParent.add(child);
    newParent.add(child);
    expect(oldParent.snapshot()).toEqual([]);
    expect(newParent.snapshot()).toEqual([child]);
  });
});
```

Use strict identity and record collection events from both parents.

- [ ] **Step 2: Run focused tests and capture failure**

Run `npx vitest run -t 'COMP-038|COMP-039|COMP-040|COMP-041'`; expected: old-parent membership and rollback failures.

- [ ] **Step 3: Implement the ownership token**

Add internal `IOwningParentVM` with owner identity, owner-parent traversal, `containsChild`, and `detachForTransfer`. Keep the exported `IParentVM` selection surface unchanged; `ComponentVMBase` stores a separate private ownership parent. A one-shot token stores closures for deferred removal publication and exact restoration; group-parent adaptors delegate to `GroupVM`.

- [ ] **Step 4: Route mutation and population through staged transfer**

Validate indices before detachment, reject duplicate identity/cycles, undo destination membership on `_maybeAutoConstruct` failure, and defer both parents' external callbacks until commit.

- [ ] **Step 5: Run TypeScript gates**

Run fixture sync, both typechecks, lint, build, tests, and audit. Expected: all pass and no emitted API declaration exposes the ownership helpers beyond their existing internal surface.

### Task 5: Swift throwing mutation parity

**Files:**

- Modify: `langs/swift/Sources/VMx/Lifecycle/ComponentVMBase.swift`
- Modify: `langs/swift/Sources/VMx/Composites/CompositeVM.swift`
- Modify: `langs/swift/Sources/VMx/Groups/GroupVM.swift`
- Modify: `langs/swift/Sources/VMx/Forwarding/ForwardingCompositeVM.swift`
- Modify: `examples/swift/notes-showcase/Sources/NotesShowcaseCore/ViewModels/NotesViewVM.swift`
- Modify: `langs/swift/Tests/VMxTests/AggregateChangeStreamConformanceTests.swift`
- Modify: `langs/swift/Tests/VMxTests/AutoConstructOnAddTests.swift`
- Modify: `langs/swift/Tests/VMxTests/BatchUpdateTests.swift`
- Modify: `langs/swift/Tests/VMxTests/CompositeCollectionChangedTests.swift`
- Modify: `langs/swift/Tests/VMxTests/CompositeCrudParentTests.swift`
- Modify: `langs/swift/Tests/VMxTests/CompositeVMTests.swift`
- Modify: `langs/swift/Tests/VMxTests/DisposalInvariantTests.swift`
- Modify: `langs/swift/Tests/VMxTests/FilteredCompositeVMTests.swift`
- Modify: `langs/swift/Tests/VMxTests/GroupVMTests.swift`
- Modify: `langs/swift/Tests/VMxTests/ThreadingTests.swift`
- Modify: `langs/swift/Tests/VMxTests/TokenPagedCompositionTests.swift`
- Modify: `langs/swift/Tests/VMxTests/VMCollectionMoveConformanceTests.swift`

**Interfaces:**

- Produces: internal weak `OwnershipParentVM` and `ParentTransfer` token while preserving public `ParentVM`.

- Produces: catchable `ContainerOwnershipError` for duplicate/cycle failures and throwing mutation methods where failure was previously trapped.

- [ ] **Step 1: Write failing XCTest conformance cases**

```swift
/// COMP-038 — a new parent atomically takes ownership from the old parent.
func testCrossParentTransfer() throws {
    try oldParent.add(child)
    try newParent.add(child)
    XCTAssertTrue(oldParent.snapshot().isEmpty)
    XCTAssertTrue(newParent.snapshot().first === child)
}
```

Cover all four IDs and both container kinds.

- [ ] **Step 2: Compile to demonstrate the missing throwing contract**

Run `swift test --package-path langs/swift --filter 'COMP-03'`. Expected before implementation: test compile failures because mutation methods are nonthrowing and do not transfer.

- [ ] **Step 3: Add weak ownership and staged transfer**

Add internal `OwnershipParentVM` with owner identity, owner-parent traversal, membership lookup, and staged detach. Preserve the public selection-only `ParentVM`; `ComponentVMBase` stores a second weak ownership-parent reference. `ParentTransfer` retains restoration closures but only weakly references parent owners. Resume any waiter or publish any event only after releasing state locks.

- [ ] **Step 4: Convert mutation paths to catchable throws**

Make add/insert/replace propagate ownership and auto-construction failures instead of `assertionFailure`. Update the listed forwarding, example, and test call sites explicitly: library/example paths propagate with `try`, test methods become throwing and use `try`, and the one intentionally best-effort UI refresh path catches and records its established error notification.

- [ ] **Step 5: Run Swift gates**

Run root and nested release builds and tests where XCTest is available. On this host, record the exact full-Xcode limitation if tests remain unavailable; builds must still pass.

### Task 6: Rust weak parent owner and rollback token

**Files:**

- Modify: `langs/rust/src/lib.rs`
- Modify: `langs/rust/tests/conformance/composite_vm.rs`
- Modify: `langs/rust/tests/conformance/group_vm.rs`

**Interfaces:**

- Produces: doc-hidden Rust infrastructure `ParentHandle { id, owner: Weak<dyn ParentOwner> }` stored in `ComponentCore` and exposed only as required by the public `VmNode` implementer contract.

- Produces: object-safe `ParentOwner::detach_for_transfer(child_id) -> VmxResult<Box<dyn TransferRollback>>`.

- Preserves: `VmNode::parent_id() -> Option<usize>` as a derived compatibility accessor.

- [ ] **Step 1: Write failing Rust conformance tests**

```rust
/// COMP-038 — adding to a new parent transfers ownership atomically.
#[test]
fn new_parent_removes_child_from_old_parent() {
    old_parent.add(child.clone()).unwrap();
    new_parent.add(child.clone()).unwrap();
    assert!(old_parent.items().is_empty());
    assert_eq!(new_parent.items(), vec![child]);
}
```

Add event-order, duplicate/cycle, rollback, and weak-cycle-drop probes.

- [ ] **Step 2: Run focused tests and capture failure**

Run `cargo test --manifest-path langs/rust/Cargo.toml --test conformance 'new_parent_removes_child' -- --exact`; expected: old parent still contains the child.

- [ ] **Step 3: Replace authoritative `parent_id` state**

Store an optional `ParentHandle` in `ComponentState`. `set_parent_id` must no longer be used by containers; container wiring calls an internal `set_parent_handle`. `parent_id()` upgrades the weak owner and returns its stable ID, or clears/returns `None` if the owner is gone.

- [ ] **Step 4: Add type-erased parent coordinators**

Each composite/group owns an `Arc` coordinator that implements `ParentOwner` using cloned shared collection/current state. The coordinator itself is strongly held by the parent and only weakly by children. The rollback token owns the removed typed child, index, current flag, and deferred publication action.

- [ ] **Step 5: Implement atomic mutations and ancestry checks**

Prevalidate index and destination ancestry; reject same-destination identity; stage old detach; attach/construct; commit or restore. Never hold a parent mutex while invoking construction, hub delivery, or collection subscribers.

- [ ] **Step 6: Run Rust gates**

Run fmt, clippy with `-D warnings`, unit/conformance/doc tests, docs, package, and fresh-consumer smoke. Expected: all pass and the drop probe proves no ownership `Arc` cycle.

### Task 7: Versions, changelogs, and three documentation surfaces

**Files:**

- Modify: `compatibility-matrix.md`
- Modify: `langs/csharp/src/VMx/VMx.csproj`
- Modify: `langs/python/src/vmx/__about__.py`
- Modify: `langs/typescript/package.json`
- Modify: `langs/typescript/package-lock.json`
- Modify: `langs/typescript/src/version.ts`
- Modify: `langs/swift/Sources/VMx/Version.swift`
- Modify: `langs/rust/Cargo.toml`
- Modify: `langs/rust/Cargo.lock`
- Modify: `langs/csharp/CHANGELOG.md`
- Modify: `langs/python/CHANGELOG.md`
- Modify: `langs/typescript/CHANGELOG.md`
- Modify: `langs/swift/CHANGELOG.md`
- Modify: `langs/rust/CHANGELOG.md`
- Modify: `README.md`
- Modify: `spec/README.md`
- Modify: `langs/csharp/README.md`
- Modify: `langs/python/README.md`
- Modify: `langs/typescript/README.md`
- Modify: `langs/swift/README.md`
- Modify: `langs/rust/README.md`
- Modify: `docs/content/primitives/viewmodel-families/component-family.md`
- Modify: `docs/content/primitives/viewmodel-families/composite-family.md`
- Modify: `docs/content/primitives/viewmodel-families/group-family.md`
- Modify: `docs/content/primitives/viewmodel-families/aggregate-family.md`
- Regenerate: MkDocs site and GitHub wiki outputs
- Modify: architecture diagram sources/outputs only if ownership arrows are now inaccurate

**Interfaces:**

- Consumes: spec `3.21.0` and final public API impact.

- Produces: synchronized minimum-spec declarations and current package versions.

- [ ] **Step 1: Apply SemVer deliberately**

Bump spec to `3.21.0`; bump additive/runtime-error flavors by their policy. Treat Swift's new throwing signatures as source-breaking and apply its required major package version. Update Rust for the internal parity feature and any public trait compatibility impact. Use repository version scripts rather than hand-editing generated lock data.

- [ ] **Step 2: Update changelogs and compatibility claims**

Describe automatic transfer, rollback, duplicate/cycle rejection, and Rust weak-parent parity. If the four planned IDs remain the final catalog delta, update the count to 395 library IDs and 400 total IDs; otherwise use the exact count printed by `tools/check-conformance-coverage.py`.

- [ ] **Step 3: Update canonical docs and regenerate**

Explain single ownership, automatic transfer, and non-disposal. Run the repository's docs generator, site checker, wiki exporter, link checker, and drift checks.

- [ ] **Step 4: Validate diagrams**

Run canonical diagram generation with `--check` and the architecture-diagram validator. If any diagram encodes the old relationship, edit its canonical source, regenerate all required formats, and rerun validation.

### Task 8: Completion verification and commit

**Files:**

- Modify: `/tmp/vmx-overnight-maintenance-log.md` outside the repository with pass/finding evidence.

**Interfaces:**

- Produces: one verified maintenance commit for the ownership finding.

- [ ] **Step 1: Run cross-flavor conformance coverage**

Run:

```bash
uv --project langs/python run python tools/check-conformance-coverage.py --require csharp --require python --require typescript --require swift --require rust
uv --project langs/python run pytest tools/tests/ -q
```

Expected: every library ID is covered in all five flavors and tool tests pass.

- [ ] **Step 2: Run every applicable full gate**

Run all language, docs/site/wiki, fixture-sync, version, package, examples, audit, pre-commit, and `git diff --check` commands required by `AGENTS.md` and the overnight-maintenance specification. Record exact evidence and any environment-only skip.

- [ ] **Step 3: Review the final diff**

Confirm no unrelated files, generated drift, secrets, submodule changes, or public surface changes beyond the approved design.

- [ ] **Step 4: Commit the verified fix**

```bash
git add spec README.md compatibility-matrix.md langs/csharp langs/python langs/typescript langs/swift langs/rust docs/content docs/assets
git commit -m "fix: transfer container ownership atomically"
```

Expected: hooks pass and the worktree becomes clean. Do not push yet; the overnight loop pushes only after its terminal condition.
