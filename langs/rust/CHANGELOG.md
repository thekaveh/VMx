# Changelog — VMx (Rust)

All notable changes to the Rust flavor of VMx are documented here. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/).

## [0.14.0] — 2026-07-11

Implements `spec-v3.14.0` and keeps Rust at full library parity: 342/342
conformance IDs covered.

### Changed

- The package line advances to 0.14.0 with minimum spec 3.14.0. The Rust runtime
  surface is unchanged because ADR-0094 records TypeScript-only message
  predicate ergonomics and adds no language-neutral conformance requirement.

## [0.13.0] — 2026-07-11

Implements `spec-v3.13.0` and keeps Rust at full library parity: 342/342
conformance IDs covered.

### Added

- Writable, read-only, and forwarding modeled components expose
  `republish_model()`, which retains model and observable hint state, skips
  assignment and hinter work, and emits one ordinary `"model"` hub/local pair
  (`CVM-010`, ADR-0093).

## [0.12.0] — 2026-07-11

Implements `spec-v3.12.0` and keeps Rust at full library parity: 341/341
conformance IDs covered.

### Changed

- `FormVm::set_model` retains its `PartialEq` no-op gate and now publishes the
  model notification only after validation and approve-command state settle
  (`FORM-030`, ADR-0092).

### Fixed

- Deny now publishes one ordered `FormReverted` + idiomatic `"model"` pair
  instead of the embedded component's early `"model"` plus legacy `"Model"`;
  approval reset no longer leaks a component model notification.

## [0.11.0] — 2026-07-11

Implements `spec-v3.11.0` and keeps Rust at full library parity: 340/340
conformance IDs covered.

### Changed

- `ComponentVm::set_model` returns before equality, retained-state, hinting, or
  notification work after disposal (`DISP-014`, ADR-0091). The existing
  `FormVm::set_model` terminal guard satisfies the same contract.

## [0.10.0] — 2026-07-10

Implements `spec-v3.10.0` and keeps Rust at full library parity: 339/339
conformance IDs covered.

### Added

- `ComponentVm::hub()` exposes the injected shared hub.
- `ComponentVm::own(...)` registers `FnOnce` cleanup for exactly-once LIFO
  terminal cleanup (`DISP-007..013`).

## [0.9.0] — 2026-07-10

Implements `spec-v3.9.0` and keeps Rust at full library parity: 332/332
conformance IDs covered.

### Added

- `ObservableList::replace_all(...)` snapshots iterator input and emits one
  Reset plus cardinality-dependent `Count` (`COL-040..047`).

### Fixed

- `ObservableList::batch_update` now restores nesting after panics and suppresses
  `Count` for count-preserving batches before resuming the original panic.

## [0.8.0] — 2026-07-10

Implements `spec-v3.8.0` and keeps Rust at full library parity: 324/324
conformance IDs covered.

### Added

- `attach_many(...)` with consumer key selectors, stable fixpoint resolution,
  non-replacing deduplication, park/reject orphan policy, structured rejection
  results, and root-owned disposal cleanup (`HIER-023..030`).

## [0.7.0] — 2026-07-10

Implements `spec-v3.7.0` and keeps Rust at full library parity: 316/316
conformance IDs covered.

### Added

- Immutable-builder `reset_on_approved(...)` returning `VmxResult<M>` for
  declarative post-persist reset, including independent snapshots,
  revalidation, deterministic race semantics, and existing approval error
  routing (`FORM-024..029`).

## [0.6.0] — 2026-07-10

Implements `spec-v3.6.0` and keeps Rust at full library parity: 310/310
conformance IDs covered.

### Added

- `raise_can_execute_changed()` on synchronous, parameterized, and async relay
  commands, with the previous `trigger_can_execute_changed()` retained as an
  alias (`CMD-014..019`).
- Async relay execution-start and execution-completion notifications on the
  existing command channel, completing the normative in-flight sequence.

## [0.5.0] — 2026-07-10

Implements `spec-v3.5.0` and keeps Rust at full library parity: 304/304
conformance IDs covered.

### Added

- Shared `VmCollection<T>` and selection-specific
  `SelectableVmCollection<T>` traits.
- Atomic identity-preserving `move_item(from_index, to_index)`, `Move`
  collection actions with both indices, and VM wrapper replacement methods
  (`COL-032..039`).

## [0.4.0] — 2026-07-10

Implements `spec-v3.4.0` and keeps Rust at full library parity: 296/296
conformance IDs covered.

### Added

- Cross-cutting disposal conformance for lifecycle owners, commands, hubs,
  interaction owners, reactive helpers, and collection/projection helpers
  (`DISP-001..006`).
- A public disposal-surface inventory documenting completion, owned teardown,
  post-dispose behavior, and second-call behavior.

### Fixed

- Lifecycle disposal now publishes its terminal `Disposed` transition exactly
  once instead of dispatching the identical intermediate and final state.
- `NotificationHub::dispose` now claims disposal atomically, so racing callers
  cannot complete subscriber snapshots more than once.

## [0.3.0] — 2026-07-10

Implements `spec-v3.3.0` and keeps Rust at full library parity: 290/290
conformance IDs covered.

### Added

- `PropertyChangedStream` and `property_changed` accessors across component,
  container, hierarchy, aggregate, readonly, and forwarding handles provide
  the per-instance local notification surface.
- `ComponentVm::notify_property_changed` emits one hub
  `PropertyChangedMessage` followed by one local notification and becomes
  inert after disposal (`CVM-007..009`).

### Changed

- Internal component-family property setters now use the shared dual-channel
  helper after equality checks and assignment.

## [0.2.0] — 2026-07-10

Implements `spec-v3.2.0` and keeps Rust at full library parity: 287/287
conformance IDs covered.

### Added

- `MessageHub::batch` for nested, lossless FIFO transactions
  (`HUB-008..013`).
- Iterative re-entrant delivery, condition-variable serialization for
  concurrent producers, and a debug-only publish-cycle diagnostic naming
  message variants.

### Changed

- The null hub executes transaction closures while continuing to publish
  nothing.

## [0.1.0] — 2026-07-09

### Added

- Initial full-parity Rust source flavor with behavioral coverage for the 281
  library conformance IDs in `spec-v3.1.0`.
