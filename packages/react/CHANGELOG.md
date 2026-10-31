# Changelog

All notable changes to `@thekaveh/vmx-react` are documented here. The adapter
uses independent [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- The locked development dependency graph now uses `minimatch` 11.0.3 through
  an `overrides` entry. This removes the glob-pattern denial-of-service
  advisory GHSA-g3hv-75wg-m249. The published package does not depend on
  `minimatch`.
- A `useCommand` binding to a disposed `DecoratorCommand`, `CompositeCommand`
  or `ConfirmationDecoratorCommand` now renders as disabled. The adapter code
  is unchanged; this needs the next `@thekaveh/vmx` release, where those
  wrappers notify on `dispose()` (#771).

## [0.1.2] - 2026-10-21

### Fixed

- `useVm` re-renders for every hub message the VM sends: property, lifecycle
  status, collection, and tree-structure changes, as "whole-VM invalidation"
  promises. Before, it reacted only to property changes, so a component
  rendering `vm.status`, or a `children.length` selector after `addChild`,
  stayed stale.
- `useCommand` re-reads `canExecute` when the command's `canExecuteChanged`
  stream completes, so a disposed `AsyncRelayCommand` renders as disabled.
- `shallowEqual` compares only plain objects by their keys. A `Date`, `Map`,
  `Set`, or class instance now compares by identity; before, two different
  instances compared equal and a selector returning them never re-rendered.
- `createVmxStore` advances its snapshot on every hub message, not only the
  first one of a synchronous drain, so a render between two messages of the
  same drain cannot miss the second change (#638).

## [0.1.1] - 2026-10-16

First version published to npm. It also contains everything listed under
0.1.0, which was a source-only release.

### Fixed

- The README's conditional-VM example reads `live.model.title`; it read
  `live.title`, which a `ComponentVMOf` does not have. Its store and
  conditional-VM examples are now checked against the executed React recipe
  by `make docs-check` (#347).
- `useDerivedProperty` renders a delayed first value as soon as it arrives
  instead of `undefined` until a second, different value. It observes the core's
  internal first-value seam, so the `@thekaveh/vmx` peer minimum rises to
  3.24.1 (#415).

## [0.1.0] - 2026-08-10

### Added

- Initial official React 18/19 adapter with shared selector stores and focused
  VM, command, derived-property, async-resource, observable-list, and VM
  collection hooks.
- StrictMode-safe subscription ownership, cached monotonic snapshots,
  render-to-subscribe catch-up, synchronous-drain coalescing, SSR/hydration
  support, and shallow equality.
- Package, flagship migration, consumer-pilot, and release verification
  contracts.
