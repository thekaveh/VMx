# Changelog

All notable changes to the Python flavor are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.0.0](https://github.com/thekaveh/VMx/compare/python-v3.1.0...python-v4.0.0) (2026-07-02)


### ⚠ BREAKING CHANGES

* **v3:** VMx v3.0.0 framework overhaul — verified-merged critique remediation ([#37](https://github.com/thekaveh/VMx/issues/37))

### Features

* absorption-audit-followup — D2/D3 + ADR-0039..0042 (v2.6.0) ([#18](https://github.com/thekaveh/VMx/issues/18)) ([001af07](https://github.com/thekaveh/VMx/commit/001af070b39357a1b7e45ec33a58f3baa6627d50))
* **absorption-cycle-12:** v2.0.0 — version bumps + compat matrix ([6e29af4](https://github.com/thekaveh/VMx/commit/6e29af453023b6f16e659072fe26b98403a71a77))
* **absorption-cycle-1:** capability micro-interfaces (CAP-001..020) ([23ec03c](https://github.com/thekaveh/VMx/commit/23ec03c4935795c9f561fb07d0ce5f007b72f375))
* **absorption-cycle-2:** null-object service convention (NULL-001..003) ([8b26c64](https://github.com/thekaveh/VMx/commit/8b26c64706b190885cf95cdad493b8491aa9a76f))
* **absorption-cycle-3:** derived properties (DPROP-001..012) ([93f2af4](https://github.com/thekaveh/VMx/commit/93f2af419fc1c84fa5bb4f9208ef1e90640a60c4))
* **absorption-cycle-4:** command decorators (CMDD-001..009) ([2f92252](https://github.com/thekaveh/VMx/commit/2f92252be212cf23ec45aa654e8b406209807b9a))
* **absorption-cycle-5:** notification sub-package (NOTIF-001..010) ([fc85b67](https://github.com/thekaveh/VMx/commit/fc85b67b6be69356cf9eeded600b72053295006b))
* **absorption-cycle-6:** expand/collapse + walk_expanded (EXP-001..005) ([93497f2](https://github.com/thekaveh/VMx/commit/93497f29997a5ee48ef51e63ef205cf12d2d93ca))
* **absorption-cycle-7:** search/filter (COMP-014..018, GRP-007..010) ([66ae06e](https://github.com/thekaveh/VMx/commit/66ae06e087777870c72b67c7b0294c061d174fcc))
* **absorption-cycle-8:** modeled CRUD commands (COMP-019..024) ([b30ff0f](https://github.com/thekaveh/VMx/commit/b30ff0f25b7a9534a676279c815049ec49c84cf4))
* **absorption-cycle-9:** localization hooks (LOC-001..003) ([422567f](https://github.com/thekaveh/VMx/commit/422567f6f0f0acdf304d2be6cc4cb99165b392a8))
* implement v3.1 upstream consumer asks ([edefcef](https://github.com/thekaveh/VMx/commit/edefcefd8170ce94716774eb9d9db125c11cfeda))
* **python:** Aggregates module (3g) — AggregateVM1..AggregateVM5 ([3bb857a](https://github.com/thekaveh/VMx/commit/3bb857a21c64f19083a9ebcffecc705b4735ed80))
* **python:** Commands module (3c) — RelayCommand + parameterized variant ([3e3e81b](https://github.com/thekaveh/VMx/commit/3e3e81b972ccec0d20c044834a481c2988bee503))
* **python:** Components module (3d) — ComponentVM + ComponentVMOf + ReadonlyComponentVMOf ([77bbdf0](https://github.com/thekaveh/VMx/commit/77bbdf0d639a6b219e86645e73952d63c6f5c8e4))
* **python:** Composites module (3e) — CompositeVM + CompositeVMOf ([bac2cd6](https://github.com/thekaveh/VMx/commit/bac2cd6735ebc608835622ff5d1dd893538898ab))
* **python:** expand top-level vmx re-exports to full public surface ([811f4c1](https://github.com/thekaveh/VMx/commit/811f4c1834dc72e293c39dcd7275fba723898477))
* **python:** Forwarding module (3h) — ForwardingComponentVM + ForwardingCompositeVM ([17bc559](https://github.com/thekaveh/VMx/commit/17bc559b9203224954a0454e7a530b59d0805ea6))
* **python:** Groups module (3h) — GroupVM peer-container, GRP-001..004 conformance ([db305a7](https://github.com/thekaveh/VMx/commit/db305a7cd4de608923157b226f1232a0d923784c))
* **python:** Lifecycle module (3a) — ConstructionStatus, StatusTransitionError, transition validator ([ca768f2](https://github.com/thekaveh/VMx/commit/ca768f2d23cbc4c89bdd58e46f0af7a2831abd35))
* **python:** Messages module (3b) — PropertyChangedMessage, ConstructionStatusChangedMessage, protocols ([827baa2](https://github.com/thekaveh/VMx/commit/827baa2226327b0e06ab75e6184524d1462f7c36))
* **python:** scaffold vmx package with smoke tests ([cbaa7e5](https://github.com/thekaveh/VMx/commit/cbaa7e588c628575bad90f87c450f0bcab5ce287))
* **python:** Services module (3b/2) — MessageHub + RxDispatcher ([ebd1a85](https://github.com/thekaveh/VMx/commit/ebd1a851d8a19cb49179d215d6771d67700acf56))
* **python:** v1.2.0 — RelayCommandOf/AggregateVMNBuilder parity aliases ([8352cb7](https://github.com/thekaveh/VMx/commit/8352cb7706ba742f2f68eff08ed3e57f290aec5f))
* **spec:** v1.1.0 — AutoConstructOnAdd, BatchUpdate, Tree utilities ([ededa6a](https://github.com/thekaveh/VMx/commit/ededa6af62fd86d0c598756ed4e7e78913ac3803))
* **v2.1:** absorb 15 post-v2.0 candidates ([#4](https://github.com/thekaveh/VMx/issues/4)) ([796370a](https://github.com/thekaveh/VMx/commit/796370a6338dc6642cf3e912749237a15c1f41ae))
* **v2.2.0:** notes-showcase flagship examples + AggregateVM6 + downstream-driven maintenance ([#6](https://github.com/thekaveh/VMx/issues/6)) ([9ee9e20](https://github.com/thekaveh/VMx/commit/9ee9e206fe92d193310ad36e206b7626833c5448))
* **v2.3.0:** builder pattern audit follow-through (ADR-0035) ([#10](https://github.com/thekaveh/VMx/issues/10)) ([bc03a6d](https://github.com/thekaveh/VMx/commit/bc03a6d14db1868be52cccb27ce4b7654ea4bd39))
* **v2.4.0:** publication + Swift flavor + ThemeVM + coverage backfill (ADR-0036) ([#11](https://github.com/thekaveh/VMx/issues/11)) ([f91a2b3](https://github.com/thekaveh/VMx/commit/f91a2b379dcc48109955ad34aa5593bb4a1a1558))
* **v3:** VMx v3.0.0 framework overhaul — verified-merged critique remediation ([#37](https://github.com/thekaveh/VMx/issues/37)) ([e979ed6](https://github.com/thekaveh/VMx/commit/e979ed61d6dc7d69b18729a13b6185ef01d02197))


### Bug Fixes

* align parity gaps across flavors ([2eace45](https://github.com/thekaveh/VMx/commit/2eace45c1610c889efc0bb7e34b0a0e58c8b2b72))
* **audit:** final audit pass — version pins, ADR, TS setAt parity ([fc8cd8f](https://github.com/thekaveh/VMx/commit/fc8cd8fca4d200fa2132b31dcdfa1c4307e85561))
* harden async lifecycle and paging behavior ([60a58e9](https://github.com/thekaveh/VMx/commit/60a58e9156fff92bbab3af9435c76c08a3c813ff))
* harden lifecycle and async race handling ([eaa4b69](https://github.com/thekaveh/VMx/commit/eaa4b69fb66b7293be352dece5cbbe071ca721ed))
* **maint-pass-1:** AggregateVM6 reachability in walk + TS dispose ordering parity ([646cbcf](https://github.com/thekaveh/VMx/commit/646cbcf223b253455a018c86003d3c2301845cac))
* **maint-pass-1:** Python AggregateVM1..6 dispose ordering matches cross-flavor LIFE-013 invariant ([66efdea](https://github.com/thekaveh/VMx/commit/66efdeabdc0a066082384ac89b0a3b9c10055054))
* **maint:** audit-report verification follow-ups (code, spec/ADR, examples) ([#32](https://github.com/thekaveh/VMx/issues/32)) ([63b9c51](https://github.com/thekaveh/VMx/commit/63b9c51ef0c3014f68cb11de21f3b9e5a17076a8))
* make Python sdist rebuildable ([db61146](https://github.com/thekaveh/VMx/commit/db61146e75128339f18e1efe8dcf3a2f8d8a529a))
* **python:** address code-review nits on Task 4 ([7e2de8d](https://github.com/thekaveh/VMx/commit/7e2de8d0165b1b4aeffc903e375fb55fa7fab80d))
* **python:** correct two cross-language behavior divergences ([ce39f3a](https://github.com/thekaveh/VMx/commit/ce39f3ad02aa330b6e058b5b1fec3626d202fcd8))
* **python:** drop unused fixture force-includes and duplicate dev group ([b9efd61](https://github.com/thekaveh/VMx/commit/b9efd61c5bb0a580a354b25dd087b454bc8308e5))
* **python:** remove spurious PropertyChangedMessage emissions for status / is_constructed ([0aae8bc](https://github.com/thekaveh/VMx/commit/0aae8bce0dee66654d994e86c4a6111ed9d874f3))


### Documentation

* add repo metadata, code of conduct, issue/PR templates ([20a43fa](https://github.com/thekaveh/VMx/commit/20a43fa36f051929c3ea2db5a75ea6ccde843cf2))
* **changelog:** note spec-v1.0.0 as the implementation target ([ca9f694](https://github.com/thekaveh/VMx/commit/ca9f694f59ef618aee0be3db16d9a765da57a39a))
* clarify Python fixture packaging ([6821fce](https://github.com/thekaveh/VMx/commit/6821fce47492bcdd88d5a2791037309f3b4490c8))
* **forwarding:** consolidate type-ignore rationale comment block ([5f1bde6](https://github.com/thekaveh/VMx/commit/5f1bde6faee96fd50c425589dd53f0883e618ed9))
* **maint-pass-14:** correct NullDispatcher / NullMessageHub docstrings — Python has no 'I' prefix on these service protocols ([3036a2a](https://github.com/thekaveh/VMx/commit/3036a2a6bfcdc2c4bdcf5172bbe751eb3f23d5a4))
* **maint-pass-15:** finish Python I-prefix-docstring sweep — Command / MessageHubProto / Dispatcher / ComponentVMProto ([31923f6](https://github.com/thekaveh/VMx/commit/31923f60d00b564def63316046a9b4337306fbca))
* **maint-pass-16:** finish I-prefix-docstring sweep — relay_command + group_vm src files ([2fc2095](https://github.com/thekaveh/VMx/commit/2fc2095c1b70c8716a20dbdd3a910a5acafddf0e))
* **maint-pass-22:** fix AggregateVM arity + align CONTRIBUTING with CI commands ([5cbeec9](https://github.com/thekaveh/VMx/commit/5cbeec9afc2a98eb13acd61b06517f3d97f36ef4))
* **maint-pass-6:** add swift column to cross-language naming table in 3 flavor READMEs ([e5e67fa](https://github.com/thekaveh/VMx/commit/e5e67fac1ac6389077e5fc8e5dcf462d09276ebb))
* **maint-pass-8:** repair phantom ADR-0036 section refs (§3.C/§3.A → §2.C/§2.A) and IFilterable&lt;TItem&gt; in active parity matrix ([8e86c0e](https://github.com/thekaveh/VMx/commit/8e86c0e72d07e01ca8ea5e5028c474398d8b4108))
* **python:** add docstrings to Message and TypedMessage Protocols ([258f43a](https://github.com/thekaveh/VMx/commit/258f43aeded5a6c752e60aa945de52e94b19189c))
* **python:** RELEASING URL-validation checklist + bootstrap tag-ordering gotcha + PyPI badge ([#24](https://github.com/thekaveh/VMx/issues/24)) ([cef3629](https://github.com/thekaveh/VMx/commit/cef3629d623e694350989754c225de1a9c27f909))
* **readme:** bring C# and Python flavor READMEs to TypeScript parity ([30b1d08](https://github.com/thekaveh/VMx/commit/30b1d08badf59200217c06090456d84d2eab9b17))
* update status to v1.0.0 across READMEs, SECURITY, compatibility matrix, tools README ([12855c7](https://github.com/thekaveh/VMx/commit/12855c73b9acffea417022ba8bea971689812eab))

## [3.1.0] — 2026-07-01

Implements `spec-v3.1.0` and keeps Python at full library parity: 281/281
conformance IDs covered.

### Added

- `RelayCommand` / `RelayCommandOf` disposed-state inertness (`CMD-013`).
- `TokenPagedComposition`, filtered/scored composite views, declarative
  `FormVM` validation, VM-backed modal presentation, hierarchical child-cache
  invalidation, and `DiscriminatorVM`.

### Changed

- Clarified serviced collection ownership and per-instance property-change
  surfaces in docs/spec comments.
- Pinned existing common options-factory behavior (`BLD-006`) and group-child
  non-selection behavior (`GRP-011`) in conformance coverage.

### Fixed

- Lifecycle operation entry now serializes the status read, in-flight claim, and
  first transient status write under the per-VM lock, preventing a racing
  `dispose()` from winning before `construct()`/`destruct()` enters its hook.
- `AsyncRelayCommand` is now inert after disposal and no longer emits
  `can_execute_changed` into a disposed Rx subject when an in-flight task
  completes after disposal.
- `TokenPagedComposition` skips in-flight load/refresh mutation and notifications
  if it is disposed before the fetch completes.

## [3.0.0] — 2026-06-28

The **v3 framework overhaul** — a breaking release that hardens the
lifecycle/dispose concurrency path and reconciles the public surface across
flavors. Implements `spec-v3.0.0`. See ADRs 0047–0058 and
`docs/audit/2026-06-27-vmx-merged-critique.md`.

### Added

- Positional-options construction for the common VMs — a `create(...)` classmethod
  taking keyword-only arguments alongside the unchanged fluent builders:
  `ComponentVM.create(...)`, `ComponentVMOf.create(...)`, `CompositeVM.create(...)`,
  `GroupVM.create(...)`. Delegates to the builder, so required-field validation
  (`BuilderValidationError`) and the resulting VM are identical to the fluent path
  (ADR-0055; VMX-020).
- `AsyncRelayCommand` — an additive async command that flows asyncio task
  cancellation into a long-running coroutine and adds a `cancel()` method, closing
  the cancellation gap the synchronous `RelayCommand` had. Cancellation is
  non-throwing to the caller by default with an opt-in throwing mode;
  fire-and-forget task faults route to an `errors` observable. `RelayCommand` is
  unchanged (ADR-0056; CMD-012; VMX-052).
- `FormVM` surfaces approve-path persister failures on a new `approve_errors`
  observable instead of swallowing them; `is_dirty` uses the model's own value
  equality and the default snapshot is a deep value-copy (`copy.deepcopy`), both
  injectable; `on_approved` is pinned to the persisted value (ADR-0048; FORM-015).

### Removed

- **BREAKING:** Removed the legacy v1.0.0 `RelayCommandOfT` /
  `RelayCommandOfTBuilder` identity aliases (ADR-0052; VMX-095, deferral recorded
  in ADR-0009). Use the canonical `RelayCommandOf` / `RelayCommandOfBuilder`.
- **BREAKING:** Removed the legacy `AggregateVMBuilder1..6` identity aliases
  (ADR-0052; VMX-081). The concrete builders are the canonical
  `AggregateVM1Builder..6Builder`.
- **BREAKING:** Removed `null_message_hub_of` from the top-level `vmx` export
  (ADR-0052; VMX-081). It remains available as `from vmx.services import
  null_message_hub_of` for the narrow-typing case; the package root now offers a
  single null hub, `NULL_MESSAGE_HUB`.

### Changed

- **BREAKING:** `HierarchicalVM.__init__` now requires explicit `hub` and
  `dispatcher` arguments (the silent `MessageHub()` / `RxDispatcher.immediate()`
  defaults are removed) so a tree node can no longer acquire an isolated hub
  (ADR-0052; VMX-080). The builder is unchanged — it already required
  `services(hub, dispatcher)` and still offers `with_default_services()`.
- **BREAKING:** `ConfirmationDecoratorCommand.execute()` (synchronous
  fire-and-forget) now surfaces a rejecting `confirm` delegate or a throwing inner
  command on a new `errors` observable instead of swallowing them; the awaitable
  `execute_async()` keeps its raise behavior (ADR-0049; CMDD-010).
  `ModeledCrudCommands` update/delete `can_execute` is now reactive to
  current-selection change so bound buttons refresh (ADR-0049; VMX-011).
- Relicensed from MIT to **Apache-2.0** (ADR-0043). Effective from this point
  forward; the already-published 2.6.1 artifact remains MIT-licensed.

### Fixed

- **Lifecycle/dispose concurrency cluster (ADR-0047):** status transitions are
  atomic and dispose-safe behind a per-VM guard; background lifecycle completions
  marshal their terminal emission onto the foreground dispatcher; a post-dispose
  `is_current` change is a silent no-op; and a throwing `on_construct`/`on_destruct`
  hook rolls `status` back to the prior settled state (LIFE-008, the new LIFE-014).

## [2.6.1](https://github.com/thekaveh/VMx/compare/python-v2.6.0...python-v2.6.1) (2026-06-17)


### Documentation

* **python:** RELEASING URL-validation checklist + bootstrap tag-ordering gotcha + PyPI badge ([#24](https://github.com/thekaveh/VMx/issues/24)) ([cef3629](https://github.com/thekaveh/VMx/commit/cef3629d623e694350989754c225de1a9c27f909))

## [2.6.0] — 2026-06-13

Implements `spec-v2.6.0`. Adds two declarative selection hooks to the
composite builders, plus four ADRs capturing absorption-audit decisions.

### Added

- `CompositeVMBuilder[VM].current(selector)` — declarative initial-current
  selector (ADR-0042, COMP-025).
- `CompositeVMBuilder[VM].on_current_changed(callback)` — synchronous
  post-change selection callback (ADR-0042, COMP-026).
- Same hooks on the modeled `CompositeVMOfBuilder[M, VM]`.

### Documentation

- ADR-0039 — `INotifyPropertyChanging` not supported (teaching).
- ADR-0040 — `IProperty[T]` reactive backing-field not adopted (teaching).
- ADR-0041 — Single disposable lifecycle, no two-tier bags (teaching).
- ADR-0042 — `CompositeVMBuilder.current` + `on_current_changed` (behavior change).

## [2.5.0] — 2026-06-10

Implements `spec-v2.5.0` (ADR-0037).

### Fixed

- `FormVM.dispose()` is idempotent — a second call raised reactivex
  `DisposedException` (rxjs no-ops, C# guards).
- `CompositeVM.clear()` routes through the current-selection setter; the old
  current child no longer keeps `is_current == True` with no notification.
- `PagedComposition` subscribes `on_item_replaced`; `replace()` on the
  current page refreshes `items`.
- `ObservableList.clear()` emits `PropertyChanged("Count")` after `Reset`
  when the count changed (spec/21 §3.3).
- `GroupVM` construct/destruct iterate a snapshot so a child lifecycle hook
  that mutates the group cannot skip siblings.
- A background construct/destruct racing `dispose()` could resurrect the
  VM and publish post-dispose status messages; `DISPOSED` is now terminal
  in `_set_status` and the scheduled work (spec/02 invariant 3).
- `FormVM.approve_async` no longer raises `DisposedException` when
  `dispose()` runs during the persister await (mirrors the C# guard).
- `NotificationHub.dispose()` tolerates waiters whose event loop is
  already closed instead of raising and skipping the remaining waiters.
- `ObservableList.remove_at`/`replace` normalize negative indexes before
  emitting, so the event payload carries the spec-mandated
  index-before-removal instead of a raw `-1` (spec/21 §3.2; TS/C# raise
  on negative indexes by design). Out-of-range negatives raise
  `IndexError` instead of wrapping to a valid index.
- `FormVM`'s deny path is a no-op after `dispose()` (previously it
  reverted the model and re-published hub messages on a disposed form;
  same guard added in C# and TS). `approve_async()` on a disposed form
  is likewise a full no-op — the persister is no longer invoked.
- `ObservableList.insert` emits the actual insertion index: in-range
  negatives normalize and out-of-range indexes clamp per stdlib
  `list.insert` semantics, instead of the raw argument leaking into the
  `ItemAdded` payload (spec/21 §3.2). The same normalization applies to
  `ServicedObservableCollection.insert`, `CompositeVM.insert`, and
  `GroupVM.insert` (catalogued vs the C#/TS fail-fast contracts in
  ADR-0009).
- `FormVM`'s `on_approved` now emits the value that was actually
  persisted rather than the live model (parity with C#'s captured
  payload under a racing `set_model`).
- `NotificationHub` emits pending snapshots inside the lock (ordering +
  dispose-race discipline, mirroring C#).
- Post-2.4.0 maintenance backfill: `AggregateVM1..6` dispose ordering
  (LIFE-013) and aggregates walk/dispose drift.
- `FormVM.builder()` raised `TypeError` on every call (subscripted
  instantiation of a frozen+slots dataclass); it was the only builder
  entrypoint no test had ever exercised.
- `SearchableState.can_search()` returned `False` when the first item was
  a legal `None` value (sentinel conflation; C#/TS were unaffected).
- `ConfirmationDecoratorCommand`'s fire-and-forget done-callback raised
  `CancelledError` into the event loop when the task was cancelled.
- `fluent.confirm()` now types its callback as
  `Callable[[], Awaitable[bool]]`, matching the constructor contract it
  forwards to (a sync callback previously passed mypy and failed at
  `await`).

### Added

- `FORM-014` conformance coverage: a disposed `FormVM` is inert — approve
  never invokes the persister, deny does not revert (ADR-0038; pins the
  guards shipped earlier in this release).

- `HierarchicalVM.reparent_child` rejects self- and ancestor-reparenting
  with `ValueError` instead of silently corrupting the tree (HIER-018).
- `NotificationHub.dispose()` — resolves in-flight waiters with `PENDING`,
  completes `pending`, refuses new enqueues, idempotent (NOTIF-017).
- The `Dispatcher` protocol is exported from the top-level `vmx` package
  (parity with TS `IDispatcher` / C# `IDispatcher`).
- Idempotent `dispose()` on `DecoratorCommand` and
  `ConfirmationDecoratorCommand` (teardown symmetry with the C#
  IDisposable surface; the decorators own no subscriptions).

## [2.4.0] — 2026-06-02

Implements spec v2.4.0 — umbrella publication-readiness + Swift flavor
sibling + example-app theming scenario contract + test-coverage backfill
(ADR-0036). Purely additive at the surface level; no behaviour changes
to existing Python APIs.

### Added

- **ThemeVM scenario contract** (example apps): the v2.4.0
  `spec-v2.4.0` cycle defines a normative shape for example-app
  theming (`ThemeModel` + `ThemeVM : ComponentVMOf[ThemeModel]` +
  per-framework `ThemeAdapter`) built from the existing core
  primitives (`ComponentVMOf[M]`, `DerivedProperty[T]`, `RelayCommand`,
  `MessageHub`). No new core types are introduced; the contract is
  implemented by the Textual Notes-Showcase flagship under
  `examples/python/textual/notes_showcase/`. See
  `spec/proposals/2026-06-02-theme-vm-scenario.md` + ADR-0036 §2.C.

### Fixed

- **Aggregate parametric test coverage backfill.** The
  `AggregateVM1..6` test suite was expanded with parametric
  per-arity cases for construction, destruction, modeled-hint
  propagation, and dispose-cascade ordering — bringing aggregate-family
  line coverage to **100%** across all six arities. Existing
  Notes-Showcase edge cases (filter / search / paging interaction,
  capability-aware action-bar gating) gained dedicated tests in the
  same pass. No production code changed; tests only.

### Conformance

- 5 new IDs (`THEME-001..005`); running total goes from 227 to **232**.
  The Python flavor implements `THEME-001..005` as part of the Textual
  Notes-Showcase flagship's conformance suite (the contract is
  scenario-level, not a core library addition).

### Min spec version

- 2.4.0 (previously 2.3.0).

## [2.3.0] — 2026-05-31

Implements spec v2.3.0 — builder pattern audit follow-through (ADR-0035).
Purely additive at the surface level. One behaviour change brings
`CompositeVMBuilder` and `GroupVMBuilder` into compliance with the
existing spec §3 contract (see Fixed below); callers that were relying
on the previously-lazy validation were already buggy.

### Added

- **`FormVMBuilder`** (`vmx.forms`) — fluent immutable builder for
  `FormVM` with `.initial(...)` and `.persister(...)` required, and
  optional `.hub(...)`, `.strict(bool)`, `.snapshotter(...)`. Validates
  at `build()`. Conformance: `FORM-011..013`. See ADR-0035 §FV1/FV2.
- **`HierarchicalVMBuilder`** (`vmx.hierarchical`) — fluent immutable
  builder for `HierarchicalVM` with `.model(...)`,
  `.children_factory(...)`, `.services(hub, dispatcher)` required, and
  optional `.name(...)`, `.hint(...)`, `.eager_children(bool)`. Adds
  `.with_default_services()` Wither for opt-in implicit defaults.
  Validates at `build()`. Conformance: `HIER-015..017`. See ADR-0035
  §H1/H2/H3.
- **`with_null_services()`** Wither extension on `ComponentVMBuilder`
  (and friends) — chainable convenience that wires
  `NULL_MESSAGE_HUB` + `NULL_DISPATCHER` in one call, for parity with
  the C# `WithNullServices()` extension. See ADR-0035 §SV1.
- **Typed-arity DerivedProperty factories** — `DerivedProperty.from_one`
  through `DerivedProperty.from_five` with per-source type inference;
  `DerivedProperty.from_many` retained as alias of the existing
  `from_sources(...)` for arbitrary-N consumers. See ADR-0035 §DP2.

### Fixed

- `CompositeVMBuilder.build()` and `GroupVMBuilder.build()` now raise
  `BuilderValidationError` when `children` is unset, matching the
  spec/10 §3 contract and the TypeScript flavor's existing behaviour.
  Previously the Python flavor silently accepted a missing `children`
  factory and raised later at `on_construct`. See ADR-0035 §CP1/GR2.

### Conformance

- 7 new IDs (`BLD-005`, `FORM-011..013`, `HIER-015..017`); running total
  goes from 220 to 227.

### Min spec version

- 2.3.0 (previously 2.2.0).

## [2.2.0] — 2026-05-30

### Added

- `AggregateVM6` — sixth-arity heterogeneous aggregate.
  Conformance: `AGG-006`. See ADR-0034.

### Conformance

- 1 new ID (`AGG-006`); running total: 220.

### Min spec version

- 2.2.0 (previously 2.1.0).

## [2.1.0] — 2026-05-28

Implements spec v2.1.0. Purely additive — no breaking changes from v2.0.x.

### Added

- **`HierarchicalVM`** (`vmx.hierarchical`) — first-class recursive tree VM with
  lazy/eager child loading, depth-first construction, materialized path,
  parent-change and structural-change hub messages. `TreeStructureChangedMessage`
  new type. (ADR-0028; HIER-001..014)
- **`DialogService`** + **`NullDialogService`** (`vmx.dialogs`) — host-side
  contract for modal interactions (file pick, confirm prompt, severity-tagged
  notify) distinct from `INotificationHub`. (ADR-0029; DIA-001..008)
- **`FormVM`** (`vmx.forms`) — snapshot/revert edit lifecycle (ORM-agnostic).
  `deny_command`, `approve_command`, `on_approved` event, optional strict mode.
  `FormRevertedMessage` new type. (ADR-0030; FORM-001..010)
- **`NotificationVM`** + **`ConfirmationVM`** (`vmx.notifications`) — render-side
  VMs with auto-dismiss (60s/300s default), opacity decay, dismiss/approve/reject
  commands. (ADR-0031; NOTIF-011..016)
- **`ServicedObservableCollection`** (`vmx.collections`) — observable collection
  with hub publication. (ADR-0024; COL-001..004)
- **`ObservableList`** (`vmx.collections`) — granular per-mutation events
  (item_added/removed/replaced/reset) with batch suppression. (ADR-0026;
  COL-005..009, COL-023)
- **`ObservableDictionary`** (`vmx.collections`) — composite-key observable
  dictionary with observable keys1/keys2 views and hub publication. (ADR-0025;
  COL-010..015, COL-022)
- **`PagedComposition`** (`vmx.collections`) — paging decorator over any
  composition implementing `Pageable`. (ADR-0023; COL-016..021)
- **`Filterable`** + **`Pageable`** (`vmx.capabilities`) — two new capability
  protocols. (ADR-0022, ADR-0023; CAP-021, CAP-022)
- **Fluent command helpers** (`vmx.commands`) — `confirm(…)`, `precede_with`,
  `succeed_with`, `wrap_with` extension helpers over commands. (ADR-0027;
  CMD-008..011)
- **`property_value_changed_messages_for`** helper (`vmx.messages`) —
  function that filters `PropertyChangedMessage` events for a given
  sender + property name and returns an observable stream of the
  property's value snapshots. (ADR-0032; informative)
- **Conformance**: 67 new IDs (total 219).

### Fixed

- `CompositeVM.__setitem__` now clears `current` to None when the
  replaced slot held the current selection, mirroring `_remove_at`.
  Previously `_current` would silently dangle on the removed child.
- `AggregateVM1.._on_construct` now disposes the previous slot
  instance before invoking the factory on Reconstruct, so the old
  VM's hub subscriptions and command Subjects are released instead of
  lingering until the hub itself is disposed. (Parity with the C# fix.)
- `NotificationHub.resolve()` now schedules `future.set_result` via
  `loop.call_soon_threadsafe`, making `resolve()` safe to call from a
  thread other than the future's owning event loop (`asyncio.Future`
  itself is not thread-safe).
- `CompositeCommand.dispose()` no longer iterates a permanently-empty
  `_subscriptions` list (dead state). The merged `can_execute_changed`
  observable is lazy; subscribers' own disposables tear down the
  merged chain when they unsubscribe.
- `SearchableState.search_term` setter no longer pushes the new value
  through the debounce/recompute pipeline when it equals the current
  value (spec wording: "emission on a new value").
- `SearchableState.can_search` now uses `next(iter(...), None) is not None`
  instead of `any(True for _ in ...)`, materialising one element
  instead of the entire iterable.
- `DecoratorCommand.execute` now wraps the inner `execute` call in
  try/finally so the `post_execute` callback always runs — a "busy"
  flag set in `pre_execute` no longer gets stuck when the inner
  command raises.

### Changed

- `DerivedProperty`, `SearchableState`, and `ExpandableState` `dispose()`
  methods now call `.dispose()` after `.on_completed()` on each Subject,
  matching the project-wide pattern in `MessageHub` and `RelayCommand`.
- `properties.derived._apply` uses `cast()` instead of
  `assert isinstance(values, tuple)` so the runtime guard is not
  stripped by `python -O`.

## [2.0.0] — 2026-05-25

Implements spec v2.0.0 — capability micro-interfaces, derived properties,
search/filter, expand/collapse, modeled-CRUD commands, null-object services,
opt-in notifications sub-package, and a localization hook.

### Added
- **Capabilities** (`vmx.capabilities`): 20 opt-in micro-interfaces —
  `ISelectable`, `IDeselectable`, `ISelectionTogglable`, `IExpandable`,
  `ICollapsible`, `IExpansionTogglable`, `ISearchable`, `IClosable`,
  `IApprovable`, `ICancelable`, `INewCreatable`, `IDeletable`,
  `IUpdatable`, `ISavable`, `ICurrentDeletable`, `ICurrentUpdatable`,
  `IManagable`, `IConstructable`, `IDestructable`, `IReconstructable`
  (see `src/vmx/capabilities/`).
- **Helpers** (`vmx.capabilities`): `SearchableState[TItem]` (debounced
  filter), `ExpandableState` (expand/collapse + observable change).
- **Derived properties** (`vmx.properties`): `DerivedProperty[TValue]` +
  `from_sources(*sources, transform)` factory for N-source computed values
  with `distinct_until_changed` + optional write-back.
- **Commands**: `ConfirmationDecoratorCommand` + the abstract
  `DecoratorCommand` base, `make_confirm` helper,
  `ModeledCrudCommands[M, VM]` for the CRUD trio
  (create / update_current / delete_current) on modeled composites.
- **Null-object services** (per ADR-0017): `NullMessageHub`, `NullDispatcher`,
  `NullLocalizer`, plus `NullNotificationHub` (in the notifications package).
- **Localization** (`vmx.localization`): `ILocalizer` Protocol and
  `NullLocalizer` (identity translator) — the only opinionated localizer
  shipped in core.
- **Notifications sub-package** (`vmx.notifications`, opt-in): `Notification`,
  `NotificationType`, `NotificationReaction`, `INotificationHub` +
  `NotificationHub` reference impl + `NullNotificationHub`.
- **Tree utilities**: `walk_expanded(root)` — variant of `walk` that only
  descends into expanded composites (uses the new `IExpandable` capability).
- **Conformance**: 77 new IDs (`CAP-NNN`, `DPROP-NNN`, `NOTIF-NNN`,
  `LOC-NNN`, `COMP-014..024`, `GRP-007..010`) — total now 152 IDs.

### Internal
- `vmx.builders._validation.require_field` / `require_services` return
  narrowed values for tighter mypy --strict downstream typing.
- Dispose paths across `Modeled*` / `Searchable*` / `Expandable*` /
  `Derived*` are guarded with `_disposed` for idempotence.

### Notes
- The legacy aliases `RelayCommandOfT` / `RelayCommandOfTBuilder` and
  `AggregateVMBuilder1..5` continue to ship in v2.0.0; their removal has
  been deferred to **vmx v3.0.0** (next major). See ADR-0009.

## [1.2.0] — 2026-05-23

### Added
- `RelayCommandOf` and `RelayCommandOfBuilder` are now the canonical names for
  the parameterised command + builder pair, matching the TypeScript flavor's
  `RelayCommandOf` / `RelayCommandOfBuilder`.
- `AggregateVM1Builder` through `AggregateVM5Builder` are now the canonical
  builder names for the aggregate VMs, matching the TypeScript flavor's
  `AggregateVMNBuilder` shape.

### Deprecated
- `RelayCommandOfT` and `RelayCommandOfTBuilder` remain as identity aliases for
  backward compatibility. Removal deferred to **vmx v3.0.0** (was originally
  targeted for v2.0.0; see v2.0.0 Notes and ADR-0009).
- `AggregateVMBuilder1` through `AggregateVMBuilder5` remain as identity aliases
  for backward compatibility. Removal deferred to **vmx v3.0.0** (was originally
  targeted for v2.0.0; see v2.0.0 Notes and ADR-0009).

### Internal
- Per-suppression rationale comments added at every `# type: ignore` in
  `vmx.forwarding.composite` and `vmx.components.builders` (10 + 2 sites).
- `vmx.builders._validation` now declares parameters as `object | None` instead
  of `Any`, with a module docstring explaining why a Hub/Dispatcher Protocol is
  intentionally not used.
- `vmx.components.base` empty B027-silenced override hooks now carry an inline
  reason in their `noqa` comment.

## [1.1.0] — 2026-05-23

### Added
- Implements spec-v1.1.0 on top of the v1.0.0 surface.
- `CompositeVM` / `CompositeVMOf` / `GroupVM`: new `.auto_construct_on_add(bool)` builder option. When `True`, a child added after the container reaches `Constructed` is automatically constructed before the `CollectionChanged(Add)` event fires.
- `CompositeVM` / `CompositeVMOf` / `GroupVM`: new `batch_update()` method returns a context manager / disposable that suppresses per-mutation `CollectionChanged` events. The outermost handle disposal emits a single `CollectionChanged(Reset)` event iff any mutations occurred during the batch.
- New `vmx.tree` module with `walk(root)` (DFS pre-order generator) and `find(root, predicate)` (short-circuiting first-match).
- New conformance IDs: COMP-012, COMP-013, GRP-005, GRP-006, UTIL-001, UTIL-002, UTIL-003 (75/75 catalog coverage).
- Top-level `vmx.collections` module hosting the canonical `CollectionChangedEvent` (unified across composites and groups).
- Top-level `vmx` re-exports for the most-used types (`from vmx import ComponentVMOf, MessageHub, RxDispatcher, walk, find`).

### Fixed
- `GroupVM.dispose()` now cascades depth-first, matching the spec's LIFE-013 contract and the C# behavior.
- `CompositeVM` factory children now emit `CollectionChanged(Add)` events (previously silent), matching C#.
- Removed a stale "scaffolding state / Phase 3" docstring from `vmx/__init__.py`.

## [1.0.0] — 2026-05-23

### Added
- Full implementation of spec-v1.0.0:
  - Lifecycle: `ConstructionStatus` IntEnum + `StatusTransitionError` + JSON-fixture-backed transition validator
  - Messages: `Message`/`TypedMessage` Protocols + `PropertyChangedMessage` + `ConstructionStatusChangedMessage` frozen dataclasses
  - Services: `MessageHub` (Subject-backed hot stream with per-subscription exception isolation) + `Dispatcher` Protocol + `RxDispatcher` (with `immediate()` and `asyncio(loop)` factories)
  - Commands: `RelayCommand` + `RelayCommandOfT[T]` with reactive triggers and immutable frozen-dataclass builders; Execute is gated on can_execute
  - Components: `ComponentVM`, `ComponentVMOf[M]`, `ReadonlyComponentVMOf[M]` with full lifecycle, modeled hint, 5 built-in commands, async variants
  - Composites: `CompositeVM[VM]` + `CompositeVMOf[M, VM]` with selection contract, MutableSequence + Observable[CollectionChangedEvent], async-selection dispatch
  - Groups: `GroupVM[VM]` (children-as-peers; no Current; retains SelectCommand/DeselectCommand)
  - Aggregates: `AggregateVM1`..`AggregateVM5` fixed-arity tuples
  - Forwarding: `ForwardingComponentVM[M]` + `ForwardingCompositeVM[VM]` decorators
  - Background option dispatches construct/destruct on `Dispatcher.background` scheduler
- 68 conformance tests covering LIFE-001..013, HUB-001..007, PROP-001..004, CMD-001..007, CVM-001..006, COMP-001..011, GRP-001..004, AGG-001..005, FWD-001..003, BLD-001..004, THR-001..004 — all pass.
- 376+ unit tests across all modules — all pass.
- Python 3.10–3.13 supported.
- `mypy --strict` clean across the entire `src/vmx/` tree.
- Examples: `examples/python/hello_vmx/` (console) and `examples/python/tk_todo_app/` (tkinter MVVM).
- Getting-started tutorial at `docs/getting-started/python.md`.
