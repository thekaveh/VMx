# Changelog

All notable changes to the C# flavor are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-05-22

### Added
- Full implementation of spec-v1.0.0:
  - Lifecycle: `ConstructionStatus` + `StatusTransitionException` + transition validator
  - Messages: `IMessage` hierarchy + `PropertyChangedMessage` + `ConstructionStatusChangedMessage`
  - Services: `IMessageHub`/`MessageHub` + `IDispatcher`/`RxDispatcher`
  - Commands: `RelayCommand` + `RelayCommand<T>` with reactive triggers and immutable builders
  - Components: `ComponentVM<M>` + `ReadonlyComponentVM<M>` with full lifecycle, modeled hint, and built-in commands
  - Composites: `CompositeVM<VM>` + `CompositeVM<M, VM>` with selection contract, IList + INotifyCollectionChanged, async-selection dispatch
  - Groups: `GroupVM<VM>` (children-as-peers; retains SelectCommand/DeselectCommand for self-selection in parent)
  - Aggregates: `AggregateVM1`..`AggregateVM5` fixed-arity tuples with parallel construction
  - Forwarding: `ForwardingComponentVM<M>` + `ForwardingCompositeVM<VM>` decorators
  - Background option (`Background(true)`) dispatches construct/destruct on `IDispatcher.Background`
  - Optional DI companion package `VMx.Extensions.DependencyInjection` with `AddVMx()`
- 68 conformance tests covering LIFE-001..013, HUB-001..007, PROP-001..004, CMD-001..007, CVM-001..006, COMP-001..011, GRP-001..004, AGG-001..005, FWD-001..003, BLD-001..004, THR-001..004 — all pass.
- 194 unit tests across all modules — all pass.
- Multi-target `netstandard2.0;net8.0`. Test runner targets `net9.0`.
- Examples: `examples/csharp/HelloVMx/` (console) and `examples/csharp/WpfTodoApp/` (WPF binding, Windows-only build).
- Getting-started tutorial at `docs/getting-started/csharp.md`.

## [Unreleased]
