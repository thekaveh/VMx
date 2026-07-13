# spec/

The language-neutral specification of VMx. Source of truth for every language flavor.

This directory is the contract. Every published package declares the spec
version it implements; see [`compatibility-matrix.md`](../compatibility-matrix.md)
for current per-flavor versions. Each flavor's registered conformance suite
re-implements the catalog at `12-conformance.md`: C# under
`langs/csharp/tests/VMx.Conformance.Tests`, Python under
`langs/python/tests/conformance`, TypeScript under
`langs/typescript/tests/conformance`, Swift under `langs/swift/Tests/VMxTests`,
and Rust under `langs/rust/tests/conformance`. Behavioral conformance must pass
before any flavor releases a stable version.

## 1. Contents

### 1.1 Chapters (foundational, v1.x)

- `00-overview.md` — vision, scope, glossary.
- `01-concepts.md` — VM hierarchy, MVVM role, dependency philosophy.
- `02-lifecycle.md` — `ConstructionStatus` state machine and invariants.
- `03-messages.md` — message hub semantics, ordering, threading.
- `04-commands.md` — command contract, predicates, reactive triggers.
- `05-component-vm.md` — `ComponentVM` (readonly and modeled variants).
- `06-composite-vm.md` — `CompositeVM` (selectable children, `Current`).
- `07-group-vm.md` — `GroupVM`.
- `08-aggregate-vm.md` — `AggregateVM<VM1..VM6>` and arity rationale (arity-6 added in v2.2.0).
- `09-forwarding.md` — forwarding decorators.
- `10-builders.md` — builder semantics (immutability, fluent flow).
- `11-threading.md` — foreground/background and scheduler contract.
- `12-conformance.md` — cross-language conformance test catalog (396 IDs).
- `13-tree-utilities.md` — `walk` / `find` / `walk_expanded` tree introspection.

### 1.2 Chapters (v2.0 additions)

- `14-capabilities.md` — 20 opt-in capability micro-interfaces (extended to 22 in v2.1; see §1.3).
- `15-derived-properties.md` — `DerivedProperty<TValue>` N-source computed values.
- `16-notifications.md` — opt-in `INotificationHub` sub-package.
- `17-localization.md` — `ILocalizer` hook + `NullLocalizer` default.

### 1.3 Chapters (v2.1 additions)

- `18-hierarchical-vm.md` — `HierarchicalVM<TModel, TVM>`: first-class recursive
  tree VM with lazy/eager children, depth-first construction, materialized path,
  and `TreeStructureChangedMessage`.
- `19-dialogs.md` — `IDialogService`: host-side contract for modal interactions
  (file pick, confirm prompt, severity-tagged notify). `NullDialogService`
  per ADR-0017.
- `20-form-vm.md` — `FormVM<TM>`: snapshot/revert edit lifecycle (ORM-agnostic);
  `DenyCommand`, `ApproveCommand`, `OnApproved`, strict mode.
- `21-collections.md` — opt-in collection primitives: `ServicedObservableCollection<T>`,
  `ObservableList<T>`, `ObservableDictionary`, `PagedComposition<TVM>`.
- `22-discriminator-vm.md` — active-key / modal-overlay state coordinator.
- `23-async-resource-vm.md` — one-value asynchronous presentation lifecycle,
  cancellation, stale-result suppression, retention, and optional cleanup.

The following existing chapters were also extended in v2.1:

- `03-messages.md` — §7 Convenience helpers (ADR-0032, informative):
  `PropertyValueChangedMessagesFor` batch publisher.
- `04-commands.md` — §9 "Fluent composition" (ADR-0027): four fluent extension
  methods (`Confirm`, `PrecedeWith`, `SucceedWith`, `WrapWith`) over `ICommand`.
- `14-capabilities.md` — §2.6 `IFilterable<TItem>` (ADR-0022, CAP-021) and §2.10
  `IPageable` (ADR-0023, CAP-022).
- `15-derived-properties.md` — §8 Recipe for avoiding double-subscription on
  lazy initialization.
- `16-notifications.md` — §6–§7 render-side VMs `NotificationVM` and
  `ConfirmationVM` (ADR-0031, NOTIF-011..016) with auto-dismiss lifecycle.

### 1.4 v2.1.x → v2.2.0 changes

v2.2.0 is a minor, non-breaking spec bump motivated by the
[Notes Workspace flagship example portfolio](proposals/2026-05-29-notes-showcase-scenario.md)
(see also `examples/notes-showcase-parity.md`). All v2.1.x consumers continue
to work unchanged.

- **ADR-0034** — extends `AggregateVM` arity to 6. Supersedes ADR-0007 §4's
  "future major" stance on grounds of additivity.
- `08-aggregate-vm.md` — now covers arities 1–6 (was 1–5); adds the arity-6
  row to the members table and extends builder semantics.
- `12-conformance.md` — adds `AGG-006` (arity-6 construction / destruction
  ordering); catalog total goes from 219 to 220.

### 1.5 v2.2.x → v2.3.0 changes

v2.3.0 is a minor, non-breaking spec bump motivated by a comprehensive
builder-pattern audit (see ADR-0035). All v2.2.x consumers continue to work
unchanged; the one behaviour change (C# / Python `CompositeVMBuilder` and
`GroupVMBuilder` now validate `Children` at `Build()`) brings those flavors
into compliance with the existing spec §3 contract and matches TypeScript's
existing behaviour.

- **ADR-0035** — builder pattern audit follow-through: `FormVMBuilder<TM>`
  and `HierarchicalVMBuilder<TModel, TVM>` added across the three v2.3
  flavors (C# / Python / TypeScript — pre-Swift; both are deferred in the
  v2.4 Swift skeleton, see `langs/swift/README.md` §5);
  Children validation for `CompositeVMBuilder` / `GroupVMBuilder` aligned
  with spec; Python + TS gain `with_null_services()` / `withNullServices()`
  Wither parity with C#; Python gains typed-arity
  `DerivedProperty.from_one..from_five` factories.
- `10-builders.md` — §3 table gains rows for `HierarchicalVM<M, VM>` and
  `FormVM<TM>` with required-field contracts; §2 documents `BLD-005`
  additive-retention invariant.
- `12-conformance.md` — adds `BLD-005` (additive setter retention),
  `FORM-011..013` (FormVM builder validate / repeat / defaults), and
  `HIER-015..017` (HierarchicalVM builder validate / repeat / defaults);
  catalog total goes from 220 to 227.

### 1.6 v2.3.x → v2.4.0 changes

v2.4.0 is a minor, non-breaking spec bump that coordinates a publication-readiness pass, a Swift flavor skeleton, an example-app theming scenario contract, and example-app edge-case coverage backfill (see ADR-0036). All v2.3.x consumers continue to work unchanged.

- **ADR-0036** — umbrella for the v2.4.0 release: (a) C# / Python / TS
  publication-readiness (TS npm rename `vmx` → `@thekaveh/vmx` because the
  unscoped name was unavailable; CI workflow polish); (b) Swift flavor
  skeleton at `langs/swift/` covering LIFE / CVM / COMP / GRP / AGG / CMD /
  BLD subsets; (c) Theme as a VM concern — a scenario contract for
  example-app theming wiring `ComponentVM` + `DerivedProperty` +
  `RelayCommand` + `MessageHub` into a `ThemeVM` (no new core types); (d)
  test-coverage backfill (C# Forwarding decorators, Python aggregates,
  edge cases across the three flagship Notes-Showcase apps).
- `12-conformance.md` — adds the `THEME-NNN` family with five scenarios
  (`THEME-001..005`) under §28; catalog total goes from 227 to 232. The
  ThemeVM contract proper lives in `proposals/2026-06-02-theme-vm-scenario.md`.
- Chapter count stays at 22 (no new chapters); the ThemeVM contract is a
  scenario proposal, not a new chapter.

### 1.7 v2.4.x → v2.5.0 changes

v2.5.0 is a minor, non-breaking maintenance bump (see ADR-0037). All
v2.4.x consumers continue to work unchanged.

- **ADR-0037** — maintenance clarifications and additions: hub
  `PropertyName` casing follows the flavor idiom (ch03 §2.1); `Clear()`
  emits `Count` after `Reset` (ch21 §3.3); `ReparentChild` rejects
  self/ancestor cycles (ch18 §5, **HIER-018**); `NotificationHub` dispose
  semantics are normative (ch16 §9, **NOTIF-017**); the Swift lifecycle
  trap is a documented divergence (ch02 §2); the Swift conformance subset
  is recounted 53 → 39 (corrects ADR-0036 §2.E); fixture-prose and
  `NULL-*` listing corrections (ch15 §7, ch03 §8, ch11 §6).
- **ADR-0038** — spec-accuracy corrections (ch. 14 / 16 / 20 / 21) and the
  FormVM approve/deny round-trip clarification (ch20, **FORM-014**).
- `12-conformance.md` — adds `HIER-018` + `NOTIF-017` (ADR-0037) and
  `FORM-014` (ADR-0038); catalog total goes from 232 to 235 (230 library +
  5 THEME scenario IDs).
- Chapter count stays at 22.

### 1.8 v2.5.x → v2.6.0 changes

v2.6.0 is a minor, non-breaking maintenance bump from the absorption-audit
follow-up (see ADRs 0039 / 0040 / 0041 / 0042 and
`proposals/2026-06-13-vmx-absorption-audit-followup.md`). All v2.5.x
consumers continue to work unchanged.

- **ADR-0039** — `INotifyPropertyChanging` not supported (teaching note;
  no code change).
- **ADR-0040** — `IProperty<T>` reactive backing-field not adopted
  (teaching note; no code change).
- **ADR-0041** — Single disposable lifecycle, no two-tier bags (teaching
  note; no code change).
- **ADR-0042** — `CompositeVMBuilder.Current(selector)` +
  `OnCurrentChanged(callback)` declarative selection hooks on the
  composite builders (behavior change, additive). Implemented across C# /
  Python / TypeScript on both modeled and non-modeled builders; Swift
  ships on the non-modeled builder (modeled composite is outside Swift's
  documented subset).
- `06-composite-vm.md` — §3.2 documents the builder selection hooks.
- `12-conformance.md` — adds `COMP-025` (`current(selector)` invariants)
  and `COMP-026` (`onCurrentChanged(callback)` invariants); catalog total
  goes from 235 to 237 (232 library + 5 THEME scenario IDs).
- Chapter count stays at 22.

### 1.9 v2.6.x → v3.0.0 changes

v3.0.0 was a **breaking** major bump: the framework overhaul hardened the
lifecycle/dispose concurrency path and reconciled the spec with it (see ADR-0047
and `docs/audit/2026-06-27-vmx-merged-critique.md`). For that release,
`spec/VERSION` was `3.0.0` and every active flavor bumped to `3.0.0` in lockstep
(per the README §6.1 SemVer policy: a spec major triggers a major in every
flavor). The entries below describe the spec-level changes; the per-flavor
public-surface breaks are catalogued in ADRs 0052/0053/0054 and each flavor's
`CHANGELOG.md`.

- **ADR-0047** — v3 lifecycle/threading semantics: status transitions are atomic
  and dispose-safe behind a per-VM guard (`02 §2.3`); background lifecycle
  completions marshal their terminal emission onto `IDispatcher.Foreground`
  (`11 §3/§4`); the `LIFE-008` enforcement primitive is named; a post-dispose
  `IsCurrent` change is a silent no-op (`02` invariant 3); and a throwing
  `OnConstruct`/`OnDestruct` hook rolls `Status` back to the prior settled state
  (`02 §2.4`, the new **`LIFE-014`**).

- `02-lifecycle.md` and `11-threading.md` are revised accordingly.

- `12-conformance.md` — adds `LIFE-014` (transactional hook-failure rollback);
  catalog total goes from 237 to 238 (233 library + 5 THEME scenario IDs).

- Chapter count stays at 22.

- **ADR-0048** — v3 FormVM semantics: `IsDirty` uses an injectable structural
  equality (TypeScript default is a deep-equal, not `JSON.stringify`; C#/Python
  use the model's own value equality); the default snapshot is a deep value-copy
  (`System.Text.Json` round-trip / `copy.deepcopy` / `structuredClone`) with the
  snapshotter still injectable; `ApproveCommand.Execute()` is fire-and-forget and
  surfaces persister failures on a new `ApproveErrors` observable instead of
  swallowing them; and `OnApproved` is pinned to the persisted value across flavors
  (`20 §2/§3/§4/§7/§9`).

- `20-form-vm.md` is revised accordingly.

- `12-conformance.md` — adds `FORM-015` (approve command-path error channel);
  catalog total goes from 238 to 239 (234 library + 5 THEME scenario IDs).

- Chapter count stays at 22.

- **ADR-0049** — v3 command semantics: `ConfirmationDecoratorCommand`'s
  synchronous fire-and-forget `Execute()` surfaces a rejecting `confirm` delegate
  or a throwing inner command on a new `errors` observable instead of swallowing
  them — normative in every flavor that ships the decorator (C#/Python/TypeScript;
  the C# swallow is fixed for parity); the awaitable `ExecuteAsync()` keeps its
  throw behavior (`04 §8.3.1`). `ModeledCrudCommands` Update/Delete `CanExecute`
  becomes reactive to current-selection change via an optional `current_changed`
  trigger so bound buttons refresh (`04 §4.2`, `06 §7`; VMX-011).

- `04-commands.md` and `06-composite-vm.md` are revised accordingly.

- `12-conformance.md` — adds `CMDD-010` (confirmation-decorator error channel);
  catalog total goes from 239 to 240 (235 library + 5 THEME scenario IDs).

- Chapter count stays at 22.

- **ADR-0050** — v3 spec reconciliation (no runtime change): `whenPropertyChanged`
  is documented as the canonical typed cross-VM subscription helper (`03 §7.2`,
  informative — no conformance ID); the `Parent` back-reference is declared as a VM
  member with its type/nullability/set-on-add/clear-on-remove/non-observable contract
  (`01 §1.3`, `05 §2/§6.1`); `SelectNext`/`SelectPrevious` are documented as
  always-`false`/no-op on the base leaf (`05 §5`); and the initial-current selector is
  reconciled to a non-raising validated assignment, not the raising `select_component`
  path (`06 §3.2`).

- `01-concepts.md`, `03-messages.md`, `05-component-vm.md`, and `06-composite-vm.md`
  are revised accordingly.

- `12-conformance.md` — adds `COMP-027` (`Add` sets a child's `Parent`, `Remove`
  clears it); catalog total goes from 240 to 241 (236 library + 5 THEME scenario IDs).

- Chapter count stays at 22.

- **ADR-0052** — v3 flavor public-surface breaking removals (no spec-chapter or
  conformance-ID change): the Python `RelayCommandOfT`/`AggregateVMBuilderN`
  deferred aliases (ADR-0009) are removed in favor of the canonical
  `RelayCommandOf`/`AggregateVM1Builder` names; the C# off-domain `LinqHelpers`
  is dropped; `HierarchicalVM` requires explicit `hub`/`dispatcher` (matching the
  builder and ADR-0003); and `null_message_hub_of` is demoted from the top-level
  `vmx` export to `vmx.services` (VMX-095/068/080/081).

- **ADR-0056** — v3 async command cancellation: an additive `IAsyncCommand` /
  `AsyncRelayCommand` flows the idiomatic cancellation channel
  (`CancellationToken` / asyncio task cancellation / `AbortSignal`) into a
  long-running task and adds a `Cancel()` method, closing the gap where the
  synchronous `RelayCommand` task had no cancellation while `IDialogService`
  already did (`DIA-007`). Cancellation is non-throwing to the caller by default
  with an opt-in throwing mode — aligned with the dialog contract; fire-and-forget
  task faults route to an `errors` observable (`04 §10`). `RelayCommand` is
  unchanged. Full-parity (C#/Python/TypeScript); Swift deferred (VMX-052).

- `04-commands.md` is revised: §10 (new — async command cancellation), with the
  prior §10 Conformance renumbered §11.

- `12-conformance.md` — adds `CMD-012` (cancel cancels an in-flight async task;
  the command returns to a non-executing state; no exception surfaces by default);
  catalog total goes from 241 to 242 (237 library + 5 THEME scenario IDs).

- Chapter count stays at 22.

- **ADRs 0051 / 0053 / 0054 / 0055 / 0057 / 0058** — the remaining v3 decisions
  add no new conformance ID. **ADR-0051** reconciles the tree / collections /
  capability chapters and the proposal-as-normative-scenario-contract wording
  (`13`/`14`/`21`, and `README` §1.10). **ADR-0053** converges the Swift flavor to
  throw on illegal lifecycle transitions and a non-child `current` (documented as
  the divergence-resolution to ch. 02 §2; names `LIFE-008` in the Swift subset).
  **ADR-0054** renames the TypeScript `senderObject` field to the canonical
  `sender` for ADR-0006 parity (ch. 03 §2.1, informative). **ADR-0055** adds the
  positional-options `Create`/`create` construction path alongside the builders
  (ch. 10, informative). **ADR-0057** holds capability micro-interface granularity
  as-is, and **ADR-0058** holds the explicit `AggregateVM1..6` arity surface — both
  are "no change" decisions (teaching notes).

- The catalog therefore ends v3.0 at **242 total (237 library + 5 THEME scenario
  IDs)**; chapter count stays at 22.

### 1.10 v3.0.0 → v3.1.0 changes

v3.1.0 is an additive minor bump driven by upstream consumer adoption feedback.
It keeps the active full-parity flavors at total parity and raises the conformance
catalog from 242 to 286 total IDs (281 library + 5 THEME scenario IDs).

- **ADR-0068** — disposed `RelayCommand` instances are inert (`CMD-013`).
- **ADR-0069** — token/cursor pagination via `TokenPagedComposition`
  (`COL-024..031`).
- **ADR-0070** — filtered and scored composite views
  (`COMP-028..037`).
- **ADR-0071** — declarative `FormVM` field/model validation
  (`FORM-016..023`).
- **ADR-0072** — VM-backed modal presentation
  (`DIA-009..013`).
- **ADR-0073** — explicit hierarchical child-cache invalidation
  (`HIER-019..022`).
- **ADR-0074** — documentation clarifications for serviced collection
  ownership and per-instance property-change surfaces.
- **ADR-0075** — `DiscriminatorVM` active-key/modal stack coordinator
  (`DISC-001..006`) and new chapter `22-discriminator-vm.md`.
- **ADR-0076** — Swift `AsyncRelayCommand` parity documentation correction.
- **ADR-0077** — Swift `FormVM` snapshot default documentation correction.
- **ADR-0078** — `TokenPagedComposition` post-dispose load/refresh completion
  clarification.
- **ADR-0079** — Swift options-value factories and non-selectable group
  children add `BLD-006` and `GRP-011`.
- **ADR-0080** — accepts Rust as the fifth VMx flavor candidate.
- **ADR-0081** — promotes Rust to full library conformance in source. Rust now
  carries behavioral tests for all 281 library IDs and is required by the
  conformance coverage gate; crates.io publication remains a separate release
  channel task.

### 1.11 v3.1.0 → v3.2.0 changes

v3.2.0 adds lossless, synchronous message-hub transactions and iterative
re-entrant delivery across all five flavors. The six `HUB-008..013` scenarios
raise the catalog from 286 to 292 total IDs (287 library + 5 THEME scenario
IDs).

- **ADR-0082** — adds an optional transaction capability implemented by every
  shipped real and null message hub. Nested scopes defer every typed message in
  FIFO order, callback errors drain before rethrow, subscriber sends join an
  iterative drain, concurrent producers serialize without losing their
  calling-thread guarantee, and development builds diagnose suspected publish
  cycles without imposing a release-mode limit.

### 1.12 v3.2.0 → v3.3.0 changes

v3.3.0 adds one dual-channel property notification helper without adopting a
property wrapper. The three `CVM-007..009` scenarios raise the catalog from 292
to 295 total IDs (290 library + 5 THEME scenario IDs).

- **ADR-0083** — ordinary equality-gated setters assign state, then call one
  idiomatic helper that publishes exactly one shared-hub
  `PropertyChangedMessage` followed by exactly one VM-local binding
  notification. Calls after disposal are inert. Rust gains the missing
  per-instance property-name stream so the contract applies to all five
  flavors.

### 1.13 v3.3.0 → v3.4.0 changes

v3.4.0 makes disposal idempotency a cross-cutting invariant and publishes a
public-surface inventory for every flavor. The six `DISP-001..006` scenarios
raise the catalog from 295 to 301 total IDs (296 library + 5 THEME scenario
IDs).

- **ADR-0084** — classifies disposable surfaces into six ownership families,
  requires repeated disposal to be safe in every state, limits terminal
  publication and owned teardown to one observable occurrence, and preserves
  each type's documented post-dispose behavior. Thread-safe hubs and lifecycle
  owners additionally prove concurrent disposal.

### 1.14 v3.4.0 → v3.5.0 changes

v3.5.0 introduces one shared VM child-collection capability for groups and
composites, keeps selection in a composite-only extension, and adds atomic
identity-preserving move semantics. The eight `COL-032..039` scenarios raise
the catalog from 301 to 309 total IDs (304 library + 5 THEME scenario IDs).

- **ADR-0085** — defines the five idiomatic shared capability names, complete
  mutation surface, explicit move bounds/final-index semantics, one `Move`
  event, batch coalescing, and preservation of identity, parent, lifecycle,
  subscriptions, selection, and auto-construction state.

### 1.15 v3.5.0 → v3.6.0 changes

v3.6.0 adds an imperative command re-evaluation notification to concrete
synchronous, parameterized, and async relay commands while keeping trigger
wiring as the declarative path. The six `CMD-014..019` scenarios raise the
catalog from 309 to 315 total IDs (310 library + 5 THEME scenario IDs).

- **ADR-0086** — defines the five idiomatic raise names, exact one-call/one-event
  behavior without delegate invocation, additive trigger and async-state
  notifications, post-dispose inertness, concrete relay ownership, and Rust's
  source-compatible legacy alias.

### 1.16 v3.6.0 → v3.7.0 changes

v3.7.0 adds declarative post-persist reset semantics to `FormVM` in all five
flavors. The callback derives the next pristine model from the captured
persisted value; VMx snapshots it twice, revalidates, commits before
`OnApproved`, and routes post-persist reset failures through the existing
single-observer approval error split. `FORM-024..029` raise the catalog from
315 to 321 total IDs (316 library + 5 THEME scenario IDs).

See ADR-0087 and chapter 20 §5.1.

### 1.17 v3.7.0 → v3.8.0 changes

v3.8.0 adds consumer-keyed batch hydration to `HierarchicalVM` in all five
flavors. Stable fixpoint scans resolve child-before-parent windows without
forcing lazy subtrees; duplicates never replace an existing VM; missing parents
can park across batches or reject immediately; cycles and failures return typed
per-item results. `HIER-023..030` raise the catalog from 321 to 329 total IDs
(324 library + 5 THEME scenario IDs).

See ADR-0088 and chapter 18 §6.

### 1.18 v3.8.0 → v3.9.0 changes

v3.9.0 adds atomic whole-list replacement to `ObservableList` in all five
flavors. Input is snapshotted before mutation; every effective replacement
emits one Reset and cardinality-dependent `Count`; identical non-empty contents
do not require element equality; and nested or exceptional batch exits preserve
one outer notification. `COL-040..047` raise the catalog from 329 to 337 total
IDs (332 library + 5 THEME scenario IDs).

See ADR-0089 and chapter 21 §3.6.

### 1.19 v3.9.0 → v3.10.0 changes

v3.10.0 adds one disposal-lifetime ownership helper and makes the injected hub
a public read-only, non-owned baseline member. Cleanup is exactly once in LIFO
order, failures are isolated, post-dispose registration cleans immediately,
and reconstruct leaves registrations intact. `DISP-007..013` raise the catalog
from 337 to 344 total IDs (339 library + 5 THEME scenario IDs).

The NNx Studio pilot removed 16 inherited hub getters, two subscription fields,
two manual disposal overrides, and its two-case framework getter regression
test; the package remained type-clean and all 319 remaining tests passed.

See ADR-0090 and chapters 02 §2.3 and 05 §2.2.

### 1.20 v3.10.0 → v3.11.0 changes

v3.11.0 makes modeled assignment that begins after disposal inert before
candidate equality, retained-state mutation, hinting, validation, command-state
work, callbacks, or notification. TypeScript and Swift forms join the existing
C#, Python, and Rust form behavior; modeled components converge in all five
flavors. `DISP-014` raises the catalog from 344 to 345 total IDs (340 library +
5 THEME scenario IDs).

See ADR-0091 and chapters 02 §7, 05 §3, and 20 §5/§10.

### 1.21 v3.11.0 → v3.12.0 changes

v3.12.0 makes an accepted unequal FormVM model edit observable on the injected
hub after model, validation/errors, and approve-command state settle. Equal
candidates are complete no-ops under each flavor's configured or idiomatic
equality. Deny retains one ordered reverted/model pair, while approval reset
does not publish a model message; Rust's prior early/duplicate component leaks
are removed. `FORM-030` raises the catalog from 345 to 346 total IDs (341
library + 5 THEME scenario IDs).

See ADR-0092 and chapter 20 §5.2/§8.

### 1.22 v3.12.0 → v3.13.0 changes

v3.13.0 adds an explicit allocation-free modeled-component republish operation
to writable, read-only, and forwarding leaves. It retains model identity/value
and observable hint state, skips assignment/hinter/callback work, and emits one
ordinary idiomatic hub/local model pair. `CVM-010` raises the catalog from 346
to 347 total IDs (342 library + 5 THEME scenario IDs).

See ADR-0093 and chapter 05 §3.3/§4.

### 1.23 v3.13.0 → v3.14.0 changes

v3.14.0 adds three non-normative TypeScript predicates for classifying existing
property, collection, and construction-status messages in mixed raw-message
arrays and streams. This TypeScript-only type-narrowing surface does not change
message semantics or create an other-flavor requirement, so the catalog remains
347 total IDs (342 library + 5 THEME scenario IDs).

See ADR-0094 and chapter 03 §7.3.

### 1.24 v3.14.0 → v3.15.0 changes

v3.15.0 adds the cross-flavor `subscribeValue` imperative selected-state bridge
for one fixed VM, with idiomatic equality, optional immediate delivery,
current/previous callback values, deterministic teardown, and existing hub
ordering and failure isolation. `SUBV-001..004` raise the catalog from 347 to
351 total IDs (346 library + 5 THEME scenario IDs).

See ADR-0095 and chapter 03 §7.4/§8.

### 1.25 v3.15.0 → v3.16.0 changes

v3.16.0 completes the serviced observable collection mutation surface across
all five flavors. Value and indexed removal, replacement, snapshot-based
whole-list replacement, move, and clear now share precise position payloads,
no-op rules, local-before-hub delivery, and caller-owned item lifecycle. Rust
gains a distinct serviced collection rather than aliasing `ObservableList`.
`COL-048..055` raise the catalog from 351 to 359 total IDs (354 library + 5
THEME scenario IDs).

See ADR-0096 and chapter 21 §2/§8.

### 1.26 v3.16.0 → v3.17.0 changes

v3.17.0 adds a distinct keyed serviced observable collection across all five
flavors. The primitive preserves ordered sequence behavior and standard
local-before-hub collection messages while adding captured-key lookup,
duplicate prevention, upsert, key removal, indexed rekeying, and atomic bulk
validation. `COL-056..064` raise the catalog from 359 to 368 total IDs (363
library + 5 THEME scenario IDs).

See ADR-0097 and chapter 21 §2.2/§8.

### 1.27 v3.17.0 → v3.18.0 changes

v3.18.0 adds a dynamic aggregate change stream across all five flavors. The
primitive follows committed membership in composites, groups, serviced
collections, and keyed serviced collections while subscribing once per
distinct current member. Provenance envelopes distinguish initial readiness,
membership, item, and explicit batch changes; selectors may observe nested
state, and component conveniences select the standard property stream.
`AGCH-001..010` raise the catalog from 368 to 378 total IDs (373 library + 5
THEME scenario IDs).

See ADR-0098 and chapter 21 §9.

### 1.28 v3.18.0 → v3.19.0 changes

v3.19.0 makes `SearchableState` source-reactive without breaking the existing
lazy supplier or explicit-refresh path. An optional source-change signal now
recomputes immediately with the current term, remains independent of term
debounce, preserves upstream batch boundaries, isolates signal termination, and
owns only its subscription. Consumers needing member-property invalidation map
the ADR-0098 aggregate stream instead of creating another dynamic registry.
`SRCH-001..007` raise the catalog from 378 to 385 total IDs (380 library + 5
THEME scenario IDs).

See ADR-0099 and chapter 06 §8.

### 1.29 v3.19.0 → v3.20.0 changes

v3.20.0 adds `AsyncResourceVM<T>` as a UI- and transport-neutral component for
one asynchronously acquired value. Immutable idle/loading/ready/error state,
existing async relay command cancellation, monotonic latest-start-wins
admission, discard-by-default or retained previous values, and acquisition-based
optional cleanup replace repeated consumer-owned race policy. `ARES-001..011`
raise the catalog from 385 to 396 total IDs (391 library + 5 THEME scenario
IDs).

See ADR-0100 and chapter 23.

ADR-0101 records the standards posture for TC39 Signals without changing the
3.20.0 behavior contract: Rx remains the five-flavor reactive primitive, no
Signal adapter or dependency is added at Stage 1, and any future reconsideration
must satisfy objective standards, implementation, and consumer-evidence gates.

ADR-0102 defines the non-normative consumer conformance adapter schema and the
TypeScript factory runner. It adds no behavior chapter, spec version bump, or
conformance ID; the supporting schema versions independently.

### 1.30 Supporting artefacts

- `VERSION` — current spec SemVer (`3.20.0`).
- `fixtures/` — machine-checkable test inputs (JSON, 4 files).
- `ADRs/` — Architecture Decision Records (0001-0102); see
  [`ADRs/README.md`](ADRs/README.md) for the registry index.
- `schemas/` — versioned supporting machine contracts. The consumer
  conformance v1 schema is non-normative; see ADR-0102.
- `proposals/` — planning artifacts (accepted proposals that landed in past
  releases). These are **mostly historical and not part of the published
  normative spec**, with one documented exception: a proposal MAY carry a
  **scenario contract** that `12-conformance.md` references normatively. The
  ThemeVM scenario contract (`proposals/2026-06-02-theme-vm-scenario.md`,
  ADR-0036 §2.C) is such a case — its `THEME-001..THEME-005` IDs are normative
  for any flavor or example app that implements the contract (`12-conformance.md`
  §29). Where `12-conformance.md` cites a proposal, that proposal's referenced
  scenario contract is normative even though the surrounding proposal prose is
  not (clarified in v3 via ADR-0051).

## 2. Versioning

Spec version is tracked in `VERSION` and follows SemVer. Each language flavor
declares the spec version it implements (see
[`../compatibility-matrix.md`](../compatibility-matrix.md)). Breaking spec
changes require a major-version bump in every active flavor.

The historical design rationale lives in the ADRs alongside this spec.
