# Changelog — VMx (Swift)

All notable changes to the Swift flavor of VMx are documented here. This
project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## 2.4.0 — 2026-06-02

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
