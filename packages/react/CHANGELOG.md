# Changelog

All notable changes to `@thekaveh/vmx-react` are documented here. The adapter
uses independent [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.3] - unreleased source version

First npm release since 0.1.1. The `react-v0.1.2` tag never reached npm, so
this package also contains the changes in the 0.1.2 section of
`packages/react/CHANGELOG.md`.

### Added

- `useCommand(command, { onError })` calls `onError` with each failure that
  the command sends on its `errors` channel while the component is mounted
  (#1394). The new `UseCommandOptions` type describes the option.

### Changed

- The `@thekaveh/vmx` peer range is now `^3.30.0`; it was `^3.24.1` (#1357).
  `useVm` and `createVmxStore` see `CompositeVM` and `GroupVM` membership
  changes only through hub messages, and the core sends those messages from
  3.27.0. Version 3.30.0 is the lowest published core that sends them. With
  an older core, a `useVm(composite, (c) => c.count)` selector could stay
  stale after `add`.

### Fixed

- The locked development dependency graph now uses `minimatch` 11.0.3 through
  an `overrides` entry. This removes the glob-pattern denial-of-service
  advisory GHSA-g3hv-75wg-m249. The published package does not depend on
  `minimatch`.
- A `useCommand` binding to a disposed `DecoratorCommand`, `CompositeCommand`
  or `ConfirmationDecoratorCommand` now renders as disabled. The adapter code
  is unchanged; this needs the next `@thekaveh/vmx` release, where those
  wrappers notify on `dispose()` (#771).
- `useVm` re-renders a component bound to a forwarding decorator (#1350).
  The wrapped VM sends every hub message, so the hook now also matches the
  senders that the decorator's public `wrappedBase` chain reaches, including
  nested decorators. A message from another VM on the same hub still causes
  no re-render. `ForwardingComponentVM` works with every `@thekaveh/vmx` in
  the peer range; `ForwardingCompositeVM` needs the next `@thekaveh/vmx`
  release, which adds its `wrappedBase` (ADR-0213).
- A failed `AsyncRelayCommand` bound with `useCommand` no longer has to fail
  silently. Before, the hook had no way to observe the command's `errors`
  channel, so a rejected fire-and-forget task was lost (#1394).
- `createVmxStore` delivers no further notification after `dispose()`, even
  inside a flush already in progress. Before, a listener that disposed the
  store let the listeners copied for that flush run after it.

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
