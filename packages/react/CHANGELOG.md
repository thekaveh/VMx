# Changelog

All notable changes to `@thekaveh/vmx-react` are documented here. The adapter
uses independent [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - unreleased source version

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
