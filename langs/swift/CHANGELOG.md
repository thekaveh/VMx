# Changelog — VMx (Swift)

All notable changes to the Swift flavor of VMx are documented here. The
format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [3.1.0] — 2026-06-30

### Added

- **Cross-module subclassing support for `ComponentVMBase`** (ADR-0066). The
  subclass-facing messaging surface — `hub`, `dispatcher`, and
  `_raisePropertyChanged(_:)` — is now `public` (read-only for the two
  properties) instead of `internal`, so consumers in another module can
  subclass `ComponentVMBase` and publish hub messages / fire the
  `propertyChanged` side-channel. Swift has no `protected`; `internal` did not
  cross the module boundary, so the base was previously only subclassable
  in-module. Purely additive — no behavior or conformance change (still
  237/237). Surfaced while building the Swift notes-showcase flagship.

## [3.0.0] — 2026-06-28

The **v3 framework overhaul** (subset). Implements the `spec-v3.0.0` subset.
See ADRs 0047–0058; the Swift-specific convergence is ADR-0053.

### Changed

- **BREAKING:** Illegal lifecycle transitions and a non-child `current`
  assignment now **throw catchable errors** (`StatusTransitionError` /
  `CompositeMembershipError`) instead of trapping via `preconditionFailure`
  (ADR-0053, superseding ADR-0037 §2.5). `construct()` / `destruct()` /
  `reconstruct()` and `setCurrent(_:)` are throwing; `LIFE-005` / `LIFE-006` /
  `LIFE-008` now assert a catchable throw. `dispose()` stays terminal/idempotent
  and never throws; the read-only model setter (`CVM-003`) still traps because
  Swift setters cannot throw. The conformance subset grows 41 → 42 (+`LIFE-008`).
- Relicensed from MIT to **Apache-2.0** (ADR-0043). Effective from this point
  forward; the already-published 2.6.0 subset remains MIT-licensed.

## [2.6.0] — 2026-06-13

Implements the spec-v2.6.0 subset. Adds two declarative selection hooks
to the non-modeled composite builder (the modeled composite is outside
Swift's documented subset; see `README.md` §5).

### Added

- `CompositeVMBuilder<Child>.current(_:)` — declarative initial-current
  selector (ADR-0042, COMP-025).
- `CompositeVMBuilder<Child>.onCurrentChanged(_:)` — synchronous
  post-change selection callback (ADR-0042, COMP-026).

### Documentation

- ADR-0039 — `INotifyPropertyChanging` not supported (teaching).
- ADR-0040 — `IProperty<T>` reactive backing-field not adopted (teaching).
- ADR-0041 — Single disposable lifecycle, no two-tier bags (teaching).
- ADR-0042 — `CompositeVMBuilder.current` + `onCurrentChanged` (behavior change).
- Conformance subset bumped 39 → 41 (+ COMP-025, COMP-026).

## [2.5.0] — 2026-06-10

Implements the spec-v2.5.0 subset (ADR-0037). 39 conformance IDs claimed
(honest recount — see the corrected 2.4.0 notes below).

### Changed

- **`ParentVM.supportsSelection` removed.** spec/05 §5 defines
  `can_select()` without a parent-slot condition, so a constructed group
  child now reports `canSelect() == true` and `select()` is a no-op,
  matching C# / Python / TypeScript. Code conforming to `ParentVM` no
  longer declares the member.
- **Hub `PropertyChangedMessage` names are camelCase everywhere** per the
  Swift idiom (spec/04 §4, ADR-0037): `"model"`, `"modeledHint"`,
  `"current"`, `"isCurrent"`, `"component1".."component6"`.
- Illegal lifecycle transitions remain traps (`preconditionFailure`) — now
  a *documented* divergence (spec/02 §2, ADR-0037) rather than an accident;
  LIFE-005/006 are claimed at the gating-predicate level and LIFE-008 is
  not claimed.

### Fixed

- **The five built-in commands were permanent no-op placeholders** —
  `selectCommand.canExecute()` returned `true` for orphan VMs and
  `execute()` silently discarded. They are now wired to the spec/05 §5
  predicates/tasks with the status trigger driving `canExecuteChanged`.
- `ReadonlyComponentVMOf.builder()` resolved to the inherited writable
  builder and produced a writable VM; the dedicated
  `ReadonlyComponentVMOfBuilder<Model>()` is now the readonly entry point.
  (A static `builder()` shadow on the subclass is not expressible in
  Swift — a different-return variant is ambiguous at annotation-free call
  sites and a same-signature redeclaration is an illegal static override —
  so the inherited `builder()` still resolves and builds a value
  statically typed `ComponentVMOf`; prefer the dedicated builder.)
- `ComponentVMOf.builder()` actually defaults `modelEquals` to `==` for
  `Equatable` models, as the documentation always claimed (the builder
  previously fell back to an always-false predicate).
- A background construct/destruct racing `dispose()` could resurrect the VM
  and publish post-dispose status messages; `.disposed` is now terminal in
  `_setStatus` and the scheduled work (spec/02 invariant 3). The same
  invariant now also gates the `_setIsCurrent` / `_setModel` hub sends,
  which previously published from disposed VMs.
- Conformance-ID citations in the test suite re-mapped against
  `spec/12-conformance.md` (~30 of 53 were shifted or vacuous).

### Added

- `VMxVersion.current` / `VMxVersion.minSpecVersion` constants (parity with
  the other flavors' programmatic version exports).
- New tests for CVM-001/003/006, AGG-004, CMD-006, BLD-003/004, GRP-002,
  and the Equatable builder default.

## [2.4.0] — 2026-06-02

**First release of the Swift flavor.** Implements a subset of spec
v2.4.0 covering the core viewmodel family + builders. This is a
skeleton release; the follow-up PR will widen coverage to full
cross-language parity.

### Added

- **`ConstructionStatus`** — five-state lifecycle enum (`.destructed`,
  `.constructing`, `.constructed`, `.destructing`, `.disposed`) with
  stable string `name` for fixture round-trip.
- **`ComponentVMBase`** — open base class for every VMx viewmodel.
  Manages the lifecycle state machine, hub publishing, the built-in
  command set, and parent/child selection delegation.
- **`ComponentVM`** — non-modeled leaf viewmodel.
- **`ComponentVMOf<Model>`** — modeled leaf viewmodel with a settable
  model, optional `modeledHinter`, and optional `modelEquals` predicate
  (defaults to `==` for `Equatable` models via a convenience
  initialiser).
- **`ReadonlyComponentVMOf<Model>`** — read-only modeled variant.
- **`CompositeVM<Child>`** — homogeneous-child container with a
  `current` selection slot.
- **`GroupVM<Child>`** — homogeneous peer-child container without a
  current slot.
- **`AggregateVM1..AggregateVM6`** — fixed-arity heterogeneous
  component-slot containers.
- **`RelayCommand`** — concrete `Command` with predicate + task closures
  and additive trigger publishers, backed by Combine.
- **Services:** `MessageHubProtocol` + `MessageHub` (Combine-backed),
  `NullMessageHub.INSTANCE`, `Dispatcher` protocol, `DefaultDispatcher`,
  `ImmediateDispatcher.INSTANCE`, `NullDispatcher.INSTANCE`.
- **Messages:** `Message` protocol, `PropertyChangedMessage`,
  `ConstructionStatusChangedMessage`.
- **Builders:** immutable fluent builders for `ComponentVM`,
  `ComponentVMOf`, `CompositeVM`, `GroupVM`, `AggregateVM1..6`,
  `RelayCommand`. Each ships a `withNullServices()` wither per
  ADR-0035. `BuilderValidationError` is thrown by `build()` when a
  required field is missing.

### Conformance subset

*(Corrected post-release — see ADR-0037. The list below originally
claimed `LIFE-001..013`, `CVM-001..006`, `COMP-001..010`, `GRP-001..006`,
`AGG-001..006`, `CMD-001..007`, `BLD-001..005`; several of those IDs'
behaviors did not exist in this release.)*

- `LIFE-001..007, 009, 010, 012, 013` — lifecycle state machine
  (LIFE-005/006 assert the gates; the raise is a trap).
- `CVM-002, 004, 005` — modeled component basics, as released.
- `COMP-003..005`, `GRP-003, 004` — lifecycle cascades + child-select.
- `AGG-001..006` — AggregateVM1..6 parametric coverage.
- `CMD-001..004` — RelayCommand task + predicate + triggers.
- `BLD-001, 002, 004, 005` — builders immutable + validation + defaults.

### Deferred to follow-up PRs

`HUB-*`, `PROP-*`, `THR-*`, `FWD-*`, `CAP-*`, `NULL-*`, `DPROP-*`,
`CMDD-*`, `NOTIF-*`, `EXP-*`, `LOC-*`, `COL-*`, `HIER-*`, `DIA-*`,
`FORM-*`, `UTIL-*`, and the fixture-backed `LIFE-011`. See README
§5 for the full status table.
