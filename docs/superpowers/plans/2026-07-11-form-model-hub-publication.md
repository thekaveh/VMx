# FormVM Model Hub Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every accepted unequal FormVM model assignment publish exactly one
settled model property message on its hub, with portable equality, ordering,
re-entrancy, deny, reset, and disposal behavior.

**Architecture:** Keep each flavor's existing FormVM architecture and add a
prepare/commit/notify-last edit pipeline. C#, Python, TypeScript, and Swift send
from their standalone forms after validation and command invalidation; Rust gains
one private silent replacement seam so FormVm owns notification timing without
changing public ComponentVm behavior.

**Tech Stack:** Markdown specification and ADRs; C#/.NET/System.Reactive/xUnit;
Python/reactivex/pytest; TypeScript/RxJS/Vitest; Swift/Combine/XCTest;
Rust/rxrust facade/cargo tests; MkDocs and repository documentation generators.

## Global Constraints

- `spec/` is the behavior source of truth; numbered-spec changes require new
  ADR-0092 in the same PR.
- Public conceptual shape remains identical across C#, Python, TypeScript, Swift,
  and Rust, with property names `"Model"` / `"model"` per ADR-0006.
- No new public API, reactive dependency, local FormVM property stream, fixture,
  or architecture boundary is introduced.
- Direct assignment publishes only after model, validation/errors, and command
  state settle; validator failures retain their existing non-transactional behavior.
- Equal assignment uses the existing dirty-tracking equality and is a complete
  no-op; explicit equal-value republish remains #89.
- Post-dispose admission remains inert under #141 before null/equality/validation.
- Deny remains `FormRevertedMessage` then one model property message; approval
  reset does not publish a model hub message.
- Stable packages advance from 3.11.0 to 3.12.0; Rust advances from 0.11.0 to
  0.12.0 and every flavor declares spec 3.12.0.
- `FORM-030` is a real behavioral conformance test in all five flavors; library
  count advances 340→341 and total count advances 345→346.
- Canonical docs generate the in-repo, `.io`, and wiki surfaces; generated output
  is never hand-edited.
- Swift XCTest requires full Xcode; when unavailable locally, a release build is
  mandatory and macOS CI is authoritative.
- Tableau validation uses a temporary clone and never pushes consumer changes.

______________________________________________________________________

### Task 1: Define the normative FormVM transaction

**Files:**

- Create: `spec/ADRs/0092-form-model-hub-publication.md`
- Modify: `spec/ADRs/README.md`
- Modify: `spec/20-form-vm.md`
- Modify: `spec/12-conformance.md`
- Modify: `spec/VERSION`

**Interfaces:**

- Consumes: chapter 20 equality, validation, deny, approval-reset, and #141
  disposal admission contracts.

- Produces: spec 3.12.0 and catalog key `FORM-030` used by every flavor test.

- [ ] **Step 1: Add ADR-0092 and its index row**

Record Accepted status, date 2026-07-11, spec 3.12.0, the notify-last decision,
equality gating, property-name idioms, the private Rust replacement seam, deny and
reset boundaries, compatibility impact, alternatives, and `FORM-030`.

- [ ] **Step 2: Add the exact SetModel sequence to chapter 20**

Add this normative sequence to §5/§8:

```text
disposed admission → null rejection where applicable → live-model equality →
capture dirty/valid → install model → validation/errors → command invalidation →
one flavor-idiomatic model PropertyChangedMessage
```

State that equal candidates retain the current instance/value and run no validator,
command, or notification work. A synchronous hub observer must see the new model,
errors, validity, dirty state, and command state already settled.

- [ ] **Step 3: Pin deny and reset boundaries**

Clarify that deny emits exactly `FormReverted` then one model property message and
that reset-on-approved retains its current outcome channels without a model hub
message. Apply per-flavor naming to FORM-008 instead of treating `"Model"` as a
cross-language literal.

- [ ] **Step 4: Add FORM-030**

Append one catalog entry after FORM-029 with scenarios for changed/equal/disposed
assignments, final-state visibility, re-entrancy, null/default hub, exact counts,
deny order, and reset silence. Add the same ID to chapter 20 §11.

- [ ] **Step 5: Advance and verify the spec**

Set `spec/VERSION` to `3.12.0`, then run:

```bash
git diff --check
rg -n "ADR-0092|FORM-030|3\.12\.0" spec
```

Expected: the ADR index, chapter, catalog, and version all expose the new contract
without whitespace errors.

### Task 2: Add red FORM-030 tests in all five flavors

**Files:**

- Create: `langs/csharp/tests/VMx.Conformance.Tests/FORM_030_SetModelHubPublicationTests.cs`
- Create: `langs/python/tests/conformance/test_form_030_set_model_hub_publication.py`
- Create: `langs/typescript/tests/conformance/form-030-set-model-hub-publication.test.ts`
- Create: `langs/swift/Tests/VMxTests/FormVMSetModelHubPublicationTests.swift`
- Create: `langs/rust/tests/conformance/form_model_hub_publication.rs`
- Modify: `langs/rust/tests/conformance.rs`
- Modify: `langs/rust/tests/conformance/forms.rs`

**Interfaces:**

- Consumes: public FormVM constructors/builders, validators, errorsChanged,
  approve-command change streams, message hubs, deny, approval reset, and dispose.

- Produces: one discoverable `FORM-030` marker per flavor and corrected Rust
  FORM-008 exact-count/naming assertions.

- [ ] **Step 1: Cover accepted and equal assignment**

Each dedicated test uses a strict form whose initial model is invalid and whose
unequal replacement is valid. Record validator, errors, command, and hub events and
assert this trace:

```text
validate → errors → can_execute → model_message
```

In the model-message handler assert the live model is the replacement, errors are
empty, `IsValid` is true, `IsDirty` is true, and approval is enabled. Then pass a
distinct but equality-equal candidate and assert the retained model identity,
validator count, command count, and hub count do not change.

- [ ] **Step 2: Cover re-entrancy and disposal**

On the first unequal model message, synchronously call SetModel with a second
unequal value. Assert exactly two model messages, each handler sees its own settled
value, and the final form state is the nested value. Dispose a fresh form, invoke a
late assignment closure, and assert no equality, validation, command, state, or hub
work (composing with DISP-014).

- [ ] **Step 3: Cover null/default hub, deny, and reset**

Construct through each flavor's null/default-hub path and prove an unequal edit
settles without raising. On a hub-backed form, clear direct-edit observations,
execute deny, and assert one `FormReverted` followed by one idiomatic model change.
On a reset-on-approved form, clear the direct-edit message, approve, and assert the
reset model is installed with no new model property message.

- [ ] **Step 4: Strengthen Rust FORM-008**

Replace the legacy presence-only `"Model"` assertion with an exact ordered slice:

```rust
assert!(matches!(messages[0], Message::FormReverted(_)));
assert!(matches!(
    messages[1],
    Message::PropertyChanged(ref change) if change.property_name == "model"
));
assert_eq!(messages.len(), 2);
```

- [ ] **Step 5: Run focused tests and retain red evidence**

```bash
dotnet test langs/csharp/tests/VMx.Conformance.Tests/VMx.Conformance.Tests.csproj -c Release --filter 'Conformance=FORM-030'
uv --project langs/python run pytest langs/python/tests/conformance/test_form_030_set_model_hub_publication.py -q
npm --prefix langs/typescript test -- --run tests/conformance/form-030-set-model-hub-publication.test.ts
cargo test --manifest-path langs/rust/Cargo.toml --test conformance form_model_hub_publication
cd langs/swift && swift test --filter FormVMSetModelHubPublicationTests
```

Expected before implementation: C#/Python/TypeScript/Swift fail on the missing
model message; Rust fails ordering/exact-count/reset assertions. If local Swift
lacks XCTest, record that environment result and rely on macOS CI after a release
build.

### Task 3: Implement standalone FormVM notify-last pipelines

**Files:**

- Modify: `langs/csharp/src/VMx/Forms/FormVM.cs`
- Modify: `langs/python/src/vmx/forms/form_vm.py`
- Modify: `langs/typescript/src/forms/formVm.ts`
- Modify: `langs/swift/Sources/VMx/Forms/FormVM.swift`

**Interfaces:**

- Consumes: existing equality, revalidation, command-trigger, hub, and
  PropertyChangedMessage helpers.

- Produces: one model hub message after every accepted unequal edit; no new API.

- [ ] **Step 1: Add equality gating before dirty/validation work**

After the existing disposal and null guards, use:

```csharp
if (Equals(_model, model)) return;
```

```python
if self._model == model:
    return
```

```typescript
if (this.#equals(this.#model, model)) return;
```

```swift
if equals(_model, newModel) { return }
```

- [ ] **Step 2: Publish after command invalidation**

Keep existing assignment, revalidation, and trigger logic, then append exactly:

```csharp
_hub.Send(PropertyChangedMessage<FormVM<TM>>.Create(
    this, nameof(FormVM<TM>), nameof(Model)));
```

```python
self._hub.send(PropertyChangedMessage.create(
    sender=self, sender_name="FormVM", property_name="model"
))
```

```typescript
this.#hub.send(PropertyChangedMessage.create(this, "FormVM", "model"));
```

```swift
hub.send(PropertyChangedMessage(
    sender: self, senderName: "FormVM", propertyName: "model"
))
```

- [ ] **Step 3: Run focused and adjacent suites**

Run the four applicable FORM-030 commands plus existing FORM-001..029 and
post-dispose suites. Expected: new tests pass and deny/reset tests remain green.

### Task 4: Converge Rust FormVm notification ownership

**Files:**

- Modify: `langs/rust/src/lib.rs`
- Test: `langs/rust/tests/conformance/form_model_hub_publication.rs`
- Test: `langs/rust/tests/conformance/forms.rs`

**Interfaces:**

- Consumes: `ComponentVm<M>` retained model/core notifier and `FormVm<M>` form
  transaction.

- Produces: private `replace_model(&self, model: M) -> bool`; unchanged public
  `ComponentVm::set_model`; settled direct FormVm notification timing.

- [ ] **Step 1: Extract silent component replacement**

Move the current equality/lock mutation into:

```rust
fn replace_model(&self, model: M) -> bool {
    let mut current = lock(&self.model);
    if *current == model {
        false
    } else {
        *current = model;
        true
    }
}
```

Keep the existing ComponentVm terminal guard, hint comparison, and notifications
around this helper so all component tests remain unchanged.

- [ ] **Step 2: Make FormVm direct assignment notify last**

Capture previous approval state, return when `replace_model` is false, validate,
publish approval-state change, then call:

```rust
self.component.notify_property_changed("model");
```

- [ ] **Step 3: Silence internal reset and order deny explicitly**

Use `replace_model` for reset-on-approved without any model notifier. In revert,
replace silently, validate, send `FormReverted`, call
`notify_property_changed("model")`, then retain the current approval-state trigger
position. Remove the explicit legacy `"Model"` send.

- [ ] **Step 4: Verify Rust**

```bash
cargo fmt --manifest-path langs/rust/Cargo.toml -- --check
cargo clippy --manifest-path langs/rust/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path langs/rust/Cargo.toml --test conformance form_model_hub_publication
cargo test --manifest-path langs/rust/Cargo.toml --test conformance forms
```

Expected: exact notification counts/order pass and public ComponentVm tests stay
unchanged.

### Task 5: Publish versions, compatibility, and changelogs

**Files:**

- Modify: `langs/csharp/src/VMx/VMx.csproj`, `langs/csharp/README.md`, `langs/csharp/CHANGELOG.md`
- Modify: `langs/python/src/vmx/__about__.py`, `langs/python/README.md`, `langs/python/CHANGELOG.md`
- Modify: `langs/typescript/package.json`, `langs/typescript/package-lock.json`, `langs/typescript/src/version.ts`, `langs/typescript/README.md`, `langs/typescript/CHANGELOG.md`
- Modify: `langs/swift/Package.swift`, `langs/swift/Sources/VMx/Version.swift`, `langs/swift/README.md`, `langs/swift/CHANGELOG.md`
- Modify: `langs/rust/Cargo.toml`, `langs/rust/Cargo.lock`, `langs/rust/src/lib.rs`, `langs/rust/README.md`, `langs/rust/CHANGELOG.md`
- Modify: `compatibility-matrix.md`, `README.md`, `spec/README.md`, `AGENTS.md`

**Interfaces:**

- Consumes: completed spec 3.12.0 and 341-test catalog.

- Produces: consistent package/spec declarations and current-facing counts.

- [ ] **Step 1: Set exact versions**

Set C#/Python/TypeScript/Swift package and min-spec versions to `3.12.0`; set Rust
package to `0.12.0` and `MIN_SPEC_VERSION` to `3.12.0`. Update locks only through
their package tools.

- [ ] **Step 2: Add 2026-07-11 changelog entries**

Name ADR-0092, FORM-030, unequal assignment hub publication, equal-value gating,
settled notification ordering, and Rust deny/reset convergence. Explicitly note
that callers relying on silent unequal edits or equal-value replacement must adapt.

- [ ] **Step 3: Update current counts and compatibility rows**

Change 340/345 to 341/346 and current 3.11.0/0.11.0 claims to
3.12.0/0.12.0 while preserving historical release text.

- [ ] **Step 4: Verify metadata**

```bash
uv --project langs/python run python tools/check-version-consistency.py
python3 tools/check-conformance-coverage.py
rg -n "340|345|3\.11\.0|0\.11\.0" README.md compatibility-matrix.md spec/README.md langs/*/README.md AGENTS.md
```

Expected: consistency and coverage pass; remaining prior values are explicitly
historical rather than current-source claims.

### Task 6: Update and regenerate all documentation surfaces

**Files:**

- Modify: `docs/content/primitives/viewmodel-families/specialized/form-vm.md`
- Modify: `docs/content/primitives/disposal-contract.md`
- Modify: `docs/content/specification-conformance.md`
- Modify: `docs/content/installation.md`
- Modify generated mirrors selected by `docs/manifest.yaml`.

**Interfaces:**

- Consumes: canonical FORM-030 contract and current metadata.

- Produces: synchronized in-repo, Pages, and wiki documentation.

- [ ] **Step 1: Document the edit transaction**

Explain equality gating, notify-last state visibility, idiomatic property names,
re-entrancy, disposal, deny ordering, reset silence, and the distinction from
#89's future explicit republish.

- [ ] **Step 2: Regenerate canonical outputs**

Use the repository's docs build commands rather than editing generated files.

- [ ] **Step 3: Run strict documentation gates**

```bash
uv --project langs/python run python -m scripts.docs.build_docs --check
uv --project langs/python run python -m scripts.docs.check_docs
uv --project langs/python run python -m scripts.docs.push_wiki --dry-run
uv --project langs/python run mkdocs build --strict
uv --project langs/python run python docs/assets/diagrams/generate_diagrams.py --check
```

Expected: deterministic generation, links, diagrams, site, and wiki checks pass.
No diagram content should change.

### Task 7: Run the no-push Tableau pilot

**Files (temporary clone only):**

- Modify: `frontend/vendor/VMx` submodule checkout
- Modify: `frontend/view-model/src/appVm.ts`
- Modify: `frontend/view/react/src/components/CreatePanel.tsx`
- Modify: `frontend/view-model/tests/genesisBufferReset.test.ts`
- Modify: `frontend/view-model/tests/appRefreshDisposeLeak.test.ts`
- Modify: `frontend/view/react/tests/CreatePanel.test.tsx`
- Modify: `frontend/view/react/tests/CreatePanelReactive.test.tsx`

**Interfaces:**

- Consumes: local VMx 3.12.0 TypeScript package and Tableau's hub-backed store.

- Produces: consumer evidence only; no VMx or Tableau push.

- [ ] **Step 1: Create a disposable clone and point VMx at the ticket commit**

Clone Tableau with submodules, fetch the VMx worktree commit into the vendor
submodule, and install using the repository's locked workspace command.

- [ ] **Step 2: Remove the framework workaround**

Delete the `setGenesisModel` command/refresh explanation and route genesis field
edits directly through `app.genesis.setModel`. Preserve refreshes whose purpose is
unrelated shell projection/resource coordination.

- [ ] **Step 3: Add/adjust the consumer regression**

Keep the real-app controlled-input assertion and additionally count the shared hub
model message so the test proves the input and Create command update from FormVM's
own publication.

- [ ] **Step 4: Run Tableau verification and delete the clone**

Run its workspace typechecks and tests plus the focused CreatePanel suite. Record
commit, exact commands, counts, and diff summary on #128/PR; never push the pilot.

### Task 8: Full gates, review, and git-flow integration

**Files:** all changed files from Tasks 1–7.

**Interfaces:**

- Consumes: complete implementation, docs, and pilot evidence.

- Produces: green feature PR to `develop`, then green promotion PR to `main`.

- [ ] **Step 1: Run every applicable local gate**

Run full Python pytest/Ruff/mypy, C# restore/build/test/format, TypeScript
sync/typecheck/lint/build/test/audit, Swift release build/test when available,
Rust fmt/clippy/test/doc, repository tools, version/fixture/conformance checks,
docs gates, all-files pre-commit, `git diff --check`, and a secret scan. Document
only genuine environment skips with their exact error.

- [ ] **Step 2: Review the complete diff**

Verify every changed line maps to #128, FORM-030 appears exactly once per flavor,
generated docs are deterministic, no user files are touched, and no API from #89
has leaked into scope.

- [ ] **Step 3: Push and merge the feature PR**

Push `codex/issue-128-form-model-hub-publish`, open a PR to `develop` with issue,
TDD, pilot, docs, risks, and test evidence; wait for every check, fix failures,
resolve conversations, then squash-merge and delete the remote feature branch.

- [ ] **Step 4: Promote through a separate PR**

Confirm `origin/main..origin/develop` contains exactly the #128 squash commit,
open `develop`→`main` with `Closes #128`, wait for independent green CI and clear
review threads, then merge with a merge commit while preserving `develop`.

- [ ] **Step 5: Verify publication and finalize**

Wait for all main workflows, verify the live Pages and wiki FormVM content, comment
the issue with both PRs/commits/tests/pilot/live URLs, set the card to
Done/Completed, clear Priority and Work order, and remove only the clean #128
worktree/local branch.
