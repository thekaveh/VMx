# Aggregate Change Stream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cross-flavor aggregate change stream that follows live collection membership, emits provenance for current-member changes, supports explicit coalescing, and removes bespoke fan-in logic from validated Tableau and DayDreams pilots.

**Architecture:** A small read-only observable-membership capability supplies atomic snapshots and structural pulses. `AggregateChangeStream<TItem>` owns one refcounted selected-stream subscription per distinct identity, reconciles membership transactionally behind a serialized FIFO gate, emits `AggregateChange` provenance, and offers per-subscriber initial delivery plus an explicit nested batch scope. The normative contract and ten `AGCH` conformance IDs are implemented identically in C#, Python, TypeScript, Swift, and Rust with only idiomatic surface differences.

**Tech Stack:** Markdown specification and ADRs; System.Reactive/.NET; reactivex/Python; RxJS/TypeScript; Combine/Swift; VMx local reactive facades/Rust; pytest, xUnit, Vitest, XCTest, Cargo test; MkDocs three-surface generation.

## Global Constraints

- The reviewed contract is `docs/superpowers/specs/2026-07-12-aggregate-change-stream-design.md`; do not weaken its identity, setup-race, failure, epoch, ordering, batching, or disposal rules.
- Target spec and stable flavor version is `3.18.0`; Rust is `0.18.0`; the five core flavor minimum-spec declarations become `3.18.0`. Independently versioned C# companion packages keep their current floors because their code is unchanged.
- Add exactly `AGCH-001..010`; library coverage becomes 373 and catalog coverage becomes 378 including five `THEME` scenarios.
- Add no reactive dependency: use System.Reactive, reactivex, RxJS, Combine, and the existing Rust `PropertyChangedStream`/subscription facade.
- `CompositeVM`, `GroupVM`, `ServicedObservableCollection`, and `KeyedServicedObservableCollection` participate; dictionary, paging, and filtered projections do not.
- Identity is reference identity in C#/Python/TypeScript/Swift and `VmNode::id()` in Rust; null members are rejected; duplicates refcount one selected subscription.
- Selected-stream completion/error ends only the current positive-refcount epoch; only final removal followed by re-add creates a new epoch.
- Structural subscription attaches before the first snapshot; staged synchronous item emissions never race ahead of membership commit.
- Setup-race reconciliation publishes no history; only post-construction structural pulses emit `Membership`, while a requested subscriber-local `Initial` represents ready state.
- Terminal null/selector/subscription failure detaches structural, staged, and admitted subscriptions before output error/throw.
- On exceptional batch exit, a synchronous final-delivery failure is suppressed so the original body error wins; otherwise subscriber failures follow the host contract.
- Behavior changes begin in `spec/`; ADR-0098 and all five conformance suites must land in this issue branch.
- Canonical docs under `docs/content/` must regenerate both `generated/site/` and `generated/wiki/`; do not hand-edit generated output.
- Preserve the user's primary VMx checkout and both consumer checkouts; pilots run only in disposable clones/worktrees and their patches/reports are retained outside those repositories.

______________________________________________________________________

## File map

- `spec/21-collections.md`: normative aggregate source, envelope, identity, delivery, batch, failure, and ownership contract.
- `spec/12-conformance.md`: `AGCH` prefix plus exact `AGCH-001..010` Given/When/Then catalog.
- `spec/ADRs/0098-dynamic-aggregate-change-stream.md` and `spec/ADRs/README.md`: accepted decision and ledger row.
- `langs/csharp/src/VMx/Collections/{IObservableMembershipSource,AggregateChangeStream}.cs`: unconstrained source capability plus reference-bound aggregate implementation; existing generic serviced collection compatibility is preserved.
- `langs/python/src/vmx/collections/{observable_membership,aggregate_change_stream}.py`: Python protocol and implementation; package exports expose both.
- `langs/typescript/src/collections/{observableMembership,aggregateChangeStream}.ts`: TypeScript interfaces and implementation; barrel exports expose both.
- `langs/swift/Sources/VMx/Collections/{ObservableMembershipSource,AggregateChangeStream}.swift`: Swift protocol/adapters and Combine implementation.
- `langs/rust/src/lib.rs`: Rust traits, envelope, options, stream, adapters, and exports in the crate's established single-file layout.
- One new `aggregate_change_stream` conformance file per flavor contains all ten IDs and source-family coverage.
- `docs/content/primitives/builders-collections-tree-utilities.md`: canonical user guide, examples, provenance table, and hub-batch composition.
- Root/spec/flavor READMEs, compatibility matrix, five changelogs, package manifests/locks, and version constants: 3.18/0.18 release line and 373/378 counts.

______________________________________________________________________

### Task 1: Publish the normative contract and catalog

**Files:**

- Create: `spec/ADRs/0098-dynamic-aggregate-change-stream.md`
- Modify: `spec/ADRs/README.md`
- Modify: `spec/21-collections.md`
- Modify: `spec/12-conformance.md`

**Interfaces:**

- Produces: `ObservableMembershipSource<T>`, `AggregateChangeStream<T>`, `AggregateChange<T>`, reasons `Initial|Membership|Item|Batch`, `observe(emitInitial)`, explicit nested batch, and `AGCH-001..010`.

- Consumes: the exact reviewed semantics in the design document; no flavor implementation exists yet.

- [ ] **Step 1: Add the ADR and ledger row**

Write ADR-0098 with `Status: Accepted (2026-07-12)` and `Spec version: introduced in 3.18.0`. Its decision sections must state the four supported source families, exact read-only capability, selected-stream selector and component convenience, provenance envelope, per-subscriber atomic initial seed, identity/refcount/epoch rules, subscribe-before-snapshot setup, transactional selector/null failure, explicit batching, completion/disposal, and excluded source families. Record the consequences as `363 -> 373` library IDs and `368 -> 378` total IDs.

- [ ] **Step 2: Add the normative chapter section**

Append `## 9. Dynamic aggregate change stream` to `spec/21-collections.md`, with numbered subsections matching the ADR. Include this portable shape:

```text
ObservableMembershipSource<T>:
    snapshot() -> ordered snapshot<T>
    subscribe_membership(callback) -> disposable subscription

AggregateChange<T>:
    Reason : Initial | Membership | Item | Batch
    Item   : T?  # present only for Item

AggregateChangeStream<T>:
    constructor(source, observe_item)
    observe(emit_initial = false) -> hot observable/publisher
    batch()/withBatch(callback) -> explicit ref-counted coalescing scope
    dispose()
```

- [ ] **Step 3: Add the ten exact catalog cases**

Add `AGCH-NNN` to the prefix table and add one Given/When/Then entry for each reviewed case: atomic late-subscriber initial; committed structural resync; current item identity; zero-refcount silence plus selected-stream completion/error epoch; Reset rebuild; duplicate refcount; exceptional nested batch; empty batch and Move stability; reentrant FIFO plus stale-epoch discard; null/selector transactional failure plus terminal output error, idempotent disposal, ownership, and subscriber isolation. Update chapter conformance to `COL-001..064`, `AGCH-001..010`, and `DISP-006`.

- [ ] **Step 4: Verify the expected red coverage gate**

Run:

```bash
uv --project langs/python run python tools/check-conformance-coverage.py \
  --require csharp --require python --require typescript --require swift --require rust
```

Expected: FAIL listing `AGCH-001..010` as missing in all five flavors and no malformed/duplicate catalog IDs.

- [ ] **Step 5: Format, validate, and commit**

Run `pre-commit run mdformat --files spec/21-collections.md spec/12-conformance.md spec/ADRs/0098-dynamic-aggregate-change-stream.md spec/ADRs/README.md`, then `git diff --check`, then commit:

```bash
git add spec/21-collections.md spec/12-conformance.md spec/ADRs/0098-dynamic-aggregate-change-stream.md spec/ADRs/README.md
git commit -m "spec: define aggregate change stream (#136)"
```

### Task 2: Implement and prove C# parity

**Files:**

- Create: `langs/csharp/src/VMx/Collections/IObservableMembershipSource.cs`
- Create: `langs/csharp/src/VMx/Collections/AggregateChangeStream.cs`
- Modify: `langs/csharp/src/VMx/Collections/ServicedObservableCollection.cs`
- Modify: `langs/csharp/src/VMx/Collections/KeyedServicedObservableCollection.cs`
- Modify: `langs/csharp/src/VMx/Composites/CompositeVMBase.cs`
- Modify: `langs/csharp/src/VMx/Groups/GroupVMBase.cs`
- Create: `langs/csharp/tests/VMx.Conformance.Tests/AggregateChangeStreamConformanceTests.cs`

**Interfaces:**

- Produces: `IObservableMembershipSource<T>.Snapshot/SubscribeMembership`, `AggregateChangeReason`, `AggregateChange<T>`, `AggregateChangeStream<T>(IObservableMembershipSource<T>, Func<T, IObservable<Unit>>).Observe/Batch/Dispose`, and the non-generic `AggregateChangeStream.ForComponents<T>` factory.

- Consumes: `INotifyCollectionChanged`, `IComponentVM.PropertyChanged`, `System.Reactive.Subjects.Subject<T>`, and `System.Reactive.Linq.Observable`.

- [ ] **Step 1: Write all ten failing xUnit conformance tests**

Use `[Trait("Conformance", "AGCH-00N")]` on ten facts. Build counted cold item observables with `Observable.Create<string>` and a reference-type `TestItem`; test normal VM collection plus serviced and keyed-serviced sources. Assert reason/item sequences, selector subscription/disposal counts, same-reference duplicates, Reset/Move behavior, synchronous staging emissions, reentrant remove, selected-stream completion/error epochs, null/selector transactional failure, exceptional nested `Batch`, source item ownership, and repeated dispose.

- [ ] **Step 2: Confirm the C# red state**

Run `dotnet test langs/csharp/VMx.sln --filter "Conformance~AGCH"`. Expected: compile failure because the new public types do not exist.

- [ ] **Step 3: Add the capability and adapters**

Define the source capability without an item constraint so existing serviced collections retain value-type compatibility:

```csharp
public interface IObservableMembershipSource<T>
{
    IReadOnlyList<T> Snapshot();
    IDisposable SubscribeMembership(Action callback);
}
```

Keep `IVmCollection<VM>` unchanged. Add the new capability independently to `CompositeVMBase`, `GroupVMBase`, and both serviced types. Each implementation supplies explicit `Snapshot()` and `SubscribeMembership(Action)` methods, ignores structural event payload, and returns an idempotent event-detach disposable. This is additive for external collection implementers, compiles for `netstandard2.0`, and leaves the generic serviced classes unconstrained.

- [ ] **Step 4: Implement the serialized aggregate**

Implement `AggregateChangeStream<T> where T : class` with a private gate, FIFO queue, monotonically increasing epoch, refcount, selected subscription, and terminal flag. Key its identity dictionary with a private `IEqualityComparer<T>` whose `Equals` calls `ReferenceEquals` and whose `GetHashCode` calls `RuntimeHelpers.GetHashCode`; do not use the BCL `ReferenceEqualityComparer`, which is unavailable on `netstandard2.0`. Its selector is `Func<T, IObservable<Unit>>`. Subscribe structurally before first snapshot; reconcile into a temporary entry set, buffer synchronous selected emissions, commit only after every selector/subscription succeeds, preserve retained identities, and terminate the existing output with the same null/selector error after detaching structural, staged, and admitted subscriptions. Construction failure throws before an aggregate is returned; later callback propagation beyond the output follows System.Reactive/event conventions. Setup reconciliation emits no historical `Membership`. `Observe(true)` must register and queue `Initial` atomically. `Batch` increments depth and emits one `Batch` on dirty outer exit; if body and synchronous delivery both fail, suppress delivery failure and rethrow the body error. `Dispose` is idempotent and completes the output. Add the executable component factory:

```csharp
public static AggregateChangeStream<T> ForComponents<T>(
    IObservableMembershipSource<T> source)
    where T : class, IComponentVM =>
    new(
        source,
        item => Observable
            .FromEventPattern<PropertyChangedEventHandler, PropertyChangedEventArgs>(
                handler => item.PropertyChanged += handler,
                handler => item.PropertyChanged -= handler)
            .Select(_ => Unit.Default));
```

- [ ] **Step 5: Make the conformance tests green**

Run `dotnet test langs/csharp/VMx.sln --filter "Conformance~AGCH"`; expected: 10 passed. Then run `dotnet test langs/csharp/VMx.sln`; expected: all tests pass.

- [ ] **Step 6: Format and commit C#**

Run `dotnet format langs/csharp/VMx.sln --verify-no-changes`, `git diff --check`, and commit the listed C# source/test paths with `feat(csharp): add aggregate change stream (#136)`.

### Task 3: Implement and prove Python parity

**Files:**

- Create: `langs/python/src/vmx/collections/observable_membership.py`
- Create: `langs/python/src/vmx/collections/aggregate_change_stream.py`
- Modify: `langs/python/src/vmx/collections/serviced_observable_collection.py`
- Modify: `langs/python/src/vmx/collections/keyed_serviced_observable_collection.py`
- Modify: `langs/python/src/vmx/composites/composite_vm.py`
- Modify: `langs/python/src/vmx/groups/group_vm.py`
- Modify: `langs/python/src/vmx/collections/__init__.py`
- Modify: `langs/python/src/vmx/__init__.py`
- Create: `langs/python/tests/conformance/test_aggregate_change_stream.py`

**Interfaces:**

- Produces: `ObservableMembershipSource[T]`, frozen `AggregateChange`, `AggregateChangeReason`, `AggregateChangeStream.observe/batch/dispose/for_components`.

- Consumes: each source's `on_collection_changed`, reactivex `Observable`, `Subject`, `Disposable`, and the component protocol's `property_changed`.

- [ ] **Step 1: Write ten failing pytest cases**

Mark each case with `@pytest.mark.conformance("AGCH-00N")`. Use a counted `rx.create` selector and weak/reference identity assertions; cover composite, group, unkeyed serviced, and keyed serviced sources across the file. Assert `id(item)` duplicate behavior rather than equality/hash behavior, plus synchronous staging, selected-stream completion/error epochs, and null/selector transactional failure.

- [ ] **Step 2: Confirm the Python red state**

Run `uv --project langs/python run pytest langs/python/tests/conformance/test_aggregate_change_stream.py -q`. Expected: import failure for `AggregateChangeStream`.

- [ ] **Step 3: Add protocol methods and source implementations**

Define a new independent `ObservableMembershipSource[T]` protocol with `snapshot(self) -> tuple[T, ...]` and `subscribe_membership(self, callback: Callable[[], None]) -> Disposable`; do not extend `VmCollectionProto`. Each VMx concrete returns `tuple(self)` and subscribes `lambda _: callback()` to its existing local observable; no hub subscription is introduced. External structural implementations of existing protocols gain no requirement.

- [ ] **Step 4: Implement Python aggregate state**

Use `threading.RLock`, `deque`, and `dict[int, _Entry[T]]` keyed only by `id(item)`. The entry stores a strong `item`, count, epoch, disposable, and terminal flag, preventing ID reuse while admitted. Stage new subscriptions, buffer synchronous callbacks, commit retained/new entries transactionally, invalidate queued epochs on final removal/termination, and atomically terminate the existing output on `None` or selector/subscription failure after detaching structural, staged, and admitted subscriptions. Construction failure raises before return; later callback propagation beyond the output follows reactivex convention. Setup emits no historical membership event. `observe(emit_initial=True)` must return a per-subscriber `rx.create` wrapper; `batch()` preserves the body exception over a synchronous final-delivery failure.

- [ ] **Step 5: Verify strict Python parity**

Run:

```bash
uv --project langs/python run pytest langs/python/tests/conformance/test_aggregate_change_stream.py -q
uv --project langs/python run pytest langs/python -q
uv --project langs/python run ruff check langs/python/src langs/python/tests/conformance/test_aggregate_change_stream.py
uv --project langs/python run ruff format --check langs/python/src langs/python/tests/conformance/test_aggregate_change_stream.py
uv --project langs/python run mypy --strict langs/python/src/vmx
```

Expected: all commands pass.

- [ ] **Step 6: Commit Python**

Commit the listed Python paths with `feat(python): add aggregate change stream (#136)`.

### Task 4: Implement and prove TypeScript parity

**Files:**

- Create: `langs/typescript/src/collections/observableMembership.ts`
- Create: `langs/typescript/src/collections/aggregateChangeStream.ts`
- Modify: `langs/typescript/src/collections/servicedObservableCollection.ts`
- Modify: `langs/typescript/src/collections/keyedServicedObservableCollection.ts`
- Modify: `langs/typescript/src/composites/compositeVMBase.ts`
- Modify: `langs/typescript/src/groups/groupVM.ts`
- Modify: `langs/typescript/src/collections/index.ts`
- Modify: `langs/typescript/src/index.ts`
- Create: `langs/typescript/tests/conformance/aggregate-change-stream.test.ts`

**Interfaces:**

- Produces: unconstrained `ObservableMembershipSource<T>`, `AggregateChangeReason`, discriminated `AggregateChange<T>`, and object-bound `AggregateChangeStream.observe/withBatch/dispose/forComponents`.

- Consumes: RxJS `Observable`, `Subject`, `Subscription`; `ComponentVMBase.propertyChanged`; source-local collection observables.

- [ ] **Step 1: Write ten failing Vitest cases**

Create one `describe("AGCH-00N", ...)` block per ID. Use `Observable` teardowns to count one selected subscription per object identity, and verify late initial, structural ordering, synchronous staging, item provenance, zero-refcount silence, selected-stream completion/error epochs, null/selector transactional failure through the aggregate output error channel, Reset, duplicates, nested/error batch, Move, reentrancy/epoch discard, and disposal/ownership. Do not require the collection mutator to catch an RxJS observer exception.

- [ ] **Step 2: Confirm the TypeScript red state**

Run `npm --prefix langs/typescript test -- --run tests/conformance/aggregate-change-stream.test.ts`. Expected: module resolution failure for the new aggregate.

- [ ] **Step 3: Add source capability implementations**

Use:

```typescript
export interface ObservableMembershipSource<T> {
  snapshot(): readonly T[];
  subscribeMembership(callback: () => void): Subscription;
}
```

Keep the existing `IVmCollection` interface unchanged. VMx's concrete composite/group classes implement the separate capability by subscribing to `collectionChanged`; serviced/keyed sources subscribe to their own `collectionChanged`; all snapshots are shallow arrays. Keep the aggregate itself declared as `AggregateChangeStream<T extends object>` and reject runtime `null`/`undefined` despite that strict bound. Existing external structural `IVmCollection` implementations gain no requirement.

- [ ] **Step 4: Implement the aggregate**

Use a `Map<T, Entry<T>>` (native object identity), a serialized array queue, and per-entry epoch/refcount/subscription/terminal state. Structural subscription precedes first snapshot; staged callbacks buffer until membership commit, and setup emits no historical membership event. Construction-time selector failure throws before return; later selector/subscription failure detaches structural, staged, and admitted subscriptions before terminating the aggregate's existing output with that error. Do not promise a synchronous mutator throw because RxJS captures/reports observer exceptions through its host mechanism. `observe({emitInitial:true})` uses a custom `Observable` to register under the gate before seed delivery. Rx item errors terminate only that epoch. `withBatch` uses `try/finally`, emits once if dirty, and suppresses synchronous final-delivery failure only when necessary to preserve an active body error.

- [ ] **Step 5: Verify TypeScript parity**

Run `npm --prefix langs/typescript run typecheck`, `typecheck:tests`, `lint`, `build`, and `test`. Expected: all pass.

- [ ] **Step 6: Commit TypeScript**

Commit the listed TypeScript paths with `feat(typescript): add aggregate change stream (#136)`.

### Task 5: Implement and prove Swift parity

**Files:**

- Create: `langs/swift/Sources/VMx/Collections/ObservableMembershipSource.swift`
- Create: `langs/swift/Sources/VMx/Collections/AggregateChangeStream.swift`
- Modify: `langs/swift/Sources/VMx/Collections/ServicedObservableCollection.swift`
- Modify: `langs/swift/Sources/VMx/Collections/KeyedServicedObservableCollection.swift`
- Modify: `langs/swift/Sources/VMx/Composites/CompositeVM.swift`
- Modify: `langs/swift/Sources/VMx/Groups/GroupVM.swift`
- Create: `langs/swift/Tests/VMxTests/AggregateChangeStreamConformanceTests.swift`

**Interfaces:**

- Produces: class-bound `ObservableMembershipSource`, `AggregateChangeReason`, `AggregateChange<Item>`, `AggregateChangeStream.observe/withBatch/dispose`, and an inferable constrained `forComponents` extension.

- Consumes: Combine `AnyPublisher<_, Never>`, `PassthroughSubject`, `AnyCancellable`, and `ComponentVMBase.propertyChanged`.

- [ ] **Step 1: Write ten failing XCTest cases**

Put `/// AGCH-00N — ...` immediately above each test. Use reference-type test members and counted `handleEvents(receiveSubscription:receiveCancel:)` publishers. Exercise all three source categories and assert exact ordered envelopes, synchronous staging order, publisher completion epochs, and cancellation counts; Swift's type system supplies the non-failing/null guarantees.

- [ ] **Step 2: Confirm the Swift red state**

Run `swift test --package-path langs/swift --filter AggregateChangeStreamConformanceTests`. Expected: compile failure for the absent types.

- [ ] **Step 3: Add class-bound source capability**

Define a separate protocol with associated `Item: AnyObject`, `snapshot() -> [Item]`, and `subscribeMembership(_:) -> AnyCancellable`; do not add requirements to `VMCollection`. VMx composite/group classes and conditional reference-item serviced types adapt their local collection publishers; source objects remain non-owning and external `VMCollection` conformers remain compatible. Define the convenience with an enclosing-item equality constraint so Swift can infer it:

```swift
public extension AggregateChangeStream where Item: ComponentVMBase {
    static func forComponents<S>(_ source: S) -> Self
    where S: ObservableMembershipSource, S.Item == Item {
        Self(source: source, observeItem: { $0.propertyChanged.eraseToAnyPublisher() })
    }
}
```

- [ ] **Step 4: Implement the locked FIFO aggregate**

Use `NSRecursiveLock`, `ObjectIdentifier` keys, an epoch counter, `[QueuedChange]`, and `AnyCancellable` entries. Subscribe structurally before snapshot, stage selected publishers (`Failure == Never`), buffer synchronous values until commit, and preserve identity-retaining epochs. Create per-subscriber initial delivery with `Deferred`/custom publisher registration under the same lock. `withBatch` is `rethrows`; dirty exceptional exit emits one batch before rethrow. Dispose completes the subject once.

- [ ] **Step 5: Verify Swift parity**

Run `swift build --package-path langs/swift` and `swift test --package-path langs/swift`. Expected: both pass; if local Xcode licensing prevents tests, record that exact environment failure and require macOS CI before merge.

- [ ] **Step 6: Commit Swift**

Commit the listed Swift paths with `feat(swift): add aggregate change stream (#136)`.

### Task 6: Implement and prove Rust parity

**Files:**

- Modify: `langs/rust/src/lib.rs`
- Create: `langs/rust/tests/conformance/aggregate_change_stream.rs`
- Modify: `langs/rust/tests/conformance.rs`

**Interfaces:**

- Produces: `ObservableMembershipSource<T: VmNode>`, `ObservablePropertySource`, `AggregateChangeReason`, `AggregateChange<T>`, `AggregateObserveOptions`, `AggregateChangeStream::new/observe/batch/dispose/for_components`.

- Consumes: `VmNode::id()`, `PropertyChangedStream`, the existing cloneable subscription handle, collection-local message hubs, `Arc<Mutex<_>>`, and `VecDeque`.

- [ ] **Step 1: Write ten failing Rust conformance tests**

Add `/// AGCH-00N — ...` as the first doc-comment token on each `#[test]`. Use a cloneable `TestNode: VmNode + ObservablePropertySource` and the built-in normal/serviced/keyed types. Prove one-subscription behavior observably: one property emission from duplicate same-ID clones must produce exactly one aggregate item envelope, final removal silences it, and re-add restores one envelope. Also cover synchronous staging, terminal epoch, reentrant removal, and panic/error-safe batch cleanup according to existing `VmxResult` conventions; do not add public subscription-count instrumentation.

- [ ] **Step 2: Confirm the Rust red state**

Run `cargo test --manifest-path langs/rust/Cargo.toml aggregate_change_stream`. Expected: compile failure for absent exports.

- [ ] **Step 3: Add exact traits and built-in implementations**

Add the reviewed `ObservableMembershipSource<T>: Clone + Send + Sync + 'static` trait with `snapshot` and `subscribe_membership`; add `ObservablePropertySource: VmNode`. Built-in collection implementations filter their local hub by sender/owner identity before invoking the structural callback.

- [ ] **Step 4: Implement Rust aggregate state**

Store state in `Arc<Mutex<AggregateInner<T>>>`; key entries by `usize` VM ID and retain a strong cloned node, positive refcount, epoch, optional subscription, and terminal flag. Attach structural observation before snapshot, stage new item subscriptions outside/through the existing lock discipline without deadlock, buffer synchronous callbacks, then commit or dispose transactionally. Setup emits no historical membership envelope. The local output facade must support independent `observe(AggregateObserveOptions)` subscriptions and completion-on-dispose. Nested `batch` uses a guard so dirty exit emits once during normal return or unwind; when `std::thread::panicking()` is true, wrap final delivery with `catch_unwind(AssertUnwindSafe(...))` so a subscriber panic cannot replace the active body panic.

- [ ] **Step 5: Verify Rust parity**

Run `cargo fmt --manifest-path langs/rust/Cargo.toml -- --check`, `cargo clippy --manifest-path langs/rust/Cargo.toml --all-targets -- -D warnings`, and `cargo test --manifest-path langs/rust/Cargo.toml`. Expected: all pass.

- [ ] **Step 6: Commit Rust**

Commit `langs/rust/src/lib.rs`, the new conformance file, and module registration with `feat(rust): add aggregate change stream (#136)`.

### Task 7: Complete cross-flavor coverage, release metadata, and three-surface docs

**Files:**

- Modify: `spec/VERSION`, `README.md`, `spec/README.md`, `compatibility-matrix.md`, `AGENTS.md`
- Modify: `langs/{csharp,python,typescript,swift,rust}/CHANGELOG.md`
- Modify: `langs/{csharp,python,typescript,swift,rust}/README.md`
- Modify: `langs/csharp/src/VMx/VMx.csproj`
- Modify: `langs/python/src/vmx/__about__.py`
- Modify: `langs/typescript/package.json`, `langs/typescript/package-lock.json`, `langs/typescript/src/version.ts`
- Modify: `langs/swift/Package.swift`, `langs/swift/Sources/VMx/Version.swift`
- Modify: `langs/rust/Cargo.toml`, `langs/rust/src/lib.rs`
- Modify: `docs/content/primitives/builders-collections-tree-utilities.md`
- Modify: `docs/content/flavors/rust.md`
- Modify generated files under `generated/site/` and `generated/wiki/` only through the generator.

**Interfaces:**

- Produces: documented 3.18/0.18 release line, 373/378 counts, canonical usage examples, and synchronized repo/site/wiki outputs.

- Consumes: all five passing flavor implementations and the canonical docs generator.

- [ ] **Step 1: Prove complete conformance markers**

Run the required five-flavor coverage command. Expected: each flavor reports `373/373`; total catalog reports 378 with no missing/extra/duplicate IDs.

- [ ] **Step 2: Update every version/count surface**

Set spec/stable packages/min-spec to `3.18.0`, Rust package to `0.18.0` with `MIN_SPEC_VERSION = "3.18.0"`, add current changelog sections dated 2026-07-12, add the 3.18 compatibility row, and replace current-line 363/368 claims with 373/378. Update the Swift package comment and canonical Rust flavor page. Preserve historical release claims and the published Python `.release-please-manifest.json` value.

- [ ] **Step 3: Write canonical documentation**

Add a numbered aggregate-stream section containing the supported-source table, provenance table, custom nested selector example, component convenience example, explicit `aggregate.withBatch(() => hub.batch(...))` composition, disposal ownership note, non-failing selected-stream rule, and explicit exclusions. Link ADR-0098 and distinguish ADR-0095 fixed-sender `subscribeValue`.

- [ ] **Step 4: Regenerate and verify all three surfaces**

Install the pinned documentation environment, then run every executable docs gate:

```bash
python3 -m pip install -r docs/requirements.txt
python3 -m scripts.docs.build_docs --site --wiki
python3 -m scripts.docs.build_docs --site --wiki --check
python3 -m scripts.docs.check_docs
python3 -m scripts.docs.validate_diagrams
mkdocs build --strict
python3 -m scripts.docs.push_wiki --check
python3 tools/check-version-consistency.py
```

Expected: generation is deterministic, links/structure pass, and the dry-run wiki sync succeeds.

- [ ] **Step 5: Commit release/docs synchronization**

Run mdformat/pre-commit on changed Markdown, `git diff --check`, and commit all listed metadata/canonical/generated paths with `docs: publish aggregate stream parity (#136)`.

### Task 8: Validate both downstream consumer pilots without mutating user checkouts

**Files:**

- Disposable Tableau clone: `frontend/view-model/src/canvasVm.ts` and focused projection tests.
- Disposable DayDreams clone: `packages/view/renderer-three/src/reconcile.ts`, `packages/view/renderer-three/src/index.ts`, `packages/view/renderer-babylon/src/index.ts`, and focused renderer tests.
- Create tracked reports: `docs/superpowers/reports/2026-07-12-issue-136-tableau-pilot.md`, `docs/superpowers/reports/2026-07-12-issue-136-daydreams-pilot.md`.

**Interfaces:**

- Produces: evidence that the public API replaces real bespoke fan-in logic without VMx source edits or consumer commits.

- Consumes: a locally packed/built VMx artifact from this issue branch and clean disposable clones pinned to the recorded consumer develop SHAs.

- [ ] **Step 1: Pilot Tableau**

Replace its revision counter, sender set, broad property hub filter, and defer depth with an aggregate over its supported internal `cellComposite` source selecting `node.model.state.propertyChanged`; do not aggregate the `ObservableList` mirror `allCells`. Preserve collection add/remove detail where required and wrap tree/hub mutations in the explicit aggregate batch so the pulse still occurs only after tree attachment. Add tests for initial computation, post-attach pulse, nested state, remove/Reset silence, duplicate refcount, and one batch pulse.

- [ ] **Step 2: Pilot DayDreams**

Keep precise collection add/remove reconciliation, replace broad `PropertyChanged(model)` casts with `AggregateChangeReason.Item` identity delivery, and apply the same integration to Three and Babylon. Add tests proving unrelated hub messages and removed/replaced members are silent while renderer order/unsubscribe behavior remains unchanged.

- [ ] **Step 3: Run consumer-native verification and record evidence**

Use each clone's declared install/typecheck/lint/test commands, record pinned SHA, exact patch/stat, exact commands/results, API friction, and net bespoke-line change in the two tracked VMx reports. Force-add the ignored report paths, review them for secrets/local-only details, and commit them before deleting disposable clones. Do not commit or push consumer changes.

- [ ] **Step 4: Feed only demonstrated API corrections back into VMx**

If a pilot exposes an API defect, first add a failing VMx test, make the smallest parity correction in all affected flavors, rerun the relevant full flavor suites and pilots, and commit `fix: address aggregate stream pilot finding (#136)`. Do not add consumer-specific shortcuts.

### Task 9: Full verification, review, and publication

**Files:**

- All issue-branch changes; no new production scope.

**Interfaces:**

- Produces: one reviewed issue branch, green feature-to-develop PR, then green develop-to-main PR, closed issue, and Done board item.

- Consumes: Tasks 1-8 and both pilot reports.

- [ ] **Step 1: Run the complete repository matrix**

Run all commands from AGENTS.md: Python tests/ruff/format/mypy; C# locked restore/build/test/format; TypeScript install/sync/typecheck/test/lint/build; Swift build/test; Rust fmt/clippy/test; conformance coverage and tool tests; pre-commit; docs generate/check/wiki dry run. Record every command and result; skip only an impossible environment check with exact evidence.

- [ ] **Step 2: Request two-stage review and correct findings**

Review first against ADR-0098/design/`AGCH-001..010`, then for code quality, races, resource leaks, API idiom, generated drift, and unrelated changes. Any accepted finding starts with a failing focused test and repeats the affected full suite.

- [ ] **Step 3: Push and merge feature to develop**

Push `codex/issue-136-aggregate-change-stream`, open a PR targeting `develop` with issue link, design summary, flavor matrix, docs evidence, pilot reports, and risks. Wait for all required checks, fix until green, resolve conversations, squash-merge, and delete the feature branch.

- [ ] **Step 4: Promote develop to main through a second PR**

Open `develop -> main`, wait for the complete required matrix, fix only through a new branch/PR back into develop if needed, then merge the green promotion PR. Never push directly to either protected branch.

- [ ] **Step 5: Verify post-main publication and close the ticket**

Verify all post-main workflows, raw canonical docs, `.io` site, and native wiki show 3.18/373/378 and the aggregate guide. Comment on #136 with both merged PRs, exact verification and pilot evidence; close it; set board Status Done and Roadmap Status Completed; clear Priority/Work order; then select the next topologically ordered ready issue.

______________________________________________________________________

## Self-review

- Spec coverage: every reviewed design section maps to Tasks 1-7 and every consumer acceptance case maps to Task 8.
- Completeness scan: every implementation action names its exact contract, failure behavior, and verification command.
- Type consistency: source/aggregate/reason/observe/batch/dispose names match the reviewed flavor-specific API; all later tasks consume the interfaces produced by their flavor task.
- Scope: dictionary, paging, filtered projections, automatic hub-idle detection, domain revision state, and consumer-specific shortcuts remain excluded.
