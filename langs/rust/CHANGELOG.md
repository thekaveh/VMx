# Changelog — VMx (Rust)

All notable changes to the Rust flavor of VMx are documented here. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/).

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
