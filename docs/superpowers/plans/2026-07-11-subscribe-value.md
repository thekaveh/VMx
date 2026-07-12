# Cross-Flavor `subscribeValue` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fixed-source selector subscription that gives imperative consumers current/previous values, equality suppression, immediate synchronization, and deterministic teardown in all five VMx flavors.

**Architecture:** Each helper snapshots a selector, subscribes to the source VM's existing hub, filters property messages by fixed source identity, and updates its retained baseline before invoking the callback. Rust uses the equivalent hub-plus-sender-ID shape. The existing hub supplies ordering, batching, re-entrancy, and subscriber-error isolation; no new reactive library or dynamic fan-in layer is introduced.

**Tech Stack:** C# / System.Reactive, Python / reactivex, TypeScript / RxJS, Swift / Combine, Rust / VMx MessageHub facade, cross-flavor conformance tests, Markdown ADR/spec, MkDocs three-surface docs.

## Global Constraints

- Follow `docs/superpowers/specs/2026-07-11-subscribe-value-design.md` exactly.
- Observe one fixed source only; dynamic collection membership remains #136.
- Evaluate the selector and equality function at most once per matching message.
- Update the selected baseline before invoking `(current, previous)`.
- Run the immediate callback before attaching the subscription.
- Initial failures propagate; delivery-time failures use the existing HUB-007 route.
- Return each flavor's normal disposable/subscription and never auto-own it.
- Preserve lossless hub batching, iterative re-entrant FIFO delivery, and message contracts.
- Add no reactive dependency and do not change existing property helpers.
- Add `SUBV-001` through `SUBV-004` in every full-parity flavor.
- Advance spec/stable flavors to 3.15.0 and Rust to 0.15.0.
- Publish the same canonical docs to repository, `.io`, and wiki surfaces.
- Pilot DayDreams only in a disposable clone; never alter or push its real checkout.
- Local Swift verification is `swift build`; `swift test` requires full Xcode and must pass in CI.

______________________________________________________________________

### Task 1: Record the behavioral decision before runtime changes

**Files:**

- Create: `spec/ADRs/0095-cross-flavor-subscribe-value.md`
- Modify: `spec/ADRs/README.md`
- Modify: `spec/03-messages.md`

**Interfaces:**

- Consumes: existing hub, property-message, transaction, and HUB-007 contracts.

- Produces: normative setup/delivery state machine and exact per-flavor API table.

- [ ] **Step 1: Add ADR-0095**

Record the selected hub-based approach, rejected local-stream/observable-factory
alternatives, fixed-source boundary, current/previous callback, equality table,
immediate-before-attachment order, failure phases, batch final-snapshot behavior,
and #136 exclusion. State that four `SUBV` IDs and the 3.15.0 line land with the
implementations.

- [ ] **Step 2: Add the normative messages-chapter section**

Add `## 7.4 subscribeValue — imperative selected-state bridge` after the
TypeScript predicates. Include this state transition verbatim:

```text
initial = selector(source)
if fireImmediately: callback(initial, initial)
current = initial
on each property message from source:
    next = selector(source)
    if equality(current, next): stop this delivery
    previous = current
    current = next
    callback(current, previous)
```

Document sender identity, default equality per flavor, setup versus delivery
errors, disposal, re-entrancy, batching, and the Rust sender-ID expression.

- [ ] **Step 3: Run documentation format checks**

```bash
uv --project langs/python run --with 'mdformat==0.7.22' \
  --with 'mdformat-gfm==1.0.0' --with 'mdformat-tables==1.0.0' \
  mdformat --check spec/03-messages.md spec/ADRs/0095-cross-flavor-subscribe-value.md spec/ADRs/README.md
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 4: Commit the contract**

```bash
git add spec/03-messages.md spec/ADRs/0095-cross-flavor-subscribe-value.md spec/ADRs/README.md
git commit -m "spec: define cross-flavor subscribe value contract #93"
```

______________________________________________________________________

### Task 2: Implement the TypeScript bridge test-first

**Files:**

- Create: `langs/typescript/src/messages/subscribeValue.ts`
- Create: `langs/typescript/tests/conformance/subscribeValue.test.ts`
- Modify: `langs/typescript/src/messages/index.ts`
- Modify: `langs/typescript/src/index.ts`

**Interfaces:**

- Consumes: `IComponentVM`, `isPropertyChanged`, and RxJS `Subscription`.
- Produces:

```typescript
export interface SubscribeValueOptions<TValue> {
  readonly equality?: (current: TValue, next: TValue) => boolean;
  readonly fireImmediately?: boolean;
}

export function subscribeValue<TSource extends IComponentVM, TValue>(
  source: TSource,
  selector: (source: TSource) => TValue,
  callback: (current: TValue, previous: TValue) => void,
  options?: SubscribeValueOptions<TValue>,
): Subscription;
```

- [ ] **Step 1: Write the four red conformance scenarios**

Build real `ComponentVMOf` instances on one `MessageHub`. Use four `describe`
blocks named `SUBV-001` through `SUBV-004`. Assert:

```typescript
const seen: Array<[number, number]> = [];
const sub = subscribeValue(
  vm,
  source => source.model.value,
  (current, previous) => seen.push([current, previous]),
  { fireImmediately: true },
);
expect(seen).toEqual([[0, 0]]);
```

Then cover wrong-sender/non-property filtering, default `Object.is`, custom
equality counts, selector counts, re-entrant `0 -> 1 -> 2` ordering, batch final
snapshot suppression, ordinary and in-callback unsubscribe, initial throw, and
delivery callback throw. Call `allowRxUnhandledErrors()` for the intentional
delivery throw and prove a later value is compared with the already-updated
baseline.

- [ ] **Step 2: Run the TypeScript red gates**

```bash
cd langs/typescript
npm run sync-fixtures
npx vitest run tests/conformance/subscribeValue.test.ts
npm run typecheck:tests
```

Expected: missing `subscribeValue` export/type errors only.

- [ ] **Step 3: Implement the minimal state machine**

Use this production core:

```typescript
let current = selector(source);
if (options?.fireImmediately === true) callback(current, current);
const equality = options?.equality ?? Object.is;

return source.hub.messages.subscribe((message) => {
  if (!isPropertyChanged(message, { sender: source })) return;
  const next = selector(source);
  if (equality(current, next)) return;
  const previous = current;
  current = next;
  callback(next, previous);
});
```

Export the function and options type from both message and package barrels. Do
not import RxJS operators or allocate an intermediate observable.

- [ ] **Step 4: Run focused green and public declaration gates**

```bash
npx vitest run tests/conformance/subscribeValue.test.ts
npm run typecheck
npm run typecheck:tests
npm run lint
npm run build
rg -n "subscribeValue|SubscribeValueOptions" dist/index.d.ts dist/index.d.cts
```

Expected: four scenarios pass; both declaration formats expose the exact API.

- [ ] **Step 5: Commit TypeScript**

```bash
git add langs/typescript/src langs/typescript/tests/conformance/subscribeValue.test.ts
git commit -m "feat(typescript): add subscribe value bridge #93"
```

______________________________________________________________________

### Task 3: Implement the Python bridge test-first

**Files:**

- Create: `langs/python/src/vmx/messages/subscribe_value.py`
- Create: `langs/python/tests/conformance/test_subscribe_value.py`
- Modify: `langs/python/src/vmx/messages/__init__.py`
- Modify: `langs/python/src/vmx/__init__.py`

**Interfaces:**

- Consumes: `ComponentVMProto`, `PropertyChangedMessage`, `DisposableBase`.
- Produces:

```python
def subscribe_value(
    source: TSource,
    selector: Callable[[TSource], TValue],
    callback: Callable[[TValue, TValue], None],
    *,
    equality: Callable[[TValue, TValue], bool] | None = None,
    fire_immediately: bool = False,
) -> DisposableBase:
    current = selector(source)
    if fire_immediately:
        callback(current, current)
    equality_fn = equality or operator.eq

    def on_message(message: object) -> None:
        nonlocal current
        if not isinstance(message, PropertyChangedMessage) or message.sender is not source:
            return
        next_value = selector(source)
        if equality_fn(current, next_value):
            return
        previous = current
        current = next_value
        callback(next_value, previous)

    return source.hub.messages.subscribe(on_message)
```

- [ ] **Step 1: Write four marked red tests**

Create real `ComponentVMOf` values and decorate one test per scenario:

```python
@pytest.mark.conformance("SUBV-001")
def test_fixed_source_default_equality_and_immediate() -> None:
    seen: list[tuple[int, int]] = []
    sub = subscribe_value(
        vm,
        lambda source: source.model.value,
        lambda current, previous: seen.append((current, previous)),
        fire_immediately=True,
    )
    assert seen == [(0, 0)]
```

Cover the same four semantic groups as TypeScript. Use `caplog` for an
intentional delivery-time exception and prove `MessageHub subscriber raised`
is logged while another subscriber and later selected value still work.

- [ ] **Step 2: Run the Python red gate**

```bash
cd langs/python
uv run pytest tests/conformance/test_subscribe_value.py -v
```

Expected: import failure for `subscribe_value` only.

- [ ] **Step 3: Implement with one selector/equality call**

Use `operator.eq` as the default. Snapshot and optionally callback before
subscription. Subscribe directly to `source.hub.messages`; in the delivery
handler reject non-`PropertyChangedMessage` and `message.sender is not source`,
then update `current` before callback. Export from both public modules.

- [ ] **Step 4: Run Python green, lint, and strict typing**

```bash
uv run pytest tests/conformance/test_subscribe_value.py -v
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/vmx
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit Python**

```bash
git add langs/python/src langs/python/tests/conformance/test_subscribe_value.py
git commit -m "feat(python): add subscribe value bridge #93"
```

______________________________________________________________________

### Task 4: Implement the C# bridge test-first

**Files:**

- Create: `langs/csharp/src/VMx/Messages/SubscribeValueExtensions.cs`
- Create: `langs/csharp/tests/VMx.Conformance.Tests/SubscribeValueConformanceTests.cs`

**Interfaces:**

- Consumes: `IComponentVM`, `IPropertyChangedMessage<object>`, System.Reactive.
- Produces:

```csharp
public static IDisposable SubscribeValue<TSource, TValue>(
    this TSource source,
    Func<TSource, TValue> selector,
    Action<TValue, TValue> callback,
    IEqualityComparer<TValue>? equalityComparer = null,
    bool fireImmediately = false)
    where TSource : class, IComponentVM;
```

- [ ] **Step 1: Write four red conformance facts**

Build `ComponentVM<Model>` instances with the same hub/dispatcher. Add the exact
`SUBV-001`, `SUBV-002`, `SUBV-003`, and `SUBV-004` values through
`[Trait("Conformance", "SUBV-001")]`-shaped attributes. Assert fixed sender,
initial `(0,0)`, `EqualityComparer<T>.Default`, a counting custom comparer,
one selector call, re-entrant/batch/disposal behavior, and initial versus
delivery exception routing. A second hub subscriber must still observe the
message whose callback throws.

- [ ] **Step 2: Run the C# red gate**

```bash
cd langs/csharp
dotnet test --filter "Conformance~SUBV"
```

Expected: compile failure because `SubscribeValue` is absent.

- [ ] **Step 3: Implement the extension**

Validate `source`, `selector`, and `callback` with the repository's null-guard
style. Set `comparer = equalityComparer ?? EqualityComparer<TValue>.Default`,
run the setup snapshot/immediate callback, then subscribe to `source.Hub.Messages`.
Filter `IPropertyChangedMessage<object>` by `ReferenceEquals(message.SenderObject, source)`. Compute `next` once, compare once, assign `current`, and invoke
`callback(next, previous)`.

- [ ] **Step 4: Run focused tests and formatting**

```bash
dotnet test --filter "Conformance~SUBV"
dotnet build
dotnet format --verify-no-changes
```

Expected: four conformance facts pass and formatting is unchanged.

- [ ] **Step 5: Commit C#**

```bash
git add langs/csharp/src/VMx/Messages/SubscribeValueExtensions.cs \
  langs/csharp/tests/VMx.Conformance.Tests/SubscribeValueConformanceTests.cs
git commit -m "feat(csharp): add subscribe value bridge #93"
```

______________________________________________________________________

### Task 5: Implement the Swift bridge test-first

**Files:**

- Create: `langs/swift/Sources/VMx/Messages/SubscribeValue.swift`
- Create: `langs/swift/Tests/VMxTests/SubscribeValueConformanceTests.swift`

**Interfaces:**

- Consumes: `ComponentVMBase`, `PropertyChangedMessage`,
  `MessageHubProtocol.subscribe`, `AnyCancellable`.
- Produces a custom-comparator overload and this default overload:

```swift
public func subscribeValue<Source: ComponentVMBase, Value: Equatable>(
    _ source: Source,
    selector: @escaping (Source) throws -> Value,
    callback: @escaping (Value, Value) throws -> Void,
    fireImmediately: Bool = false
) throws -> AnyCancellable
```

The custom overload adds required
`isEqual: @escaping (Value, Value) throws -> Bool` and does not constrain
`Value: Equatable`.

- [ ] **Step 1: Write four XCTest scenarios**

Attach doc markers with the ID as the first token:

Use the exact marker
`/// SUBV-001 — fixed source, default equality, and immediate current/current.`
immediately above `func testSubscribeValueInitialAndDefaultEquality() throws`;
use the corresponding `SUBV-002`, `SUBV-003`, and `SUBV-004` markers above the
other three concrete test functions.

Use a real modeled VM and cover all four semantic groups. Delivery-time selector,
comparator, and callback failures must be throwing Swift errors handled by the
existing `subscribe` helper; do not test uncatchable traps.

- [ ] **Step 2: Record the local red/compile boundary**

```bash
cd langs/swift
swift build
swift test
```

Expected locally: production build is green before the API exists only after
the test target is not compiled; `swift test` reports the known missing XCTest
toolchain. CI is the authoritative test runner. Preserve the missing-XCTest
output in the task report.

- [ ] **Step 3: Implement the two overloads**

The custom overload evaluates the initial selector, optionally invokes
`callback(initial, initial)`, then calls `source.hub.subscribe`. Downcast to
`PropertyChangedMessage`, compare sender identity with `===`, evaluate selector
and `isEqual` once, update current before the callback, and allow delivery-time
throws to reach `MessageHubProtocol.subscribe` for isolation. The default
overload delegates with `{ $0 == $1 }`.

- [ ] **Step 4: Run the available Swift gate**

```bash
swift build
```

Expected: build succeeds. Inspect the new XCTest source for all four markers;
the macOS CI matrix must later run it with full Xcode.

- [ ] **Step 5: Commit Swift**

```bash
git add langs/swift/Sources/VMx/Messages/SubscribeValue.swift \
  langs/swift/Tests/VMxTests/SubscribeValueConformanceTests.swift
git commit -m "feat(swift): add subscribe value bridge #93"
```

______________________________________________________________________

### Task 6: Implement the Rust bridge test-first

**Files:**

- Modify: `langs/rust/src/lib.rs`
- Create: `langs/rust/tests/conformance/subscribe_value.rs`
- Modify: `langs/rust/tests/conformance.rs`

**Interfaces:**

- Produces:

```rust
pub struct SubscribeValueOptions<T> {
    pub fire_immediately: bool,
    equality: Arc<dyn Fn(&T, &T) -> bool + Send + Sync>,
}

impl<T: PartialEq> Default for SubscribeValueOptions<T> {
    fn default() -> Self {
        Self::with_equality(|current, next| current == next)
    }
}

impl<T> SubscribeValueOptions<T> {
    pub fn with_equality<F>(equality: F) -> Self
    where F: Fn(&T, &T) -> bool + Send + Sync + 'static;
    pub fn fire_immediately(self, value: bool) -> Self;
}

impl MessageHub {
    pub fn subscribe_value<T, S, C>(
        &self,
        sender_id: usize,
        selector: S,
        callback: C,
        options: SubscribeValueOptions<T>,
    ) -> Subscription
    where
        T: Clone + Send + 'static,
        S: Fn() -> T + Send + Sync + 'static,
        C: Fn(T, T) + Send + Sync + 'static;
}
```

- [ ] **Step 1: Write four red Rust tests and register the module**

Use `Arc<ComponentVm<SelectedModel, NullDispatcher>>`, capture it in the
zero-argument selector, and use `Arc<Mutex<Vec<(i32, i32)>>>` for observations.
Put the exact `/// SUBV-001 —`, `/// SUBV-002 —`, `/// SUBV-003 —`, and
`/// SUBV-004 —` markers immediately above their four `#[test]` functions.
Cover custom comparator counts, re-entrant set, hub batch,
an `Arc<Mutex<Option<Subscription>>>` disposal slot, setup panic propagation
with `catch_unwind`, and delivery callback panic isolation/baseline retention.

- [ ] **Step 2: Run the Rust red gate**

```bash
cd langs/rust
cargo test subscribe_value
```

Expected: compile failure because the API is absent.

- [ ] **Step 3: Implement options and subscription state**

Store the comparator in an `Arc` and current selection in VMx's poison-tolerant
`Mutex`. Invoke the initial selector/callback before `MessageHub::subscribe`.
Inside the subscriber, accept only `Message::PropertyChanged` with the requested
`sender_id`; clone the previous/next values only as needed to release the mutex
before callback. The hub's existing `catch_unwind` isolates delivery panics.

- [ ] **Step 4: Run focused Rust gates**

```bash
cargo test subscribe_value
cargo fmt --check
cargo clippy --all-targets -- -D warnings
```

Expected: all four tests pass with no formatting or lint finding.

- [ ] **Step 5: Commit Rust**

```bash
git add langs/rust/src/lib.rs langs/rust/tests/conformance.rs \
  langs/rust/tests/conformance/subscribe_value.rs
git commit -m "feat(rust): add subscribe value bridge #93"
```

______________________________________________________________________

### Task 7: Publish conformance and the 3.15 release line

**Files:**

- Modify: `spec/12-conformance.md`
- Modify: `spec/VERSION`
- Modify: `README.md`
- Modify: `spec/README.md`
- Modify: `compatibility-matrix.md`
- Modify: every flavor manifest/version declaration, README, and CHANGELOG
- Modify: `langs/typescript/package-lock.json`

**Interfaces:**

- Consumes: real `SUBV-001..004` tests in all five flavors.

- Produces: 346 library / 351 total coverage, spec/stable 3.15.0, Rust 0.15.0.

- [ ] **Step 1: Add four atomic catalog entries**

Add `SUBV-001` through `SUBV-004` using the exact scenario boundaries from the
design. Add them to the source chapter's Conformance section. Do not add a JSON
fixture; the scenarios need executable callbacks and teardown handles.

- [ ] **Step 2: Advance all version declarations**

Set spec and stable flavor current/minimum versions to `3.15.0`; set Rust package
to `0.15.0` with minimum spec `3.15.0`. Regenerate only the TypeScript lockfile:

```bash
cd langs/typescript
npm install --package-lock-only
```

- [ ] **Step 3: Update compatibility, changelogs, and counts**

Add a 3.15.x row while retaining 3.14.x history. Add bracketed changelog entries
for every flavor. Replace current-facing 342/347 claims with 346/351 while
leaving historical changelog rows untouched.

- [ ] **Step 4: Run metadata and coverage checks**

```bash
cd ../../
uv --project langs/python run python tools/check-version-consistency.py
uv --project langs/python run python tools/check-conformance-coverage.py \
  --require csharp --require python --require typescript --require swift --require rust
```

Expected: every flavor is 346/346; version and matrix checks are clean.

- [ ] **Step 5: Commit release contract**

```bash
git add spec README.md compatibility-matrix.md langs
git commit -m "release: advance subscribe value contract to 3.15 #93"
```

______________________________________________________________________

### Task 8: Publish the imperative engine bridge on all documentation surfaces

**Files:**

- Modify: `docs/content/primitives/services-messages-dispatching.md`
- Modify: `docs/content/integration-recipes.md`
- Modify: `docs/content/flavors/csharp.md`
- Modify: `docs/content/flavors/python.md`
- Modify: `docs/content/flavors/typescript.md`
- Modify: `docs/content/flavors/swift.md`
- Modify: `docs/content/flavors/rust.md`
- Modify: per-flavor package READMEs where Task 7 did not already add API usage

**Interfaces:**

- Produces: one canonical fixed-source/uniform recipe plus idiomatic five-flavor examples.

- [ ] **Step 1: Add the TypeScript uniforms bridge**

Use the exact public API:

```typescript
const exposureSubscription = subscribeValue(
  cameraVm,
  vm => vm.model.exposure,
  exposure => { material.uniforms.exposure.value = exposure; },
  { fireImmediately: true },
);
```

Show explicit `unsubscribe()` in adapter disposal. Explain current/previous,
custom equality, selector reevaluation on any fixed-source property message,
and why this is change-driven rather than frame polling.

- [ ] **Step 2: Add idiomatic flavor examples and boundary guidance**

Document C# `IDisposable`, Python `DisposableBase`, TypeScript `Subscription`,
Swift `AnyCancellable`, and Rust `Subscription`. State that callback ownership
belongs to the host, batches may collapse repeated final snapshots through
equality, initial failures propagate, and dynamic member fan-in is #136.

- [ ] **Step 3: Run the required three-surface workflow**

Use the `three-surface-docs` skill, then run:

```bash
uv run --project langs/python --with-requirements docs/requirements.txt python -m scripts.docs.check_docs
uv run --project langs/python --with-requirements docs/requirements.txt python -m scripts.docs.validate_diagrams
uv run --project langs/python --with-requirements docs/requirements.txt mkdocs build --strict
```

Expected: generated site/wiki drift and strict build pass. Search
`generated/site` and `generated/wiki` for `subscribeValue`, `subscribe_value`,
and the uniforms bridge; do not commit generated outputs.

- [ ] **Step 4: Commit documentation**

```bash
git add docs/content langs/*/README.md
git commit -m "docs: add imperative engine subscription bridge #93"
```

______________________________________________________________________

### Task 9: Pilot one fixed DayDreams renderer path without touching the real checkout

**Files:**

- Disposable clone: `packages/view/renderer-three/src/reconcile.ts`
- Disposable clone: `packages/view/renderer-three/tests/reconcile.test.ts`
- Never modify: `/Users/kaveh/repos/daydreams`

**Interfaces:**

- Consumes: TypeScript `subscribeValue` from this branch.

- Produces: two fixed subscriptions replacing one raw manifest/state hub filter.

- [ ] **Step 1: Record and protect the real checkout**

Capture real DayDreams HEAD, status, submodule SHAs, and untracked paths. Create
`/Users/kaveh/repos/VMx-worktrees/pilots/daydreams-issue-93`, initialize
submodules, and point only its `vendor/VMx` at this feature commit.

- [ ] **Step 2: Migrate only `subscribeOverlayReconcile`**

Replace the raw `PropertyChangedMessage` subscription with:

```typescript
const manifest = subscribeValue(
  world.manifest,
  vm => vm.model.entries,
  entries => handlers.onManifestChanged(entries),
  { fireImmediately: true },
);
const focus = subscribeValue(
  world.state,
  vm => vm.model.focusedCellKey,
  key => handlers.onFocusChanged(key),
  { fireImmediately: true },
);
return { unsubscribe() { manifest.unsubscribe(); focus.unsubscribe(); } };
```

Remove the duplicated manual initial callbacks and property-message cast/filter.
Leave `subscribeReconcile` unchanged because its dynamic cell fan-in belongs to
#136.

- [ ] **Step 3: Verify the consumer**

Run the focused renderer reconcile tests, view package tests/typecheck, full
workspace tests, and the renderer/web production build used by the repository.
Compare any pre-existing typecheck failure with the untouched baseline before
classifying it.

- [ ] **Step 4: Record evidence and remove the clone**

Create one local-only pilot commit, record changed-line/filter deletion and test
totals, never push, delete the disposable clone, and prove the real checkout's
HEAD/status/submodules are unchanged.

______________________________________________________________________

### Task 10: Run full verification and independent review

**Files:**

- Review: exact `origin/develop...HEAD` range.

**Interfaces:**

- Produces: a clean branch ready for the feature PR.

- [ ] **Step 1: Run all flavor gates**

```bash
cd langs/csharp && dotnet restore VMx.sln --locked-mode && dotnet build && dotnet test && dotnet format --verify-no-changes
cd ../python && uv sync --all-extras && uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy --strict src/vmx
cd ../typescript && npm ci && npm run sync-fixtures && npm run typecheck && npm run typecheck:tests && npm run lint && npm run build && npm test && npm audit --audit-level=low
cd ../rust && cargo test && cargo fmt --check && cargo clippy --all-targets -- -D warnings
cd ../swift && swift build
```

Swift XCTest remains CI-only in this local CommandLineTools environment.

- [ ] **Step 2: Run repository and docs gates**

Run tool tests/lint/format, version consistency, both fixture sync checks,
346/346 conformance coverage, four example-contract scripts, docs generation,
diagram validation, strict MkDocs, and relevant flagship example suites.

- [ ] **Step 3: Run final hygiene**

```bash
pre-commit run --all-files
git diff --check origin/develop...HEAD
git status --short
```

Expected: all hooks pass and the worktree is clean.

- [ ] **Step 4: Request independent review**

Review the full range for API consistency, error routing, re-entrancy, lock
safety, callback baseline ordering, teardown, version/count drift, docs drift,
and DayDreams scope. Resolve every finding and rerun affected gates.

______________________________________________________________________

### Task 11: Publish through `develop` and `main`

**Files:**

- GitHub PR/issue/project state only.

**Interfaces:**

- Produces: released 3.15 source, live docs/wiki, closed #93, next queue item #90.

- [ ] **Step 1: Open and merge the feature PR**

Push the branch; open a ready PR to `develop` with `Relates #93`, exact API,
four-ID coverage, five-flavor verification, Swift local limitation, and pilot
evidence. Wait for every check and thread, fix until green, squash-merge, and
delete the feature branch while keeping #93 open.

- [ ] **Step 2: Open and merge the promotion PR**

Open `develop` to `main` with `Closes #93`. Wait for the full second matrix and
zero unresolved threads, then merge with a merge commit without deleting
`develop`.

- [ ] **Step 3: Verify release state**

Wait for all post-main language, conformance, docs, wiki, and release workflows.
Verify live `.io` and wiki pages contain the five-flavor helper table and uniforms
bridge. Comment exact PR/commit/check/pilot evidence on #93.

- [ ] **Step 4: Complete and clean up**

Set the card `Done / Completed`, clear priority/work order, verify the issue is
closed, remove only the owned worktree/local branch, confirm the user's primary
VMx and DayDreams checkouts are unchanged, and continue to #90.
