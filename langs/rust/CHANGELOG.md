# Changelog — VMx (Rust)

All notable changes to the Rust flavor of VMx are documented here. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/).

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
